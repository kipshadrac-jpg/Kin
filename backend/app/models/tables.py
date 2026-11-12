"""SQLAlchemy models mirroring supabase/migrations/0001_init.sql.

The SQL migration is the source of truth; these models never create tables.
`memories.embedding` is deliberately not mapped: vectors are written and
searched with explicit SQL in services/memory.py.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str | None] = mapped_column(Text)
    privacy_mode: Mapped[str] = mapped_column(Text, server_default="cloud")
    onboarding_state: Mapped[str] = mapped_column(Text, server_default="not_started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserContext(Base):
    __tablename__ = "user_context"
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    region: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    economic_frame: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    values_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    emotional_baseline: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserContextVersion(Base):
    __tablename__ = "user_context_versions"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    change_source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text, server_default="journal")
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default="{}")
    embedding_model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextProposal(Base):
    __tablename__ = "context_proposals"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    section: Mapped[str] = mapped_column(Text)
    field_path: Mapped[str] = mapped_column(Text)
    proposed_value: Mapped[Any] = mapped_column(JSONB)
    evidence_quote: Mapped[str] = mapped_column(Text)
    evidence_memory_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Habit(Base):
    __tablename__ = "habits"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(Text)
    why: Mapped[str | None] = mapped_column(Text)
    cadence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    minimum_version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HabitCheckin(Base):
    __tablename__ = "habit_checkins"
    id: Mapped[UUID] = _uuid_pk()
    habit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    occurred_on: Mapped[date] = mapped_column(Date)
    outcome: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinanceEntry(Base):
    __tablename__ = "finance_entries"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    direction: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    amount_min: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount_max: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    frequency: Mapped[str] = mapped_column(Text)
    is_obligation: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    domain: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReasoningSession(Base):
    __tablename__ = "reasoning_sessions"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    topic: Mapped[str] = mapped_column(Text)
    transcript: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    outcome_summary: Mapped[str | None] = mapped_column(Text)
    decisions: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    premise: Mapped[str] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB)
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActionQueue(Base):
    __tablename__ = "action_queue"
    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    action_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_history: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    preview: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    event: Mapped[str] = mapped_column(Text)
    entity: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Tables that hold a person's data, in an order safe for deletion (children first).
USER_TABLES: list[type[Base]] = [
    ActionQueue,
    Scenario,
    Reminder,
    HabitCheckin,
    Habit,
    FinanceEntry,
    Goal,
    ContextProposal,
    Memory,
    ReasoningSession,
    UserContextVersion,
    UserContext,
    Profile,
]
