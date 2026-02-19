import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from src.config import settings
from src.handlers import (
    start_handler,
    help_handler,
    book_handler,
    dump_handler,
    done_handler,
    status_handler,
    atomic_handler,
    cancel_handler,
    opencode_handler,
    photo_handler,
    text_handler,
    voice_handler,
    callback_handler,
    search_handler,
    reading_handler,
    orphan_handler,
    find_handler,
    reindex_handler,
    jobs_handler,
    chain_handler,
    quiz_handler,
    exam_handler,
    score_handler,
    review_handler,
    skip_handler,
)
from src.scheduler import register_scheduled_jobs

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("book", book_handler))
    app.add_handler(CommandHandler("dump", dump_handler))
    app.add_handler(CommandHandler("done", done_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("atomic", atomic_handler))
    app.add_handler(CommandHandler("cancel", cancel_handler))
    app.add_handler(CommandHandler("opencode", opencode_handler))
    app.add_handler(CommandHandler("oc", opencode_handler))
    
    # NEW COMMAND HANDLERS
    app.add_handler(CommandHandler("search", search_handler))
    app.add_handler(CommandHandler("reading", reading_handler))
    app.add_handler(CommandHandler("orphan", orphan_handler))
    app.add_handler(CommandHandler("find", find_handler))
    app.add_handler(CommandHandler("reindex", reindex_handler))
    app.add_handler(CommandHandler("jobs", jobs_handler))
    app.add_handler(CommandHandler("chain", chain_handler))

    # Exam / Quiz commands
    app.add_handler(CommandHandler("quiz", quiz_handler))
    app.add_handler(CommandHandler("exam", exam_handler))
    app.add_handler(CommandHandler("score", score_handler))
    app.add_handler(CommandHandler("review", review_handler))
    app.add_handler(CommandHandler("skip", skip_handler))

    # Callback queries (inline keyboard buttons)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Photos with /oc or /opencode caption → opencode handler (before generic photo)
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r"^/(oc|opencode)\b"),
        opencode_handler,
    ))

    # Message handlers
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )

    # Scheduled agent jobs
    register_scheduled_jobs(app)

    logger.info("🧠 Librarian bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
