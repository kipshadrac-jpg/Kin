"""arq worker: scheduled jobs and per-person background work.

Runs with WORKER_DATABASE_URL (role kin_worker). Cross-user sweeps (expiry,
reminders) use its BYPASSRLS; per-person jobs switch to kin_agent with that
person's claims, exactly like the API.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select, text

from app.agents import background
from app.config import get_settings
from app.db.engine import get_sessionmaker, user_session
from app.logging_setup import setup_logging
from app.models.tables import Memory, Reminder
from app.services.actions import expire_stale_all
from app.services.reminders import next_fire

log = logging.getLogger("kin.worker")


async def job_expire_actions(ctx: dict[str, Any]) -> int:
    async with get_sessionmaker()() as s, s.begin():
        n = await expire_stale_all(s)
    if n:
        log.info("actions_expired", extra={"count": n})
    return n


async def job_advance_reminders(ctx: dict[str, Any]) -> int:
    """Move each due reminder to its next time and record that it fired.
    Delivery is in-app (Today screen); push delivery is a later phase."""
    now = datetime.now(UTC)
    fired = 0
    async with get_sessionmaker()() as s, s.begin():
        rows = (
            await s.execute(
                select(Reminder)
                .where(Reminder.status == "active", Reminder.next_fire_at <= now)
                .with_for_update(skip_locked=True)
                .limit(500)
            )
        ).scalars()
        for r in rows:
            r.next_fire_at = next_fire(r.schedule, now)
            await s.execute(
                text(
                    "insert into public.audit_log (user_id, event, entity, entity_id) "
                    "values (:u, 'reminder.fired', 'reminders', :i)"
                ),
                {"u": r.user_id, "i": r.id},
            )
            fired += 1
    return fired


async def job_extract_from_memory(ctx: dict[str, Any], user_id: str, memory_id: str) -> int:
    uid, mid = UUID(user_id), UUID(memory_id)
    async with user_session(uid, "kin_agent") as db:
        mem = await db.scalar(select(Memory).where(Memory.id == mid, Memory.user_id == uid))
        content = mem.content if mem else None
    if not content:
        return 0
    return await background.extract_proposals(uid, content, mid)


async def job_extract_from_text(ctx: dict[str, Any], user_id: str, message: str) -> int:
    return await background.extract_proposals(UUID(user_id), message, None)


async def job_summarize_session(ctx: dict[str, Any], user_id: str, session_id: str) -> bool:
    return await background.summarize_session(UUID(user_id), UUID(session_id))


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging()


class WorkerSettings:
    functions = [job_extract_from_memory, job_extract_from_text, job_summarize_session]
    cron_jobs = [
        cron(job_expire_actions, minute=set(range(0, 60, 10)), run_at_startup=True),
        cron(job_advance_reminders, second=0),
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 120
