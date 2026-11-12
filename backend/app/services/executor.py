"""Executor: the only code that turns an APPROVED action into domain writes.

It runs in the person's own session (role `authenticated`) at the moment they
tap Approve, so the write is theirs, protected by RLS like any direct write.
The agent runtime never imports this module.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models.tables import Goal
from app.providers.registry import embeddings_for
from app.services import finance, habits, memory, reminders
from app.services.actions import (
    AddFinanceEntryPayload,
    CreateHabitPayload,
    LogHabitPayload,
    SaveJournalPayload,
    SetGoalPayload,
    SetReminderPayload,
)
from app.services.context import get_profile


async def execute(
    session: AsyncSession, user_id: UUID, action_type: str, p: BaseModel, action_id: UUID
) -> dict[str, Any]:
    if isinstance(p, CreateHabitPayload):
        h = await habits.create_habit(
            session,
            user_id,
            {
                "title": p.title,
                "why": p.why,
                "minimum_version": p.minimum_version,
                "cadence": p.cadence.model_dump(exclude_none=True),
            },
        )
        return {"habit_id": str(h.id)}
    if isinstance(p, LogHabitPayload):
        c = await habits.log_checkin(session, user_id, p.habit_id, p.occurred_on, p.outcome, p.note)
        return {"checkin_id": str(c.id)}
    if isinstance(p, SetGoalPayload):
        detail = p.model_dump(mode="json", exclude={"domain", "title"}, exclude_none=True)
        g = Goal(user_id=user_id, domain=p.domain, title=p.title, detail=detail)
        session.add(g)
        await session.flush()
        return {"goal_id": str(g.id)}
    if isinstance(p, SetReminderPayload):
        r = await reminders.create_reminder(session, user_id, p.kind, p.message, p.days, p.time, p.timezone)
        return {"reminder_id": str(r.id)}
    if isinstance(p, AddFinanceEntryPayload):
        if p.amount_max < p.amount_min:
            raise AppError(422, "invalid_payload", "Range is inverted")
        e = await finance.create_entry(session, user_id, p.model_dump())
        return {"entry_id": str(e.id)}
    if isinstance(p, SaveJournalPayload):
        profile = await get_profile(session, user_id)
        mid = await memory.store(
            session,
            user_id,
            p.content,
            embeddings_for(profile.privacy_mode),
            kind="journal",
            metadata={"from_action": str(action_id)},
        )
        return {"memory_id": str(mid)}
    raise AppError(422, "unknown_action", f"No executor for {action_type}")
