"""Work that follows a turn or a journal entry: fact extraction into
context_proposals, and session summaries. Both run as `kin_agent` for one
person, so they can only insert proposals / summaries, never edit the profile."""

from uuid import UUID

from sqlalchemy import delete, select

from app.agents.llm_io import ExtractionOut, SummaryOut, prompt, structured
from app.db.engine import user_session
from app.models.tables import Memory, Profile, ReasoningSession
from app.providers.base import Message, ProviderError, privacy_mode_var
from app.providers.registry import embeddings_for, llm_for
from app.services import memory as memory_svc
from app.services import proposals as proposals_svc
from app.services.bundle import FIELD_LABELS


async def _mode(user_id: UUID) -> str:
    async with user_session(user_id, "kin_agent") as db:
        p = await db.get(Profile, user_id)
        return p.privacy_mode if p else "cloud"


async def extract_proposals(user_id: UUID, text: str, memory_id: UUID | None) -> int:
    mode = await _mode(user_id)
    privacy_mode_var.set(mode)
    llm = llm_for(mode)
    if llm is None or len(text.strip()) < 15:
        return 0
    field_paths = "\n".join(f"- {fp}: {label}" for fp, label in FIELD_LABELS.items())
    try:
        out = await structured(
            llm,
            system=prompt("extraction_v1.md").replace("{field_paths}", field_paths),
            schema=ExtractionOut,
            max_tokens=800,
            effort="low",
            messages=[Message(role="user", content=f"<text>\n{text}\n</text>")],
        )
    except ProviderError:
        return 0
    async with user_session(user_id, "kin_agent") as db:
        created = await proposals_svc.add_candidates(
            db, user_id, text, memory_id, [c.model_dump() for c in out.candidates]
        )
    return len(created)


async def summarize_session(user_id: UUID, session_id: UUID) -> bool:
    mode = await _mode(user_id)
    privacy_mode_var.set(mode)
    llm = llm_for(mode)
    if llm is None:
        return False
    async with user_session(user_id, "kin_agent") as db:
        sess = await db.scalar(
            select(ReasoningSession).where(ReasoningSession.id == session_id, ReasoningSession.user_id == user_id)
        )
        if sess is None or len(sess.transcript) < 4:
            return False
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in sess.transcript[-30:])
    try:
        out = await structured(
            llm,
            system=prompt("summary_v1.md"),
            schema=SummaryOut,
            max_tokens=600,
            effort="low",
            messages=[Message(role="user", content=f"<transcript>\n{transcript}\n</transcript>")],
        )
    except ProviderError:
        return False
    async with user_session(user_id, "kin_agent") as db:
        sess = await db.scalar(select(ReasoningSession).where(ReasoningSession.id == session_id))
        if sess is None:
            return False
        sess.outcome_summary, sess.decisions = out.outcome_summary, out.decisions
        # One summary memory per session; it links back to the session it came from.
        await db.execute(
            delete(Memory).where(
                Memory.user_id == user_id,
                Memory.kind == "session_summary",
                Memory.metadata_["session_id"].astext == str(session_id),
            )
        )
        content = out.outcome_summary + ("" if not out.decisions else " Decisions: " + "; ".join(out.decisions))
        await memory_svc.store(
            db,
            user_id,
            content,
            embeddings_for(mode),
            kind="session_summary",
            metadata={"session_id": str(session_id), "topic": sess.topic},
        )
    return True
