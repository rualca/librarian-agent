from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class EntryType(str, Enum):
    IDEA = "idea"
    QUOTE = "quote"
    PROBLEM_SOLUTION = "problem_solution"
    CHAPTER_SUMMARY = "chapter_summary"
    KEY_TAKEAWAY = "key_takeaway"
    THOUGHT = "thought"
    ACTION_ITEM = "action_item"

    @property
    def icon(self) -> str:
        return {
            "idea": "💡",
            "quote": "💬",
            "problem_solution": "🔧",
            "chapter_summary": "📖",
            "key_takeaway": "🔑",
            "thought": "💭",
            "action_item": "✅",
        }[self.value]

    @property
    def section_heading(self) -> str:
        return {
            "idea": "### 💡 Ideas & Concepts",
            "quote": "### 💬 Quotes & Phrases",
            "problem_solution": "### 🔧 Problems & Solutions",
            "chapter_summary": "### 📖 Chapter Summaries",
            "key_takeaway": "### 🔑 Key Takeaways",
            "thought": "## My Thoughts",
            "action_item": "## Action Items",
        }[self.value]


class SourceType(str, Enum):
    BOOK = "book"
    ARTICLE = "article"
    PODCAST = "podcast"
    VIDEO = "video"
    COURSE = "course"
    TALK = "talk"


@dataclass
class ExtractedEntry:
    entry_type: EntryType
    content: str
    page: str | None = None
    chapter: str | None = None
    is_verbatim: bool = False
    confidence: float = 1.0
    needs_clarification: str | None = None

    def to_markdown(self) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        page_ref = f"p.{self.page}" if self.page else "p.??"
        lines: list[str] = []

        if self.entry_type == EntryType.QUOTE:
            lines.append(f'> "{self.content}"')
            lines.append(f"> — {page_ref}")
        elif self.entry_type == EntryType.PROBLEM_SOLUTION:
            lines.append(f"- **{page_ref}** — {self.content}")
        elif self.entry_type == EntryType.CHAPTER_SUMMARY:
            chapter_label = self.chapter or "?"
            lines.append(f"#### {chapter_label}")
            lines.append(f"- {self.content}")
        elif self.entry_type == EntryType.THOUGHT:
            lines.append(f"- {self.content}")
        elif self.entry_type == EntryType.ACTION_ITEM:
            lines.append(f"- [ ] {self.content}")
        else:
            lines.append(f"- **{page_ref}** — {self.content}")

        lines.append(f"<!-- capture:{timestamp} -->")
        return "\n".join(lines)


@dataclass
class AtomicNoteProposal:
    title: str
    idea: str
    origin: str
    page: str | None = None
    note_type: str = "concept"
    related_mocs: list[str] = field(default_factory=list)
    related_cards: list[str] = field(default_factory=list)


@dataclass
class LLMResult:
    entries: list[ExtractedEntry] = field(default_factory=list)
    book_title: str | None = None
    book_author: str | None = None
    atomic_proposals: list[AtomicNoteProposal] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    raw_response: str = ""


class TurnRole(str, Enum):
    USER = "user"
    BOT = "bot"
    EVENT = "event"


class TurnKind(str, Enum):
    TEXT = "text"
    PHOTO = "photo"
    VOICE = "voice"
    COMMAND = "command"
    RESULT = "result"


@dataclass
class HistoryTurn:
    ts: datetime
    role: TurnRole
    kind: TurnKind
    text: str
    book: str | None = None


MAX_TURNS = 200
MAX_TURN_CHARS = 800
MAX_CONTEXT_CHARS = 6000
CONTEXT_TTL = timedelta(hours=3)
KEEP_LAST_TURNS = 30


@dataclass
class ConversationMemory:
    turns: deque[HistoryTurn] = field(default_factory=lambda: deque(maxlen=MAX_TURNS))
    summary: str = ""
    last_activity: datetime | None = None


@dataclass
class SessionContext:
    active_book: str | None = None
    active_author: str | None = None
    is_dump_session: bool = False
    pending_retries: list[str] = field(default_factory=list)
    pending_atomic: list[AtomicNoteProposal] = field(default_factory=list)
    entries_this_session: int = 0
    memory: ConversationMemory = field(default_factory=ConversationMemory)
