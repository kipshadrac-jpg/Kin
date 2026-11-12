"""get_context_bundle: the ONLY door from other modules into the profile (Section 7.5).

It returns the minimum profile slice for the purpose, the most relevant
memories, and `gaps` — things that would matter for this question but are
unknown. Callers must ask or stay general when gaps exist; never fill them.
"""

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.base import EmbeddingProvider
from app.services import memory as memory_svc
from app.services.context import get_context_row

Purpose = Literal["finance", "habits", "motivation", "general"]

# Which fields each purpose may see. Finance does not need the whole values
# profile, habits do not need money details: send the minimum.
PURPOSE_FIELDS: dict[str, dict[str, list[str] | None]] = {
    "finance": {
        "region": ["country", "area_type", "currency", "notes"],
        "economic_frame": None,  # all
        "values_profile": ["matters_most", "sensitivities", "non_negotiables"],
        "emotional_baseline": ["encouragement", "backfires", "preferred_tone"],
    },
    "habits": {
        "region": ["timezone", "notes", "area_type"],
        "values_profile": None,
        "emotional_baseline": None,
    },
    "motivation": {
        "values_profile": ["matters_most", "aspirations", "sensitivities"],
        "emotional_baseline": None,
    },
    "general": {"region": None, "economic_frame": None, "values_profile": None, "emotional_baseline": None},
}

PURPOSE_GAPS: dict[str, list[str]] = {
    "finance": [
        "region.currency",
        "economic_frame.income_pattern",
        "economic_frame.how_money_arrives",
        "economic_frame.obligations",
    ],
    "habits": ["emotional_baseline.encouragement", "region.timezone"],
    "motivation": ["emotional_baseline.encouragement", "emotional_baseline.backfires"],
    "general": [],
}

FIELD_LABELS: dict[str, str] = {
    "region.country": "Where you live",
    "region.area_type": "City, town or rural",
    "region.languages": "Languages",
    "region.currency": "Currency",
    "region.timezone": "Time zone",
    "region.notes": "About where you live",
    "economic_frame.income_pattern": "How regular your income is",
    "economic_frame.how_money_arrives": "How money reaches you",
    "economic_frame.stability": "How stable money feels",
    "economic_frame.obligations": "Who or what you support",
    "economic_frame.saving_methods": "How you save",
    "values_profile.matters_most": "What matters most",
    "values_profile.non_negotiables": "Non-negotiables",
    "values_profile.sensitivities": "Things not to suggest",
    "values_profile.aspirations": "What you're working towards",
    "emotional_baseline.encouragement": "What encouragement feels like",
    "emotional_baseline.backfires": "What backfires",
    "emotional_baseline.preferred_tone": "Preferred tone",
    "emotional_baseline.checkin_times": "Check-in times",
    "emotional_baseline.quiet_hours": "Quiet hours",
}


@dataclass
class ContextBundle:
    purpose: str
    profile: dict[str, dict[str, Any]]  # section -> field -> plain value
    memories: list[dict[str, Any]]
    gaps: list[str]
    gap_labels: list[str] = field(default_factory=list)

    def fact_refs(self) -> list[str]:
        return [f"{s}.{k}" for s, fields in self.profile.items() for k in fields]

    def label_for(self, ref: str) -> str:
        if ref.startswith("memory:"):
            mem = next((m for m in self.memories if f"memory:{m['id']}" == ref), None)
            snippet = (
                (mem["content"][:60] + "…") if mem and len(mem["content"]) > 60 else (mem or {}).get("content", "")
            )
            return f"Something you wrote: “{snippet}”" if snippet else "Something you wrote"
        section, _, key = ref.partition(".")
        value = self.profile.get(section, {}).get(key)
        base = FIELD_LABELS.get(ref, key.replace("_", " ").capitalize())
        if value is None:
            return base
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value = ", ".join(f"{k} {v}" for k, v in value.items())
        return f"{base}: {value}"


def _plain_values(section_data: dict[str, Any], allowed: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, fact in (section_data or {}).items():
        if allowed is not None and key not in allowed:
            continue
        value = fact.get("value") if isinstance(fact, dict) else fact
        if value in (None, "", [], "prefer_not_to_say"):
            continue
        out[key] = value
    return out


async def get_context_bundle(
    session: AsyncSession,
    user_id: UUID,
    purpose: Purpose,
    query: str,
    embedder: EmbeddingProvider,
    k: int = 5,
) -> ContextBundle:
    row = await get_context_row(session, user_id)
    spec = PURPOSE_FIELDS.get(purpose, PURPOSE_FIELDS["general"])
    profile = {section: _plain_values(getattr(row, section), allowed) for section, allowed in spec.items()}
    profile = {s: f for s, f in profile.items() if f}
    gaps = [ref for ref in PURPOSE_GAPS.get(purpose, []) if ref.split(".")[1] not in profile.get(ref.split(".")[0], {})]
    memories = await memory_svc.search(
        session, user_id, query, embedder, k=k, kinds=["journal", "note", "session_summary", "chat"]
    )
    # Drop weak matches: unrelated memories add noise and leak more than needed.
    memories = [m for m in memories if m["score"] >= 0.12]
    return ContextBundle(
        purpose=purpose,
        profile=profile,
        memories=memories,
        gaps=gaps,
        gap_labels=[FIELD_LABELS.get(g, g) for g in gaps],
    )
