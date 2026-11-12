"""Read-only access to the human-maintained resources file."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


@lru_cache
def _load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / path
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text()) or {}
    return data.get("countries", {}) or {}


def resources_for(country: str | None) -> dict[str, Any] | None:
    """Verified entry for a country code, or None. Unverified entries never show,
    so Kin can never display a number no human has checked."""
    if not country:
        return None
    entry = _load(get_settings().safety_resources_path).get(country.strip().upper())
    if not entry or not entry.get("verified_on"):
        return None
    return dict(entry)
