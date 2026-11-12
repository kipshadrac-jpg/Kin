from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.deps import DbDep, UserDep
from app.schemas.domain import ReminderIn, ReminderOut
from app.services import reminders as svc

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("", response_model=list[ReminderOut])
async def list_reminders(user: UserDep, db: DbDep) -> list[Any]:
    return await svc.list_reminders(db, user.id)


@router.post("", response_model=ReminderOut, status_code=201)
async def create(body: ReminderIn, user: UserDep, db: DbDep) -> Any:
    return await svc.create_reminder(db, user.id, body.kind, body.message, body.days, body.time, body.timezone)


@router.post("/{reminder_id}/{status}", response_model=ReminderOut)
async def set_status(reminder_id: UUID, status: str, user: UserDep, db: DbDep) -> Any:
    from app.errors import AppError

    mapping = {"pause": "paused", "resume": "active", "cancel": "cancelled"}
    if status not in mapping:
        raise AppError(404, "not_found", "unknown operation")
    return await svc.set_status(db, user.id, reminder_id, mapping[status])
