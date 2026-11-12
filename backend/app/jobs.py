"""Enqueue background work on Redis (arq). If Redis is unavailable the turn
still succeeds; extraction and summaries are best-effort."""

import logging
import time
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings

log = logging.getLogger("kin.jobs")
_pool: ArqRedis | None = None
_down_until = 0.0


async def _get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        rs = RedisSettings.from_dsn(get_settings().redis_url)
        rs.conn_retries, rs.conn_timeout = 0, 1
        _pool = await create_pool(rs)
    return _pool


async def enqueue(name: str, *args: object) -> None:
    global _down_until
    if time.monotonic() < _down_until:
        return  # Redis was just unreachable; don't slow every request down
    try:
        pool = await _get_pool()
        await pool.enqueue_job(name, *args)
    except Exception as exc:  # noqa: BLE001
        _down_until = time.monotonic() + 30
        log.warning("enqueue_failed", extra={"job": name, "error_type": type(exc).__name__})


async def after_memory(user_id: UUID, memory_id: UUID) -> None:
    await enqueue("job_extract_from_memory", str(user_id), str(memory_id))


async def after_turn(user_id: UUID, session_id: UUID, message: str) -> None:
    await enqueue("job_extract_from_text", str(user_id), message)
    await enqueue("job_summarize_session", str(user_id), str(session_id))
