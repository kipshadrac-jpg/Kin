"""Finance entries: flows with ranges, no bank account assumed (Section 10)."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import audit
from app.errors import not_found
from app.models.tables import FinanceEntry


async def list_entries(session: AsyncSession, user_id: UUID) -> list[FinanceEntry]:
    q = select(FinanceEntry).where(FinanceEntry.user_id == user_id).order_by(FinanceEntry.created_at)
    return list((await session.execute(q)).scalars())


async def create_entry(session: AsyncSession, user_id: UUID, data: dict[str, Any]) -> FinanceEntry:
    e = FinanceEntry(user_id=user_id, **data)
    session.add(e)
    await session.flush()
    await audit(session, "finance.entry_created", "finance_entries", e.id)
    return e


async def get_entry(session: AsyncSession, user_id: UUID, entry_id: UUID) -> FinanceEntry:
    e = await session.scalar(select(FinanceEntry).where(FinanceEntry.id == entry_id, FinanceEntry.user_id == user_id))
    if e is None:
        raise not_found("entry")
    return e


async def update_entry(session: AsyncSession, user_id: UUID, entry_id: UUID, data: dict[str, Any]) -> FinanceEntry:
    e = await get_entry(session, user_id, entry_id)
    for k, v in data.items():
        setattr(e, k, v)
    await session.flush()
    await audit(session, "finance.entry_updated", "finance_entries", e.id)
    return e


async def delete_entry(session: AsyncSession, user_id: UUID, entry_id: UUID) -> None:
    e = await get_entry(session, user_id, entry_id)
    await session.delete(e)
    await audit(session, "finance.entry_deleted", "finance_entries", entry_id)
