from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.deps import DbDep, UserDep
from app.jobs import after_memory
from app.providers.registry import embeddings_for, set_privacy_mode
from app.ratelimit import limit
from app.schemas.domain import Created, MemoryHit, MemoryIn, MemoryOut, MemorySearchIn
from app.services import memory as svc
from app.services.context import get_profile

router = APIRouter(prefix="/memories", tags=["memories"], dependencies=[Depends(limit("memories"))])


@router.post("", response_model=Created, status_code=201)
async def create_memory(body: MemoryIn, user: UserDep, db: DbDep) -> dict[str, Any]:
    prof = await get_profile(db, user.id)
    set_privacy_mode(prof.privacy_mode)
    mid = await svc.store(db, user.id, body.content, embeddings_for(prof.privacy_mode), body.kind, body.metadata)
    if body.kind == "journal":
        await after_memory(user.id, mid)  # proposal extraction runs in the worker
    return {"id": mid}


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    user: UserDep,
    db: DbDep,
    limit_: int = Query(20, alias="limit", ge=1, le=100),
    before: datetime | None = None,
    kind: str | None = None,
) -> list[Any]:
    return await svc.list_memories(db, user.id, limit_, before, kind)


@router.post("/search", response_model=list[MemoryHit])
async def search(body: MemorySearchIn, user: UserDep, db: DbDep) -> list[dict[str, Any]]:
    prof = await get_profile(db, user.id)
    set_privacy_mode(prof.privacy_mode)
    return await svc.search(db, user.id, body.query, embeddings_for(prof.privacy_mode), k=body.k, max_age_days=None)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: UUID, user: UserDep, db: DbDep) -> Response:
    await svc.delete(db, user.id, memory_id)
    return Response(status_code=204)
