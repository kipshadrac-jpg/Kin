# Kin

A personal life companion: habits, money decisions, motivation and daily planning — grounded only in what the person says about themselves. Spec: `KIN_MASTER_PROMPT.md`.

- **Install on a server:** `sudo bash install.sh` (details in `docs/RUNBOOK.md`)
- **Manage:** `./kin.sh help`
- **Develop:** `CLAUDE.md`
- **Why things are the way they are:** `docs/DECISIONS.md`

Stack: FastAPI · SQLAlchemy (async) · Postgres + pgvector (Supabase image) · Supabase GoTrue auth · Redis + arq · LangGraph · Claude (Anthropic SDK) · Next.js static web app (installable) · Caddy (automatic HTTPS).
