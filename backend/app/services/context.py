"""Context Engine: the person's self-described profile (Section 7).

Only three things change the profile: onboarding, the person's own edits, and
proposals the person accepted. Every change writes a version row so it can be
reviewed and undone. There is no "inferred" source anywhere in this module.
"""

from datetime import UTC, datetime
from typing import Any, get_args, get_origin
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import audit
from app.errors import AppError, not_found
from app.models.tables import Profile, UserContext, UserContextVersion
from app.schemas.context import SECTION_MODELS, SECTIONS, ContextIn

Source = str  # "onboarding" | "user_edit" | "accepted_proposal"


def now_utc() -> datetime:
    return datetime.now(UTC)


def wrap(value: Any, source: Source, evidence_memory_id: UUID | None = None) -> dict[str, Any]:
    """Section 7.2: every stored fact carries where it came from."""
    return {
        "value": value,
        "source": source,
        "stated_at": now_utc().isoformat(),
        "evidence_memory_id": str(evidence_memory_id) if evidence_memory_id else None,
    }


def _plain(model_obj: Any) -> dict[str, Any]:
    """Only the fields the client actually sent, JSON-ready, with aliases (quiet_hours.from)."""
    return model_obj.model_dump(mode="json", by_alias=True, exclude_unset=True)


async def ensure_rows(session: AsyncSession, user_id: UUID) -> None:
    # Check first: the agent role (kin_agent) may read but not insert these rows.
    if await session.scalar(select(Profile.user_id).where(Profile.user_id == user_id)) is None:
        await session.execute(pg_insert(Profile).values(user_id=user_id).on_conflict_do_nothing())
    if await session.scalar(select(UserContext.user_id).where(UserContext.user_id == user_id)) is None:
        await session.execute(pg_insert(UserContext).values(user_id=user_id, version=0).on_conflict_do_nothing())


async def get_profile(session: AsyncSession, user_id: UUID) -> Profile:
    await ensure_rows(session, user_id)
    p = await session.get(Profile, user_id)
    assert p is not None
    return p


async def get_context_row(session: AsyncSession, user_id: UUID) -> UserContext:
    await ensure_rows(session, user_id)
    row = (await session.execute(select(UserContext).where(UserContext.user_id == user_id))).scalar_one()
    return row


def snapshot(row: UserContext) -> dict[str, Any]:
    return {s: dict(getattr(row, s) or {}) for s in SECTIONS}


async def _write_version(session: AsyncSession, row: UserContext, source: str) -> int:
    last = await session.scalar(
        select(func.coalesce(func.max(UserContextVersion.version), 0)).where(UserContextVersion.user_id == row.user_id)
    )
    new_version = int(last or 0) + 1
    row.version = new_version
    session.add(
        UserContextVersion(user_id=row.user_id, version=new_version, snapshot=snapshot(row), change_source=source)
    )
    await session.flush()
    return new_version


async def onboard(session: AsyncSession, user_id: UUID, body: ContextIn) -> UserContext:
    """Save confirmed onboarding answers (the client shows a read-back screen first)."""
    row = await get_context_row(session, user_id)
    data = _plain(body)
    for section in SECTIONS:
        values = data.get(section) or {}
        setattr(row, section, {k: wrap(v, "onboarding") for k, v in values.items() if v not in (None, "", [])})
    await _write_version(session, row, "onboarding")
    profile = await get_profile(session, user_id)
    profile.onboarding_state = "complete"
    await audit(session, "context.onboarded", "user_context", None)
    return row


async def patch(session: AsyncSession, user_id: UUID, body: ContextIn) -> UserContext:
    """Edit fields. A field sent as null is removed. Each edit bumps the version."""
    row = await get_context_row(session, user_id)
    data = _plain(body)
    if not any(data.get(s) for s in SECTIONS):
        raise AppError(422, "empty_patch", "Nothing to change")
    for section in SECTIONS:
        changes = data.get(section)
        if not changes:
            continue
        current = dict(getattr(row, section) or {})
        for key, value in changes.items():
            if value is None or value == "" or value == []:
                current.pop(key, None)
            else:
                current[key] = wrap(value, "user_edit")
        setattr(row, section, current)
    await _write_version(session, row, "user_edit")
    await audit(session, "context.edited", "user_context", None)
    return row


async def list_versions(session: AsyncSession, user_id: UUID) -> list[UserContextVersion]:
    res = await session.execute(
        select(UserContextVersion)
        .where(UserContextVersion.user_id == user_id)
        .order_by(UserContextVersion.version.desc())
    )
    return list(res.scalars())


async def revert(session: AsyncSession, user_id: UUID, version: int) -> UserContext:
    target = await session.scalar(
        select(UserContextVersion).where(UserContextVersion.user_id == user_id, UserContextVersion.version == version)
    )
    if target is None:
        raise not_found("version")
    row = await get_context_row(session, user_id)
    for section in SECTIONS:
        setattr(row, section, dict(target.snapshot.get(section) or {}))
    await _write_version(session, row, "revert")
    await audit(session, "context.reverted", "user_context", None)
    return row


def _is_list_field(section: str, key: str) -> bool:
    model = SECTION_MODELS[section]
    field = model.model_fields.get(key)
    if field is None:
        return False
    for arg in (field.annotation, *get_args(field.annotation)):
        if get_origin(arg) is list or arg is list:
            return True
    return False


def valid_field_path(field_path: str) -> tuple[str, str] | None:
    parts = field_path.split(".")
    if len(parts) != 2 or parts[0] not in SECTION_MODELS:
        return None
    section, key = parts
    model = SECTION_MODELS[section]
    if key not in model.model_fields and key not in {f.alias for f in model.model_fields.values() if f.alias}:
        return None
    return section, key


async def apply_accepted_fact(
    session: AsyncSession, user_id: UUID, field_path: str, value: Any, evidence_memory_id: UUID | None
) -> UserContext:
    """Write one accepted proposal into the profile (the only non-direct write path)."""
    parsed = valid_field_path(field_path)
    if parsed is None:
        raise AppError(422, "bad_field", "That profile field does not exist")
    section, key = parsed
    # Validate the value against the same schema the person's own edits use.
    model = SECTION_MODELS[section]
    row = await get_context_row(session, user_id)
    current = dict(getattr(row, section) or {})
    if _is_list_field(section, key):
        existing = list((current.get(key) or {}).get("value") or [])
        items = value if isinstance(value, list) else [value]
        merged = existing + [str(i) for i in items if str(i) not in existing]
        model.model_validate({key: merged})
        current[key] = wrap(merged, "accepted_proposal", evidence_memory_id)
    else:
        model.model_validate({key: value})
        current[key] = wrap(value, "accepted_proposal", evidence_memory_id)
    setattr(row, section, current)
    await _write_version(session, row, "accepted_proposal")
    return row
