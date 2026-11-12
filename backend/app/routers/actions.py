from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.deps import DbDep, UserDep
from app.schemas.domain import ActionEditIn, ActionOut
from app.services import actions as svc

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("", response_model=list[ActionOut])
async def list_actions(user: UserDep, db: DbDep, status: str | None = "pending") -> list[Any]:
    return await svc.list_actions(db, user.id, status)


@router.post("/{action_id}/approve", response_model=ActionOut)
async def approve(action_id: UUID, user: UserDep, db: DbDep) -> Any:
    return await svc.approve(db, user.id, action_id)


@router.post("/{action_id}/edit", response_model=ActionOut)
async def edit(action_id: UUID, body: ActionEditIn, user: UserDep, db: DbDep) -> Any:
    return await svc.edit(db, user.id, action_id, body.payload)


@router.post("/{action_id}/cancel", response_model=ActionOut)
async def cancel(action_id: UUID, user: UserDep, db: DbDep) -> Any:
    return await svc.cancel(db, user.id, action_id)
