"""Request/response shapes for memories, habits, reminders, finance, actions, chat."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryIn(_In):
    content: str = Field(min_length=1, max_length=8000)
    kind: Literal["journal", "note"] = "journal"
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryOut(BaseModel):
    id: UUID
    kind: str
    content: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class MemorySearchIn(_In):
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)


class MemoryHit(BaseModel):
    id: UUID
    kind: str
    content: str
    created_at: datetime
    score: float


class Created(BaseModel):
    id: UUID


class DeleteAccountIn(_In):
    confirm: str


class HabitIn(_In):
    title: str = Field(min_length=1, max_length=120)
    why: str | None = Field(default=None, max_length=500)
    minimum_version: str | None = Field(default=None, max_length=120)
    cadence: dict[str, Any] = Field(default_factory=dict)


class HabitPatch(_In):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    why: str | None = Field(default=None, max_length=500)
    minimum_version: str | None = Field(default=None, max_length=120)
    cadence: dict[str, Any] | None = None
    status: Literal["active", "paused", "archived"] | None = None


class CheckinIn(_In):
    occurred_on: date
    outcome: Literal["done", "minimum", "skipped"]
    note: str | None = Field(default=None, max_length=500)


class CheckinOut(BaseModel):
    id: UUID
    habit_id: UUID
    occurred_on: date
    outcome: str
    note: str | None
    model_config = ConfigDict(from_attributes=True)


class ReminderOut(BaseModel):
    id: UUID
    kind: str
    message: str
    schedule: dict[str, Any]
    next_fire_at: datetime | None
    status: str
    model_config = ConfigDict(from_attributes=True)


class ReminderIn(_In):
    message: str = Field(min_length=1, max_length=200)
    kind: Literal["habit", "checkin", "custom"] = "custom"
    days: list[Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]] = Field(min_length=1)
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="UTC", max_length=64)


class FinanceEntryIn(_In):
    direction: Literal["in", "out", "set_aside"]
    label: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    amount_min: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    amount_max: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    frequency: Literal["daily", "weekly", "monthly", "seasonal", "one_off", "irregular"]
    is_obligation: bool = False
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _range(self) -> "FinanceEntryIn":
        if self.amount_max < self.amount_min:
            raise ValueError("amount_max must be at least amount_min")
        return self


class FinanceEntryOut(BaseModel):
    id: UUID
    direction: str
    label: str
    category: str | None
    amount_min: Decimal
    amount_max: Decimal
    currency: str
    frequency: str
    is_obligation: bool
    notes: str | None
    model_config = ConfigDict(from_attributes=True)


class ScenarioRequest(_In):
    kind: Literal["set_aside", "cash_flow"] = "set_aside"
    amount_per_period: Decimal | None = Field(default=None, gt=0)
    period: Literal["day", "week", "month"] = "week"
    horizon_periods: int = Field(default=12, gt=0, le=520)
    premise: str | None = Field(default=None, max_length=200)


class ActionOut(BaseModel):
    id: UUID
    action_type: str
    payload: dict[str, Any]
    preview: str
    status: str
    session_id: UUID | None
    result: dict[str, Any] | None
    created_at: datetime
    expires_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ActionEditIn(_In):
    payload: dict[str, Any]


class ChatIn(_In):
    message: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    stream: bool = True
