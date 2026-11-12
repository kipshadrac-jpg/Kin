"""Shapes the model must return, and a helper that validates them.

Section 15: structured outputs are validated with Pydantic; on failure, one
repair attempt, then the caller falls back to a graceful message.
These models use only simple JSON types (no Decimal) so every provider's
structured-output mode can follow them.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.providers.base import LLMProvider, Message, ProviderError

PROMPTS = Path(__file__).parent / "prompts"
T = TypeVar("T", bound=BaseModel)

Intent = Literal[
    "habit_log",
    "habit_plan",
    "finance_query",
    "finance_log",
    "motivation_request",
    "open_reasoning",
    "profile_edit",
    "safety_escalation",
]


@lru_cache
def prompt(name: str) -> str:
    return (PROMPTS / name).read_text()


class RouterOut(BaseModel):
    intent: Intent
    commitment_language: bool


class HabitChoice(BaseModel):
    title: str
    why: str | None
    minimum_version: str | None
    times_per_week: int | None
    preferred_days: list[Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]] | None


class LogHabitChoice(BaseModel):
    habit_id: str
    occurred_on: str  # YYYY-MM-DD
    outcome: Literal["done", "minimum", "skipped"]


class ReminderChoice(BaseModel):
    message: str
    kind: Literal["habit", "checkin", "custom"]
    days: list[Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]]
    time: str  # HH:MM 24h


class GoalChoice(BaseModel):
    domain: Literal["habit", "finance", "general"]
    title: str
    amount_per_period: float | None
    period: Literal["day", "week", "month"] | None
    horizon_periods: int | None


class FinanceEntryChoice(BaseModel):
    direction: Literal["in", "out", "set_aside"]
    label: str
    amount_min: float
    amount_max: float
    frequency: Literal["daily", "weekly", "monthly", "seasonal", "one_off", "irregular"]
    is_obligation: bool


class ActionChoice(BaseModel):
    type: Literal["none", "create_habit", "log_habit", "set_reminder", "set_goal", "add_finance_entry", "save_journal"]
    create_habit: HabitChoice | None
    log_habit: LogHabitChoice | None
    set_reminder: ReminderChoice | None
    set_goal: GoalChoice | None
    add_finance_entry: FinanceEntryChoice | None
    save_journal_text: str | None


class WhatIf(BaseModel):
    """A set-aside what-if the person described, if any (amounts only as they said them)."""

    amount_per_period: float
    period: Literal["day", "week", "month"]
    horizon_periods: int


class TurnOut(BaseModel):
    reply: str
    used_refs: list[str]
    asks_about_gap: bool
    what_if: WhatIf | None
    action: ActionChoice


class CaseOut(BaseModel):
    name: Literal["best", "realistic", "stress"]
    periods_hit_min: int
    periods_hit_max: int
    assumptions: list[str]
    what_would_have_to_be_true: str


class ScenarioOut(BaseModel):
    cases: list[CaseOut]
    unknowns: list[str]
    used_refs: list[str]


class Candidate(BaseModel):
    field_path: str
    value: str
    evidence_quote: str


class ExtractionOut(BaseModel):
    candidates: list[Candidate]


class SummaryOut(BaseModel):
    outcome_summary: str
    decisions: list[str]


async def structured(
    llm: LLMProvider,
    *,
    system: str,
    messages: list[Message],
    schema: type[T],
    max_tokens: int = 1500,
    effort: str = "low",
) -> T:
    """Call the model for a structured answer, with exactly one repair attempt."""
    last_error = ""
    for attempt in range(2):
        msgs = messages
        if attempt == 1:
            msgs = [
                *messages,
                Message(
                    role="user",
                    content=(
                        "Your previous answer did not match the required JSON format "
                        f"({last_error[:300]}). Answer again, using only the required format."
                    ),
                ),
            ]
        try:
            res = await llm.complete(
                system=system, messages=msgs, response_schema=schema, max_tokens=max_tokens, effort=effort
            )
            if isinstance(res.parsed, schema):
                return res.parsed
            return schema.model_validate_json(res.text)
        except ValidationError as exc:
            last_error = str(exc)
    raise ProviderError("model output did not validate after one repair")
