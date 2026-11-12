"""Async engine and the per-request Row Level Security context.

Why this file matters: the API logs in as `kin_api`, a role with NO table
privileges of its own and no BYPASSRLS. Every unit of work opens a transaction
and runs `set local role authenticated` (or `kin_agent` for the agent runtime)
plus `set_config('request.jwt.claims', ...)`. Supabase's `auth.uid()` reads the
`sub` from those claims, so the "own rows" policies apply to every query.
`set local` is scoped to the transaction, so a pooled connection can never leak
one person's identity into the next request.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

DbRole = Literal["authenticated", "kin_agent"]
_ALLOWED_ROLES: set[str] = {"authenticated", "kin_agent"}

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _to_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            _to_async_url(get_settings().database_url),
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def apply_rls_context(session: AsyncSession, user_id: UUID, role: DbRole) -> None:
    if role not in _ALLOWED_ROLES:  # role is interpolated, so whitelist it
        raise ValueError(f"role not allowed: {role}")
    await session.execute(text(f"set local role {role}"))
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    await session.execute(text("select set_config('request.jwt.claims', :c, true)"), {"c": claims})


@asynccontextmanager
async def user_session(user_id: UUID, role: DbRole = "authenticated") -> AsyncIterator[AsyncSession]:
    """One transaction, scoped to one person, committed on success."""
    sm = get_sessionmaker()
    async with sm() as session:
        async with session.begin():
            await apply_rls_context(session, user_id, role)
            yield session


async def audit(session: AsyncSession, event: str, entity: str | None = None, entity_id: UUID | None = None) -> None:
    """Record what happened (never content). user_id comes from the JWT claims in the DB."""
    await session.execute(text("select public.kin_audit(:e, :n, :i)"), {"e": event, "n": entity, "i": entity_id})
