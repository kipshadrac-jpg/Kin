"""Reminders: weekly day/time schedules stored as an RRULE plus timezone."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import audit
from app.errors import AppError, not_found
from app.models.tables import Reminder


def build_rrule(days: Sequence[str], time: str) -> str:
    hh, mm = time.split(":")
    return f"FREQ=WEEKLY;BYDAY={','.join(days)};BYHOUR={int(hh)};BYMINUTE={int(mm)};BYSECOND=0"


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AppError(422, "bad_timezone", "Unknown time zone") from exc


def next_fire(schedule: dict[str, Any], after: datetime) -> datetime | None:
    tz = _tz(schedule.get("timezone") or "UTC")
    local_after = after.astimezone(tz).replace(tzinfo=None)
    rule = rrulestr(schedule["rrule"], dtstart=local_after.replace(second=0, microsecond=0))
    nxt = rule.after(local_after, inc=False)
    if nxt is None:
        return None
    return nxt.replace(tzinfo=tz).astimezone(UTC)


async def create_reminder(
    session: AsyncSession, user_id: UUID, kind: str, message: str, days: Sequence[str], time: str, timezone: str
) -> Reminder:
    schedule = {"rrule": build_rrule(days, time), "timezone": timezone, "days": list(days), "time": time}
    r = Reminder(
        user_id=user_id,
        kind=kind,
        message=message,
        schedule=schedule,
        next_fire_at=next_fire(schedule, datetime.now(UTC)),
    )
    session.add(r)
    await session.flush()
    await audit(session, "reminder.created", "reminders", r.id)
    return r


async def list_reminders(session: AsyncSession, user_id: UUID) -> list[Reminder]:
    q = select(Reminder).where(Reminder.user_id == user_id, Reminder.status != "cancelled")
    return list((await session.execute(q.order_by(Reminder.next_fire_at))).scalars())


async def set_status(session: AsyncSession, user_id: UUID, reminder_id: UUID, status: str) -> Reminder:
    r = await session.scalar(select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user_id))
    if r is None:
        raise not_found("reminder")
    r.status = status
    if status == "active":
        r.next_fire_at = next_fire(r.schedule, datetime.now(UTC))
    await session.flush()
    await audit(session, f"reminder.{status}", "reminders", r.id)
    return r
