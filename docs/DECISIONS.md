# Decisions

One line per assumption or tradeoff. Newest at the bottom.

1. **Built all phases in one pass, not one per session.** The owner asked for a running app on their server; each phase still has tests, and unmet exit criteria are listed in RUNBOOK.md.
2. **Self-hosted Supabase subset** (supabase/postgres + supabase/gotrue) instead of the full Supabase stack or Supabase cloud: fits a 4 GB VPS, no extra account needed, keeps `auth.users`, `auth.uid()` and the `authenticated` role exactly as the spec assumes.
3. **No Supabase CLI on the server.** `app/db/migrate.py` applies `supabase/migrations/*.sql` in order and records them in `kin_meta.schema_migrations`; the same files still work with the CLI locally.
4. **pgvector in the `extensions` schema** (`extensions.vector(1536)`), as Supabase recommends; queries use `operator(extensions.<=>)` so they don't depend on search_path.
5. **Three DB login/role layers:** `kin_api` (login, no privileges of its own, can `SET ROLE` to `authenticated`/`kin_agent`, granted WITH INHERIT FALSE), `kin_agent` (read + insert-only on agent tables), `kin_worker` (BYPASSRLS, narrow grants for cross-user sweeps). The supabase `postgres` role bypasses RLS, so the API never uses it.
6. **Audit inserts via a SECURITY DEFINER function** `public.kin_audit()`, so people can read but not write their audit rows; user_id comes from JWT claims inside the database.
7. **The agent may delete only its own session-summary memories** (restrictive RLS policy) so a session has one up-to-date summary.
8. **JWT verification: HS256 shared secret** (what self-hosted GoTrue signs with); JWKS is used automatically when `SUPABASE_JWKS_URL` is set and the token is asymmetric.
9. **No email server**: GoTrue autoconfirms sign-ups. `./kin.sh lock-signups` closes registration after the owner creates their account.
10. **Default embeddings are local feature-hashing (1536 dims)** when no OpenAI key is given: works offline, sends nothing out, lexical rather than truly semantic. OpenAI `text-embedding-3-small` is used when a key is set; `./kin.sh set-openai-key` re-embeds. Search only compares rows from the same embedding model.
11. **Local mode** blocks every cloud provider call via a per-request context variable (`PrivacyModeError`). An Ollama model can be plugged in (`LLM_PROVIDER=ollama`), but none is installed on the 4 GB server, so Think is unavailable in local mode there.
12. **LLM: Claude via the official Anthropic SDK**, model from `LLM_MODEL` (default `claude-opus-5-5`), structured outputs via `output_config.format`, server-side refusal fallback on by default (`LLM_REFUSAL_FALLBACK=default`) with an automatic retry without it if the account rejects the beta. Effort `low` for routing/extraction, `medium` for replies. Change with `./kin.sh set-model`.
13. **LangGraph graph:** safety_screen → router → context_inject → domain_agent → output_checks → persist. `persist` is an extra last node so nothing is written before the output checks pass.
14. **"Streaming" sends stage events then the checked reply**, not raw tokens: the output checks (directive phrases, invented numbers) must see the whole reply first, and a reply should never appear and then be retracted.
15. **Commitment boundary is decided in code** (`explicit_commitment()` regex with hedge detection). The model's opinion alone can only make Kin ask "Want me to set that up, or are we still thinking?".
16. **Output-check failures:** one model rewrite, then sentence-level removal of offending sentences, then a fixed fallback line.
17. **Number check allows counting numbers 0–12** (days, times a week) and numbers from the scenario object, the person's finance entries, profile and their own messages.
18. **Scenario ordering is enforced on period counts** (stress ≤ realistic ≤ best at both ends) after a property test found overlapping ranges could be mis-ordered by sorting alone.
19. **Cash-flow scenario** counts daily amounts over 7 days a week, monthly as 12/52 per week, and leaves seasonal/irregular/one-off/other-currency entries out, listing each in `unknowns`.
20. **Currency `XXX`** (ISO "no currency") is used when the profile has no currency, and is reported as unknown.
21. **Safety resources ship unverified** (`verified_on: null`) so no phone number is shown until a person checks it and sets the date; until then Kin points to local emergency services.
22. **Minor detection is per message** (no stored age): money commitments are blocked in that turn.
23. **Reminders are in-app** (Today screen) for now; the worker advances `next_fire_at` and records `reminder.fired`. Push notifications are future work (needs Web Push keys).
24. **Clients: one installable web app (PWA) instead of Expo + Next.js.** A phone-first static Next.js export served by Caddy covers the owner's Android phone with no app-store step; the Expo app is future work (Kin-Android repo left untouched).
25. **shadcn/ui not used**: a dozen small hand-written components match the mockups with fewer dependencies.
26. **Offline queue** (localStorage) covers habit check-ins and journal entries, as the spec asks; other writes need a connection.
27. **Mood check-in** ("How is today going?") is stored as a `note` memory with `metadata.type = "mood"`; notes are not mined for profile proposals.
28. **Account deletion** deletes every table's rows under RLS, then removes the login through GoTrue's admin API with a 60-second service-role token minted from the JWT secret (only on this path).
29. **Backups:** daily `pg_dump` at 02:17 to `./backups`, 14 days kept. Restore is scripted but the restore drill (Phase 6) has not been run on the server yet.
