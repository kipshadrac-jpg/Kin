"""Context profile shapes (Section 7.1). Every field is optional; clients send
plain values and the service wraps each with its origin (Section 7.2)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Text2k = Field(default=None, max_length=2000)
ShortList = Field(default=None, max_length=20)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuietHours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_: str = Field(alias="from", pattern=r"^\d{2}:\d{2}$")
    to: str = Field(pattern=r"^\d{2}:\d{2}$")


class RegionIn(_Section):
    country: str | None = Field(default=None, max_length=60)
    area_type: Literal["city", "town", "rural", "prefer_not_to_say"] | None = None
    languages: list[str] | None = ShortList
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    timezone: str | None = Field(default=None, max_length=64)
    notes: str | None = Text2k


class EconomicFrameIn(_Section):
    income_pattern: Literal["regular", "irregular", "cash", "mixed", "none", "prefer_not_to_say"] | None = None
    how_money_arrives: str | None = Text2k
    stability: str | None = Text2k
    obligations: list[str] | None = ShortList
    saving_methods: list[str] | None = ShortList


class ValuesProfileIn(_Section):
    matters_most: list[str] | None = ShortList
    non_negotiables: list[str] | None = ShortList
    sensitivities: list[str] | None = ShortList
    aspirations: list[str] | None = ShortList


class EmotionalBaselineIn(_Section):
    encouragement: str | None = Text2k
    backfires: str | None = Text2k
    preferred_tone: str | None = Text2k
    checkin_times: list[str] | None = ShortList
    quiet_hours: QuietHours | None = None


SECTION_MODELS: dict[str, type[_Section]] = {
    "region": RegionIn,
    "economic_frame": EconomicFrameIn,
    "values_profile": ValuesProfileIn,
    "emotional_baseline": EmotionalBaselineIn,
}
SECTIONS = tuple(SECTION_MODELS)


class ContextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: RegionIn | None = None
    economic_frame: EconomicFrameIn | None = None
    values_profile: ValuesProfileIn | None = None
    emotional_baseline: EmotionalBaselineIn | None = None


class Fact(BaseModel):
    value: Any
    source: Literal["onboarding", "user_edit", "accepted_proposal"]
    stated_at: datetime
    evidence_memory_id: UUID | None = None


class ContextOut(BaseModel):
    region: dict[str, Fact] = {}
    economic_frame: dict[str, Fact] = {}
    values_profile: dict[str, Fact] = {}
    emotional_baseline: dict[str, Fact] = {}
    version: int
    updated_at: datetime | None = None


class VersionOut(BaseModel):
    version: int
    change_source: str
    created_at: datetime


class ProposalOut(BaseModel):
    id: UUID
    section: str
    field_path: str
    proposed_value: Any
    evidence_quote: str
    status: str
    created_at: datetime


class ProposalResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "edit", "not_now", "never_ask"]
    edited_value: Any | None = None


class MeOut(BaseModel):
    user_id: UUID
    email: str | None
    display_name: str | None
    locale: str | None
    privacy_mode: str
    onboarding_state: str
    app_name: str
    providers: dict[str, Any]


class MePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=80)
    locale: str | None = Field(default=None, max_length=20)
    privacy_mode: Literal["cloud", "local"] | None = None
    onboarding_state: Literal["not_started", "in_progress", "complete"] | None = None
