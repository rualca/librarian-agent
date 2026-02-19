from __future__ import annotations

import asyncio
import datetime
import logging
import traceback
from dataclasses import dataclass

from telegram import Bot
from telegram.ext import Application, ContextTypes

from src import opencode
from src.config import settings

logger = logging.getLogger(__name__)

_job_locks: dict[str, asyncio.Lock] = {}


@dataclass
class ScheduledJob:
    name: str
    agent: str
    prompt: str
    description: str
    enabled: bool = True


DEFAULT_JOBS: list[ScheduledJob] = [
    ScheduledJob(
        name="weekly_orphan_check",
        agent="reviewer",
        prompt="Find all orphan Cards that are not linked to any MOC. Report a summary of orphans found and suggest connections.",
        description="🔍 Revisión semanal de Cards huérfanas",
    ),
    ScheduledJob(
        name="weekly_stale_check",
        agent="archivist",
        prompt="Find stale content: Encounters with status 'in-progress' not updated in 60+ days, seed Cards older than 90 days never developed, and empty Inbox items. Report a health summary.",
        description="⏰ Detección semanal de contenido obsoleto",
    ),
    ScheduledJob(
        name="weekly_connections",
        agent="connector",
        prompt="Analyze the vault and find 5 strong missing connections between existing Cards. For each, explain why they should be linked. Focus on cross-domain connections.",
        description="🕸️ Sugerencias semanales de conexiones",
    ),
    ScheduledJob(
        name="daily_quiz",
        agent="examiner",
        prompt="Select 1 Card or Encounter entry due for spaced repetition review. Generate a single question about it. Prefer items that haven't been reviewed or are overdue. Format: state the question clearly and include the source reference. The user will answer via Telegram.",
        description="🧪 Pregunta diaria de retención",
    ),
]

_JOB_SCHEDULES: dict[str, tuple[tuple[int, ...], int, str]] = {
    "weekly_orphan_check": ((0,), 10, "Lunes 10:00 UTC"),
    "weekly_stale_check": ((2,), 10, "Miércoles 10:00 UTC"),
    "weekly_connections": ((4,), 10, "Viernes 10:00 UTC"),
    "daily_quiz": ((0, 1, 2, 3, 4, 5, 6), 9, "Diario 09:00 UTC"),
}


def _split_message(text: str, max_len: int = 3900) -> list[str]:
    """Split text into chunks that fit within Telegram's message limit."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.split("\n"):
        line_with_nl = line + "\n"

        if len(line_with_nl) > max_len:
            # Flush current buffer first
            if current:
                chunks.append(current)
                current = ""
            # Hard-split the long line
            for i in range(0, len(line_with_nl), max_len):
                piece = line_with_nl[i : i + max_len]
                chunks.append(piece)
            continue

        if len(current) + len(line_with_nl) > max_len:
            chunks.append(current)
            current = line_with_nl
        else:
            current += line_with_nl

    if current:
        chunks.append(current)

    return chunks


async def _run_scheduled_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute a scheduled job and notify authorized users."""
    job: ScheduledJob = context.job.data

    if job.name not in _job_locks:
        _job_locks[job.name] = asyncio.Lock()

    lock = _job_locks[job.name]
    if lock.locked():
        logger.warning("Job %s is already running, skipping", job.name)
        return

    async with lock:
        logger.info("Starting scheduled job: %s", job.name)
        try:
            result = await opencode.execute_opencode_task(job.prompt, agent=job.agent)
        except Exception:
            tb = traceback.format_exc()
            logger.error("Scheduled job %s failed:\n%s", job.name, tb)
            error_msg = f"❌ Error en tarea programada: {job.description}\n\n{tb[-500:]}"
            for user_id in settings.authorized_user_ids:
                try:
                    await context.bot.send_message(chat_id=user_id, text=error_msg)
                except Exception:
                    logger.error("Failed to send error notification to %s", user_id)
            return

        logger.info("Finished scheduled job: %s", job.name)

        header = f"📋 *{job.description}*\n\n"
        full_text = header + result
        chunks = _split_message(full_text)

        for user_id in settings.authorized_user_ids:
            for chunk in chunks:
                try:
                    await context.bot.send_message(chat_id=user_id, text=chunk)
                except Exception:
                    logger.error("Failed to send result to user %s", user_id)


def register_scheduled_jobs(app: Application) -> None:
    """Register all enabled scheduled jobs on the application's job queue."""
    job_queue = app.job_queue

    for job in DEFAULT_JOBS:
        if not job.enabled:
            continue

        schedule = _JOB_SCHEDULES.get(job.name)
        if not schedule:
            logger.warning("No schedule defined for job %s, skipping", job.name)
            continue

        days, hour, _ = schedule
        job_queue.run_daily(
            _run_scheduled_job,
            time=datetime.time(hour=hour, minute=0, tzinfo=datetime.timezone.utc),
            days=days,
            data=job,
            name=job.name,
        )
        logger.info("Registered scheduled job: %s (days=%s)", job.name, days)


async def run_job_now(job_name: str, bot: Bot) -> str:
    """Run a scheduled job immediately and return the result."""
    job = next((j for j in DEFAULT_JOBS if j.name == job_name), None)
    if job is None:
        raise ValueError(f"Unknown job: {job_name}")

    return await opencode.execute_opencode_task(job.prompt, agent=job.agent)


def list_jobs() -> list[dict]:
    """Return metadata for all scheduled jobs."""
    result = []
    for job in DEFAULT_JOBS:
        _, _, schedule_description = _JOB_SCHEDULES.get(job.name, ((), 10, "Sin programar"))
        result.append({
            "name": job.name,
            "agent": job.agent,
            "description": job.description,
            "enabled": job.enabled,
            "schedule_description": schedule_description,
        })
    return result
