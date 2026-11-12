"""POST /chat — one agent turn, streamed as Server-Sent Events.

Events: {"type":"status","stage":<node>} as each graph node finishes, then one
{"type":"message", ...} with the checked reply, then {"type":"done"}.
The reply is sent only after the output checks, so nothing unchecked is ever
shown and then retracted.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.agents.graph import build_graph, person_today
from app.db.engine import user_session
from app.deps import UserDep
from app.errors import AppError
from app.jobs import after_turn
from app.models.tables import ReasoningSession
from app.providers.base import EmbeddingProvider, LLMProvider, Message, PrivacyModeError, ProviderError
from app.providers.registry import embeddings_for, llm_for, set_privacy_mode
from app.ratelimit import limit
from app.schemas.domain import ChatIn
from app.services.context import get_context_row, get_profile

router = APIRouter(tags=["chat"])
log = logging.getLogger("kin.chat")
STAGE_LABELS = {
    "safety_screen": "Checking in",
    "router": "Understanding",
    "context_inject": "Remembering what you told me",
    "domain_agent": "Thinking",
    "output_checks": "Double-checking",
    "persist": "Saving",
}


_graphs: dict[tuple[int, int], Any] = {}


def _graph(llm: LLMProvider | None, emb: EmbeddingProvider) -> Any:
    key = (id(llm), id(emb))
    if key not in _graphs:
        _graphs[key] = build_graph(llm, emb)
    return _graphs[key]


def _value(section: dict[str, Any], key: str) -> Any:
    fact = (section or {}).get(key)
    return fact.get("value") if isinstance(fact, dict) else None


async def _initial_state(user_id: UUID, body: ChatIn) -> tuple[dict[str, Any], str]:
    async with user_session(user_id) as db:
        prof = await get_profile(db, user_id)
        ctx = await get_context_row(db, user_id)
        history: list[Message] = []
        if body.session_id:
            sess = await db.scalar(
                select(ReasoningSession).where(
                    ReasoningSession.id == body.session_id, ReasoningSession.user_id == user_id
                )
            )
            if sess is None:
                raise AppError(404, "not_found", "conversation not found")
            history = [Message(role=m["role"], content=m["content"]) for m in sess.transcript[-12:]]
    tz = _value(ctx.region, "timezone") or "UTC"
    country = _value(ctx.region, "country")
    state = {
        "user_id": user_id,
        "privacy_mode": prof.privacy_mode,
        "session_id": body.session_id,
        "message": body.message,
        "history": history,
        "today": person_today(tz),
        "timezone": tz,
        "country": country.upper() if isinstance(country, str) and len(country) == 2 else country,
    }
    return state, prof.privacy_mode


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


async def run_turn(state: dict[str, Any], mode: str) -> AsyncIterator[dict[str, Any]]:
    set_privacy_mode(mode)  # set inside the task that makes the provider calls
    graph = _graph(llm_for(mode), embeddings_for(mode))
    result: dict[str, Any] | None = None
    try:
        async for chunk in graph.astream(state, stream_mode="updates"):
            for node, update in chunk.items():
                yield {"type": "status", "stage": node, "label": STAGE_LABELS.get(node, node)}
                if node == "persist" and update:
                    result = update.get("result")
    except AppError as exc:
        yield {"type": "error", "code": exc.code, "message": exc.message}
        return
    except PrivacyModeError:
        yield {
            "type": "error",
            "code": "local_mode",
            "message": "Local mode is on, and this server has no local model.",
        }
        return
    except ProviderError:
        yield {
            "type": "error",
            "code": "model_unavailable",
            "message": "I couldn't reach my thinking model. Try again soon.",
        }
        return
    if result is None:
        yield {"type": "error", "code": "internal_error", "message": "Something went wrong"}
        return
    await after_turn(state["user_id"], UUID(result["session_id"]), state["message"])
    yield {"type": "message", **result}


@router.post("/chat", dependencies=[Depends(limit("chat"))])
async def chat(body: ChatIn, user: UserDep) -> Any:
    state, mode = await _initial_state(user.id, body)
    if not body.stream:
        final: dict[str, Any] = {}
        async for ev in run_turn(state, mode):
            if ev["type"] in ("message", "error"):
                final = ev
        if final.get("type") == "error":
            raise AppError(503, final["code"], final["message"])
        return final

    async def gen() -> AsyncIterator[str]:
        async for ev in run_turn(state, mode):
            yield _sse(ev)
        yield _sse({"type": "done"})

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/chat/sessions")
async def sessions(user: UserDep) -> list[dict[str, Any]]:
    async with user_session(user.id) as db:
        rows = (
            await db.execute(
                select(ReasoningSession)
                .where(ReasoningSession.user_id == user.id)
                .order_by(ReasoningSession.updated_at.desc())
                .limit(30)
            )
        ).scalars()
        return [
            {
                "id": r.id,
                "topic": r.topic,
                "outcome_summary": r.outcome_summary,
                "updated_at": r.updated_at,
                "turns": len(r.transcript) // 2,
            }
            for r in rows
        ]


@router.get("/chat/sessions/{session_id}")
async def session_detail(session_id: UUID, user: UserDep) -> dict[str, Any]:
    async with user_session(user.id) as db:
        r = await db.scalar(
            select(ReasoningSession).where(ReasoningSession.id == session_id, ReasoningSession.user_id == user.id)
        )
        if r is None:
            raise AppError(404, "not_found", "conversation not found")
        return {
            "id": r.id,
            "topic": r.topic,
            "transcript": r.transcript,
            "outcome_summary": r.outcome_summary,
            "decisions": r.decisions,
            "updated_at": r.updated_at,
        }
