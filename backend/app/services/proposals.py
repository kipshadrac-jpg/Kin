"""The proposal loop (Section 7.4): Kin notices a durable fact and ASKS.

Code-side guards (the model's output is never trusted on its own):
  * the evidence quote must appear verbatim in what the person wrote
  * the field must exist in the profile schema
  * never re-ask a field the person said "never ask about"
  * special categories only when stated plainly, in the first person
  * at most 3 new proposals per day
"""

import re
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import audit
from app.errors import AppError, not_found
from app.models.tables import ContextProposal
from app.services.context import apply_accepted_fact, now_utc, valid_field_path

DAILY_LIMIT = 3
SPECIAL_CATEGORY_WORDS = {
    "health": r"\b(diabet|hiv|cancer|depress|anxiety|bipolar|pregnan|disab|illness|medicat|therapy)",
    "religion": (r"\b(church|mosque|temple|pray|faith|muslim|christian|hindu|jewish|catholic|ramadan|sabbath|god\b)"),
    "sexuality": r"\b(gay|lesbian|bisexual|queer|trans|sexual)",
    "immigration": r"\b(visa|asylum|refugee|undocumented|immigra|work permit|residen(ce|cy) permit)",
    "ethnicity": r"\b(tribe|ethnic|race|racial)",
}
FIRST_PERSON = re.compile(r"\b(i|i'm|i am|i've|my|me|mine)\b", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def special_category(quote: str) -> str | None:
    for cat, pat in SPECIAL_CATEGORY_WORDS.items():
        if re.search(pat, quote, re.IGNORECASE):
            return cat
    return None


def candidate_problems(source_text: str, field_path: str, quote: str, value: Any) -> list[str]:
    problems = []
    if not quote or _norm(quote) not in _norm(source_text):
        problems.append("quote not found in source")
    if valid_field_path(field_path) is None:
        problems.append("unknown field")
    if value in (None, "", []):
        problems.append("empty value")
    if special_category(quote) and not FIRST_PERSON.search(quote):
        problems.append("special category not stated directly by the person")
    return problems


async def created_today(session: AsyncSession, user_id: UUID) -> int:
    since = now_utc() - timedelta(hours=24)
    n = await session.scalar(
        select(func.count())
        .select_from(ContextProposal)
        .where(ContextProposal.user_id == user_id, ContextProposal.created_at >= since)
    )
    return int(n or 0)


async def blocked_fields(session: AsyncSession, user_id: UUID) -> set[str]:
    rows = await session.execute(
        select(ContextProposal.field_path).where(
            ContextProposal.user_id == user_id, ContextProposal.status == "never_ask"
        )
    )
    return set(rows.scalars())


async def add_candidates(
    session: AsyncSession,
    user_id: UUID,
    source_text: str,
    memory_id: UUID | None,
    candidates: list[dict[str, Any]],
) -> list[ContextProposal]:
    """Runs as kin_agent: may only INSERT proposals, never touch the profile."""
    room = DAILY_LIMIT - await created_today(session, user_id)
    if room <= 0:
        return []
    blocked = await blocked_fields(session, user_id)
    pending = await session.execute(
        select(ContextProposal.field_path, ContextProposal.proposed_value).where(
            ContextProposal.user_id == user_id, ContextProposal.status == "pending"
        )
    )
    seen = {(fp, str(v)) for fp, v in pending}
    created: list[ContextProposal] = []
    for c in candidates:
        if len(created) >= room:
            break
        fp, quote, value = c.get("field_path", ""), c.get("evidence_quote", ""), c.get("value")
        if candidate_problems(source_text, fp, quote, value) or fp in blocked or (fp, str(value)) in seen:
            continue
        section = fp.split(".")[0]
        row = ContextProposal(
            user_id=user_id,
            section=section,
            field_path=fp,
            proposed_value=value,
            evidence_quote=quote.strip()[:500],
            evidence_memory_id=memory_id,
        )
        session.add(row)
        await session.flush()
        await audit(session, "proposal.created", "context_proposals", row.id)
        seen.add((fp, str(value)))
        created.append(row)
    return created


async def list_pending(session: AsyncSession, user_id: UUID, limit: int = DAILY_LIMIT) -> list[ContextProposal]:
    q = (
        select(ContextProposal)
        .where(ContextProposal.user_id == user_id, ContextProposal.status == "pending")
        .order_by(ContextProposal.created_at)
        .limit(limit)
    )
    return list((await session.execute(q)).scalars())


async def resolve(
    session: AsyncSession, user_id: UUID, proposal_id: UUID, decision: str, edited_value: Any | None
) -> ContextProposal:
    p = await session.scalar(
        select(ContextProposal)
        .where(ContextProposal.id == proposal_id, ContextProposal.user_id == user_id)
        .with_for_update()
    )
    if p is None:
        raise not_found("proposal")
    if p.status != "pending":
        raise AppError(409, "already_resolved", "This was already answered")
    if decision == "accept":
        await apply_accepted_fact(session, user_id, p.field_path, p.proposed_value, p.evidence_memory_id)
        p.status = "accepted"
    elif decision == "edit":
        if edited_value in (None, "", []):
            raise AppError(422, "missing_value", "Add the edited value")
        await apply_accepted_fact(session, user_id, p.field_path, edited_value, p.evidence_memory_id)
        p.proposed_value, p.status = edited_value, "edited"
    elif decision == "not_now":
        p.status = "dismissed"
    elif decision == "never_ask":
        p.status = "never_ask"
    p.resolved_at = now_utc()
    await session.flush()
    await audit(session, f"proposal.{p.status}", "context_proposals", p.id)
    return p
