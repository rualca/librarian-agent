from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from src.config import settings
from src.models import (
    SessionContext,
    AtomicNoteProposal,
    HistoryTurn,
    TurnRole,
    TurnKind,
    CONTEXT_TTL,
    MAX_TURN_CHARS,
    MAX_CONTEXT_CHARS,
    KEEP_LAST_TURNS,
)
from src import llm, vault, opencode, openlibrary

logger = logging.getLogger(__name__)

# In-memory session storage (per user)
_sessions: dict[int, SessionContext] = {}


def _get_session(user_id: int) -> SessionContext:
    if user_id not in _sessions:
        _sessions[user_id] = SessionContext()
    return _sessions[user_id]


def _is_authorized(user_id: int) -> bool:
    allowed = settings.authorized_user_ids
    return not allowed or user_id in allowed


async def _check_auth(update: Update) -> bool:
    user = update.effective_user
    if not user or not _is_authorized(user.id):
        if update.message:
            await update.message.reply_text("⛔ No autorizado.")
        return False
    return True


# --- Conversation Memory Helpers ---


def _add_turn(
    session: SessionContext,
    *,
    role: TurnRole,
    kind: TurnKind,
    text: str,
    book: str | None = None,
) -> None:
    """Record a turn in conversation memory."""
    mem = session.memory
    now = datetime.utcnow()

    # Auto-clear stale context
    if mem.last_activity and (now - mem.last_activity) > CONTEXT_TTL:
        mem.turns.clear()
        mem.summary = ""

    mem.last_activity = now

    cleaned = text.strip()
    if len(cleaned) > MAX_TURN_CHARS:
        cleaned = cleaned[:MAX_TURN_CHARS] + "…"

    mem.turns.append(
        HistoryTurn(ts=now, role=role, kind=kind, text=cleaned, book=book)
    )


def _record_user_text(session: SessionContext, text: str) -> None:
    _add_turn(session, role=TurnRole.USER, kind=TurnKind.TEXT, text=text, book=session.active_book)


def _record_user_photo(session: SessionContext, description: str) -> None:
    _add_turn(session, role=TurnRole.USER, kind=TurnKind.PHOTO, text=description, book=session.active_book)


def _record_user_voice(session: SessionContext, transcript: str) -> None:
    _add_turn(session, role=TurnRole.USER, kind=TurnKind.VOICE, text=transcript, book=session.active_book)


def _record_command(session: SessionContext, command: str) -> None:
    _add_turn(session, role=TurnRole.EVENT, kind=TurnKind.COMMAND, text=command, book=session.active_book)


def _record_bot_reply(session: SessionContext, text: str) -> None:
    _add_turn(session, role=TurnRole.BOT, kind=TurnKind.RESULT, text=text, book=session.active_book)


def build_telegram_context(session: SessionContext) -> str:
    """Build a context string from conversation memory for OpenCode injection."""
    mem = session.memory
    if not mem.turns:
        return ""

    cutoff = datetime.utcnow() - CONTEXT_TTL
    recent = [t for t in mem.turns if t.ts >= cutoff]
    if not recent:
        return ""

    lines: list[str] = []

    if mem.summary:
        lines.append("## Conversation summary (older)")
        lines.append(mem.summary.strip())
        lines.append("")

    lines.append("## Recent Telegram conversation")
    for t in recent[-KEEP_LAST_TURNS:]:
        tag = t.role.value.upper()
        kind_tag = f"[{t.kind.value}]" if t.kind != TurnKind.TEXT else ""
        book_tag = f" (book: {t.book})" if t.book else ""
        lines.append(f"- {tag}{kind_tag}{book_tag}: {t.text}")

    lines.append("")
    lines.append("## Current session state")
    lines.append(f"- active_book: {session.active_book or 'none'}")
    lines.append(f"- dump_mode: {session.is_dump_session}")
    lines.append(f"- entries_this_session: {session.entries_this_session}")
    if session.pending_atomic:
        lines.append(f"- pending_atomic_proposals: {len(session.pending_atomic)}")

    context = "\n".join(lines)
    if len(context) > MAX_CONTEXT_CHARS:
        context = "…(truncated)\n" + context[-MAX_CONTEXT_CHARS:]

    return context


# --- Command Handlers ---


async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    text = (
        "🧠 *Librarian* — Tu asistente de lectura\n\n"
        "Envíame:\n"
        "📸 Foto de portada → identifico el libro\n"
        "📸 Foto de página con etiqueta → extraigo y clasifico\n"
        "💬 Texto → lo proceso como quote/idea/reflexión\n"
        "🎤 Audio → transcribo y proceso\n\n"
        "*Comandos:*\n"
        "/book `título` — Establecer libro activo\n"
        "/dump — Iniciar sesión de volcado\n"
        "/done — Marcar libro como terminado\n"
        "/status — Ver sesión actual\n"
        "/atomic — Ver propuestas de notas atómicas\n"
        "/search `término` — Buscar en vault\n"
        "/reading — Dashboard de lectura\n"
        "/orphan — Cards sin enlazar a MOCs\n"
        "/find `título` — Buscar libros en Open Library\n"
        "/cancel — Resetear sesión\n"
        "/oc — OpenCode con agente\n"
        "/help — Mostrar esta ayuda"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    await start_handler(update, ctx)


async def book_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    session = _get_session(update.effective_user.id)

    if not ctx.args:
        if session.active_book:
            await update.message.reply_text(f"📖 Libro activo: *{session.active_book}*", parse_mode="Markdown")
        else:
            await update.message.reply_text("Uso: /book `Título del libro`", parse_mode="Markdown")
        return

    title = " ".join(ctx.args)
    _record_command(session, f"/book {title}")
    existing = vault.find_encounter(title)

    if existing:
        session.active_book = existing
        reply = f"📖 Libro activo: *{existing}* (encontrado en vault)"
        await update.message.reply_text(reply, parse_mode="Markdown")
        _record_bot_reply(session, reply)
    else:
        safe = vault.sanitize_filename(title)
        session.active_book = safe
        reply = (
            f"📖 Libro activo: *{safe}*\n"
            f"⚠️ No existe en el vault. Se creará cuando captures la primera entrada.\n"
            f"💡 Envía una foto de la portada para que extraiga autor y metadata."
        )
        await update.message.reply_text(reply, parse_mode="Markdown")
        _record_bot_reply(session, reply)


async def dump_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    session = _get_session(update.effective_user.id)
    session.is_dump_session = True
    session.entries_this_session = 0
    session.pending_retries = []

    _record_command(session, "/dump")

    book_msg = f" — Libro: *{session.active_book}*" if session.active_book else ""
    reply = (
        f"📦 *Sesión de volcado iniciada*{book_msg}\n\n"
        f"Envía fotos, textos o audios. Procesaré todo.\n"
        f"Usa /done cuando termines."
    )
    await update.message.reply_text(reply, parse_mode="Markdown")
    _record_bot_reply(session, reply)


async def done_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    session = _get_session(update.effective_user.id)
    _record_command(session, "/done")

    if not session.active_book:
        await update.message.reply_text("No hay libro activo.")
        return

    keyboard = [
        [
            InlineKeyboardButton("⭐ 1", callback_data="rate:1"),
            InlineKeyboardButton("⭐ 2", callback_data="rate:2"),
            InlineKeyboardButton("⭐ 3", callback_data="rate:3"),
            InlineKeyboardButton("⭐ 4", callback_data="rate:4"),
            InlineKeyboardButton("⭐ 5", callback_data="rate:5"),
        ],
        [InlineKeyboardButton("📖 Sigo leyendo (no terminado)", callback_data="rate:skip")],
    ]

    summary = f"📊 Sesión: *{session.entries_this_session}* entradas capturadas\n"
    if session.pending_retries:
        summary += f"⚠️ {len(session.pending_retries)} fotos sin procesar\n"
    if session.pending_atomic:
        summary += f"💡 {len(session.pending_atomic)} notas atómicas pendientes\n"

    await update.message.reply_text(
        f"{summary}\n¿Has terminado el libro *{session.active_book}*?\nValóralo:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def status_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    session = _get_session(update.effective_user.id)
    _record_command(session, "/status")

    parts = ["📊 *Estado de la sesión*\n"]
    parts.append(f"📖 Libro activo: {session.active_book or 'ninguno'}")
    parts.append(f"📦 Modo volcado: {'sí' if session.is_dump_session else 'no'}")
    parts.append(f"📝 Entradas esta sesión: {session.entries_this_session}")

    if session.pending_retries:
        parts.append(f"⚠️ Fotos pendientes: {len(session.pending_retries)}")
    if session.pending_atomic:
        parts.append(f"💡 Notas atómicas pendientes: {len(session.pending_atomic)}")

    encounters = vault.list_encounters()
    if encounters:
        parts.append(f"\n📚 Libros en vault: {len(encounters)}")

    cards = vault.list_cards()
    if cards:
        parts.append(f"🗂️ Notas atómicas: {len(cards)}")

    await update.message.reply_text("\n".join(parts), parse_mode="Markdown")


async def atomic_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    session = _get_session(update.effective_user.id)

    if not session.pending_atomic:
        await update.message.reply_text("No hay propuestas de notas atómicas pendientes.")
        return

    for i, proposal in enumerate(session.pending_atomic):
        mocs = ", ".join(proposal.related_mocs) if proposal.related_mocs else "—"
        keyboard = [
            [
                InlineKeyboardButton("✅ Crear", callback_data=f"atomic:yes:{i}"),
                InlineKeyboardButton("❌ Descartar", callback_data=f"atomic:no:{i}"),
            ]
        ]
        await update.message.reply_text(
            f"💡 *Propuesta #{i + 1}*\n\n"
            f"📌 *{proposal.title}*\n"
            f"💭 {proposal.idea}\n"
            f"📚 Origen: {proposal.origin}\n"
            f"🗺️ MOCs: {mocs}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )


async def cancel_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    user_id = update.effective_user.id
    _sessions[user_id] = SessionContext()  # clears memory too
    await update.message.reply_text("🔄 Sesión reseteada.")


# ============================================
# NEW COMMAND HANDLERS
# ============================================


async def search_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command - Search vault for Cards and Encounters."""
    if not await _check_auth(update):
        return
    
    if not ctx.args:
        await update.message.reply_text(
            "🔍 *Búsqueda en vault*\n\n"
            "Uso: `/search <término>` — Búsqueda simple\n"
            "`/search --ai <término>` — Búsqueda semántica con IA\n\n"
            "Ejemplo: `/search productividad`",
            parse_mode="Markdown",
        )
        return
    
    # Parse arguments
    args = list(ctx.args)
    use_llm = False
    
    # Check for --ai or -a flag
    if args[0] in ("--ai", "-a"):
        use_llm = True
        args = args[1:]
    
    if not args:
        await update.message.reply_text("🔍 Debes especificar un término de búsqueda.")
        return
    
    query = " ".join(args)
    session = _get_session(update.effective_user.id)
    _record_command(session, f"/search {query}")
    
    await update.message.reply_text(f"🔍 Buscando: *{query}*...")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # Perform search
    cards_results, encounters_results = vault.search_vault(query)
    
    # Format response
    parts: list[str] = []
    
    if not cards_results and not encounters_results:
        reply = (
            f"🔍 *Resultados para:* '{query}'\n\n"
            "❌ No se encontraron resultados."
        )
        await update.message.reply_text(reply, parse_mode="Markdown")
        _record_bot_reply(session, reply)
        return
    
    parts.append(f"🔍 *Resultados para:* '{query}'\n")
    
    # Encounters results
    if encounters_results:
        parts.append(f"\n📚 *ENCOUNTERS ({len(encounters_results)})*")
        parts.append("━" * 20)
        for r in encounters_results[:10]:
            pages_info = f" ({', '.join(r.get('pages', [])[:3])})" if r.get('pages') else ""
            parts.append(f"• {r['title']}{pages_info}")
        if len(encounters_results) > 10:
            parts.append(f"  ...y {len(encounters_results) - 10} más")
    
    # Cards results
    if cards_results:
        parts.append(f"\n🗂️ *CARDS ({len(cards_results)})*")
        parts.append("━" * 20)
        for r in cards_results[:10]:
            parts.append(f"• {r['title']}")
        if len(cards_results) > 10:
            parts.append(f"  ...y {len(cards_results) - 10} más")
    
    parts.append("\n💡 Usa `/search --ai <término>` para búsqueda semántica más inteligente")
    
    reply = "\n".join(parts)
    await update.message.reply_text(reply, parse_mode="Markdown")
    _record_bot_reply(session, reply)


async def reading_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reading command - Dashboard de lectura."""
    if not await _check_auth(update):
        return
    
    session = _get_session(update.effective_user.id)
    _record_command(session, "/reading")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    books = vault.get_reading_dashboard()
    
    if not books:
        await update.message.reply_text(
            "📚 *Tu Biblioteca*\n\n"
            "❌ No hay libros en tu vault.\n"
            "¡Envía una foto de portada para empezar!",
            parse_mode="Markdown",
        )
        return
    
    # Separate in-progress and done books
    in_progress = [b for b in books if b.get("status") == "in-progress"]
    done = [b for b in books if b.get("status") == "done"]
    
    parts: list[str] = ["📚 *TUS LIBROS EN LECTURA*\n"]
    parts.append("━" * 24)
    
    if not in_progress:
        parts.append("\n📖 No hay libros en progreso.")
    else:
        total_entries = 0
        for book in in_progress:
            title = book.get("title", "")
            author = book.get("author", "")
            entries = book.get("entries_count", 0)
            updated = book.get("updated", "")
            rating = book.get("rating", 0)
            
            total_entries += entries
            
            # Format rating
            rating_str = "⭐" * rating if rating > 0 else "—"
            
            # Format updated date
            if updated:
                try:
                    # Parse and format date
                    from datetime import datetime
                    dt = datetime.strptime(updated, "%Y-%m-%d %H:%M")
                    updated_str = dt.strftime("%Y-%m-%d")
                except ValueError:
                    updated_str = updated
            else:
                updated_str = "—"
            
            parts.append(f"\n📖 *{title}*")
            if author:
                parts.append(f"   Autor: {author}")
            parts.append(f"   Estado: 📖 En progreso")
            parts.append(f"   Entradas: {entries} bookmarks")
            parts.append(f"   Última act.: {updated_str}")
            if rating > 0:
                parts.append(f"   Valoración: {rating_str}")
        
        parts.append("\n" + "━" * 24)
        parts.append(f"💡 Total: {len(in_progress)} libro(s) en progreso")
        parts.append(f"📊 Total de entradas: {total_entries}")
    
    # Show done books count
    if done:
        parts.append(f"\n✅ {len(done)} libro(s) terminado(s)")
    
    reply = "\n".join(parts)
    await update.message.reply_text(reply, parse_mode="Markdown")
    _record_bot_reply(session, reply)


async def orphan_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /orphan command - Find and reconnect orphan Cards."""
    if not await _check_auth(update):
        return
    
    session = _get_session(update.effective_user.id)
    _record_command(session, "/orphan")
    
    # Parse arguments
    args = ctx.args if ctx.args else []
    
    list_only = "--list" in args or "-s" in args
    auto_link = "--link" in args or "-l" in args
    
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    orphans = vault.find_orphan_cards()
    
    if not orphans:
        await update.message.reply_text(
            "🗂️ *Cards Huérfanas*\n\n"
            "✅ ¡No hay Cards sin enlazar!\n"
            "Todas tus notas están conectadas a MOCs.",
            parse_mode="Markdown",
        )
        return
    
    # If auto_link flag is set, suggest connections automatically
    if auto_link:
        mocs = vault.list_mocs()
        connected_count = 0
        
        for orphan in orphans:
            content = vault.get_card_content(orphan["title"])
            if content:
                suggestions = vault.suggest_moc_connections(orphan["title"], content)
                if suggestions:
                    vault.link_card_to_moc(orphan["title"], suggestions)
                    connected_count += 1
        
        await update.message.reply_text(
            f"🗂️ *Reconexión de Cards*\n\n"
            f"✅ {connected_count} Cards conectadas a MOCs\n"
            f"📝 Total de huérfanas encontradas: {len(orphans)}",
            parse_mode="Markdown",
        )
        return
    
    # List orphans with suggestions
    parts: list[str] = ["🗂️ *CARDS HUÉRFANAS* (sin enlazar a MOCs)\n"]
    parts.append("━" * 24)
    
    mocs = vault.list_mocs()
    
    for i, orphan in enumerate(orphans[:10], 1):
        title = orphan["title"]
        snippet = orphan.get("snippet", "")[:50]
        
        # Get suggestions
        content = vault.get_card_content(title)
        suggestions = vault.suggest_moc_connections(title, content or "") if content else []
        
        parts.append(f"\n{i}. *{title}*")
        if snippet:
            parts.append(f"   📝 {snippet}...")
        if suggestions:
            parts.append(f"   💡 Sugerencias: {', '.join(suggestions)}")
    
    if len(orphans) > 10:
        parts.append(f"\n...y {len(orphans) - 10} más")
    
    parts.append("\n" + "━" * 24)
    parts.append(f"💡 {len(orphans)} Cards sin enlazar")
    parts.append("\nUsa `/orphan --link` para conectar automáticamente")
    parts.append("Usa `/orphan --list` para ver solo la lista")
    
    await update.message.reply_text("\n".join(parts), parse_mode="Markdown")


async def find_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /find command - Search for books in Open Library.
    
    Usage:
        /find <título> — Buscar libros por título, autor o ISBN
        /find "Clean Code" — Buscar con comillas para frases exactas
    """
    if not await _check_auth(update):
        return
    
    if not ctx.args:
        await update.message.reply_text(
            "📚 *Buscar libros en Open Library*\n\n"
            "Uso: `/find <título>` — Buscar libros por título, autor o ISBN\n\n"
            "Ejemplos:\n"
            "`/find Clean Code`\n"
            "`/find Robert Martin`\n"
            "`/find 9780132350884` (ISBN)",
            parse_mode="Markdown",
        )
        return
    
    query = " ".join(ctx.args)
    session = _get_session(update.effective_user.id)
    _record_command(session, f"/find {query}")
    
    # Show typing status
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    await update.message.reply_text(
        f"🔍 Buscando libros en Open Library: *{query}*...",
        parse_mode="Markdown",
    )
    
    try:
        books = await openlibrary.search_books(query, limit=10)
        
        if not books:
            reply = f"❌ No se encontraron libros para: *{query}*"
            await update.message.reply_text(reply, parse_mode="Markdown")
            _record_bot_reply(session, reply)
            return
        
        # Format and send results
        result_text = openlibrary.format_book_search_results(books, query)
        await update.message.reply_text(result_text, parse_mode="Markdown")
        _record_bot_reply(session, result_text)
        
    except Exception as e:
        logger.error(f"Error searching books: {e}")
        await update.message.reply_text(
            f"❌ Error al buscar libros: {str(e)}",
            parse_mode="Markdown",
        )


async def opencode_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /opencode and /oc commands to send tasks to OpenCode.

    Supports text, photos (via caption or reply), and forwarded images.

    Usage:
        /oc <tarea>                    - Texto con agente por defecto
        /oc librarian <tarea>          - Texto con agente librarian
        📸 foto + caption /oc <tarea>  - Foto con prompt en caption
        (reply a foto) /oc <tarea>     - Foto desde mensaje al que respondes
    """
    if not await _check_auth(update):
        return

    msg = update.message

    # --- Collect text args ---
    # CommandHandler fills ctx.args for text messages.
    # For photos with caption (MessageHandler), we parse manually.
    if ctx.args:
        args = list(ctx.args)
    elif msg.caption:
        # Parse caption: strip /oc or /opencode prefix
        parts = msg.caption.split()
        if parts and parts[0].lower() in ("/oc", "/opencode"):
            args = parts[1:]
        else:
            args = parts
    else:
        args = []

    # --- Collect images ---
    images: list[tuple[bytes, str]] = []

    # Case 1: Photo sent directly with /oc as caption
    if msg.photo:
        photo = msg.photo[-1]  # highest resolution
        file = await ctx.bot.get_file(photo.file_id)
        data = await file.download_as_bytearray()
        images.append((bytes(data), "image/jpeg"))

    # Case 2: /oc as reply to a message with photo(s)
    elif msg.reply_to_message:
        reply = msg.reply_to_message

        if reply.photo:
            photo = reply.photo[-1]
            file = await ctx.bot.get_file(photo.file_id)
            data = await file.download_as_bytearray()
            images.append((bytes(data), "image/jpeg"))

        # Reply to a document that is an image (e.g. uncompressed photo)
        elif reply.document and reply.document.mime_type and reply.document.mime_type.startswith("image/"):
            file = await ctx.bot.get_file(reply.document.file_id)
            data = await file.download_as_bytearray()
            images.append((bytes(data), reply.document.mime_type))

        # Reply to a media group: only the replied-to message is available,
        # but include its caption as extra context if no args provided
        if not args and reply.caption:
            args = reply.caption.split()

    # Case 3: Document sent directly with /oc that is an image
    if not images and msg.document and msg.document.mime_type and msg.document.mime_type.startswith("image/"):
        file = await ctx.bot.get_file(msg.document.file_id)
        data = await file.download_as_bytearray()
        images.append((bytes(data), msg.document.mime_type))

    # --- No args and no images: show help ---
    if not args and not images:
        await msg.reply_text(
            "🤖 *OpenCode — AI Coding Agent*\n\n"
            "Uso:\n"
            "`/oc <tarea>` — Enviar tarea\n"
            "`/oc [agente] <tarea>` — Usar agente específico\n"
            "📸 Foto + `/oc <tarea>` como caption\n"
            "↩️ Responde a una foto con `/oc <tarea>`\n\n"
            "*Agentes disponibles:*\n"
            "• `librarian` — Captura y procesamiento de lectura\n"
            "• `reviewer` — Auditoría y mantenimiento del vault\n"
            "• `connector` — Descubrir conexiones entre notas\n"
            "• `writer` — Generar ensayos y síntesis\n"
            "• `archivist` — Gestión de inbox y archivo\n"
            "• `developer` — Desarrollo de código\n\n"
            "Ejemplos:\n"
            "`/oc reviewer audit`\n"
            "`/oc connector find connections`\n"
            "`/oc writer essay about leadership`\n"
            "`/oc archivist process inbox`",
            parse_mode="Markdown",
        )
        return

    # --- Parse agent and prompt ---
    agent = None
    known_agents = ("librarian", "developer", "reviewer", "connector", "writer", "archivist", "plan", "build", "explore", "general", "vision")
    if args and args[0] in known_agents:
        agent = args.pop(0)

    prompt = " ".join(args) if args else ""

    # If only an image with no text, set a default prompt
    if not prompt and images:
        prompt = "Analiza esta imagen y describe su contenido."
        # Auto-select librarian for book-related image analysis
        if not agent:
            agent = "librarian"

    if not prompt:
        await msg.reply_text("❌ Debes especificar una tarea.")
        return

    # --- Record the /oc command and inject Telegram context ---
    session = _get_session(update.effective_user.id)
    _record_command(session, f"/oc {agent or ''} {prompt}".strip())

    telegram_context = build_telegram_context(session)
    if telegram_context:
        augmented_prompt = (
            "The following is the recent Telegram conversation context with this user. "
            "Use it to understand what has been discussed and avoid repeating work.\n\n"
            f"=== TELEGRAM CONTEXT ===\n{telegram_context}\n=== END CONTEXT ===\n\n"
            f"User request:\n{prompt}"
        )
    else:
        augmented_prompt = prompt

    # --- Status message ---
    img_note = f" + {len(images)} 📸" if images else ""
    await msg.reply_text(
        f"🤖 OpenCode{' (' + agent + ')' if agent else ''} trabajando...{img_note}\n"
        f"⏳ Esto puede tardar unos segundos.",
    )

    try:
        response = await opencode.execute_opencode_task(
            augmented_prompt, agent=agent, images=images if images else None,
        )

        if response:
            if len(response) > 4000:
                response = response[:3900] + "\n\n... (truncado)"
            await msg.reply_text(
                f"✅ *OpenCode respondió:*\n\n{response}",
                parse_mode="Markdown",
            )
            _record_bot_reply(session, f"[OpenCode/{agent or 'default'}] {response}")
        else:
            await msg.reply_text("✅ OpenCode completó la tarea (sin respuesta de texto).")

    except Exception as e:
        logger.error(f"OpenCode error: {e}")
        await msg.reply_text(
            f"❌ Error al ejecutar OpenCode:\n`{str(e)}`",
            parse_mode="Markdown",
        )


# --- Message Handlers ---


async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    session = _get_session(update.effective_user.id)

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    photo = update.message.photo[-1]  # highest resolution
    file = await ctx.bot.get_file(photo.file_id)
    image_data = await file.download_as_bytearray()

    caption = update.message.caption
    _record_user_photo(session, f"[photo]{f': {caption}' if caption else ''}")

    result = llm.process_photo(bytes(image_data), caption, session.active_book)

    await _handle_llm_result(update, session, result, image_data=bytes(image_data))


async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    session = _get_session(update.effective_user.id)

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    _record_user_text(session, update.message.text)

    result = llm.process_text(update.message.text, session.active_book)

    await _handle_llm_result(update, session, result)


async def voice_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    session = _get_session(update.effective_user.id)

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    voice = update.message.voice or update.message.audio
    file = await ctx.bot.get_file(voice.file_id)
    voice_data = await file.download_as_bytearray()

    transcript = llm.transcribe_audio(bytes(voice_data))
    if not transcript:
        await update.message.reply_text("❌ No pude transcribir el audio. Intenta de nuevo.")
        return

    _record_user_voice(session, transcript)

    await update.message.reply_text(f"🎤 Transcripción:\n_{transcript}_", parse_mode="Markdown")

    result = llm.process_voice_transcript(transcript, session.active_book)

    await _handle_llm_result(update, session, result)


# --- Callback Handler ---


async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not _is_authorized(user_id):
        return

    session = _get_session(user_id)
    data = query.data

    if data.startswith("rate:"):
        value = data.split(":")[1]
        if value == "skip":
            session.is_dump_session = False
            await query.edit_message_text(
                f"📖 *{session.active_book}* — sigue en progreso.\n"
                f"📊 {session.entries_this_session} entradas capturadas esta sesión.",
                parse_mode="Markdown",
            )
        else:
            rating = int(value)
            book_title = session.active_book
            
            if book_title:
                vault.update_encounter_status(book_title, status="done", rating=rating)
            
            # Generate auto-summary if book is done
            summary_text = ""
            if book_title:
                await query.message.reply_text(
                    "📝 *Generando resumen automático...*",
                    parse_mode="Markdown",
                )
                
                bookmarks_content = vault.get_all_bookmarks(book_title)
                if bookmarks_content:
                    summary_result = llm.generate_book_summary(book_title, bookmarks_content)
                    if summary_result:
                        vault.update_encounter_summary(
                            book_title,
                            summary_result.get("summary", ""),
                            summary_result.get("key_ideas", []),
                        )
                        
                        # Format summary for display
                        summary_text = f"\n\n📝 *Resumen generado:*\n\n> {summary_result.get('summary', '')}\n"
                        
                        key_ideas = summary_result.get("key_ideas", [])
                        if key_ideas:
                            summary_text += "\n💡 *Ideas clave:*\n"
                            for idea in key_ideas[:5]:
                                summary_text += f"• {idea}\n"
            
            await query.edit_message_text(
                f"✅ *{session.active_book}* — terminado ({'⭐' * rating}){summary_text}",
                parse_mode="Markdown",
            )
            session.is_dump_session = False

        if session.pending_atomic:
            await query.message.reply_text(
                f"💡 Tienes {len(session.pending_atomic)} propuestas de notas atómicas.\n"
                f"Usa /atomic para revisarlas."
            )

    elif data.startswith("atomic:"):
        parts = data.split(":")
        action = parts[1]
        idx = int(parts[2])

        if idx >= len(session.pending_atomic):
            await query.edit_message_text("⚠️ Propuesta ya procesada.")
            return

        proposal = session.pending_atomic[idx]

        if action == "yes":
            card_title = vault.create_atomic_note(
                title=proposal.title,
                idea=proposal.idea,
                origin=proposal.origin,
                page=proposal.page,
                note_type=proposal.note_type,
                related_mocs=proposal.related_mocs,
                related_cards=proposal.related_cards,
            )
            if session.active_book:
                vault.add_atomic_reference(session.active_book, card_title)

            await query.edit_message_text(
                f"✅ Nota atómica creada: *{card_title}*\n"
                f"📁 `Cards/{card_title}.md`",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(f"❌ Descartada: _{proposal.title}_", parse_mode="Markdown")

    elif data.startswith("book_confirm:"):
        title = data.split(":", 1)[1]
        session.active_book = title
        await query.edit_message_text(
            f"📖 Libro activo: *{title}*", parse_mode="Markdown"
        )

    elif data.startswith("book_new:"):
        title = data.split(":", 1)[1]
        # Will be created on first entry
        session.active_book = title
        await query.edit_message_text(
            f"📖 Nuevo libro: *{title}*\nSe creará con la primera entrada.",
            parse_mode="Markdown",
        )


# --- Core Processing ---


async def _handle_llm_result(
    update: Update,
    session: SessionContext,
    result,
    image_data: bytes | None = None,
) -> None:
    parts: list[str] = []

    # Book detection
    if result.book_title and not session.active_book:
        existing = vault.find_encounter(result.book_title)
        if existing:
            session.active_book = existing
            parts.append(f"📖 Libro detectado: *{existing}* (ya existe en vault)")
        else:
            safe = vault.sanitize_filename(result.book_title)
            author = result.book_author or ""
            vault.create_encounter(result.book_title, author=author)
            session.active_book = safe
            session.active_author = author
            parts.append(
                f"📖 Nuevo libro: *{result.book_title}*\n"
                f"✍️ Autor: {author}\n"
                f"📁 Creado: `Encounters/{safe}.md`"
            )

    # Process entries
    if result.entries:
        if not session.active_book:
            parts.append("⚠️ No hay libro activo. Usa /book `título` o envía una foto de la portada.")
            if result.entries:
                preview = "\n".join(
                    f"  {e.entry_type.icon} {e.content[:60]}..." for e in result.entries[:5]
                )
                parts.append(f"📝 Contenido detectado (sin guardar):\n{preview}")
        else:
            # Ensure encounter exists
            if not vault.read_encounter(session.active_book):
                vault.create_encounter(
                    session.active_book,
                    author=session.active_author or "",
                )

            table_lines = ["", "| # | Pág | Tipo | Contenido |", "|---|-----|------|-----------|"]
            saved = 0

            for i, entry in enumerate(result.entries):
                # Save attachment if photo
                attachment_name = None
                if image_data and i == 0:
                    attachment_name = vault.save_attachment(
                        image_data, session.active_book, entry.page
                    )

                write_result = vault.append_entry(session.active_book, entry)

                page_str = f"p.{entry.page}" if entry.page else "p.??"
                content_preview = entry.content[:50].replace("|", "\\|")

                if write_result.get("ok"):
                    saved += 1
                    table_lines.append(
                        f"| {i + 1} | {page_str} | {entry.entry_type.icon} | {content_preview} |"
                    )
                elif write_result.get("duplicate"):
                    table_lines.append(
                        f"| {i + 1} | {page_str} | 🔄 | _(duplicado, omitido)_ |"
                    )
                else:
                    error = write_result.get("error", "unknown")
                    table_lines.append(
                        f"| {i + 1} | {page_str} | ❌ | Error: {error} |"
                    )

            session.entries_this_session += saved
            parts.append(f"📖 *{session.active_book}* — {saved} entries añadidas")
            parts.append("\n".join(table_lines))

            # Low confidence warnings
            for entry in result.entries:
                if entry.confidence < 0.7:
                    parts.append(
                        f"⚠️ Baja confianza en: _{entry.content[:40]}..._ — revisa el resultado."
                    )
                if entry.needs_clarification:
                    parts.append(f"❓ {entry.needs_clarification}")

    # Atomic proposals
    if result.atomic_proposals:
        session.pending_atomic.extend(result.atomic_proposals)
        for proposal in result.atomic_proposals:
            mocs = ", ".join(proposal.related_mocs) if proposal.related_mocs else "—"
            parts.append(
                f"\n💡 *Nota atómica sugerida*: \"{proposal.title}\"\n"
                f"   🗺️ MOCs: {mocs}\n"
                f"   Usa /atomic para revisarla"
            )

    # Questions from LLM
    for q in result.questions:
        parts.append(f"❓ {q}")

    # Send response
    if parts:
        response = "\n".join(parts)
        # Telegram message limit is 4096 chars
        if len(response) > 4000:
            for chunk_start in range(0, len(response), 4000):
                chunk = response[chunk_start : chunk_start + 4000]
                await update.message.reply_text(chunk, parse_mode="Markdown")
        else:
            await update.message.reply_text(response, parse_mode="Markdown")
        _record_bot_reply(session, response)
    else:
        await update.message.reply_text("🤔 No pude extraer contenido. ¿Puedes intentar de nuevo?")
