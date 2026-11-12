# CLAUDE.md — conventions for coding agents working on Kin

Read `KIN_MASTER_PROMPT.md` (the spec) and `docs/DECISIONS.md` (what was decided and why) first.

## Run and test
```bash
# integration stack (Postgres + GoTrue on 55432 / 59999)
docker compose -f deploy/docker-compose.test.yml up -d
cd backend && uv sync
uv run pytest                    # unit + integration, no model calls
uv run ruff check app tests && uv run mypy app
KIN_EVAL_ANTHROPIC_API_KEY=... uv run pytest -m eval tests/evals   # behaviour evals, real model, costs money
cd ../web && npm ci && npm run lint && npm run build             # static site -> web/out
```
Production: `sudo bash install.sh` on the server, then `./kin.sh help`. See docs/RUNBOOK.md.

## Always
- Build only the phase you were asked to build. Later phases are context, not instructions.
- Complete files with exact paths; give exact commands; write tests with the code and run them.
- When the spec is ambiguous: pick the simpler option, add one line to docs/DECISIONS.md, continue.
- Use the latest stable library versions, pinned in the lockfile (uv.lock, package-lock.json).

## Never
- Never trust a user_id from the client. Identity comes from the verified JWT only.
- Never log journal text, money figures or profile contents. Log IDs and event types (see app/logging_setup.py allow-list).
- Never commit secrets. Config comes from env; `.env.example` is committed, `.env` is not.
- Never add a feature whose purpose is to increase time spent in the app.

## Two write paths, and only two
1. **Direct writes**: things the person does in the UI (onboarding, editing their profile, journal, tapping Done).
   They run as DB role `authenticated` with the person's claims, so RLS applies.
2. **Agent-proposed writes**: anything the agent wants to change goes into `action_queue` (or `context_proposals`)
   and is executed by `app/services/executor.py` only after the person approves the card.
   The agent runtime runs as DB role `kin_agent`, which can read but can only INSERT into action_queue,
   context_proposals, reasoning_sessions, scenarios and memories. This is enforced by Postgres grants.

## Stop and ask the human when
- a change would delete or irreversibly alter user data;
- a requirement conflicts with a security rule in Section 14;
- you need a paid third-party service not named in the spec.
