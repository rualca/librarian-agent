"""Examiner module — spaced repetition and active recall for the vault.

Handles question generation, answer evaluation, and SM-2 spaced
repetition tracking for Encounters and Cards.
"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from src.config import settings
from src import vault, llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_ITEMS_FOR_QUIZ = 1
DEFAULT_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3
DEFAULT_QUIZ_COUNT = 3
DEEP_EXAM_COUNT = 8


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class ReviewItem:
    """A single trackable item (Card or Encounter entry)."""
    item_id: str  # e.g. "card:CTO stress factors" or "encounter:The Systemic CTO"
    item_type: str  # "card" or "encounter"
    title: str
    last_reviewed: str | None = None
    next_review: str | None = None
    ease_factor: float = DEFAULT_EASE_FACTOR
    interval_days: int = 0
    repetitions: int = 0
    history: list[dict] = field(default_factory=list)


@dataclass
class QuizQuestion:
    """A generated question for the user."""
    question: str
    source_title: str
    source_type: str  # "card" or "encounter"
    question_type: str  # "recall", "application", "connection", "contrast", "synthesis", "truefalse"
    reference: str = ""  # e.g. "p.47" or section name
    expected_answer: str = ""  # for the bot to evaluate against


@dataclass
class QuizSession:
    """In-memory state for an active quiz."""
    questions: list[QuizQuestion] = field(default_factory=list)
    current_index: int = 0
    scores: list[int] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    active: bool = False

    @property
    def current_question(self) -> QuizQuestion | None:
        if 0 <= self.current_index < len(self.questions):
            return self.questions[self.current_index]
        return None

    @property
    def is_complete(self) -> bool:
        return self.current_index >= len(self.questions)

    @property
    def total(self) -> int:
        return len(self.questions)


# ---------------------------------------------------------------------------
# Tracker persistence
# ---------------------------------------------------------------------------
def _tracker_path() -> Path:
    return settings.vault_path / "copilot" / "exam-tracker.json"


def load_tracker() -> dict:
    """Load the exam tracker from disk."""
    path = _tracker_path()
    if not path.exists():
        return {"cards": {}, "encounters": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"cards": {}, "encounters": {}}
        data.setdefault("cards", {})
        data.setdefault("encounters", {})
        return data
    except (json.JSONDecodeError, OSError):
        logger.warning("Exam tracker corrupted, starting fresh")
        return {"cards": {}, "encounters": {}}


def save_tracker(data: dict) -> None:
    """Save the exam tracker to disk."""
    path = _tracker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# SM-2 algorithm
# ---------------------------------------------------------------------------
def _sm2_update(
    score: int,
    repetitions: int,
    ease_factor: float,
    interval_days: int,
) -> tuple[int, float, int]:
    """Apply SM-2 algorithm and return (new_repetitions, new_ease, new_interval)."""
    if score < 3:
        return 0, max(MIN_EASE_FACTOR, ease_factor), 1

    # Update ease factor
    new_ease = ease_factor + 0.1 - (5 - score) * (0.08 + (5 - score) * 0.02)
    new_ease = max(MIN_EASE_FACTOR, new_ease)

    if repetitions == 0:
        new_interval = 1
    elif repetitions == 1:
        new_interval = 3
    else:
        new_interval = max(1, round(interval_days * new_ease))

    return repetitions + 1, new_ease, new_interval


def record_review(item_type: str, title: str, score: int) -> dict:
    """Record a review result and update the tracker.

    Returns the updated item dict.
    """
    tracker = load_tracker()
    section = "cards" if item_type == "card" else "encounters"

    item = tracker[section].get(title, {
        "last_reviewed": None,
        "next_review": None,
        "ease_factor": DEFAULT_EASE_FACTOR,
        "interval_days": 0,
        "repetitions": 0,
        "history": [],
    })

    reps = item.get("repetitions", 0)
    ease = item.get("ease_factor", DEFAULT_EASE_FACTOR)
    interval = item.get("interval_days", 0)

    new_reps, new_ease, new_interval = _sm2_update(score, reps, ease, interval)

    today = datetime.now().strftime("%Y-%m-%d")
    next_date = (datetime.now() + timedelta(days=new_interval)).strftime("%Y-%m-%d")

    item["last_reviewed"] = today
    item["next_review"] = next_date
    item["ease_factor"] = round(new_ease, 2)
    item["interval_days"] = new_interval
    item["repetitions"] = new_reps
    item["history"].append({"date": today, "score": score})
    # Keep history bounded
    if len(item["history"]) > 50:
        item["history"] = item["history"][-50:]

    tracker[section][title] = item
    save_tracker(tracker)
    return item


# ---------------------------------------------------------------------------
# Content gathering
# ---------------------------------------------------------------------------
def _extract_encounter_entries(title: str) -> list[dict]:
    """Extract reviewable entries from an Encounter note."""
    content = vault.read_encounter(title)
    if not content:
        return []

    entries: list[dict] = []
    lines = content.split("\n")

    current_section = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("### ") or line.startswith("## "):
            current_section = line
            i += 1
            continue

        # Skip non-content sections
        skip_sections = ["## Metadata", "## Action Items", "## Atomic Notes Extracted"]
        if any(current_section.startswith(s) for s in skip_sections):
            i += 1
            continue

        # Skip empty lines, comments, and placeholder content
        if (
            not line
            or line.startswith("<!--")
            or line.startswith(">")
            and "One-paragraph summary" in line
            or line == "1."
            or line == "2."
            or line == "3."
            or "[illegible]" in line
        ):
            i += 1
            continue

        # Collect quotes (multi-line)
        if line.startswith("> "):
            quote_lines = [line]
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith(">"):
                stripped = lines[j].strip()
                if not stripped.startswith("<!--"):
                    quote_lines.append(stripped)
                j += 1
            quote_text = "\n".join(quote_lines)
            if "[illegible]" not in quote_text and "One-paragraph summary" not in quote_text:
                entries.append({
                    "content": quote_text,
                    "section": current_section,
                    "type": "quote",
                })
            i = j
            continue

        # Collect bullet entries
        if line.startswith("- **p.") or line.startswith("- "):
            if "[illegible]" not in line and len(line) > 10:
                entries.append({
                    "content": line,
                    "section": current_section,
                    "type": "entry",
                })
            i += 1
            continue

        # Chapter summaries
        if line.startswith("#### "):
            # Collect the summary text below
            summary_lines = [line]
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith("#"):
                stripped = lines[j].strip()
                if not stripped.startswith("<!--"):
                    summary_lines.append(stripped)
                j += 1
            summary_text = "\n".join(summary_lines)
            if "[illegible]" not in summary_text and len(summary_text) > 20:
                entries.append({
                    "content": summary_text,
                    "section": current_section,
                    "type": "chapter_summary",
                })
            i = j
            continue

        i += 1

    return entries


def _extract_card_content(title: str) -> dict | None:
    """Extract reviewable content from a Card."""
    content = vault.get_card_content(title)
    if not content:
        return None

    lines = content.split("\n")

    # Extract the Idea section
    idea_text = ""
    in_idea = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Idea":
            in_idea = True
            continue
        if in_idea and stripped.startswith("## "):
            break
        if in_idea and stripped and not stripped.startswith("<!--"):
            idea_text += stripped + " "

    idea_text = idea_text.strip()
    if not idea_text or "[illegible]" in idea_text:
        return None

    # Extract connections
    connections: list[str] = []
    in_connections = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Connections":
            in_connections = True
            continue
        if in_connections and stripped.startswith("## "):
            break
        if in_connections and stripped.startswith("- [["):
            link = stripped.replace("- ", "").strip()
            connections.append(link)

    # Extract origin
    origin = ""
    for line in lines:
        if "Origin:" in line:
            origin = line.split("Origin:")[-1].strip()
            break

    # Detect status from tags
    status = "seed"
    for line in lines:
        if "status/evergreen" in line:
            status = "evergreen"
            break

    return {
        "title": title,
        "idea": idea_text,
        "connections": connections,
        "origin": origin,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Reviewable items
# ---------------------------------------------------------------------------
def get_reviewable_items() -> list[dict]:
    """Get all items that can be quizzed on.

    Returns a list of dicts with type, title, and content.
    """
    items: list[dict] = []

    # Cards
    for card_name in vault.list_cards():
        card = _extract_card_content(card_name)
        if card and card["idea"]:
            items.append({
                "type": "card",
                "title": card_name,
                "content": card["idea"],
                "connections": card.get("connections", []),
                "origin": card.get("origin", ""),
                "status": card.get("status", "seed"),
            })

    # Encounters
    for enc_name in vault.list_encounters():
        entries = _extract_encounter_entries(enc_name)
        if entries:
            # Check encounter status
            enc_content = vault.read_encounter(enc_name) or ""
            status = "in-progress"
            if "status: done" in enc_content:
                status = "done"

            combined = "\n".join(e["content"] for e in entries)
            items.append({
                "type": "encounter",
                "title": enc_name,
                "content": combined[:3000],
                "entries": entries,
                "status": status,
            })

    return items


def get_due_items() -> list[dict]:
    """Get items due for spaced repetition review (overdue or never reviewed)."""
    tracker = load_tracker()
    reviewable = get_reviewable_items()
    today = datetime.now().strftime("%Y-%m-%d")

    due: list[dict] = []
    for item in reviewable:
        section = "cards" if item["type"] == "card" else "encounters"
        tracked = tracker[section].get(item["title"])

        if not tracked:
            # Never reviewed — due immediately
            item["priority"] = 0
            item["never_reviewed"] = True
            due.append(item)
        elif tracked.get("next_review", "9999-99-99") <= today:
            item["priority"] = 1
            item["never_reviewed"] = False
            item["ease_factor"] = tracked.get("ease_factor", DEFAULT_EASE_FACTOR)
            due.append(item)

    # Sort: overdue first (by priority), then by ease (harder first)
    due.sort(key=lambda x: (x.get("priority", 99), x.get("ease_factor", DEFAULT_EASE_FACTOR)))
    return due


# ---------------------------------------------------------------------------
# Question generation via LLM
# ---------------------------------------------------------------------------
QUIZ_SYSTEM_PROMPT = """Eres el Examinador, un agente de repaso activo para un Second Brain en Obsidian.
Tu tarea es generar preguntas que ayuden al usuario a retener el conocimiento capturado.

REGLAS:
1. Las preguntas deben estar basadas EXCLUSIVAMENTE en el contenido proporcionado.
2. NUNCA inventes información que no esté en el contenido.
3. Incluye una respuesta esperada para cada pregunta (para evaluación posterior).
4. Varía los tipos de preguntas: recall, application, synthesis, connection.
5. Las preguntas deben ser en ESPAÑOL.
6. Las citas se mantienen en su idioma original.
7. Sé conciso — el usuario puede estar en el móvil.
8. Para contenido de libros in-progress, no asumas nada más allá del contenido dado.

TIPOS DE PREGUNTAS:
- "recall": Recordar un dato o concepto específico
- "application": Aplicar un concepto a una situación real
- "synthesis": Explicar un concepto en sus propias palabras
- "connection": Relacionar dos o más conceptos
- "contrast": Comparar o diferenciar conceptos
- "truefalse": Verdadero o falso (incluir la respuesta correcta)

RESPONSE JSON SCHEMA:
{
  "questions": [
    {
      "question": "La pregunta en español",
      "type": "recall|application|synthesis|connection|contrast|truefalse",
      "reference": "p.47 o nombre de sección",
      "expected_answer": "La respuesta correcta resumida"
    }
  ]
}
"""

EVALUATE_SYSTEM_PROMPT = """Eres el Examinador evaluando la respuesta de un usuario a una pregunta de repaso.

REGLAS:
1. Evalúa en una escala de 0-5 (compatible con SM-2):
   - 5: Perfecto — completo, preciso, muestra comprensión profunda
   - 4: Bien — correcto con detalles menores faltantes
   - 3: Aceptable — idea central correcta pero faltan detalles importantes
   - 2: Parcial — algunos elementos correctos pero gaps significativos
   - 1: Incorrecto — muestra confusión sobre el concepto
   - 0: Sin recuerdo — completamente incorrecto o "no sé"
2. Acepta respuestas en CUALQUIER idioma.
3. Acepta parafraseo — no exijas repetición verbatim.
4. Sé generoso con sinónimos y conceptos equivalentes.
5. Si la respuesta es parcial, reconoce lo correcto antes de explicar lo faltante.
6. Da feedback en ESPAÑOL.
7. Incluye la referencia a la fuente en el feedback.

RESPONSE JSON SCHEMA:
{
  "score": 0-5,
  "emoji": "✅|🟡|❌",
  "feedback": "Feedback conciso en español",
  "correct_answer": "La respuesta correcta resumida (solo si score < 4)",
  "tip": "Un tip o mnemotécnico para recordar (opcional, solo si score < 3)"
}
"""


def generate_questions(
    content: str,
    source_title: str,
    source_type: str,
    count: int = DEFAULT_QUIZ_COUNT,
    question_types: list[str] | None = None,
) -> list[QuizQuestion]:
    """Generate quiz questions for the given content using LLM."""
    types_hint = ""
    if question_types:
        types_hint = f"\nFocus on these question types: {', '.join(question_types)}"

    user_msg = (
        f"Genera {count} preguntas sobre el siguiente contenido.\n"
        f"Fuente: {source_title} ({source_type})\n"
        f"{types_hint}\n\n"
        f"--- CONTENIDO ---\n{content[:4000]}"
    )

    messages = [
        {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        client = llm._create_client()
        response = client.chat.completions.create(
            model=settings.active_model,
            messages=messages,
            max_tokens=2048,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)

        questions: list[QuizQuestion] = []
        for q in data.get("questions", []):
            questions.append(QuizQuestion(
                question=q.get("question", ""),
                source_title=source_title,
                source_type=source_type,
                question_type=q.get("type", "recall"),
                reference=q.get("reference", ""),
                expected_answer=q.get("expected_answer", ""),
            ))
        return questions

    except Exception:
        logger.exception("Failed to generate quiz questions")
        return []


def generate_connection_questions(items: list[dict], count: int = DEFAULT_QUIZ_COUNT) -> list[QuizQuestion]:
    """Generate questions that connect concepts across different sources."""
    if len(items) < 2:
        return []

    # Pick random pairs
    pairs_content: list[str] = []
    sampled = random.sample(items, min(len(items), count * 2))
    for i in range(0, len(sampled) - 1, 2):
        a, b = sampled[i], sampled[i + 1]
        pairs_content.append(
            f"--- Item A: {a['title']} ({a['type']}) ---\n{a['content'][:500]}\n\n"
            f"--- Item B: {b['title']} ({b['type']}) ---\n{b['content'][:500]}"
        )

    user_msg = (
        f"Genera {count} preguntas de CONEXIÓN entre los siguientes pares de notas.\n"
        f"Pregunta cómo se relacionan, en qué difieren, o cómo un concepto complementa al otro.\n\n"
        + "\n\n".join(pairs_content)
    )

    messages = [
        {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        client = llm._create_client()
        response = client.chat.completions.create(
            model=settings.active_model,
            messages=messages,
            max_tokens=2048,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)

        questions: list[QuizQuestion] = []
        for q in data.get("questions", []):
            questions.append(QuizQuestion(
                question=q.get("question", ""),
                source_title="Conexiones",
                source_type="connection",
                question_type="connection",
                reference=q.get("reference", ""),
                expected_answer=q.get("expected_answer", ""),
            ))
        return questions

    except Exception:
        logger.exception("Failed to generate connection questions")
        return []


def evaluate_answer(
    question: QuizQuestion,
    user_answer: str,
) -> dict:
    """Evaluate a user's answer using LLM. Returns score, emoji, feedback."""
    user_msg = (
        f"PREGUNTA: {question.question}\n"
        f"RESPUESTA ESPERADA: {question.expected_answer}\n"
        f"FUENTE: {question.source_title} ({question.reference})\n\n"
        f"RESPUESTA DEL USUARIO: {user_answer}"
    )

    messages = [
        {"role": "system", "content": EVALUATE_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        client = llm._create_client()
        response = client.chat.completions.create(
            model=settings.active_model,
            messages=messages,
            max_tokens=512,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)

        return {
            "score": min(5, max(0, data.get("score", 0))),
            "emoji": data.get("emoji", "🟡"),
            "feedback": data.get("feedback", ""),
            "correct_answer": data.get("correct_answer", ""),
            "tip": data.get("tip", ""),
        }

    except Exception:
        logger.exception("Failed to evaluate answer")
        return {
            "score": 0,
            "emoji": "❓",
            "feedback": "Error al evaluar la respuesta.",
            "correct_answer": question.expected_answer,
            "tip": "",
        }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def get_stats() -> dict:
    """Compute retention statistics from the tracker."""
    tracker = load_tracker()
    today = datetime.now().strftime("%Y-%m-%d")

    total_tracked = 0
    reviewed_today = 0
    due_count = 0
    all_scores: list[int] = []
    strengths: list[dict] = []
    needs_work: list[dict] = []
    upcoming_tomorrow = 0
    upcoming_week = 0

    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    for section in ("cards", "encounters"):
        for title, item in tracker.get(section, {}).items():
            total_tracked += 1

            if item.get("last_reviewed") == today:
                reviewed_today += 1

            next_rev = item.get("next_review", "9999-99-99")
            if next_rev <= today:
                due_count += 1
            elif next_rev <= tomorrow:
                upcoming_tomorrow += 1
            elif next_rev <= week_end:
                upcoming_week += 1

            for h in item.get("history", []):
                all_scores.append(h.get("score", 0))

            ease = item.get("ease_factor", DEFAULT_EASE_FACTOR)
            entry = {"title": title, "type": section, "ease": ease}
            if ease >= 2.5:
                strengths.append(entry)
            elif ease < 2.0:
                needs_work.append(entry)

    strengths.sort(key=lambda x: x["ease"], reverse=True)
    needs_work.sort(key=lambda x: x["ease"])

    avg_retention = 0.0
    if all_scores:
        avg_retention = round(sum(all_scores) / len(all_scores) / 5 * 100, 1)

    reviewable = get_reviewable_items()
    never_reviewed = len(reviewable) - total_tracked

    return {
        "total_tracked": total_tracked,
        "total_reviewable": len(reviewable),
        "never_reviewed": never_reviewed,
        "reviewed_today": reviewed_today,
        "due_count": due_count,
        "avg_retention": avg_retention,
        "strengths": strengths[:5],
        "needs_work": needs_work[:5],
        "upcoming_tomorrow": upcoming_tomorrow,
        "upcoming_week": upcoming_week,
    }
