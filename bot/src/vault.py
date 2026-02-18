from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

from src.config import settings
from src.models import EntryType, ExtractedEntry


def sanitize_filename(name: str) -> str:
    sanitized = name.replace(":", " —")
    illegal = r'[\\/?*"|<>]'
    sanitized = re.sub(illegal, "", sanitized)
    sanitized = sanitized.strip(". ")
    if len(sanitized) > 80:
        sanitized = sanitized[:77].rsplit(" ", 1)[0] + "..."
    return sanitized


def list_encounters() -> list[str]:
    path = settings.encounters_path
    if not path.exists():
        return []
    return [f.stem for f in path.glob("*.md")]


def find_encounter(title: str) -> str | None:
    encounters = list_encounters()
    safe_title = sanitize_filename(title).lower()
    for name in encounters:
        if name.lower() == safe_title:
            return name
        if safe_title in name.lower() or name.lower() in safe_title:
            return name
    for name in encounters:
        ratio = SequenceMatcher(None, safe_title, name.lower()).ratio()
        if ratio > 0.75:
            return name
    return None


def read_encounter(title: str) -> str | None:
    path = settings.encounters_path / f"{title}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def create_encounter(
    title: str,
    author: str = "",
    source: str = "book",
    language: str = "",
    original_title: str = "",
) -> str:
    safe_title = sanitize_filename(title)
    now = datetime.now()
    created = now.strftime("%Y-%m-%d %H:%M")
    started = now.strftime("%Y-%m-%d")

    author_yaml = f'"{author}"' if author and (":" in author or '"' in author) else author

    content = f"""---
type: encounter
source: {source}
author: {author_yaml}
rating:
status: in-progress
created: {created}
updated: {created}
cover:
url:
tags:
  - source/{source}
---

# 📚 {title}

## Metadata

- **Author**: {author}
- **ISBN**: """

    if original_title:
        content += f"\n- **Original title**: {original_title}"
    if language:
        content += f"\n- **Language**: {language}"

    content += f"""
- **Started**: {started}
- **Finished**: 

## Summary

> One-paragraph summary.

## Key Ideas

1. 
2. 
3. 

## Bookmarks

> Each physical tab you placed becomes an entry here.

### 💡 Ideas & Concepts

### 💬 Quotes & Phrases

### 🔧 Problems & Solutions

### 📖 Chapter Summaries

### 🔑 Key Takeaways

## My Thoughts



## Action Items

- [ ] 

## Atomic Notes Extracted

"""

    settings.encounters_path.mkdir(parents=True, exist_ok=True)
    filepath = settings.encounters_path / f"{safe_title}.md"
    filepath.write_text(content, encoding="utf-8")
    return safe_title


def _find_section_range(lines: list[str], heading: str) -> tuple[int, int]:
    heading_lower = heading.lower()
    start = -1
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped == heading_lower or (
            heading_lower.split()[-1] in stripped
            and stripped.startswith("#")
            and stripped.count("#") == heading_lower.count("#")
        ):
            start = i
            break
    if start == -1:
        return -1, -1

    heading_level = len(heading.split()[0])
    end = len(lines)
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            current_level = len(stripped.split()[0]) if stripped.split() else 0
            if current_level <= heading_level:
                end = i
                break
    return start, end


def _is_duplicate(existing_content: str, new_entry: ExtractedEntry) -> bool:
    normalized_new = re.sub(r"\s+", " ", new_entry.content.lower().strip())
    if new_entry.page and f"p.{new_entry.page}" in existing_content:
        section_text = existing_content.lower()
        if normalized_new[:50] in section_text:
            return True
    for line in existing_content.split("\n"):
        normalized_line = re.sub(r"\s+", " ", line.lower().strip())
        if not normalized_line or normalized_line.startswith("#"):
            continue
        ratio = SequenceMatcher(None, normalized_new[:100], normalized_line[:100]).ratio()
        if ratio > 0.80:
            return True
    return False


def append_entry(book_title: str, entry: ExtractedEntry) -> dict:
    filepath = settings.encounters_path / f"{book_title}.md"
    if not filepath.exists():
        return {"ok": False, "error": f"Encounter note '{book_title}' not found"}

    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")
    heading = entry.entry_type.section_heading
    start, end = _find_section_range(lines, heading)

    if start == -1:
        bookmarks_start, bookmarks_end = _find_section_range(lines, "## Bookmarks")
        if bookmarks_start == -1:
            return {"ok": False, "error": f"Section '{heading}' not found and cannot repair"}
        insert_at = bookmarks_end
        lines.insert(insert_at, "")
        lines.insert(insert_at + 1, heading)
        lines.insert(insert_at + 2, "")
        content = "\n".join(lines)
        lines = content.split("\n")
        start, end = _find_section_range(lines, heading)

    section_content = "\n".join(lines[start:end])
    if _is_duplicate(section_content, entry):
        return {"ok": False, "duplicate": True, "section": heading}

    entry_md = entry.to_markdown()
    insert_at = end
    for i in range(end - 1, start, -1):
        if lines[i].strip():
            insert_at = i + 1
            break
    else:
        insert_at = start + 1

    entry_lines = [""] + entry_md.split("\n") + [""]
    for j, line in enumerate(entry_lines):
        lines.insert(insert_at + j, line)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = "\n".join(lines)
    content = re.sub(r"updated: .+", f"updated: {now}", content, count=1)

    filepath.write_text(content, encoding="utf-8")
    return {"ok": True, "section": heading}


def update_encounter_status(
    book_title: str,
    status: str | None = None,
    rating: int | None = None,
) -> bool:
    filepath = settings.encounters_path / f"{book_title}.md"
    if not filepath.exists():
        return False

    content = filepath.read_text(encoding="utf-8")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if status:
        content = re.sub(r"status: .+", f"status: {status}", content, count=1)
    if rating is not None:
        content = re.sub(r"rating:.*", f"rating: {rating}", content, count=1)
    if status == "done":
        today = datetime.now().strftime("%Y-%m-%d")
        content = re.sub(r"\*\*Finished\*\*:.*", f"**Finished**: {today}", content, count=1)

    content = re.sub(r"updated: .+", f"updated: {now}", content, count=1)
    filepath.write_text(content, encoding="utf-8")
    return True


def save_attachment(data: bytes, book_title: str, page: str | None, ext: str = "jpg") -> str:
    settings.attachments_path.mkdir(parents=True, exist_ok=True)
    safe_book = sanitize_filename(book_title)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    page_part = f"-p{page}" if page else ""
    filename = f"{safe_book}{page_part}-{timestamp}.{ext}"
    filepath = settings.attachments_path / filename
    filepath.write_bytes(data)
    return filename


def create_atomic_note(
    title: str,
    idea: str,
    origin: str,
    page: str | None = None,
    note_type: str = "concept",
    related_mocs: list[str] | None = None,
    related_cards: list[str] | None = None,
) -> str:
    safe_title = sanitize_filename(title)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    moc_links = ""
    if related_mocs:
        moc_links = ", ".join(f"[[MOC - {m}]]" for m in related_mocs)

    card_links = ""
    if related_cards:
        card_links = "\n".join(f"- [[{c}]]" for c in related_cards)
    else:
        card_links = "- "

    page_ref = f", p.{page}" if page else ""
    content = f"""---
type: note
created: {now}
updated: {now}
tags:
  - status/seed
  - type/{note_type}
---

# {title}

## Idea

{idea}

## Context

- Origin: [[{origin}]]
- Related to: {moc_links if moc_links else ""}

## Connections

{card_links}

## References

- {origin}{page_ref}
"""

    settings.cards_path.mkdir(parents=True, exist_ok=True)
    filepath = settings.cards_path / f"{safe_title}.md"
    filepath.write_text(content, encoding="utf-8")
    return safe_title


def add_atomic_reference(book_title: str, card_title: str) -> bool:
    filepath = settings.encounters_path / f"{book_title}.md"
    if not filepath.exists():
        return False

    content = filepath.read_text(encoding="utf-8")
    ref_line = f"- [[{card_title}]]"

    if ref_line in content:
        return True

    lines = content.split("\n")
    start, end = _find_section_range(lines, "## Atomic Notes Extracted")
    if start == -1:
        lines.append("")
        lines.append("## Atomic Notes Extracted")
        lines.append("")
        lines.append(ref_line)
    else:
        insert_at = end
        for i in range(end - 1, start, -1):
            if lines[i].strip():
                insert_at = i + 1
                break
        else:
            insert_at = start + 1
        lines.insert(insert_at, ref_line)

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return True


def list_cards() -> list[str]:
    path = settings.cards_path
    if not path.exists():
        return []
    return [f.stem for f in path.glob("*.md")]


def list_mocs() -> list[str]:
    atlas_path = settings.vault_path / "Atlas"
    if not atlas_path.exists():
        return []
    return [f.stem.replace("MOC - ", "") for f in atlas_path.glob("MOC - *.md")]


# ============================================
# SEARCH FUNCTIONS
# ============================================

def search_vault(query: str) -> tuple[list[dict], list[dict]]:
    """
    Busca en Cards y Encounters por palabras clave.
    
    Args:
        query: Término de búsqueda
    
    Returns:
        Tupla de (cards_results, encounters_results)
        Cada resultado es un dict con 'title', 'snippet', 'path'
    """
    query_lower = query.lower()
    query_words = query_lower.split()
    
    cards_results: list[dict] = []
    encounters_results: list[dict] = []
    
    # Search in Cards
    for card_name in list_cards():
        filepath = settings.cards_path / f"{card_name}.md"
        if not filepath.exists():
            continue
        
        content = filepath.read_text(encoding="utf-8")
        content_lower = content.lower()
        
        # Check if query words appear in title or content
        if query_lower in card_name.lower() or any(word in content_lower for word in query_words):
            # Extract snippet around the match
            snippet = _extract_snippet(content, query_lower, max_length=150)
            cards_results.append({
                "title": card_name,
                "snippet": snippet,
                "path": str(filepath),
            })
    
    # Search in Encounters
    for encounter_name in list_encounters():
        filepath = settings.encounters_path / f"{encounter_name}.md"
        if not filepath.exists():
            continue
        
        content = filepath.read_text(encoding="utf-8")
        content_lower = content.lower()
        
        if query_lower in encounter_name.lower() or any(word in content_lower for word in query_words):
            # Find page references
            pages = _find_page_references(content, query_lower)
            snippet = f"Menciones en {len(pages)} página(s): {', '.join(pages[:5])}" if pages else _extract_snippet(content, query_lower, max_length=150)
            encounters_results.append({
                "title": encounter_name,
                "snippet": snippet,
                "path": str(filepath),
                "pages": pages,
            })
    
    return cards_results, encounters_results


def _extract_snippet(content: str, query: str, max_length: int = 150) -> str:
    """Extrae un fragmento de texto alrededor de la primera aparición del query."""
    content_lower = content.lower()
    idx = content_lower.find(query)
    
    if idx == -1:
        # Just return first lines
        lines = content.split('\n')
        for line in lines:
            if line.strip() and not line.startswith('#'):
                return line.strip()[:max_length]
        return content[:max_length]
    
    start = max(0, idx - 50)
    end = min(len(content), idx + max_length)
    snippet = content[start:end].strip()
    
    # Clean up the snippet
    snippet = re.sub(r'\s+', ' ', snippet)
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    
    return snippet


def _find_page_references(content: str, query: str) -> list[str]:
    """Encuentra todas las referencias de página que contienen el query."""
    # Pattern to find page references like p.47, p.123
    page_pattern = re.compile(r'p\.(\d+|[a-z]+)', re.IGNORECASE)
    
    pages: list[str] = []
    lines = content.split('\n')
    
    for line in lines:
        if query in line.lower():
            matches = page_pattern.findall(line)
            for match in matches:
                pages.append(match)
    
    # Deduplicate and sort
    unique_pages = list(set(pages))
    try:
        # Try to sort numerically
        return sorted(unique_pages, key=lambda x: int(x) if x.isdigit() else 0)
    except ValueError:
        return unique_pages


# ============================================
# READING DASHBOARD FUNCTIONS
# ============================================

def get_reading_dashboard() -> list[dict]:
    """
    Obtiene lista de libros con su estado de lectura.
    
    Returns:
        Lista de dicts con información de cada libro
    """
    books: list[dict] = []
    
    for encounter_name in list_encounters():
        filepath = settings.encounters_path / f"{encounter_name}.md"
        if not filepath.exists():
            continue
        
        content = filepath.read_text(encoding="utf-8")
        metadata = _parse_encounter_metadata(content)
        entries_count = count_bookmarks(encounter_name)
        
        books.append({
            "title": encounter_name,
            "author": metadata.get("author", ""),
            "status": metadata.get("status", "in-progress"),
            "rating": metadata.get("rating", 0),
            "entries_count": entries_count,
            "updated": metadata.get("updated", ""),
            "finished": metadata.get("finished", ""),
        })
    
    # Sort by updated date (most recent first)
    books.sort(key=lambda x: x["updated"], reverse=True)
    
    return books


def _parse_encounter_metadata(content: str) -> dict:
    """Extrae metadatos del frontmatter y contenido de un Encounter."""
    metadata: dict = {}
    
    # Parse frontmatter
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        fm_content = fm_match.group(1)
        
        # Extract status
        status_match = re.search(r'status:\s*(\w+)', fm_content)
        if status_match:
            metadata["status"] = status_match.group(1)
        
        # Extract rating
        rating_match = re.search(r'rating:\s*(\d*)', fm_content)
        if rating_match and rating_match.group(1):
            metadata["rating"] = int(rating_match.group(1))
        
        # Extract author
        author_match = re.search(r'author:\s*(.+)', fm_content)
        if author_match:
            metadata["author"] = author_match.group(1).strip().strip('"')
        
        # Extract updated
        updated_match = re.search(r'updated:\s*(.+)', fm_content)
        if updated_match:
            metadata["updated"] = updated_match.group(1).strip()
    
    # Extract finished date from content
    finished_match = re.search(r'\*\*Finished\*\*:\s*(.+)', content)
    if finished_match:
        metadata["finished"] = finished_match.group(1).strip()
    
    # Extract author from content (fallback)
    if "author" not in metadata:
        author_content_match = re.search(r'\*\*Author\*\*:\s*(.+)', content)
        if author_content_match:
            metadata["author"] = author_content_match.group(1).strip()
    
    return metadata


def count_bookmarks(book_title: str) -> int:
    """
    Cuenta las entradas en la sección Bookmarks de un Encounter.
    
    Args:
        book_title: Título del libro
    
    Returns:
        Número de entradas en Bookmarks
    """
    content = read_encounter(book_title)
    if not content:
        return 0
    
    lines = content.split('\n')
    
    # Find Bookmarks section
    bookmarks_start, bookmarks_end = _find_section_range(lines, "## Bookmarks")
    
    if bookmarks_start == -1:
        return 0
    
    # Count non-empty, non-heading lines in Bookmarks section
    count = 0
    in_subsection = False
    
    for i in range(bookmarks_start + 1, bookmarks_end):
        line = lines[i].strip()
        
        # Skip empty lines
        if not line:
            continue
        
        # Skip section headings
        if line.startswith('#'):
            in_subsection = line.startswith('###')
            continue
        
        # Count content lines
        if in_subsection and line:
            count += 1
    
    return count


def get_all_bookmarks(book_title: str) -> str:
    """
    Extrae todo el contenido de la sección Bookmarks.
    
    Args:
        book_title: Título del libro
    
    Returns:
        Texto completo de los bookmarks
    """
    content = read_encounter(book_title)
    if not content:
        return ""
    
    lines = content.split('\n')
    bookmarks_start, bookmarks_end = _find_section_range(lines, "## Bookmarks")
    
    if bookmarks_start == -1:
        return ""
    
    return '\n'.join(lines[bookmarks_start:bookmarks_end])


def update_encounter_summary(book_title: str, summary: str, key_ideas: list[str]) -> bool:
    """
    Actualiza las secciones Summary y Key Ideas de un Encounter.
    
    Args:
        book_title: Título del libro
        summary: Resumen generado
        key_ideas: Lista de ideas clave
    
    Returns:
        True si se actualizó correctamente
    """
    filepath = settings.encounters_path / f"{book_title}.md"
    if not filepath.exists():
        return False
    
    content = filepath.read_text(encoding="utf-8")
    lines = content.split('\n')
    
    # Update Summary section
    summary_start, summary_end = _find_section_range(lines, "## Summary")
    if summary_start != -1:
        # Find the end of current summary (next heading or end of section)
        end_idx = summary_end
        for i in range(summary_start + 1, summary_end):
            if lines[i].strip().startswith('#'):
                end_idx = i
                break
        
        # Replace summary content
        summary_lines = [f"> {summary}"]
        lines = lines[:summary_start + 1] + summary_lines + lines[end_idx:]
    
    # Update Key Ideas section
    content = '\n'.join(lines)
    lines = content.split('\n')
    
    keyideas_start, keyideas_end = _find_section_range(lines, "## Key Ideas")
    if keyideas_start != -1:
        end_idx = keyideas_end
        for i in range(keyideas_start + 1, keyideas_end):
            if lines[i].strip().startswith('#'):
                end_idx = i
                break
        
        # Replace key ideas
        ideas_lines = [f"{i+1}. {idea}" for i, idea in enumerate(key_ideas)]
        lines = lines[:keyideas_start + 1] + ideas_lines + lines[end_idx:]
    
    # Update timestamp
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = '\n'.join(lines)
    content = re.sub(r'updated: .+', f'updated: {now}', content, count=1)
    
    filepath.write_text(content, encoding="utf-8")
    return True


# ============================================
# ORPHAN CARDS FUNCTIONS
# ============================================

def find_orphan_cards() -> list[dict]:
    """
    Encuentra Cards que no están enlazadas a ningún MOC.
    
    Returns:
        Lista de dicts con información de Cards huérfanas
    """
    orphans: list[dict] = []
    
    # Get all MOCs for reference
    mocs = list_mocs()
    
    for card_name in list_cards():
        filepath = settings.cards_path / f"{card_name}.md"
        if not filepath.exists():
            continue
        
        content = filepath.read_text(encoding="utf-8")
        
        # Check if card links to any MOC
        has_moc_link = False
        for moc in mocs:
            if f"[[MOC - {moc}]]" in content or f"[[MOC - {moc}" in content:
                has_moc_link = True
                break
        
        if not has_moc_link:
            # Extract first lines of content
            lines = content.split('\n')
            snippet = ""
            for line in lines:
                if line.strip() and not line.startswith('#') and not line.startswith('---'):
                    snippet = line.strip()[:100]
                    break
            
            orphans.append({
                "title": card_name,
                "snippet": snippet,
                "path": str(filepath),
            })
    
    return orphans


def get_moc_contents() -> dict[str, str]:
    """
    Obtiene el contenido de todos los MOCs.
    
    Returns:
        Dict con nombre MOC -> contenido
    """
    mocs_content: dict[str, str] = {}
    atlas_path = settings.vault_path / "Atlas"
    
    if not atlas_path.exists():
        return mocs_content
    
    for moc_file in atlas_path.glob("MOC - *.md"):
        moc_name = moc_file.stem.replace("MOC - ", "")
        content = moc_file.read_text(encoding="utf-8")
        mocs_content[moc_name] = content
    
    return mocs_content


def suggest_moc_connections(card_title: str, card_content: str) -> list[str]:
    """
    Sugiere MOCs relacionados basándose en el contenido de la Card.
    Esta función usa coincidencia simple de palabras clave.
    Para mejor resultados, usar la versión LLM.
    
    Args:
        card_title: Título de la Card
        card_content: Contenido de la Card
    
    Returns:
        Lista de MOCs sugeridos
    """
    # Keywords mapped to MOCs
    keyword_mocs: dict[str, list[str]] = {
        "productividad": ["Productivity"],
        "productivity": ["Productivity"],
        "trabajo": ["Productivity", "Development"],
        "work": ["Productivity"],
        "liderazgo": ["Leadership"],
        "leadership": ["Leadership"],
        "gestión": ["Leadership", "Business"],
        "management": ["Leadership", "Business"],
        "negocio": ["Business"],
        "business": ["Business"],
        "desarrollo": ["Development"],
        "development": ["Development"],
        "programming": ["Development"],
        "código": ["Development"],
        "code": ["Development"],
        "finanzas": ["Finance"],
        "finance": ["Finance"],
        "money": ["Finance"],
        "salud": ["Health"],
        "health": ["Health"],
        "bienestar": ["Health"],
        "tecnología": ["Development"],
        "technology": ["Development"],
        "tech": ["Development"],
        "equipo": ["Leadership"],
        "team": ["Leadership"],
        "personas": ["People"],
        "people": ["People"],
        "arquitectura": ["Development"],
        "architecture": ["Development"],
        "estrategia": ["Business", "Leadership"],
        "strategy": ["Business", "Leadership"],
    }
    
    search_text = (card_title + " " + card_content).lower()
    
    suggested_mocs: set[str] = set()
    for keyword, mocs in keyword_mocs.items():
        if keyword in search_text:
            suggested_mocs.update(mocs)
    
    # Filter to existing MOCs
    existing_mocs = set(list_mocs())
    valid_suggestions = list(suggested_mocs.intersection(existing_mocs))
    
    return valid_suggestions


def link_card_to_moc(card_title: str, moc_names: list[str]) -> bool:
    """
    Añade enlaces a MOCs en una Card.
    
    Args:
        card_title: Título de la Card
        moc_names: Lista de nombres de MOCs
    
    Returns:
        True si se actualizó correctamente
    """
    filepath = settings.cards_path / f"{card_title}.md"
    if not filepath.exists():
        return False
    
    content = filepath.read_text(encoding="utf-8")
    
    # Find the Context section
    lines = content.split('\n')
    context_start, context_end = _find_section_range(lines, "## Context")
    
    if context_start == -1:
        # Add Context section after frontmatter
        lines = content.split('\n')
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('---') and i > 0:
                insert_idx = i + 1
                break
        
        new_lines = [
            "",
            "## Context",
            "",
            f"- Related to: {', '.join(f'[[MOC - {m}]]' for m in moc_names)}",
        ]
        lines = lines[:insert_idx] + new_lines + lines[insert_idx:]
    else:
        # Update existing Related to field
        found_related = False
        for i in range(context_start, context_end):
            if lines[i].startswith("- Related to:"):
                # Check if already has some MOCs
                existing = lines[i].split("- Related to:")[-1].strip()
                if existing and existing != "":
                    # Add new MOCs to existing
                    new_mocs = [f"[[MOC - {m}]]" for m in moc_names if m not in existing]
                    if new_mocs:
                        lines[i] = f"- Related to: {existing}, {', '.join(new_mocs)}"
                else:
                    lines[i] = f"- Related to: {', '.join(f'[[MOC - {m}]]' for m in moc_names)}"
                found_related = True
                break
        
        if not found_related:
            # Add Related to line
            insert_idx = context_start + 1
            lines.insert(insert_idx, f"- Related to: {', '.join(f'[[MOC - {m}]]' for m in moc_names)}")
    
    # Update timestamp
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = '\n'.join(lines)
    content = re.sub(r'updated: .+', f'updated: {now}', content, count=1)
    
    filepath.write_text(content, encoding="utf-8")
    return True


def get_card_content(card_title: str) -> str | None:
    """
    Obtiene el contenido completo de una Card.
    
    Args:
        card_title: Título de la Card
    
    Returns:
        Contenido de la Card o None si no existe
    """
    filepath = settings.cards_path / f"{card_title}.md"
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return None
