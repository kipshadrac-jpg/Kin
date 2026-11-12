"""Structured JSON logs. IDs and event types only: never bodies, prompts,
completions, journal text, money figures or profile contents (Section 14.5)."""

import json
import logging
import sys
from typing import Any

from app.config import get_settings

_SAFE_EXTRA = {
    "request_id",
    "user_id",
    "route",
    "method",
    "status",
    "latency_ms",
    "job",
    "count",
    "error_type",
    "event",
    "entity_id",
    "provider",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for k in _SAFE_EXTRA:  # allow-list: anything else attached to a record is dropped
            if k in record.__dict__:
                out[k] = record.__dict__[k]
        return json.dumps(out)


def setup_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root.addHandler(h)
    root.setLevel(get_settings().log_level)
    # Libraries that may log request bodies or prompts stay quiet.
    for noisy in ("httpx", "httpcore", "anthropic", "sqlalchemy.engine", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
