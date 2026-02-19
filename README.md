# 🧠 Librarian Agent

## The Problem

Building a **Second Brain** in Obsidian is powerful, but two friction points kill consistency:

1. **Capture friction** — Taking photos → transferring to computer → OCR → formatting → filing. Manually organizing notes, remembering which books you're reading, and linking related ideas.
2. **Retention gap** — Notes accumulate but knowledge fades. Without active recall, your vault becomes a graveyard of forgotten ideas.

The result? A vault that grows slower than your reading list, and one you barely remember.

---

## The Solution

**Librarian Agent** is an AI-powered Telegram bot + OpenCode agent system that acts as your personal reading assistant **and** knowledge coach. Send photos, voice notes, or text directly from your phone — it handles the entire capture-to-retention pipeline for your Obsidian vault.

### What It Does

| Input | What Happens |
|-------|-------------|
| 📸 Photo of a book page | Extracts text, identifies page number, classifies content type |
| 📷 Book cover photo | Identifies title/author via Open Library, creates Encounter note |
| 💬 Text message | Classifies as quote, idea, or reflection, stores appropriately |
| 🎤 Voice note | Transcribes with Whisper, processes into actionable notes |
| 🧠 Universal ideas | Suggests Zettelkasten atomic notes, creates on confirmation |
| 🧪 Quiz / Exam | Generates questions from your vault, evaluates answers, tracks retention |

### Key Features

- **Intelligent Classification** — AI determines if content is a quote, idea, or reflection
- **Atomic Note Suggestions** — Identifies universal concepts → proposes Zettelkasten notes
- **Duplicate Detection** — Won't pollute your vault with repeated entries
- **Batch Capture** — `/dump` command for bulk scanning sessions
- **Reading Dashboard** — Track in-progress books with `/reading`
- **Semantic Search** — AI-powered vault search with `/search --ai`
- **Orphan Management** — Find and auto-link unconnected Cards to MOCs
- **Spaced Repetition** — SM-2 algorithm tracks what you're forgetting and schedules reviews
- **Active Recall Quizzes** — AI-generated questions from your own notes
- **Daily Retention Quiz** — Automatic daily question delivered via Telegram
- **Agent Chaining** — Multi-agent pipelines for complex vault operations
- **Scheduled Jobs** — Automated weekly audits, connection suggestions, and daily quizzes
- **OpenCode Integration** — 8 specialized AI agents for vault maintenance via `/oc`

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Bot Framework | Python Telegram Bot (`telegram.ext`) |
| AI/LLM | Groq (Llama 4 Scout), OpenAI GPT-4o (fallback), Whisper |
| Embeddings | FAISS + OpenAI/Groq embeddings for semantic search |
| Knowledge Graph | Obsidian (Markdown, YAML frontmatter) |
| External APIs | Open Library (book metadata) |
| Deployment | Docker, Docker Compose |
| Agents | OpenCode AI agents (8 specialized agents) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        User                                 │
│   (Telegram: photo, voice, text, commands)                  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  Librarian Bot (Python)                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │   Handlers   │ │  AI Services │ │   Vault Manager      │ │
│  │  - photo     │ │  - Groq/     │ │   - file ops         │ │
│  │  - voice     │ │    OpenAI    │ │   - templates        │ │
│  │  - text      │ │  - Whisper   │ │   - linking          │ │
│  │  - commands  │ │  - FAISS     │ │   - dedup            │ │
│  │  - quiz/exam │ │  - semantic  │ │   - search           │ │
│  └──────────────┘ │    search    │ └──────────────────────┘ │
│  ┌──────────────┐ └──────────────┘ ┌──────────────────────┐ │
│  │  Examiner    │                  │   Scheduler          │ │
│  │  - SM-2 algo │                  │   - daily quiz       │ │
│  │  - quiz gen  │                  │   - weekly audits    │ │
│  │  - answer    │                  │   - weekly connects  │ │
│  │    eval      │                  │   - stale detection  │ │
│  └──────────────┘                  └──────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              OpenCode Agent Bridge                      │ │
│  │  librarian · reviewer · connector · writer · archivist  │ │
│  │  examiner · developer · vision                          │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Obsidian Vault                             │
│   📚 Encounters  📄 Cards  🗺️ MOCs  🧪 Exam Tracker         │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Configure

```bash
cd bot && cp .env.example .env
```

Edit `.env` with your credentials:

```env
TELEGRAM_BOT_TOKEN=your-bot-token
GROQ_API_KEY=your-groq-key
OPENAI_API_KEY=your-openai-key      # optional fallback
VAULT_PATH=/path/to/your/obsidian/vault
AUTHORIZED_USERS=your-telegram-user-id
LLM_PROVIDER=groq                   # or "openai"
```

### 2. Run with Docker

```bash
# From project root
VAULT_PATH=/path/to/your/obsidian/vault docker-compose up -d
```

### 3. Find Your Telegram User ID

Talk to [@userinfobot](https://t.me/userinfobot) to get your ID and add it to `AUTHORIZED_USERS`.

---

## Bot Commands

### Core Capture

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/book <title>` | Set active book for capture |
| `/dump` | Start batch capture session |
| `/done` | End session, rate book, generate summary |
| `/status` | Current session info |
| `/atomic` | Review pending atomic note proposals |
| `/cancel` | Reset session |

### Search & Browse

| Command | Description |
|---------|-------------|
| `/search <term>` | Search vault for Cards and Encounters |
| `/search --ai <term>` | Semantic search with AI embeddings |
| `/reading` | Reading dashboard with in-progress books |
| `/find <book>` | Search books in Open Library |
| `/orphan` | Find Cards not linked to MOCs |
| `/orphan --link` | Auto-connect orphan Cards to MOCs |

### Knowledge Retention

| Command | Description |
|---------|-------------|
| `/quiz` | Quick quiz (3 questions from random vault content) |
| `/quiz <title>` | Quiz on a specific book or Card (case-insensitive) |
| `/quiz --connect` | Connection questions across different notes |
| `/exam <title>` | Deep exam (8 questions covering all sections) |
| `/score` | Retention dashboard — stats, strengths, weak spots |
| `/review` | Show items due for spaced repetition review |
| `/skip` | Skip current quiz question |

### Agents & Automation

| Command | Description |
|---------|-------------|
| `/oc [agent] <task>` | Send task to OpenCode AI agent |
| `/chain <name> <task>` | Run multi-agent pipeline |
| `/jobs` | View/execute scheduled tasks |
| `/reindex` | Reindex vault for semantic search |
| `/help` | Show all commands |

---

## Knowledge Retention System

The Examiner agent implements **spaced repetition** (SM-2 algorithm) and **active recall** to help you retain the knowledge captured in your vault.

### How It Works

1. **Content is captured** into Encounters and Cards via the Librarian
2. **Questions are generated** from your actual notes using AI — never invented facts
3. **You answer** via Telegram — the AI evaluates your response (0–5 scale)
4. **SM-2 schedules the next review** — correct answers extend the interval, wrong answers reset it
5. **Daily quiz** is delivered automatically at 09:00 UTC

### Question Types

| Type | Icon | Description |
|------|------|-------------|
| Direct Recall | 🔄 | Remember a specific concept or fact |
| Application | 🎯 | Apply a concept to a real scenario |
| Synthesis | 🧩 | Explain a concept in your own words |
| Connection | 🔗 | Relate two or more concepts across sources |
| Contrast | ⚖️ | Compare or differentiate similar ideas |
| True/False | ✅❌ | Factual checks with deliberate traps |

### Spaced Repetition

The tracker lives at `copilot/exam-tracker.json` in your vault and persists across restarts:

- **Score ≥ 3**: Interval increases (1d → 3d → 8d → 21d → ...)
- **Score < 3**: Interval resets to 1 day (you forgot)
- **Ease factor** adjusts per-item based on your history
- **Never reviewed items** are prioritized
- **Overdue items** appear first in `/review`

---

## OpenCode Agents

8 specialized AI agents accessible via `/oc <agent> <task>` or directly through OpenCode CLI:

| Agent | Role |
|-------|------|
| `librarian` | Reading assistant — captures and processes knowledge from books and sources |
| `reviewer` | Vault auditor — checks frontmatter, links, tags, and structural integrity |
| `connector` | Knowledge graph weaver — discovers missing connections between notes |
| `writer` | Content synthesizer — drafts essays and summaries from vault knowledge |
| `archivist` | Lifecycle manager — detects stale content, manages inbox and archival |
| `examiner` | Retention coach — generates quizzes, evaluates answers, tracks spaced repetition |
| `developer` | Code assistant — development tasks on the project itself |
| `vision` | Image analyzer — extracts text and metadata from photos |

---

## Agent Chains

Multi-agent pipelines that pass output from one agent to the next:

| Chain | Pipeline | Description |
|-------|----------|-------------|
| `ingest_and_connect` | librarian → connector | Capture content, then find connections |
| `full_review` | reviewer → archivist | Audit vault, then identify stale content |
| `capture_and_write` | librarian → writer | Capture content, then draft a synthesis |
| `capture_and_quiz` | librarian → examiner | Capture content, then quiz immediately |

Usage: `/chain capture_and_quiz <your input>`

---

## Scheduled Jobs

Automated tasks that run on a schedule and notify via Telegram:

| Job | Agent | Schedule | Description |
|-----|-------|----------|-------------|
| `weekly_orphan_check` | reviewer | Monday 10:00 UTC | Find orphan Cards not linked to MOCs |
| `weekly_stale_check` | archivist | Wednesday 10:00 UTC | Detect stale in-progress books and undeveloped Cards |
| `weekly_connections` | connector | Friday 10:00 UTC | Suggest 5 missing cross-domain connections |
| `daily_quiz` | examiner | Daily 09:00 UTC | One spaced repetition question from due items |

---

## Project Structure

```
librarian-agent/
├── bot/                          # Telegram bot source
│   ├── src/
│   │   ├── config.py            # Configuration & settings
│   │   ├── handlers.py          # Message & command handlers (all Telegram commands)
│   │   ├── llm.py               # LLM integration (Groq/OpenAI)
│   │   ├── vault.py             # Obsidian vault operations (CRUD, search, linking)
│   │   ├── exam.py              # Examiner module (SM-2, quiz gen, answer eval, tracker)
│   │   ├── embeddings.py        # FAISS semantic search
│   │   ├── opencode.py          # OpenCode server bridge
│   │   ├── openlibrary.py       # Open Library book metadata API
│   │   ├── chaining.py          # Multi-agent pipeline execution
│   │   ├── scheduler.py         # Scheduled jobs (daily quiz, weekly audits)
│   │   ├── models.py            # Data models (entries, sessions, memory)
│   │   └── main.py              # Application entry point
│   ├── Dockerfile
│   └── requirements.txt
├── .opencode/                    # OpenCode agent definitions
│   └── agents/
│       ├── librarian.md         # Reading assistant agent
│       ├── reviewer.md          # Vault auditor agent
│       ├── connector.md         # Knowledge graph agent
│       ├── writer.md            # Content synthesizer agent
│       ├── archivist.md         # Lifecycle manager agent
│       ├── examiner.md          # Retention & spaced repetition agent
│       ├── developer.md         # Code assistant agent
│       └── vision.md            # Image analysis agent
├── .github/workflows/            # GitHub Actions
├── docker-compose.yml
└── README.md
```

---

## Vault Structure

The bot operates on an Obsidian vault with this structure:

```
vault/
├── 0 - Inbox/          → Unprocessed captures
├── 1 - Projects/       → Active projects
├── 2 - Areas/          → Ongoing responsibilities (Development, Leadership, ...)
├── 3 - Resources/      → Reference material
├── 4 - Archive/        → Completed items
├── Atlas/              → MOCs (Maps of Content)
├── Cards/              → Zettelkasten atomic notes
├── Encounters/         → Books, articles, podcasts
├── People/             → Personal CRM
├── Templates/          → Note templates
├── Attachments/        → Images, PDFs
└── copilot/            → Bot data files
    └── exam-tracker.json  → Spaced repetition state
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `GROQ_API_KEY` | ✅* | Groq API key (default LLM provider) |
| `OPENAI_API_KEY` | ✅* | OpenAI API key (fallback provider) |
| `VAULT_PATH` | ✅ | Path to Obsidian vault (mounted volume in Docker) |
| `AUTHORIZED_USERS` | ✅ | Comma-separated Telegram user IDs |
| `LLM_PROVIDER` | — | `groq` (default) or `openai` |

\* At least one LLM provider key is required.

---

## License

MIT — See [LICENSE](LICENSE) for details.

---

## Related Links

- [Obsidian](https://obsidian.md) — Knowledge base that works locally
- [Groq](https://groq.com) — Fast AI inference
- [OpenAI](https://openai.com) — AI models for vision and transcription
- [OpenCode](https://opencode.ai) — AI coding agents
- [Open Library](https://openlibrary.org) — Free book metadata API
