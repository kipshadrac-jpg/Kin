"""Direct writes: the person creating or ticking their own habits."""

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response

from app.deps import DbDep, UserDep
from app.schemas.domain import CheckinIn, CheckinOut, Created, HabitIn, HabitPatch
from app.services import habits as svc
from app.services.context import get_context_row

router = APIRouter(prefix="/habits", tags=["habits"])


async def _today(db: DbDep, user: UserDep) -> date:
    from app.agents.graph import person_today

    ctx = await get_context_row(db, user.id)
    tz = (
        (ctx.region or {}).get("timezone", {}).get("value")
        if isinstance((ctx.region or {}).get("timezone"), dict)
        else None
    )
    return person_today(tz)


@router.get("")
async def list_habits(user: UserDep, db: DbDep, include_archived: bool = False) -> dict[str, Any]:
    today = await _today(db, user)
    return {"today": today, "habits": await svc.list_habits(db, user.id, today, include_archived)}


@router.post("", response_model=Created, status_code=201)
async def create(body: HabitIn, user: UserDep, db: DbDep) -> Any:
    return await svc.create_habit(db, user.id, body.model_dump())


@router.patch("/{habit_id}", response_model=Created)
async def update(habit_id: UUID, body: HabitPatch, user: UserDep, db: DbDep) -> Any:
    return await svc.update_habit(db, user.id, habit_id, body.model_dump(exclude_unset=True))


@router.delete("/{habit_id}", status_code=204)
async def delete(habit_id: UUID, user: UserDep, db: DbDep) -> Response:
    await svc.delete_habit(db, user.id, habit_id)
    return Response(status_code=204)


@router.get("/{habit_id}/checkins", response_model=list[CheckinOut])
async def checkins(habit_id: UUID, user: UserDep, db: DbDep) -> list[Any]:
    return await svc.list_checkins(db, user.id, habit_id)


@router.post("/{habit_id}/checkins", response_model=CheckinOut, status_code=201)
async def checkin(habit_id: UUID, body: CheckinIn, user: UserDep, db: DbDep) -> Any:
    return await svc.log_checkin(db, user.id, habit_id, body.occurred_on, body.outcome, body.note)


@router.delete("/{habit_id}/checkins/{occurred_on}", status_code=204)
async def undo_checkin(habit_id: UUID, occurred_on: date, user: UserDep, db: DbDep) -> Response:
    await svc.delete_checkin(db, user.id, habit_id, occurred_on)
    return Response(status_code=204)
