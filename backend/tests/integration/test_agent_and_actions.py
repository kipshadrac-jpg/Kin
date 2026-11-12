"""Phases 2-4: chat graph, proposals, approvals lifecycle, habits, finance."""

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.db.engine import user_session
from tests.conftest import TestUser, load_fixture
from tests.unit.test_safety_and_checks import COMMITMENTS, WHAT_IFS

pytestmark = pytest.mark.integration


async def chat(client: httpx.AsyncClient, u: TestUser, message: str, session_id: str | None = None) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/chat", headers=u.headers, json={"message": message, "stream": False, "session_id": session_id}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def setup_person(client: httpx.AsyncClient, u: TestUser, fixture: str = "fixture_a") -> None:
    fx = load_fixture(fixture)
    await client.post("/api/v1/context/onboard", json=fx["onboarding"], headers=u.headers)
    for m in fx["memories"]:
        await client.post("/api/v1/memories", json={"content": m}, headers=u.headers)


async def pending(client: httpx.AsyncClient, u: TestUser) -> list[dict[str, Any]]:
    return (await client.get("/api/v1/actions", headers=u.headers)).json()


async def test_chat_streams_status_then_message(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    events = []
    async with client.stream(
        "POST", "/api/v1/chat", headers=user.headers, json={"message": "How can I think about this week?"}
    ) as r:
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    stages = [e["stage"] for e in events if e["type"] == "status"]
    assert stages == ["safety_screen", "router", "context_inject", "domain_agent", "output_checks", "persist"]
    msg = next(e for e in events if e["type"] == "message")
    assert msg["reply"] and msg["session_id"]
    # Only refs that exist in the bundle survive; the fake model's made-up ref is dropped.
    assert all(not c["ref"].endswith("made_up_ref") for c in msg["context_used"])
    assert events[-1] == {"type": "done"}


async def test_commitment_boundary_eval(client: httpx.AsyncClient, user: TestUser) -> None:
    """Ten what-ifs -> zero queued actions; ten commitments -> at most one each,
    and every queued action came from an explicit commitment."""
    await setup_person(client, user)
    await client.post("/api/v1/habits", json={"title": "Walk 20 minutes"}, headers=user.headers)
    for m in WHAT_IFS:
        res = await chat(client, user, m)
        assert res["action"] is None, m
    assert await pending(client, user) == []
    queued = 0
    for m in COMMITMENTS:
        res = await chat(client, user, m)
        queued += 1 if res["action"] else 0
    rows = await pending(client, user)
    assert len(rows) == queued >= 5
    keys = [r["id"] for r in rows]
    assert len(set(keys)) == len(keys)


async def test_what_if_returns_computed_scenario(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    res = await chat(client, user, "What if I set aside 300 a week for 12 weeks?")
    sc = res["scenario"]
    assert sc and sc["currency"] == "KES"
    by = {c["name"]: c["outcome_range"] for c in sc["cases"]}
    assert by == {"best": [3600, 3600], "realistic": [2400, 3000], "stress": [1200, 1800]}
    assert res["action"] is None
    assert await pending(client, user) == []
    # "Make this my goal" is a button that says so: it queues exactly one card.
    r = await client.post(f"/api/v1/finance/scenarios/{sc['id']}/make-goal", headers=user.headers)
    assert r.status_code == 201
    assert r.json()["preview"] == "Set aside KES 300 a week for 12 weeks"
    assert len(await pending(client, user)) == 1


async def test_output_checks_remove_directives_and_invented_numbers(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    res = await chat(client, user, "TEST_DIRECTIVE what if I save 300 a week for 12 weeks?")
    assert "should" not in res["reply"].lower() and "9999" not in res["reply"] and "20%" not in res["reply"]
    assert "repaired" in res["flags"]
    res = await chat(client, user, "TEST_NEEDY plan my week")
    assert "missed you" not in res["reply"].lower()


async def test_crisis_stops_coaching(client: httpx.AsyncClient, user: TestUser, fake_llm: Any) -> None:
    await setup_person(client, user)
    before = len(fake_llm.calls)
    res = await chat(client, user, "Remind me to walk. Honestly I want to end my life.")
    assert res["intent"] == "safety_escalation"
    assert res["action"] is None and res["scenario"] is None
    assert "emergency services" in res["reply"]
    assert len(fake_llm.calls) == before  # no model call at all
    assert await pending(client, user) == []


async def test_minor_cannot_queue_money_commitments(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    res = await chat(client, user, "I'm 15 years old. Make this my goal: save 300 a week")
    assert res["action"] is None


async def test_approval_lifecycle(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    res = await chat(client, user, "Remind me to walk on Monday, Wednesday and Friday at 6:30")
    action = res["action"]
    assert action and action["preview"] == "Remind me: Walk · Mon, Wed and Fri at 06:30"
    aid = action["id"]

    # Edit keeps history and rewrites the preview from the new payload.
    new_payload = {
        "message": "Walk",
        "kind": "habit",
        "days": ["TU", "TH"],
        "time": "07:00",
        "timezone": "Africa/Nairobi",
    }
    r = await client.post(f"/api/v1/actions/{aid}/edit", headers=user.headers, json={"payload": new_payload})
    assert r.json()["preview"] == "Remind me: Walk · Tue and Thu at 07:00"

    r1 = await client.post(f"/api/v1/actions/{aid}/approve", headers=user.headers)
    r2 = await client.post(f"/api/v1/actions/{aid}/approve", headers=user.headers)
    assert r1.json()["status"] == r2.json()["status"] == "executed"
    reminders = (await client.get("/api/v1/reminders", headers=user.headers)).json()
    assert len(reminders) == 1  # double-approve had no extra effect
    assert reminders[0]["schedule"]["days"] == ["TU", "TH"]
    assert (await client.post(f"/api/v1/actions/{aid}/cancel", headers=user.headers)).status_code == 409


async def test_expired_action_cannot_execute(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    res = await chat(client, user, "Create a habit: walk 20 minutes")
    aid = res["action"]["id"]
    async with user_session(user.id) as db:
        await db.execute(
            text("update public.action_queue set expires_at = now() - interval '1 minute' where id = :i"), {"i": aid}
        )
    r = await client.post(f"/api/v1/actions/{aid}/approve", headers=user.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "expired"
    habits = (await client.get("/api/v1/habits", headers=user.headers)).json()["habits"]
    assert habits == []
    rows = (await client.get("/api/v1/actions?status=expired", headers=user.headers)).json()
    assert [r["id"] for r in rows] == [aid]


async def test_cancelled_action_never_runs(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    aid = (await chat(client, user, "Save this to my journal please"))["action"]["id"]
    assert (await client.post(f"/api/v1/actions/{aid}/cancel", headers=user.headers)).json()["status"] == "cancelled"
    assert (await client.post(f"/api/v1/actions/{aid}/approve", headers=user.headers)).status_code == 409


async def test_log_habit_through_approval(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    hid = (
        await client.post(
            "/api/v1/habits", json={"title": "Walk 20 minutes", "minimum_version": "5 min"}, headers=user.headers
        )
    ).json()["id"]
    res = await chat(client, user, "I walked this morning, log that")
    assert res["action"]["action_type"] == "log_habit"
    await client.post(f"/api/v1/actions/{res['action']['id']}/approve", headers=user.headers)
    cks = (await client.get(f"/api/v1/habits/{hid}/checkins", headers=user.headers)).json()
    assert [c["outcome"] for c in cks] == ["done"]


async def test_proposal_loop(client: httpx.AsyncClient, user: TestUser) -> None:
    from app.agents.background import extract_proposals

    await setup_person(client, user)
    text_ = "Long day at the stall. I send money home every month, that's just how it is."
    created = await extract_proposals(user.id, text_, None)
    assert created == 1  # the hallucinated quote was rejected by code
    props = (await client.get("/api/v1/context/proposals", headers=user.headers)).json()
    assert len(props) == 1 and props[0]["evidence_quote"] in text_
    v_before = (await client.get("/api/v1/context", headers=user.headers)).json()["version"]
    r = await client.post(
        f"/api/v1/context/proposals/{props[0]['id']}/resolve", headers=user.headers, json={"decision": "accept"}
    )
    assert r.json()["status"] == "accepted"
    ctx = (await client.get("/api/v1/context", headers=user.headers)).json()
    fact = ctx["economic_frame"]["obligations"]
    assert "Sends money home every month" in fact["value"] and fact["source"] == "accepted_proposal"
    assert ctx["version"] == v_before + 1
    versions = (await client.get("/api/v1/context/versions", headers=user.headers)).json()
    assert versions[0]["change_source"] == "accepted_proposal"

    # "Never ask" blocks the same field from coming back.
    n2 = await extract_proposals(user.id, "Honestly I send money home every month to my aunt.", None)
    assert n2 == 1, n2
    p2 = (await client.get("/api/v1/context/proposals", headers=user.headers)).json()
    await client.post(
        f"/api/v1/context/proposals/{p2[0]['id']}/resolve", headers=user.headers, json={"decision": "never_ask"}
    )
    assert await extract_proposals(user.id, "Again: I send money home every month.", None) == 0


async def test_session_summary_links_back(client: httpx.AsyncClient, user: TestUser) -> None:
    from app.agents.background import summarize_session

    await setup_person(client, user)
    first = await chat(client, user, "Thinking about transport costs")
    sid = first["session_id"]
    await chat(client, user, "Cutting transport isn't workable for me", sid)
    assert await summarize_session(user.id, __import__("uuid").UUID(sid))
    mems = (await client.get("/api/v1/memories?kind=session_summary", headers=user.headers)).json()
    assert len(mems) == 1 and mems[0]["metadata"]["session_id"] == sid
    # Running it again replaces rather than duplicates.
    assert await summarize_session(user.id, __import__("uuid").UUID(sid))
    assert len((await client.get("/api/v1/memories?kind=session_summary", headers=user.headers)).json()) == 1


async def test_habits_consistency_and_direct_checkins(client: httpx.AsyncClient, user: TestUser) -> None:
    hid = (await client.post("/api/v1/habits", json={"title": "Read 10 pages"}, headers=user.headers)).json()["id"]
    data = (await client.get("/api/v1/habits", headers=user.headers)).json()
    today = data["today"]
    r = await client.post(
        f"/api/v1/habits/{hid}/checkins", headers=user.headers, json={"occurred_on": today, "outcome": "minimum"}
    )
    assert r.status_code == 201
    h = (await client.get("/api/v1/habits", headers=user.headers)).json()["habits"][0]
    assert h["consistency"]["label"] == "1 of last 7 days" and h["today"] == "minimum"
    assert (await client.delete(f"/api/v1/habits/{hid}/checkins/{today}", headers=user.headers)).status_code == 204


async def test_finance_cash_flow_scenario(client: httpx.AsyncClient, user: TestUser) -> None:
    await setup_person(client, user)
    for e in [
        {
            "direction": "in",
            "label": "Sales",
            "amount_min": 500,
            "amount_max": 1500,
            "currency": "KES",
            "frequency": "daily",
        },
        {
            "direction": "out",
            "label": "School fees",
            "amount_min": 4000,
            "amount_max": 4000,
            "currency": "KES",
            "frequency": "monthly",
            "is_obligation": True,
        },
    ]:
        assert (await client.post("/api/v1/finance/entries", json=e, headers=user.headers)).status_code == 201
    r = await client.post(
        "/api/v1/finance/scenarios",
        headers=user.headers,
        json={"kind": "cash_flow", "horizon_periods": 4, "period": "week"},
    )
    sc = r.json()
    assert r.status_code == 200 and sc["kind"] == "cash_flow"
    s, rl, b = (
        next(c for c in sc["cases"] if c["name"] == n)["outcome_range"] for n in ("stress", "realistic", "best")
    )
    assert s[0] <= rl[0] <= b[0] and s[1] <= rl[1] <= b[1]
    assert (
        await client.post(f"/api/v1/finance/scenarios/{sc['id']}/make-goal", headers=user.headers)
    ).status_code == 422
    bad = {"direction": "in", "label": "x", "amount_min": 10, "amount_max": 5, "currency": "KES", "frequency": "weekly"}
    assert (await client.post("/api/v1/finance/entries", json=bad, headers=user.headers)).status_code == 422


async def test_local_privacy_mode_blocks_cloud_calls(client: httpx.AsyncClient, user: TestUser) -> None:
    from app.providers.base import PrivacyModeError, privacy_mode_var
    from app.providers.llm import AnthropicLLM

    llm = AnthropicLLM("sk-test-not-real", "model-from-env")
    token = privacy_mode_var.set("local")
    try:
        with pytest.raises(PrivacyModeError):
            await llm.complete(system="s", messages=[])
    finally:
        privacy_mode_var.reset(token)
    r = await client.patch("/api/v1/me", json={"privacy_mode": "local"}, headers=user.headers)
    assert r.json()["privacy_mode"] == "local"
