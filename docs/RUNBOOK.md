# Runbook

## Install on a fresh Ubuntu server (from a phone is fine)
1. Point the domain's **A record** at the server's IP (kin-ai.site → 40.160.155.105).
2. Upload `kin.zip` to `/home/ubuntu` (Termius SFTP → Upload).
3. In the terminal:
   ```bash
   cd ~ && unzip -o kin.zip && cd kin
   sudo bash install.sh
   ```
   It installs Docker, opens ports 22/80/443, adds swap, asks for your Anthropic key (and an optional OpenAI key),
   generates every password, builds and starts Kin, and schedules daily backups.
4. Open `https://kin-ai.site`, create your account, then run `./kin.sh lock-signups`.

## Everyday
| Task | Command |
|---|---|
| What's running | `./kin.sh status` |
| Health | `./kin.sh health` |
| Logs | `./kin.sh logs api` (or worker, auth, db, caddy) |
| Restart | `./kin.sh restart` |
| Add/change Claude key | `./kin.sh set-key` |
| Change model | `./kin.sh set-model claude-sonnet-5-5` |
| Better journal search | `./kin.sh set-openai-key` |
| Backup now | `./kin.sh backup` → `backups/kin-YYYYMMDD-HHMMSS.dump` |
| Restore | `./kin.sh restore backups/kin-….dump` |
| Update to a new zip | upload, `unzip -o kin.zip`, `cd kin && ./kin.sh update` (your `.env` and data are kept) |

## Where things live
- `.env` — secrets and settings (chmod 600). Never share it.
- Database: Docker volume `kin_db-data`. Certificates: `kin_caddy-data`.
- Web app: static files in `web/out`, served by Caddy.

## Develop and test
See CLAUDE.md. Integration tests need `docker compose -f deploy/docker-compose.test.yml up -d`.

## Reset everything (destroys all data)
```bash
./kin.sh backup     # just in case
docker compose down -v && rm .env && sudo bash install.sh
```

## Phase exit checklists (status at delivery)
**Phase 1** — [x] one command brings the API up (`install.sh` / `docker compose up -d`) · [x] pytest passes with no model network access · [x] cross-user isolation tests (API + raw SQL under RLS) · [x] onboard → read → edit → revert with versions · [x] memory search returns the fixture memory · [x] export has every table; delete removes all rows and the login · [x] log test proves no personal text in logs.
**Phase 2** — [x] graph, streaming `/chat`, proposals, summaries, evals written · [ ] Grounding / No-inference / No-generic-advice / Safety evals **not yet run against the real model** (need an API key: `KIN_EVAL_ANTHROPIC_API_KEY=… uv run pytest -m eval tests/evals`).
**Phase 3** — [x] commitment boundary proven with the fake model (10 what-ifs → 0 actions) · [x] double-approve idempotent · [x] expired action cannot execute · [ ] real-model run of the same eval pending.
**Phase 4** — [x] property tests: stress ≤ realistic ≤ best · [x] directive-phrase check · [ ] Three-cases / Non-directive evals on the real model pending.
**Phase 5** — [x] web client: onboarding with read-back, profile editor with history, chat with "what I used about you", approval feed, offline queue · [ ] Expo app not built (see DECISIONS 24) · [ ] low-end-device test on a throttled connection pending.
**Phase 6** — [x] local-mode blocks cloud calls (test) · [ ] accessibility pass, localisation, restore drill, CI scanning not done.
