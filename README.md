# 🧠 Librarian Agent

Telegram bot + AI agents for managing an Obsidian Second Brain vault. Captures knowledge from books, articles, and other sources.

This project contains:
- **Telegram bot** (`bot/`) — Reading assistant that processes photos, text, and voice messages into Obsidian notes
- **OpenCode agents** (`.opencode/agents/`) — AI agents for vault management and code assistance
- **GitHub Actions** (`.github/workflows/`) — OpenCode integration for issues and PRs

## Quick Start

```bash
# 1. Configure
cd bot && cp .env.example .env
# Edit .env with your tokens

# 2. Run with Docker
VAULT_PATH=/path/to/your/obsidian/vault docker-compose up -d
```

See [bot/README.md](bot/README.md) for detailed setup instructions.

## License

MIT — See [LICENSE](LICENSE) for details.
