# 🧠 Librarian Bot — Telegram × Obsidian Second Brain

A Telegram bot that acts as your reading assistant. Send photos of book pages, covers, quotes, or voice notes — and it captures everything into your Obsidian vault.

## Features

- 📸 **Photo processing** — Send a photo of a page with a sticky tab → extracts text, page number, classifies content
- 📷 **Cover detection** — Send a book cover → identifies title/author, creates Encounter note
- 💬 **Text input** — Type a quote, idea, or reflection → classifies and stores
- 🎤 **Voice notes** — Send a voice message → transcribes and processes
- 🧠 **Atomic notes** — Suggests Zettelkasten notes for universal ideas, creates them on confirmation
- 🔄 **Duplicate detection** — Won't create duplicate entries
- 📦 **Batch mode** — `/dump` for bulk capture sessions

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and talk to [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 2. Get an OpenAI API Key

1. Go to [platform.openai.com](https://platform.openai.com)
2. Create an API key with access to GPT-4o (vision required)

### 3. Configure

```bash
cd bot
cp .env.example .env
```

Edit `.env` with your tokens:
```
TELEGRAM_BOT_TOKEN=your-bot-token
OPENAI_API_KEY=your-openai-key
VAULT_PATH=/path/to/your/obsidian/vault
AUTHORIZED_USERS=your-telegram-user-id
```

> 💡 To find your Telegram user ID, talk to [@userinfobot](https://t.me/userinfobot)

### 4. Install & Run

#### Option A: Docker (Recommended)

```bash
# From the project root directory
# Set VAULT_PATH to your Obsidian vault location
VAULT_PATH=/path/to/your/vault docker-compose up -d
```

To view logs:
```bash
docker-compose logs -f librarian-bot
```

To stop:
```bash
docker-compose down
```

#### Option B: Local Python

```bash
cd bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and help |
| `/book <title>` | Set the active book |
| `/dump` | Start a batch capture session |
| `/done` | End session, rate the book (generates auto-summary) |
| `/status` | Show current session info |
| `/atomic` | Review pending atomic note proposals |
| `/search <term>` | Search vault for Cards and Encounters |
| `/search --ai <term>` | Semantic search with AI |
| `/reading` | Reading dashboard with in-progress books |
| `/find <book>` | Search books in Open Library |
| `/orphan` | Find Cards not linked to MOCs |
| `/orphan --link` | Auto-connect orphan Cards to MOCs |
| `/cancel` | Reset session |
| `/help` | Show help |
| `/oc [agent] <task>` | Send task to OpenCode AI agent |
| `/opencode [agent] <task>` | Alias for `/oc` |

### OpenCode Integration

The `/oc` command integrates with [OpenCode](https://opencode.ai), an AI coding agent that can work on your vault:

```
/oc <task>                    → Use default agent
/oc librarian <task>          → Use librarian agent (for vault tasks)
```

**Examples:**
```
/oc refactor the process_photo function
/oc librarian create an atomic note about productivity
/oc librarian summarize the key ideas from The Systemic CTO
```

**Available agents:**
- `librarian` — Manages notes, encounters, and vault organization
- `plan` — Planning mode (suggests without making changes)
- `build` — Build mode (makes changes directly)
- `explore` — Explores and explains codebase
- `general` — General purpose

**Configuration:** Set your API key in `docker-compose.yml`:
```yaml
environment:
  - ZHIPU_API_KEY=your-key
  # or
  - OPENAI_API_KEY=your-key
  - ANTHROPIC_API_KEY=your-key
```

## New Features

### 🔍 /search — Search your vault
Search for Cards and Encounters mentioning a concept:

```
/search productividad           # Simple keyword search
/search --ai leadership         # Semantic search with AI
```

### 📚 /reading — Reading Dashboard
View your in-progress books with entry counts and last update:

```
/reading
```

Shows:
- All books currently being read
- Number of bookmarks/entries per book
- Last updated date
- Ratings (if finished)

### 📝 Auto-Summary on /done
When you mark a book as finished with `/done`, the bot automatically:
1. Generates a summary from all captured bookmarks
2. Extracts key ideas
3. Updates the Encounter note with `## Summary` and `## Key Ideas`

### 🔗 /orphan — Reconnect Orphan Cards
Find Cards that aren't linked to any MOC and suggest connections:

```
/orphan              # List orphan cards with suggestions
/orphan --list      # Just list, no suggestions
/orphan --link     # Auto-connect to suggested MOCs
```

**How it works:**
1. Finds all Cards without MOC links
2. Analyzes content for keywords
3. Suggests relevant MOCs (Productivity, Leadership, Development, etc.)
4. Can auto-apply connections with `--link` flag

## Usage Flow

### Quick capture (single entry)
1. `/book The Manager's Path`
2. Send a photo of the page with the tab
3. Bot extracts, classifies, and saves

### Dump session (batch)
1. Send a cover photo (bot identifies the book)
2. `/dump`
3. Send all your tabbed pages as photos
4. `/done` → rate the book
5. `/atomic` → review and confirm atomic notes

## Architecture

```
bot/
├── .env.example        # Environment variables template
├── requirements.txt    # Python dependencies
├── README.md
└── src/
    ├── __init__.py
    ├── main.py         # Entry point, bot setup
    ├── config.py       # Settings (from .env)
    ├── models.py       # Data models (entries, proposals, sessions)
    ├── vault.py        # Obsidian vault read/write operations
    ├── llm.py          # OpenAI GPT-4o integration (vision + text)
    ├── opencode.py     # OpenCode CLI integration
    ├── openlibrary.py  # Open Library API integration
    └── handlers.py     # Telegram command & message handlers
```

## How It Works

1. **Input** → User sends photo/text/voice to Telegram bot
2. **LLM** → GPT-4o analyzes content (vision for photos, text classification for messages)
3. **Classify** → Content is classified: 💡 Idea, 💬 Quote, 🔧 Problem/Solution, 🔑 Takeaway, 📖 Chapter
4. **Write** → Entry is appended to the correct section in `Encounters/{Book}.md`
5. **Connect** → Bot suggests atomic notes for `Cards/` with links to MOCs
