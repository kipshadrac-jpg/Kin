from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.deps import DbDep, UserDep
from app.models.tables import UserContext
from app.schemas.context import ContextIn, ContextOut, ProposalOut, ProposalResolve, VersionOut
from app.services import context as svc
from app.services import proposals as proposals_svc

router = APIRouter(prefix="/context", tags=["context"])


def _out(row: UserContext) -> dict[str, Any]:
    return {**svc.snapshot(row), "version": row.version, "updated_at": row.updated_at}


@router.post("/onboard", response_model=ContextOut)
async def onboard(body: ContextIn, user: UserDep, db: DbDep) -> dict[str, Any]:
    return _out(await svc.onboard(db, user.id, body))


@router.get("", response_model=ContextOut)
async def get_context(user: UserDep, db: DbDep) -> dict[str, Any]:
    return _out(await svc.get_context_row(db, user.id))


@router.patch("", response_model=ContextOut)
async def patch_context(body: ContextIn, user: UserDep, db: DbDep) -> dict[str, Any]:
    return _out(await svc.patch(db, user.id, body))


@router.get("/versions", response_model=list[VersionOut])
async def versions(user: UserDep, db: DbDep) -> list[Any]:
    return list(await svc.list_versions(db, user.id))


@router.post("/revert/{version}", response_model=ContextOut)
async def revert(version: int, user: UserDep, db: DbDep) -> dict[str, Any]:
    return _out(await svc.revert(db, user.id, version))


@router.get("/proposals", response_model=list[ProposalOut])
async def proposals(user: UserDep, db: DbDep) -> list[Any]:
    return list(await proposals_svc.list_pending(db, user.id))


@router.post("/proposals/{proposal_id}/resolve", response_model=ProposalOut)
async def resolve(proposal_id: UUID, body: ProposalResolve, user: UserDep, db: DbDep) -> Any:
    return await proposals_svc.resolve(db, user.id, proposal_id, body.decision, body.edited_value)
