"""Phase 1: auth, RLS isolation, context round trip, memory, export, delete."""

import logging
import uuid
from typing import Any

import asyncpg
import httpx
import pytest

from tests.conftest import TestUser, forge_token, load_fixture, signup

pytestmark = pytest.mark.integration


async def onboard(client: httpx.AsyncClient, u: TestUser, fixture: str = "fixture_a") -> dict[str, Any]:
    r = await client.post("/api/v1/context/onboard", json=load_fixture(fixture)["onboarding"], headers=u.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.json() == {"status": "ok", "db": "ok"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/me",
        "/api/v1/context",
        "/api/v1/memories",
        "/api/v1/account/export",
        "/api/v1/actions",
        "/api/v1/habits",
        "/api/v1/finance/entries",
    ],
)
async def test_auth_required(client: httpx.AsyncClient, user: TestUser, path: str) -> None:
    assert (await client.get(path)).status_code == 401
    bad = {
        "garbage": "not-a-jwt",
        "wrong_secret": forge_token(str(user.id), secret="x" * 40),
        "expired": forge_token(str(user.id), exp_delta=-60),
        "wrong_aud": forge_token(str(user.id), aud="someone-else"),
    }
    for name, tok in bad.items():
        r = await client.get(path, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, name
        assert r.json()["error"]["code"] == "invalid_token"
    anon = forge_token(str(user.id), role="anon")
    assert (await client.get(path, headers={"Authorization": f"Bearer {anon}"})).status_code == 403


async def test_error_shape_has_no_internals(client: httpx.AsyncClient, user: TestUser) -> None:
    r = await client.patch("/api/v1/context", json={"region": {"currency": "kes!!"}}, headers=user.headers)
    body = r.json()
    assert r.status_code == 422 and set(body) == {"error"}
    assert "kes!!" not in r.text  # submitted values are never echoed


async def test_onboard_get_patch_revert(client: httpx.AsyncClient, user: TestUser) -> None:
    ctx = await onboard(client, user)
    assert ctx["version"] == 1
    fact = ctx["economic_frame"]["income_pattern"]
    assert fact["value"] == "irregular" and fact["source"] == "onboarding"

    r = await client.patch(
        "/api/v1/context", headers=user.headers, json={"economic_frame": {"income_pattern": "mixed", "stability": None}}
    )
    assert r.status_code == 200
    ctx2 = r.json()
    assert ctx2["version"] == 2
    assert ctx2["economic_frame"]["income_pattern"] == {
        **ctx2["economic_frame"]["income_pattern"],
        "value": "mixed",
        "source": "user_edit",
    }
    assert "stability" not in ctx2["economic_frame"]

    versions = (await client.get("/api/v1/context/versions", headers=user.headers)).json()
    assert [(v["version"], v["change_source"]) for v in versions] == [(2, "user_edit"), (1, "onboarding")]

    r = await client.post("/api/v1/context/revert/1", headers=user.headers)
    ctx3 = r.json()
    assert ctx3["version"] == 3 and ctx3["economic_frame"]["income_pattern"]["value"] == "irregular"
    assert ctx3["economic_frame"]["stability"]["value"]
    assert (await client.post("/api/v1/context/revert/99", headers=user.headers)).status_code == 404

    me = (await client.get("/api/v1/me", headers=user.headers)).json()
    assert me["onboarding_state"] == "complete" and me["user_id"] == str(user.id)


async def test_cross_user_isolation(client: httpx.AsyncClient, user: TestUser, other_user: TestUser) -> None:
    await onboard(client, user)
    mid = (
        await client.post("/api/v1/memories", json={"content": "Private note about school fees"}, headers=user.headers)
    ).json()["id"]
    hid = (await client.post("/api/v1/habits", json={"title": "Walk"}, headers=user.headers)).json()["id"]
    eid = (
        await client.post(
            "/api/v1/finance/entries",
            headers=user.headers,
            json={
                "direction": "in",
                "label": "Sales",
                "amount_min": 500,
                "amount_max": 1500,
                "currency": "KES",
                "frequency": "daily",
            },
        )
    ).json()["id"]

    h = other_user.headers
    assert (await client.get("/api/v1/context", headers=h)).json()["region"] == {}
    assert (await client.get("/api/v1/memories", headers=h)).json() == []
    assert (await client.post("/api/v1/memories/search", json={"query": "school fees"}, headers=h)).json() == []
    assert (await client.delete(f"/api/v1/memories/{mid}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/habits", headers=h)).json()["habits"] == []
    assert (
        await client.post(
            f"/api/v1/habits/{hid}/checkins", headers=h, json={"occurred_on": "2026-11-12", "outcome": "done"}
        )
    ).status_code == 404
    assert (await client.delete(f"/api/v1/finance/entries/{eid}", headers=h)).status_code == 404
    export = (await client.get("/api/v1/account/export", headers=h)).json()
    assert all(
        rows == [] or all(r.get("user_id") == str(other_user.id) for r in rows) for rows in export["tables"].values()
    )
    # The owner still has everything.
    assert len((await client.get("/api/v1/memories", headers=user.headers)).json()) == 1


async def test_rls_blocks_direct_sql_cross_user(user: TestUser, other_user: TestUser) -> None:
    """Second lock: even raw SQL as `authenticated` with A's claims sees nothing of B."""
    from sqlalchemy import text

    from app.db.engine import user_session

    async with user_session(other_user.id) as db:
        await db.execute(
            text("insert into public.habits (user_id, title) values (:u, 'B habit')"), {"u": other_user.id}
        )
    async with user_session(user.id) as db:
        n = await db.scalar(text("select count(*) from public.habits where user_id = :u"), {"u": other_user.id})
        assert n == 0
        with pytest.raises(Exception):  # noqa: B017 — RLS with-check violation
            await db.execute(
                text("insert into public.habits (user_id, title) values (:u, 'forged')"), {"u": other_user.id}
            )


async def test_agent_role_cannot_write_domain_tables(user: TestUser) -> None:
    from sqlalchemy import text

    from app.db.engine import user_session

    for sql in [
        "insert into public.habits (user_id, title) values (:u, 'x')",
        "update public.user_context set version = 99 where user_id = :u",
        "insert into public.finance_entries (user_id, direction, label, amount_min, amount_max, currency, "
        "frequency) values (:u, 'in', 'x', 1, 2, 'KES', 'weekly')",
    ]:
        with pytest.raises(Exception, match="permission denied"):
            async with user_session(user.id, "kin_agent") as db:
                await db.execute(text(sql), {"u": user.id})


async def test_memory_search_finds_fixture_memory(client: httpx.AsyncClient, user: TestUser) -> None:
    fx = load_fixture("fixture_a")
    ids = []
    for m in fx["memories"]:
        r = await client.post("/api/v1/memories", json={"content": m}, headers=user.headers)
        assert r.status_code == 201
        ids.append(r.json()["id"])
    await client.post(
        "/api/v1/memories", json={"content": "Bought tomatoes and onions at the market."}, headers=user.headers
    )
    hits = (
        await client.post(
            "/api/v1/memories/search", json={"query": "when are my sister's school fees due?"}, headers=user.headers
        )
    ).json()
    assert hits[0]["id"] == ids[1]
    listed = (await client.get("/api/v1/memories?limit=2", headers=user.headers)).json()
    assert len(listed) == 2
    assert (await client.delete(f"/api/v1/memories/{ids[0]}", headers=user.headers)).status_code == 204


async def test_memory_input_limits(client: httpx.AsyncClient, user: TestUser) -> None:
    r = await client.post("/api/v1/memories", json={"content": "x" * 8001}, headers=user.headers)
    assert r.status_code == 422
    r = await client.post("/api/v1/context/onboard", headers=user.headers, json={"region": {"notes": "y" * 2001}})
    assert r.status_code == 422


async def test_export_and_delete_cascade(client: httpx.AsyncClient) -> None:
    u = signup()
    await onboard(client, u)
    await client.patch("/api/v1/context", json={"region": {"area_type": "town"}}, headers=u.headers)
    await client.post("/api/v1/memories", json={"content": "A journal line"}, headers=u.headers)
    hid = (await client.post("/api/v1/habits", json={"title": "Read"}, headers=u.headers)).json()["id"]
    await client.post(
        f"/api/v1/habits/{hid}/checkins", json={"occurred_on": "2026-11-12", "outcome": "done"}, headers=u.headers
    )
    await client.post(
        "/api/v1/finance/entries",
        headers=u.headers,
        json={
            "direction": "out",
            "label": "Fees",
            "amount_min": 4000,
            "amount_max": 4000,
            "currency": "KES",
            "frequency": "monthly",
            "is_obligation": True,
        },
    )
    sc = (
        await client.post(
            "/api/v1/finance/scenarios",
            headers=u.headers,
            json={"amount_per_period": 300, "period": "week", "horizon_periods": 12},
        )
    ).json()
    await client.post(f"/api/v1/finance/scenarios/{sc['id']}/make-goal", headers=u.headers)
    await client.post(
        "/api/v1/reminders",
        headers=u.headers,
        json={"message": "Walk", "days": ["MO"], "time": "06:30", "timezone": "Africa/Nairobi"},
    )
    chat = await client.post("/api/v1/chat", headers=u.headers, json={"message": "Hello there", "stream": False})
    assert chat.status_code == 200

    export = (await client.get("/api/v1/account/export", headers=u.headers)).json()["tables"]
    for table in [
        "profiles",
        "user_context",
        "user_context_versions",
        "memories",
        "habits",
        "habit_checkins",
        "finance_entries",
        "scenarios",
        "action_queue",
        "reminders",
        "reasoning_sessions",
        "audit_log",
    ]:
        assert export[table], f"export missing {table}"
    assert all("embedding" not in row for row in export["memories"])

    assert (
        await client.request("DELETE", "/api/v1/account", headers=u.headers, json={"confirm": "nope"})
    ).status_code == 422
    r = await client.request("DELETE", "/api/v1/account", headers=u.headers, json={"confirm": "delete everything"})
    assert r.status_code == 204

    conn = await asyncpg.connect("postgresql://supabase_admin:testpass@localhost:55432/postgres")
    try:
        tables = [r["tablename"] for r in await conn.fetch("select tablename from pg_tables where schemaname='public'")]
        for t in tables:
            n = await conn.fetchval(f'select count(*) from public."{t}" where user_id = $1', u.id)  # noqa: S608
            assert n == 0, f"{t} still has rows"
        assert await conn.fetchval("select count(*) from auth.users where id = $1", u.id) == 0
    finally:
        await conn.close()


async def test_logs_hold_no_personal_text(
    client: httpx.AsyncClient, user: TestUser, caplog: pytest.LogCaptureFixture
) -> None:
    secret = f"my-secret-diary-{uuid.uuid4().hex}"
    caplog.set_level(logging.DEBUG)
    await client.post("/api/v1/memories", json={"content": secret}, headers=user.headers)
    await client.post(
        "/api/v1/context/onboard", headers=user.headers, json={"economic_frame": {"how_money_arrives": secret}}
    )
    await client.post("/api/v1/chat", headers=user.headers, json={"message": secret, "stream": False})
    from app.logging_setup import JsonFormatter

    fmt = JsonFormatter()
    rendered = "\n".join(fmt.format(r) for r in caplog.records)
    assert secret not in rendered
    assert "request" in rendered  # access logs were emitted
