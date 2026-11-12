"""Apply SQL migrations and create the app's login roles.

Run with:  python -m app.db.migrate
Uses DATABASE_ADMIN_URL (a superuser). The API itself never holds that URL.

Migrations are the raw SQL files in supabase/migrations/, applied in filename
order and recorded in kin_meta.schema_migrations, so the same files work with
the Supabase CLI during local development and with this runner on a server.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import asyncpg

from app.config import get_settings

MIGRATIONS_DIR = Path(os.environ.get("MIGRATIONS_DIR", Path(__file__).resolve().parents[3] / "supabase" / "migrations"))
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _plain_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def apply_migrations(conn: asyncpg.Connection) -> list[str]:
    await conn.execute("create schema if not exists kin_meta")
    await conn.execute(
        "create table if not exists kin_meta.schema_migrations "
        "(name text primary key, applied_at timestamptz not null default now())"
    )
    done = {r["name"] for r in await conn.fetch("select name from kin_meta.schema_migrations")}
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):  # noqa: ASYNC240 — runs once at deploy
        if path.name in done:
            continue
        sql = path.read_text()  # noqa: ASYNC240
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute("insert into kin_meta.schema_migrations (name) values ($1)", path.name)
        applied.append(path.name)
    return applied


async def ensure_login_role(conn: asyncpg.Connection, name: str, password: str, *, bypassrls: bool) -> None:
    if not _IDENT.match(name):
        raise ValueError("bad role name")
    exists = await conn.fetchval("select 1 from pg_roles where rolname = $1", name)
    verb = "alter" if exists else "create"
    # Passwords cannot be bound as parameters in DDL; quote_literal via the server.
    quoted = await conn.fetchval("select quote_literal($1)", password)
    flag = "bypassrls" if bypassrls else "nobypassrls"
    await conn.execute(f"{verb} role {name} with login {flag} nosuperuser nocreatedb nocreaterole password {quoted}")


async def ensure_roles(conn: asyncpg.Connection, api_password: str, worker_password: str) -> None:
    await ensure_login_role(conn, "kin_api", api_password, bypassrls=False)
    await ensure_login_role(conn, "kin_worker", worker_password, bypassrls=True)
    stmts = [
        # kin_api has no table grants of its own; it can only act as these roles.
        # WITH INHERIT FALSE: kin_api gets no privileges by itself; it can only
        # SET ROLE into these per transaction (Postgres 16+ grant options).
        "revoke authenticated from kin_api",
        "revoke kin_agent from kin_api",
        "revoke kin_agent from kin_worker",
        "grant authenticated to kin_api with inherit false, set true",
        "grant kin_agent to kin_api with inherit false, set true",
        "grant kin_agent to kin_worker with inherit false, set true",
        "alter role kin_api set search_path = public, extensions",
        "alter role kin_worker set search_path = public, extensions",
        "grant usage on schema public, extensions to kin_worker",
        "grant select on all tables in schema public to kin_worker",
        "grant update on public.action_queue, public.reminders to kin_worker",
        "grant insert on public.audit_log to kin_worker",
        "grant connect on database postgres to kin_api, kin_worker",
    ]
    for s in stmts:
        await conn.execute(s)


async def main() -> int:
    settings = get_settings()
    if not settings.database_admin_url:
        print("DATABASE_ADMIN_URL is required for migrations", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(_plain_url(settings.database_admin_url))
    try:
        applied = await apply_migrations(conn)
        print(f"migrations applied: {applied or 'none (up to date)'}")
        if settings.kin_api_db_password and settings.kin_worker_db_password:
            await ensure_roles(conn, settings.kin_api_db_password, settings.kin_worker_db_password)
            print("login roles kin_api / kin_worker are in place")
        else:
            print("KIN_API_DB_PASSWORD / KIN_WORKER_DB_PASSWORD not set; skipped role setup")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
