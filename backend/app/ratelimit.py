"""Per-user, per-route-group fixed-window limits in Redis (Section 14.6)."""

import logging
import time

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.config import get_settings
from app.deps import CurrentUser, current_user
from app.errors import AppError

log = logging.getLogger("kin.ratelimit")
LIMITS = {"chat": (20, 60), "memories": (60, 60), "default": (240, 60)}  # (requests, seconds)
_redis: Redis | None = None


def _client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1)
    return _redis


def limit(group: str):  # noqa: ANN201
    max_req, window = LIMITS.get(group, LIMITS["default"])

    async def _dep(request: Request, user: CurrentUser = Depends(current_user)) -> None:
        if not get_settings().rate_limit_enabled:
            return
        bucket = int(time.time() // window)
        key = f"rl:{group}:{user.id}:{bucket}"
        try:
            r = _client()
            n = await r.incr(key)
            if n == 1:
                await r.expire(key, window + 1)
        except Exception as exc:  # noqa: BLE001 — fail open: Redis down must not lock people out
            log.warning("ratelimit_unavailable", extra={"error_type": type(exc).__name__})
            return
        if n > max_req:
            raise AppError(
                429, "rate_limited", "Slow down a little and try again in a minute.", {"retry_after_seconds": window}
            )

    return _dep
