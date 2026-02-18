# 🧠 Librarian Agent

## The Problem

Building a **Second Brain** in Obsidian is powerful, but the friction of manual entry kills consistency. Capturing insights from books, articles, and conversations requires:

- Taking photos → transferring to computer → OCR → formatting → filing
- Manually organizing notes into proper structures
- Remembering which books you're reading and linking related ideas
- Consistently reviewing and connecting disparate concepts

The result? A vault that grows slower than your reading list.

---

## The Solution

**Librarian Agent** is an AI-powered Telegram bot that acts as your personal reading assistant. Send photos, voice notes, or text directly from your phone — it handles the entire capture pipeline into your Obsidian vault.

### What It Does

| Input | What Happens |
|-------|-------------|
| 📸 Photo of a book page | Extracts text, identifies page number, classifies content type |
| 📷 Book cover photo | Identifies title/author via Open Library, creates Encounter note |
| 💬 Text message | Classifies as quote, idea, or reflection, stores appropriately |
| 🎤 Voice note | Transcribes with Whisper, processes into actionable notes |
| 🧠 Universal ideas | Suggests Zettelkasten atomic notes, creates on confirmation |

### Key Features

- **Intelligent Classification** — AI determines if content is a quote, idea, or reflection
- **Atomic Note Suggestions** — Identifies universal concepts → proposes Zettelkasten notes
- **Duplicate Detection** — Won't pollute your vault with repeated entries
- **Batch Capture** — `/dump` command for bulk scanning sessions
- **Reading Dashboard** — Track in-progress books with `/reading`
- **Semantic Search** — AI-powered vault search with `/search --ai`
- **Orphan Management** — Find and auto-link unconnected cards to MOCs
- **OpenCode Integration** — AI agents for vault maintenance via `/oc`

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Bot Framework | Python Telegram Bot (`telegram.ext`) |
| AI/LLM | OpenAI GPT-4o (vision), Whisper (transcription) |
| Knowledge Graph | Obsidian (Markdown, YAML frontmatter) |
| External APIs | Open Library (book metadata) |
| Deployment | Docker, Docker Compose |
| Agents | OpenCode AI agents |

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
│                  Librarian Bot (Python)                    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │   Handlers   │ │  AI Services │ │   Vault Manager      │ │
│  │  - photo     │ │  - GPT-4o    │ │   - file ops         │ │
│  │  - voice     │ │  - Whisper   │ │   - templates        │ │
│  │  - text      │ │  - semantic  │ │   - linking          │ │
│  │  - commands  │ │    search    │ │   - dedup            │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Obsidian Vault                            │
│   📚 Books / 📄 Cards / 🌍 Encounters / 🗂️ MOCs             │
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
OPENAI_API_KEY=your-openai-key
VAULT_PATH=/path/to/your/obsidian/vault
AUTHORIZED_USERS=your-telegram-user-id
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

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/book <title>` | Set active book for capture |
| `/dump` | Start batch capture session |
| `/done` | End session, rate book, generate summary |
| `/status` | Current session info |
| `/atomic` | Review pending atomic note proposals |
| `/search <term>` | Search vault for Cards and Encounters |
| `/search --ai <term>` | Semantic search with AI |
| `/reading` | Reading dashboard with in-progress books |
| `/find <book>` | Search books in Open Library |
| `/orphan` | Find Cards not linked to MOCs |
| `/orphan --link` | Auto-connect orphan Cards to MOCs |
| `/oc [agent] <task>` | Send task to OpenCode AI agent |

---

## Project Structure

```
librarian-agent/
├── bot/                      # Telegram bot source
│   ├── src/
│   │   ├── config.py        # Configuration management
│   │   ├── handlers.py     # Message & command handlers
│   │   ├── llm.py          # OpenAI integration
│   │   ├── vault.py         # Obsidian vault operations
│   │   ├── openlibrary.py  # Book metadata API
│   │   └── opencode.py     # OpenCode agent integration
│   ├── Dockerfile
│   └── requirements.txt
├── .opencode/               # OpenCode agents
│   └── agents/
├── .github/workflows/       # GitHub Actions
├── docker-compose.yml
└── README.md
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `OPENAI_API_KEY` | OpenAI API key (GPT-4o required) |
| `VAULT_PATH` | Path to Obsidian vault (mounted volume) |
| `AUTHORIZED_USERS` | Comma-separated Telegram user IDs |

---

## License

MIT — See [LICENSE](LICENSE) for details.

---

## Related Links

- [Obsidian](https://obsidian.md) — Knowledge base that works locally
- [OpenAI](https://openai.com) — AI models for vision and transcription
- [OpenCode](https://opencode.ai) — AI coding agents
- [Open Library](https://openlibrary.org) — Free book metadata API
