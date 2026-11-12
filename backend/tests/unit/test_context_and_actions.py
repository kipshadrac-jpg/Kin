from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.agents.llm_io import TurnOut
from app.errors import AppError
from app.providers.embeddings import FakeEmbeddings, HashingEmbeddings
from app.providers.llm import strict_json_schema
from app.services.actions import build_preview, idempotency_key, validate_payload
from app.services.context import valid_field_path, wrap
from app.services.habits import consistency, needs_review
from app.services.proposals import candidate_problems
from app.services.reminders import build_rrule, next_fire


def test_wrap_records_origin() -> None:
    f = wrap("Income varies", "onboarding")
    assert f["value"] == "Income varies" and f["source"] == "onboarding" and f["evidence_memory_id"] is None
    assert datetime.fromisoformat(f["stated_at"]).tzinfo is not None


def test_field_paths() -> None:
    assert valid_field_path("economic_frame.obligations") == ("economic_frame", "obligations")
    assert valid_field_path("economic_frame.inferred_religion") is None
    assert valid_field_path("nope.x") is None


def test_previews_are_written_by_code() -> None:
    p = validate_payload(
        "set_reminder",
        {"message": "Walk", "days": ["MO", "WE", "FR"], "time": "06:30", "timezone": "Africa/Nairobi", "kind": "habit"},
    )
    assert build_preview("set_reminder", p) == "Remind me: Walk · Mon, Wed and Fri at 06:30"
    g = validate_payload(
        "set_goal",
        {
            "domain": "finance",
            "title": "t",
            "amount_per_period": 300,
            "period": "week",
            "horizon_periods": 12,
            "currency": "KES",
        },
    )
    assert build_preview("set_goal", g) == "Set aside KES 300 a week for 12 weeks"
    f = validate_payload(
        "add_finance_entry",
        {
            "direction": "out",
            "label": "School fees",
            "amount_min": 4000,
            "amount_max": 4000,
            "currency": "KES",
            "frequency": "monthly",
            "is_obligation": True,
        },
    )
    assert build_preview("add_finance_entry", f) == "Money out: School fees, KES 4,000 monthly (a commitment)"


def test_payload_validation_rejects_unknown_fields() -> None:
    with pytest.raises(AppError):
        validate_payload("save_journal", {"content": "x", "user_id": "someone-else"})
    with pytest.raises(AppError):
        validate_payload("delete_everything", {})


def test_idempotency_key_is_stable() -> None:
    assert idempotency_key("a", {"x": 1, "y": 2}, None) == idempotency_key("a", {"y": 2, "x": 1}, None)


def test_consistency_not_streaks() -> None:
    today = date(2026, 11, 12)
    cks = {date(2026, 11, d): "done" for d in (6, 7, 9, 11)} | {date(2026, 11, 10): "skipped"}
    c = consistency(cks, today)
    assert c["label"] == "4 of last 7 days"
    assert [d["outcome"] for d in c["days"]] == ["done", "done", None, "done", "skipped", "done", None]
    assert needs_review(date(2026, 10, 1), {}, today)
    assert not needs_review(date(2026, 11, 5), {}, today)


def test_reminder_schedule() -> None:
    sched = {"rrule": build_rrule(["MO", "WE", "FR"], "06:30"), "timezone": "Africa/Nairobi"}
    # Thu 12 Nov 2026 12:00 UTC -> next is Fri 13 Nov 06:30 Nairobi = 03:30 UTC
    nxt = next_fire(sched, datetime(2026, 11, 12, 12, 0, tzinfo=UTC))
    assert nxt == datetime(2026, 11, 13, 3, 30, tzinfo=UTC)


def test_proposal_quote_must_be_verbatim() -> None:
    src = "Busy day. I send money home every month, it's important."
    assert candidate_problems(src, "economic_frame.obligations", "I send money home every month", "x") == []
    assert "quote not found in source" in candidate_problems(src, "economic_frame.obligations", "I am rich", "x")
    assert candidate_problems("He prays a lot", "values_profile.matters_most", "He prays a lot", "faith")


async def test_embeddings_have_column_size_and_are_deterministic() -> None:
    e = HashingEmbeddings()
    [a] = await e.embed(["school fees for my sister"])
    [b] = await e.embed(["school fees for my sister"])
    assert len(a) == 1536 and a == b
    assert FakeEmbeddings().model_name != e.model_name


def test_strict_schema_closes_objects() -> None:
    s = strict_json_schema(TurnOut)
    assert s["additionalProperties"] is False
    assert set(s["required"]) == set(s["properties"])
    assert "$defs" not in s and "$ref" not in str(s)


def test_decimal_preview_formatting() -> None:
    f = validate_payload(
        "add_finance_entry",
        {
            "direction": "in",
            "label": "Sales",
            "amount_min": Decimal("500.5"),
            "amount_max": 1500,
            "currency": "KES",
            "frequency": "daily",
        },
    )
    assert build_preview("add_finance_entry", f) == "Money in: Sales, KES 500.50–1,500 daily"
