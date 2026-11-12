"""Data rights (Section 14.10): export everything, delete everything."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import jwt
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import AppError
from app.models.tables import USER_TABLES, AuditLog

DELETE_CONFIRM_PHRASE = "delete everything"


def _jsonable(v: Any) -> Any:
    if isinstance(v, UUID | datetime | date):
        return v.isoformat() if not isinstance(v, UUID) else str(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


async def export_all(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    out: dict[str, Any] = {"exported_at": datetime.now().astimezone().isoformat(), "tables": {}}
    for model in [*USER_TABLES, AuditLog]:
        table: Any = model.__table__  # type: ignore[attr-defined]
        cols = [c for c in table.columns]
        rows = await session.execute(select(*cols).where(table.c.user_id == user_id))
        out["tables"][table.name] = [{c.name: _jsonable(v) for c, v in zip(cols, r, strict=True)} for r in rows]
    # Embeddings are derived data; include which model made them, not the vectors.
    return out


async def delete_user_rows(session: AsyncSession, user_id: UUID) -> dict[str, int]:
    """Delete every row the person owns, table by table, under RLS."""
    counts: dict[str, int] = {}
    for model in USER_TABLES:
        table: Any = model.__table__
        res = await session.execute(delete(table).where(table.c.user_id == user_id))
        counts[table.name] = int(res.rowcount or 0)  # type: ignore[attr-defined]
    return counts


def _service_role_token() -> str:
    """Short-lived service-role JWT for GoTrue's admin API. Used only here
    (account deletion), never in ordinary requests."""
    s = get_settings()
    if not s.supabase_jwt_secret:
        raise AppError(500, "not_configured", "Account deletion is not configured")
    now = int(datetime.now().timestamp())
    return jwt.encode(
        {"role": "service_role", "iat": now, "exp": now + 60, "iss": "kin-api"},
        s.supabase_jwt_secret,
        algorithm="HS256",
    )


async def delete_auth_user(user_id: UUID) -> None:
    """Remove the login itself; auth.users ON DELETE CASCADE removes anything left."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(
            f"{s.gotrue_url.rstrip('/')}/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {_service_role_token()}"},
        )
    if r.status_code not in (200, 204, 404):
        raise AppError(
            502, "auth_delete_failed", "Your data was deleted but the login could not be removed. Try again."
        )


async def count_rows(session: AsyncSession, user_id: UUID) -> int:
    total = 0
    for model in USER_TABLES:
        table: Any = model.__table__
        total += int(
            await session.scalar(select(text("count(*)")).select_from(table).where(table.c.user_id == user_id)) or 0
        )
    return total
