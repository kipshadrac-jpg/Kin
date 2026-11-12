"""Human-in-the-loop action queue (Section 9).

pending --approve--> approved -> executing -> executed
   |                                 '-----> failed (retryable)
   |--edit--> pending (old payload kept in payload_history)
   |--cancel--> cancelled
   '--72h--> expired

Rules enforced here: payloads are validated by schema; the preview is written
by code from the payload (never by the model); one approval per card; executed
actions are idempotent; expired/cancelled never run.
"""

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import audit
from app.errors import AppError, not_found
from app.models.tables import ActionQueue
from app.services.context import now_utc

DAY_NAMES = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu", "FR": "Fri", "SA": "Sat", "SU": "Sun"}
PERIOD_WORD = {"day": "a day", "week": "a week", "month": "a month"}


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Cadence(_P):
    times_per_week: int | None = Field(default=None, ge=1, le=7)
    preferred_days: list[Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]] | None = None


class CreateHabitPayload(_P):
    title: str = Field(min_length=1, max_length=120)
    why: str | None = Field(default=None, max_length=500)
    minimum_version: str | None = Field(default=None, max_length=120)
    cadence: Cadence = Cadence()


class LogHabitPayload(_P):
    habit_id: UUID
    habit_title: str = Field(max_length=120)
    occurred_on: date
    outcome: Literal["done", "minimum", "skipped"]
    note: str | None = Field(default=None, max_length=500)


class SetGoalPayload(_P):
    domain: Literal["habit", "finance", "general"]
    title: str = Field(min_length=1, max_length=160)
    amount_per_period: Decimal | None = Field(default=None, gt=0)
    period: Literal["day", "week", "month"] | None = None
    horizon_periods: int | None = Field(default=None, gt=0, le=520)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    scenario_id: UUID | None = None


class SetReminderPayload(_P):
    message: str = Field(min_length=1, max_length=200)
    kind: Literal["habit", "checkin", "custom"] = "custom"
    days: list[Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]] = Field(min_length=1)
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="UTC", max_length=64)


class AddFinanceEntryPayload(_P):
    direction: Literal["in", "out", "set_aside"]
    label: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    amount_min: Decimal = Field(ge=0)
    amount_max: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    frequency: Literal["daily", "weekly", "monthly", "seasonal", "one_off", "irregular"]
    is_obligation: bool = False
    notes: str | None = Field(default=None, max_length=500)


class SaveJournalPayload(_P):
    content: str = Field(min_length=1, max_length=8000)


PAYLOADS: dict[str, type[_P]] = {
    "create_habit": CreateHabitPayload,
    "log_habit": LogHabitPayload,
    "set_goal": SetGoalPayload,
    "set_reminder": SetReminderPayload,
    "add_finance_entry": AddFinanceEntryPayload,
    "save_journal": SaveJournalPayload,
}
LABELS = {
    "create_habit": "New habit",
    "log_habit": "Log a check-in",
    "set_goal": "Goal",
    "set_reminder": "Reminder",
    "add_finance_entry": "Money entry",
    "save_journal": "Journal entry",
}


def validate_payload(action_type: str, payload: dict[str, Any]) -> _P:
    model = PAYLOADS.get(action_type)
    if model is None:
        raise AppError(422, "unknown_action", "Unknown action type")
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise AppError(
            422,
            "invalid_payload",
            "That action is not valid",
            {"fields": [".".join(map(str, e["loc"])) for e in exc.errors()]},
        ) from exc


def _fmt_amount(x: Decimal | None) -> str:
    if x is None:
        return ""
    q = x.quantize(Decimal("0.01"))
    return f"{int(q):,}" if q == q.to_integral_value() else f"{q:,.2f}"


def _days(days: Sequence[str]) -> str:
    if set(days) == set(DAY_NAMES):
        return "Every day"
    names = [DAY_NAMES[d] for d in DAY_NAMES if d in days]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def build_preview(action_type: str, p: _P) -> str:
    """Plain-language card text, written by code from the validated payload so the
    card can never say one thing and do another."""
    if isinstance(p, CreateHabitPayload):
        parts = [f"Start a habit: {p.title}"]
        if p.cadence.times_per_week:
            parts.append(f"{p.cadence.times_per_week} times a week")
        if p.cadence.preferred_days:
            parts.append(f"on {_days(p.cadence.preferred_days)}")
        if p.minimum_version:
            parts.append(f"hard-day version: {p.minimum_version}")
        return " · ".join(parts)
    if isinstance(p, LogHabitPayload):
        word = {"done": "done", "minimum": "did the short version", "skipped": "skipped"}[p.outcome]
        return f"Mark “{p.habit_title}” as {word} on {p.occurred_on.strftime('%a %d %b')}"
    if isinstance(p, SetGoalPayload):
        if p.amount_per_period and p.period:
            s = f"Set aside {p.currency or ''} {_fmt_amount(p.amount_per_period)} {PERIOD_WORD[p.period]}".replace(
                "  ", " "
            )
            if p.horizon_periods:
                s += f" for {p.horizon_periods} {p.period}s"
            return s
        return f"Goal: {p.title}"
    if isinstance(p, SetReminderPayload):
        return f"Remind me: {p.message} · {_days(p.days)} at {p.time}"
    if isinstance(p, AddFinanceEntryPayload):
        rng = (
            _fmt_amount(p.amount_min)
            if p.amount_min == p.amount_max
            else f"{_fmt_amount(p.amount_min)}–{_fmt_amount(p.amount_max)}"
        )
        direction = {"in": "Money in", "out": "Money out", "set_aside": "Set aside"}[p.direction]
        extra = " (a commitment)" if p.is_obligation else ""
        return f"{direction}: {p.label}, {p.currency} {rng} {p.frequency.replace('_', ' ')}{extra}"
    if isinstance(p, SaveJournalPayload):
        snippet = p.content if len(p.content) <= 80 else p.content[:77] + "…"
        return f"Save to your journal: “{snippet}”"
    raise AppError(422, "unknown_action", "Unknown action type")


def idempotency_key(action_type: str, payload: dict[str, Any], session_id: UUID | None) -> str:
    canonical = json.dumps({"t": action_type, "p": payload, "s": str(session_id)}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def enqueue(
    session: AsyncSession,
    user_id: UUID,
    action_type: str,
    payload: dict[str, Any],
    session_id: UUID | None = None,
) -> ActionQueue:
    """Called by the agent (as kin_agent): it may only INSERT here."""
    p = validate_payload(action_type, payload)
    clean = p.model_dump(mode="json")
    key = idempotency_key(action_type, clean, session_id)
    stmt = (
        pg_insert(ActionQueue)
        .values(
            user_id=user_id,
            session_id=session_id,
            action_type=action_type,
            payload=clean,
            preview=build_preview(action_type, p),
            idempotency_key=key,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "idempotency_key"])
    )
    await session.execute(stmt)
    row = await session.scalar(
        select(ActionQueue).where(ActionQueue.user_id == user_id, ActionQueue.idempotency_key == key)
    )
    assert row is not None
    await audit(session, "action.queued", "action_queue", row.id)
    return row


async def list_actions(session: AsyncSession, user_id: UUID, status: str | None) -> list[ActionQueue]:
    q = select(ActionQueue).where(ActionQueue.user_id == user_id)
    if status:
        q = q.where(ActionQueue.status == status)
    q = q.order_by(ActionQueue.created_at.desc()).limit(100)
    return list((await session.execute(q)).scalars())


async def _locked(session: AsyncSession, user_id: UUID, action_id: UUID) -> ActionQueue:
    peek = await session.scalar(select(ActionQueue).where(ActionQueue.id == action_id, ActionQueue.user_id == user_id))
    if peek is None:
        raise not_found("action")
    if await _expire_if_stale(session, peek):
        raise AppError(409, "expired", "This action expired. Ask again if you still want it.")
    row = await session.scalar(
        select(ActionQueue).where(ActionQueue.id == action_id, ActionQueue.user_id == user_id).with_for_update()
    )
    if row is None:
        raise not_found("action")
    return row


async def _expire_if_stale(session: AsyncSession, row: ActionQueue) -> bool:
    """Mark a stale pending action expired. The update commits in its own
    transaction so it sticks even though the request then fails with 409.
    Called BEFORE the row is locked, so the second transaction cannot block."""
    if row.status == "pending" and row.expires_at <= now_utc():
        from app.db.engine import user_session

        async with user_session(row.user_id) as s2:
            await s2.execute(
                text(
                    "update public.action_queue set status = 'expired', decided_at = now() "
                    "where id = :i and status = 'pending' and expires_at <= now()"
                ),
                {"i": row.id},
            )
        return True
    return False


async def approve(session: AsyncSession, user_id: UUID, action_id: UUID) -> ActionQueue:
    from app.services.executor import execute  # separate module: the only code that writes domain tables

    row = await _locked(session, user_id, action_id)
    if row.status == "executed":
        return row  # double-approve: no extra effect
    if row.status not in ("pending", "failed"):
        raise AppError(409, "not_pending", f"This action is {row.status}")
    row.status, row.decided_at = "approved", now_utc()
    row.status = "executing"
    await session.flush()
    # Re-validate at execution time (Section 9.2).
    p = validate_payload(row.action_type, row.payload)
    try:
        async with session.begin_nested():
            result = await execute(session, user_id, row.action_type, p, row.id)
        row.status, row.result, row.executed_at = "executed", result, now_utc()
        await audit(session, "action.executed", "action_queue", row.id)
    except AppError as exc:
        row.status, row.result = "failed", {"error": exc.code}
        await audit(session, "action.failed", "action_queue", row.id)
    await session.flush()
    return row


async def edit(session: AsyncSession, user_id: UUID, action_id: UUID, payload: dict[str, Any]) -> ActionQueue:
    row = await _locked(session, user_id, action_id)
    if row.status != "pending":
        raise AppError(409, "not_pending", f"This action is {row.status}")
    p = validate_payload(row.action_type, payload)
    row.payload_history = [*row.payload_history, {"payload": row.payload, "replaced_at": now_utc().isoformat()}]
    row.payload = p.model_dump(mode="json")
    row.preview = build_preview(row.action_type, p)
    await session.flush()
    await audit(session, "action.edited", "action_queue", row.id)
    return row


async def cancel(session: AsyncSession, user_id: UUID, action_id: UUID) -> ActionQueue:
    row = await _locked(session, user_id, action_id)
    if row.status != "pending":
        raise AppError(409, "not_pending", f"This action is {row.status}")
    row.status, row.decided_at = "cancelled", now_utc()
    await session.flush()
    await audit(session, "action.cancelled", "action_queue", row.id)
    return row


async def expire_stale_all(session: AsyncSession) -> int:
    """Worker job (runs as kin_worker, which may see all rows)."""
    res = await session.execute(
        text(
            "update public.action_queue set status = 'expired', decided_at = now() "
            "where status = 'pending' and expires_at <= now()"
        )
    )
    return int(res.rowcount or 0)  # type: ignore[attr-defined]
