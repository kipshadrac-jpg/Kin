"""Habits (Section 10). Progress is consistency over a window, never a streak."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import audit
from app.errors import not_found
from app.models.tables import Habit, HabitCheckin

REVIEW_AFTER_DAYS = 14


def consistency(checkins: dict[date, str], today: date, window: int = 7) -> dict[str, Any]:
    """'4 of the last 7 days'. Done and the minimum version both count; a missed
    day is information, not failure. Returns per-day outcomes oldest -> newest."""
    days = [today - timedelta(days=i) for i in range(window - 1, -1, -1)]
    outcomes = [checkins.get(d) for d in days]
    count = sum(1 for o in outcomes if o in ("done", "minimum"))
    return {
        "window_days": window,
        "count": count,
        "label": f"{count} of last {window} days",
        "days": [{"date": d.isoformat(), "outcome": o} for d, o in zip(days, outcomes, strict=True)],
    }


def needs_review(created_on: date, checkins: dict[date, str], today: date) -> bool:
    """After two missed weeks, ask whether the habit still fits instead of nagging."""
    if (today - created_on).days < REVIEW_AFTER_DAYS:
        return False
    recent = [d for d, o in checkins.items() if o in ("done", "minimum") and (today - d).days < REVIEW_AFTER_DAYS]
    return not recent


async def list_habits(
    session: AsyncSession, user_id: UUID, today: date, include_archived: bool = False
) -> list[dict[str, Any]]:
    q = select(Habit).where(Habit.user_id == user_id)
    if not include_archived:
        q = q.where(Habit.status != "archived")
    habits = list((await session.execute(q.order_by(Habit.created_at))).scalars())
    since = today - timedelta(days=30)
    rows = (
        await session.execute(
            select(HabitCheckin).where(HabitCheckin.user_id == user_id, HabitCheckin.occurred_on >= since)
        )
    ).scalars()
    by_habit: dict[UUID, dict[date, str]] = {}
    for c in rows:
        by_habit.setdefault(c.habit_id, {})[c.occurred_on] = c.outcome
    out = []
    for h in habits:
        cks = by_habit.get(h.id, {})
        out.append(
            {
                "id": h.id,
                "title": h.title,
                "why": h.why,
                "cadence": h.cadence,
                "minimum_version": h.minimum_version,
                "status": h.status,
                "created_at": h.created_at,
                "consistency": consistency(cks, today),
                "needs_review": h.status == "active" and needs_review(h.created_at.date(), cks, today),
                "today": cks.get(today),
            }
        )
    return out


async def create_habit(session: AsyncSession, user_id: UUID, data: dict[str, Any]) -> Habit:
    h = Habit(user_id=user_id, **data)
    session.add(h)
    await session.flush()
    await audit(session, "habit.created", "habits", h.id)
    return h


async def get_habit(session: AsyncSession, user_id: UUID, habit_id: UUID) -> Habit:
    h = await session.scalar(select(Habit).where(Habit.id == habit_id, Habit.user_id == user_id))
    if h is None:
        raise not_found("habit")
    return h


async def update_habit(session: AsyncSession, user_id: UUID, habit_id: UUID, data: dict[str, Any]) -> Habit:
    h = await get_habit(session, user_id, habit_id)
    for k, v in data.items():
        setattr(h, k, v)
    await session.flush()
    await audit(session, "habit.updated", "habits", h.id)
    return h


async def delete_habit(session: AsyncSession, user_id: UUID, habit_id: UUID) -> None:
    h = await get_habit(session, user_id, habit_id)
    await session.delete(h)
    await audit(session, "habit.deleted", "habits", habit_id)


async def log_checkin(
    session: AsyncSession, user_id: UUID, habit_id: UUID, occurred_on: date, outcome: str, note: str | None
) -> HabitCheckin:
    await get_habit(session, user_id, habit_id)
    stmt = (
        pg_insert(HabitCheckin)
        .values(habit_id=habit_id, user_id=user_id, occurred_on=occurred_on, outcome=outcome, note=note)
        .on_conflict_do_update(index_elements=["habit_id", "occurred_on"], set_={"outcome": outcome, "note": note})
        .returning(HabitCheckin.id)
    )
    cid = (await session.execute(stmt)).scalar_one()
    await audit(session, "habit.checkin", "habit_checkins", cid)
    c = await session.get(HabitCheckin, cid, populate_existing=True)
    assert c is not None
    return c


async def list_checkins(session: AsyncSession, user_id: UUID, habit_id: UUID, limit: int = 60) -> list[HabitCheckin]:
    await get_habit(session, user_id, habit_id)
    q = (
        select(HabitCheckin)
        .where(HabitCheckin.habit_id == habit_id, HabitCheckin.user_id == user_id)
        .order_by(HabitCheckin.occurred_on.desc())
        .limit(limit)
    )
    return list((await session.execute(q)).scalars())


async def delete_checkin(session: AsyncSession, user_id: UUID, habit_id: UUID, occurred_on: date) -> None:
    c = await session.scalar(
        select(HabitCheckin).where(
            HabitCheckin.habit_id == habit_id, HabitCheckin.user_id == user_id, HabitCheckin.occurred_on == occurred_on
        )
    )
    if c is None:
        raise not_found("check-in")
    await session.delete(c)
