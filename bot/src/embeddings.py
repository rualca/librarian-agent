from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
INDEX_DIR = ".index/semantic"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
MAX_CHUNK_CHARS = 2000
BATCH_SIZE = 64

try:
    import faiss  # type: ignore[import-untyped]

    _HAS_FAISS = True
except ImportError:
    faiss = None  # type: ignore[assignment]
    _HAS_FAISS = False
    logger.warning("faiss not installed – semantic search disabled")


# ---------------------------------------------------------------------------
# Chunk dataclass
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    id: int
    rel_path: str
    title: str
    section: str
    text: str


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)


def _strip_frontmatter(raw: str) -> str:
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end != -1:
            return raw[end + 3 :].lstrip("\n")
    return raw


def _chunk_file(filepath: Path, rel_path: str) -> list[dict]:
    try:
        raw = filepath.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Cannot read %s", filepath)
        return []

    raw = _strip_frontmatter(raw)
    title = filepath.stem

    sections: list[tuple[str, str]] = []
    last_heading = title
    last_pos = 0

    for m in _HEADING_RE.finditer(raw):
        body = raw[last_pos : m.start()].strip()
        if body:
            sections.append((last_heading, body))
        last_heading = m.group(2).strip()
        last_pos = m.end()

    tail = raw[last_pos:].strip()
    if tail:
        sections.append((last_heading, tail))

    chunks: list[dict] = []
    for heading, body in sections:
        if not body:
            continue
        if len(body) <= MAX_CHUNK_CHARS:
            chunks.append(
                {"rel_path": rel_path, "title": title, "section": heading, "text": body}
            )
        else:
            paragraphs = re.split(r"\n{2,}", body)
            buf = ""
            for para in paragraphs:
                if buf and len(buf) + len(para) + 2 > MAX_CHUNK_CHARS:
                    chunks.append(
                        {"rel_path": rel_path, "title": title, "section": heading, "text": buf.strip()}
                    )
                    buf = ""
                buf += para + "\n\n"
            if buf.strip():
                chunks.append(
                    {"rel_path": rel_path, "title": title, "section": heading, "text": buf.strip()}
                )

    return chunks


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _manifest_path() -> Path:
    return settings.vault_path / INDEX_DIR / "manifest.json"


def _index_path() -> Path:
    return settings.vault_path / INDEX_DIR / "faiss.index"


def _load_manifest() -> dict:
    mp = _manifest_path()
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt manifest – rebuilding")
    return {
        "model": EMBEDDING_MODEL,
        "dim": EMBEDDING_DIM,
        "next_id": 0,
        "files": {},
        "chunks": {},
    }


def _save_manifest(manifest: dict) -> None:
    mp = _manifest_path()
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed_texts(texts: list[str]) -> list[list[float]]:
    if not settings.openai_api_key:
        logger.warning("OpenAI API key not set – cannot compute embeddings")
        return []

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        batch_vecs = [d.embedding for d in resp.data]
        all_embeddings.extend(batch_vecs)

    # Normalise to unit length for cosine similarity via inner product
    arr = np.array(all_embeddings, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms
    return arr.tolist()


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

def _scan_vault_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for subdir in ("Cards", "Encounters"):
        folder = settings.vault_path / subdir
        if folder.exists():
            for p in folder.glob("*.md"):
                rel = f"{subdir}/{p.name}"
                files[rel] = p
    return files


def ensure_index(force: bool = False) -> tuple[int, int, int]:
    if not _HAS_FAISS:
        logger.warning("FAISS unavailable – skipping index build")
        return (0, 0, 0)

    if not settings.openai_api_key:
        logger.warning("OpenAI API key not set – skipping index build")
        return (0, 0, 0)

    manifest = _load_manifest()
    ip = _index_path()

    if force or manifest.get("model") != EMBEDDING_MODEL or manifest.get("dim") != EMBEDDING_DIM:
        manifest = {
            "model": EMBEDDING_MODEL,
            "dim": EMBEDDING_DIM,
            "next_id": 0,
            "files": {},
            "chunks": {},
        }
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(EMBEDDING_DIM))
    elif ip.exists():
        index = faiss.read_index(str(ip))
    else:
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(EMBEDDING_DIM))

    vault_files = _scan_vault_files()

    # Detect removed files
    removed_count = 0
    for rel in list(manifest["files"].keys()):
        if rel not in vault_files:
            info = manifest["files"].pop(rel)
            for cid in info.get("chunk_ids", []):
                index.remove_ids(np.array([cid], dtype=np.int64))
                manifest["chunks"].pop(str(cid), None)
            removed_count += 1

    # Detect new / changed files
    to_process: list[tuple[str, Path]] = []
    for rel, path in vault_files.items():
        stat = path.stat()
        prev = manifest["files"].get(rel)
        if prev is None:
            to_process.append((rel, path))
        elif prev["mtime"] != stat.st_mtime or prev["size"] != stat.st_size:
            # Remove old chunks first
            for cid in prev.get("chunk_ids", []):
                index.remove_ids(np.array([cid], dtype=np.int64))
                manifest["chunks"].pop(str(cid), None)
            to_process.append((rel, path))

    added_count = 0
    updated_count = 0

    if to_process:
        # Chunk all files first
        file_chunks: list[tuple[str, Path, list[dict]]] = []
        all_texts: list[str] = []
        for rel, path in to_process:
            chunks = _chunk_file(path, rel)
            file_chunks.append((rel, path, chunks))
            all_texts.extend(c["text"] for c in chunks)

        # Embed in one pass
        if all_texts:
            embeddings = _embed_texts(all_texts)
            if not embeddings:
                return (0, 0, removed_count)

            emb_idx = 0
            for rel, path, chunks in file_chunks:
                was_existing = rel in manifest["files"]
                stat = path.stat()
                chunk_ids: list[int] = []

                for chunk in chunks:
                    cid = manifest["next_id"]
                    manifest["next_id"] += 1
                    chunk_ids.append(cid)

                    vec = np.array([embeddings[emb_idx]], dtype=np.float32)
                    index.add_with_ids(vec, np.array([cid], dtype=np.int64))
                    manifest["chunks"][str(cid)] = chunk
                    emb_idx += 1

                manifest["files"][rel] = {
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                    "chunk_ids": chunk_ids,
                }

                if was_existing:
                    updated_count += 1
                else:
                    added_count += 1

    # Persist
    ip.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(ip))
    _save_manifest(manifest)

    logger.info(
        "Index updated: added=%d, updated=%d, removed=%d", added_count, updated_count, removed_count
    )
    return (added_count, updated_count, removed_count)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    if not _HAS_FAISS:
        return []

    if not settings.openai_api_key:
        logger.warning("OpenAI API key not set – cannot search")
        return []

    ensure_index()

    ip = _index_path()
    if not ip.exists():
        return []

    index = faiss.read_index(str(ip))
    if index.ntotal == 0:
        return []

    vecs = _embed_texts([query])
    if not vecs:
        return []

    q = np.array(vecs, dtype=np.float32)
    scores, ids = index.search(q, min(top_k, index.ntotal))

    manifest = _load_manifest()
    results: list[dict] = []
    for score, cid in zip(scores[0], ids[0]):
        if cid == -1:
            continue
        if score < 0.3:
            continue
        chunk = manifest["chunks"].get(str(cid))
        if chunk is None:
            continue
        results.append(
            {
                "title": chunk["title"],
                "section": chunk["section"],
                "text": chunk["text"],
                "score": float(score),
                "rel_path": chunk["rel_path"],
            }
        )

    return results


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def index_stats() -> dict:
    manifest = _load_manifest()
    ip = _index_path()

    last_updated: float | None = None
    if ip.exists():
        last_updated = ip.stat().st_mtime

    return {
        "total_chunks": len(manifest.get("chunks", {})),
        "total_files": len(manifest.get("files", {})),
        "model": manifest.get("model", EMBEDDING_MODEL),
        "last_updated": last_updated,
    }
