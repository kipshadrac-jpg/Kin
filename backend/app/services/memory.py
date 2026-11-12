"""Semantic memory: store text with an embedding, search by similarity.

Vectors are written with an explicit cast to extensions.vector and compared
with pgvector's cosine-distance operator (<=>). We qualify the operator with its
schema so it resolves no matter what search_path the session has.
Search only compares rows embedded by the SAME model as the query, because
vectors from different models are not comparable.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import audit
from app.errors import not_found
from app.models.tables import Memory
from app.providers.base import EmbeddingProvider

MAX_CONTENT = 8000


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"


async def store(
    session: AsyncSession,
    user_id: UUID,
    content: str,
    embedder: EmbeddingProvider,
    kind: str = "journal",
    metadata: dict[str, Any] | None = None,
) -> UUID:
    [vec] = await embedder.embed([content])
    row = await session.execute(
        text(
            """insert into public.memories (user_id, kind, content, metadata, embedding, embedding_model)
               values (:u, :k, :c, cast(:m as jsonb), cast(:e as extensions.vector), :em)
               returning id"""
        ),
        {
            "u": user_id,
            "k": kind,
            "c": content,
            "m": _json(metadata or {}),
            "e": vector_literal(vec),
            "em": embedder.model_name,
        },
    )
    mem_id: UUID = row.scalar_one()
    await audit(session, "memory.created", "memories", mem_id)
    return mem_id


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj)


async def list_memories(
    session: AsyncSession, user_id: UUID, limit: int, before: datetime | None, kind: str | None
) -> list[Memory]:
    q = select(Memory).where(Memory.user_id == user_id)
    if before is not None:
        q = q.where(Memory.created_at < before)
    if kind is not None:
        q = q.where(Memory.kind == kind)
    q = q.order_by(Memory.created_at.desc()).limit(limit)
    return list((await session.execute(q)).scalars())


async def search(
    session: AsyncSession,
    user_id: UUID,
    query: str,
    embedder: EmbeddingProvider,
    k: int = 5,
    kinds: list[str] | None = None,
    max_age_days: int | None = 365,
) -> list[dict[str, Any]]:
    [vec] = await embedder.embed([query])
    sql = """
        select id, kind, content, metadata, created_at,
               1 - (embedding operator(extensions.<=>) cast(:q as extensions.vector)) as score
        from public.memories
        where user_id = :u and embedding is not null and embedding_model = :em
          and (cast(:kinds as text[]) is null or kind = any(cast(:kinds as text[])))
          and (cast(:age as int) is null or created_at > now() - make_interval(days => cast(:age as int)))
        order by embedding operator(extensions.<=>) cast(:q as extensions.vector)
        limit :k
    """
    rows = await session.execute(
        text(sql),
        {
            "q": vector_literal(vec),
            "u": user_id,
            "em": embedder.model_name,
            "kinds": kinds,
            "age": max_age_days,
            "k": k,
        },
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "content": r.content,
            "metadata": r.metadata,
            "created_at": r.created_at,
            "score": float(r.score),
        }
        for r in rows
    ]


async def delete(session: AsyncSession, user_id: UUID, memory_id: UUID) -> None:
    mem = await session.scalar(select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
    if mem is None:
        raise not_found("memory")
    await session.delete(mem)
    await audit(session, "memory.deleted", "memories", memory_id)
