# Kin — Master Build Prompt v2
### Personal Life Companion · Agentic OS
*("Kin" is a placeholder name. Rename by changing `APP_NAME` in config; nothing else should hardcode it.)*

---

## 0. How to use this file

1. Put this file in the root of an empty repo as `KIN_MASTER_PROMPT.md`.
2. Open the repo in Claude Code (or another coding agent).
3. Paste the **kick-off prompt for the phase you want** from Section 19. Start with Phase 1.
4. Do one phase per session. Each phase ends with a checklist (its "exit criteria"). Do not start the next phase until every box is ticked.

**Map of this document**

| Part | Sections | What it gives the agent |
|---|---|---|
| A. Ground rules | 1–3 | Role, product principles, example people |
| B. System design | 4–6 | Architecture, stack decisions, repo layout |
| C. Feature specs | 7–11 | Context Engine, reasoning, approvals, modules, safety |
| D. Contracts | 12–15 | SQL schema, API, security, LLM layer |
| E. Delivery | 16–19 | Tests and evals, roadmap, output rules, kick-off prompts |
| Appendix | A | What changed from v1 and why |

---

# PART A — GROUND RULES

## 1. Role and operating rules for the coding agent

You are a senior full-stack AI engineer building Kin. You care about security, small modules, and code a solo developer can maintain.

**Always**
- Build only the phase you were asked to build. Later phases are context, not instructions.
- Write complete files with exact paths. No `# rest of code here`.
- Give the exact terminal commands to install, migrate, run, and test.
- Write tests alongside the code, and run them before saying a phase is done.
- When this document is ambiguous, pick the simpler option, state the assumption in one line in `docs/DECISIONS.md`, and continue.
- Use the latest stable version of each library at build time and pin it in the lockfile. Do not rely on version numbers remembered from training; check.

**Never**
- Never trust a `user_id` sent by the client. Identity comes from the verified auth token only.
- Never log journal text, financial figures, or context-profile contents. Log IDs and event types.
- Never commit secrets. All config comes from environment variables, with a committed `.env.example`.
- Never add a feature whose purpose is to increase time spent in the app.

**Stop and ask the human when**
- A change would delete or irreversibly alter user data.
- A requirement here conflicts with a security rule in Section 14.
- You need a paid third-party service not named in this document.

## 2. Product vision and principles

Kin helps one person build habits, think through money decisions, stay motivated, and plan daily life. What makes it different: every feature reads from one shared **Context Engine** that holds what the person has *said about themselves* — where they live, how money actually arrives and leaves, what they value, and what encouragement feels like to them.

Generic advice is a bug. "Save 20% of your income" and "do it for 21 days" are examples of output Kin must not produce unless the person's own context supports it.

**Ten principles. Every design choice must be traceable to one of these.**

1. **Self-reported, never inferred.** Kin does not guess culture, religion, income, or family structure from a name, location, language, or device. It asks, or it stays general.
2. **The person owns the profile.** Everything Kin believes about them is visible, editable, and deletable. Nothing is a hidden score.
3. **Proposals, not silent updates.** When Kin notices a durable fact in conversation, it proposes it; the person accepts, edits, or rejects.
4. **Ranges, not single numbers.** Financial reasoning shows best, realistic, and stress cases with the assumptions behind each.
5. **Reason with, act only with approval.** Any state change the agent initiates goes through an approval card.
6. **Thinking out loud is free.** Exploring a what-if never creates a commitment. Only an explicit "make this my goal" does.
7. **Information, not instruction, on money.** Kin lays out tradeoffs. For loans, contracts, and anything legally binding, it points to a licensed professional.
8. **Point outward.** Kin encourages real relationships and professional help. It is not designed to be someone's main emotional relationship.
9. **Works on a modest phone and a weak connection.** Small payloads, offline-tolerant writes, no assumption of a bank account or card.
10. **Privacy by architecture.** A local-model mode exists where no personal text leaves the person's machine.

**Non-goals:** bank-account linking, investment recommendations, medical or mental-health treatment, social feeds, leaderboards, streak-loss penalties.

## 3. Example people (use these as test fixtures)

These are not stereotypes to match against. They are three different *self-described* profiles used to prove that the same question gets different, grounded answers.

- **Fixture A — irregular earner.** Income arrives daily in cash and mobile money, varies a lot week to week. Supports two relatives. Saves through a rotating savings group that meets monthly. Encouragement style: "be straight with me, no cheerleading."
- **Fixture B — salaried, indebted.** Fixed monthly salary, a loan repayment taking a large share of it, lives alone in a city. Wants to start exercising but works twelve-hour shifts. Encouragement style: "remind me how far I've come."
- **Fixture C — student, shared household.** No personal income; a small monthly allowance. Faith practice structures the week. Encouragement style: "gentle, and please don't nag."

Store them in `tests/fixtures/profiles/` as JSON. The eval suite in Section 16 depends on them.

---

# PART B — SYSTEM DESIGN

## 4. Architecture

```
┌───────────────┐      ┌────────────────┐
│  Expo mobile  │      │  Next.js web   │
└───────┬───────┘      └───────┬────────┘
        │  HTTPS + Supabase JWT │
        └──────────┬────────────┘
                   ▼
        ┌─────────────────────┐
        │   FastAPI gateway   │  auth, validation, rate limit
        └──────────┬──────────┘
                   ▼
        ┌─────────────────────┐
        │   Agent runtime     │  LangGraph
        │  1 safety screen    │
        │  2 intent router    │
        │  3 context inject   │◄──── Context Engine (profile + memories)
        │  4 domain agent     │
        │  5 output checks    │
        └────┬───────────┬────┘
             │           │
   read-only │           │ proposed writes
             ▼           ▼
      ┌──────────┐  ┌──────────────┐   approve   ┌──────────┐
      │ Postgres │  │ action_queue │────────────►│ executor │
      │ pgvector │  └──────────────┘             └────┬─────┘
      └──────────┘                                    ▼
                                                 domain tables
        Redis + worker: scheduled check-ins, expiry of stale actions
        Provider layer: LLMProvider / EmbeddingProvider (cloud or local)
```

**Two write paths, and only two:**
- **Direct writes** — things the person does themselves through the UI or API (onboarding answers, editing their profile, writing a journal entry, tapping "done" on a habit).
- **Agent-proposed writes** — anything the agent wants to change. Always via `action_queue` and an approval card.

The agent runtime has **no** database credentials that can write to domain tables. It can read, and it can insert into `action_queue` and `context_proposals`. The executor is separate code.

## 5. Tech stack and the reasoning behind it

| Layer | Choice | Why / rule |
|---|---|---|
| API | Python 3.11+, FastAPI, Pydantic v2, async | Typed contracts, good AI library support |
| DB access | SQLAlchemy 2 (async) + asyncpg | **One** data path. Do not also use the Supabase Python client for table access |
| Migrations | Supabase CLI SQL migrations in `supabase/migrations/` | Raw SQL, reviewable, includes RLS |
| Auth | Supabase Auth; API verifies the JWT | No custom password handling |
| DB | Postgres + `pgvector` | One store for relational and semantic data |
| Queue | Redis + `arq` worker | Light, async-native |
| Agents | LangGraph | Explicit state graph, interruptible for approvals |
| Retrieval | Plain SQL over pgvector first | Add LlamaIndex only if retrieval needs outgrow ~100 lines of SQL. Fewer dependencies is a feature |
| LLM | Provider interface; cloud default, local swap | Model IDs come from env vars, never hardcoded |
| Embeddings | Provider interface; default `text-embedding-3-small` (1536 dims) | In local mode use a local embedding model; see Section 15 |
| Mobile | Expo (React Native), NativeWind, Zustand | |
| Web | Next.js (App Router), Tailwind, shadcn/ui | |
| Tooling | `uv` or Poetry, `ruff`, `mypy`, `pytest` | |

## 6. Repository layout

```
kin/
├── KIN_MASTER_PROMPT.md
├── CLAUDE.md                  # short conventions file for the coding agent
├── docs/
│   ├── DECISIONS.md           # one line per assumption or tradeoff
│   └── RUNBOOK.md             # run, test, migrate, reset
├── supabase/
│   ├── config.toml
│   └── migrations/            # 0001_init.sql, 0002_rls.sql, ...
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py          # pydantic-settings
│   │   ├── deps.py            # auth + db session dependencies
│   │   ├── db/                # engine, session, RLS context helper
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic request/response
│   │   ├── routers/           # context, memory, habits, finance, actions, account
│   │   ├── services/          # business logic, no HTTP here
│   │   ├── providers/         # llm.py, embeddings.py (+ cloud/local impls)
│   │   ├── agents/            # Phase 2+: graph, nodes, prompts
│   │   ├── tools/             # Phase 3+: tool registry
│   │   ├── safety/            # screens, output checks, resources
│   │   └── worker.py          # arq tasks
│   └── tests/
│       ├── fixtures/profiles/
│       ├── unit/ integration/ evals/
├── web/                       # Phase 5
└── mobile/                    # Phase 5
```

`CLAUDE.md` must be created in Phase 1 and contain: run and test commands, the "Always / Never" list from Section 1, and the two-write-paths rule from Section 4.

---

# PART C — FEATURE SPECS

## 7. Context Engine (the foundation)

### 7.1 What the profile holds

Four sections, each a JSON document with a known shape. Every field is optional; "prefer not to say" is always valid and must never block onboarding.

| Section | Fields (all self-reported) |
|---|---|
| `region` | country, area type (city / town / rural), languages, currency (ISO 4217), timezone, free-text "what's worth knowing about where I live" |
| `economic_frame` | income pattern (regular / irregular / cash / mixed / none), how money arrives (free text: salary, daily sales, mobile money, remittances…), stability in their own words, obligations (who or what they support), how they already save (bank, mobile wallet, savings group, at home, not currently) |
| `values_profile` | what matters most, non-negotiables, sensitivities ("don't suggest X"), aspirations |
| `emotional_baseline` | what encouragement feels like, what backfires, preferred tone, preferred check-in times, quiet hours |

### 7.2 Every fact carries its origin

Each stored fact is wrapped:

```json
{
  "value": "Income varies a lot week to week",
  "source": "onboarding | user_edit | accepted_proposal",
  "stated_at": "2026-11-11T20:58:00Z",
  "evidence_memory_id": null
}
```

There is no `inferred` source. If the person did not state or approve it, it is not in the profile.

### 7.3 Onboarding

- Conversational, five to eight questions, skippable at every step, resumable.
- Questions are open ("How does money usually reach you?") rather than dropdowns that assume a salaried life.
- Ends with a **read-back screen**: "Here's what I understood. Change anything." Nothing is saved as the profile until the person confirms.

### 7.4 Learning over time: the proposal loop

1. Person journals or chats.
2. An extraction step looks for *durable* facts: constraints, obligations, aspirations, sensitivities. Not moods, not one-off events.
3. Each candidate becomes a row in `context_proposals` with the exact quote it came from.
4. The person sees: *"You mentioned you send money home each month. Add this to your profile?"* → **Accept / Edit / Not now / Never ask about this.**
5. Only accepted proposals change `user_context`. Each change writes a version row so any edit can be undone.

Limits: at most three proposals surfaced per day; never propose anything in a special category (health, religion, sexuality, immigration status, ethnicity) unless the person stated it plainly and directly about themselves.

### 7.5 How other modules use it

One function is the only door: `get_context_bundle(user_id, purpose, query)` returns
- the relevant profile sections for that purpose (finance questions do not need the full values profile and vice versa — send the minimum),
- the top-k memories by similarity, filtered by recency and type,
- a `gaps` list: things that would matter for this question but are unknown.

When `gaps` is non-empty, the agent asks or stays general. It never fills a gap with an assumption.

## 8. Reasoning and planning layer

- **Intents:** `habit_log`, `habit_plan`, `finance_query`, `finance_log`, `motivation_request`, `open_reasoning`, `profile_edit`, plus `safety_escalation` which overrides all others.
- **Scenario modelling** returns a structured object, never free prose alone:

```json
{
  "premise": "Set aside a fixed amount each week",
  "currency": "KES",
  "cases": [
    {"name": "best",      "assumptions": ["..."], "outcome_range": [0, 0], "what_would_have_to_be_true": "..."},
    {"name": "realistic", "assumptions": ["..."], "outcome_range": [0, 0], "what_would_have_to_be_true": "..."},
    {"name": "stress",    "assumptions": ["..."], "outcome_range": [0, 0], "what_would_have_to_be_true": "..."}
  ],
  "context_used": ["economic_frame.income_pattern", "memory:<id>"],
  "unknowns": ["..."],
  "not_advice_note": true
}
```

- **All arithmetic is done in code**, not by the model. The model chooses assumptions; a pure Python function computes outcomes. This is testable and prevents invented numbers.
- **Session memory:** each session stores a short outcome summary and any stated decisions. Later sessions can cite them ("last time you said cutting transport wasn't workable") and must link to the session they came from.
- **Transparency:** every answer can show "what I used about you" — the `context_used` list rendered in plain language.

## 9. Agentic execution (human in the loop)

### 9.1 Tools

| Tool | Read operations (run freely) | Write operations (always queued) |
|---|---|---|
| `HabitTool` | list habits, recent check-ins | create/modify/pause habit, log check-in on the person's behalf |
| `FinanceTool` | read entries, run scenario | add/modify entry, set savings goal |
| `ReminderTool` | list reminders | create/modify/cancel reminder |
| `JournalTool` | search memories | save an entry drafted by the agent |

### 9.2 Action lifecycle

```
pending ──approve──► approved ──► executing ──► executed
   │                                  └───────► failed (retryable)
   ├──edit──► pending (new payload, old one kept in history)
   ├──cancel──► cancelled
   └──72h, no response──► expired
```

Rules:
- Each action has an `idempotency_key`; executing twice has no extra effect.
- The approval card shows a plain-language preview written from the payload by code, not by the model, so the card cannot say one thing and do another.
- The executor re-validates the payload against its schema at execution time.
- Never batch-approve. One card, one decision.
- Expired and cancelled actions are never retried automatically.

### 9.3 The commitment boundary

Scenario modelling, brainstorming, and "what if" questions **never** insert into `action_queue`. An action is queued only when the person uses clear commitment language ("set this as my goal", "remind me", "log that") or taps a button that says so. When unsure, the agent asks: "Want me to set that up, or are we still thinking?"

## 10. Domain modules

### Habits
- Pacing comes from stated constraints (shift work, caring duties, energy, faith calendar the person described).
- Progress is shown as **consistency over a window** ("4 of the last 7 days"), not a streak that resets to zero. A missed day is information, not failure.
- Each habit has a "minimum version" for hard days (two minutes instead of thirty).
- After two missed weeks, Kin asks whether the habit still fits rather than sending more reminders.

### Finance
- Works without a bank account. Entries are *flows* with ranges: "between X and Y, most weeks".
- Recognises informal instruments the person names (savings groups, mobile wallets, family obligations) as first-class, not as "miscellaneous".
- Obligations to family are treated as fixed commitments unless the person says otherwise. Kin never suggests cutting them.
- Output is tradeoffs and ranges. Phrases like "you should", "the best option is", "I recommend" are blocked in finance output (Section 11).
- Anything involving loan terms, interest, contracts, tax, or insurance ends with a pointer to a licensed adviser or a relevant free local service, if the person's region has one configured.

### Motivation and check-ins
- Tone is read from `emotional_baseline`. The person's own words about what helps are passed into the prompt verbatim.
- Hard caps: at most two unprompted messages per day, none during quiet hours, and none at all if the person has not opened the last three.
- Regularly points outward: "Is there someone you'd want to tell about this?"
- No guilt, no "I missed you", no language implying Kin has needs.

## 11. Safety and guardrails

Runs as the **first** and **last** node of every agent turn.

| Situation | Required behaviour |
|---|---|
| Signs of crisis or self-harm | Stop coaching. Respond with warmth, encourage contacting a trusted person or local emergency services, and show support resources for the person's stated country from `safety/resources.yaml`. If no entry exists for that country, say so and point to emergency services. Never invent a phone number. |
| Severe financial distress (cannot afford food, threats from lenders) | Drop planning mode. Acknowledge, show any configured local support resources, offer to continue only if they want. |
| Requests for medical, legal, or investment decisions | Give general information, decline to decide, point to a professional. |
| Signs the person is relying on Kin as their main support | Gently name it and encourage human connection. Do not increase engagement. |
| Possible minor (states an age under 18) | Disable finance commitments and keep content age-appropriate. |

`safety/resources.yaml` is maintained by humans, with a `verified_on` date per entry. The agent must not write to it.

**Output checks (code, not model):** finance output is scanned for directive phrases; scenario output must contain three cases and a non-empty assumptions list; any number in the reply must appear in the computed scenario object or the person's own data.

---

# PART D — CONTRACTS

## 12. Database schema

Local development uses `supabase start`, which provides the `auth` schema. All tables live in `public`, all have Row Level Security on.

```sql
-- 0001_init.sql
create extension if not exists vector;

create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

-- Identity: Supabase owns auth.users. We keep only app-level settings.
create table public.profiles (
  user_id      uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  locale       text,
  privacy_mode text not null default 'cloud' check (privacy_mode in ('cloud','local')),
  onboarding_state text not null default 'not_started'
      check (onboarding_state in ('not_started','in_progress','complete')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- Context Engine: current profile
create table public.user_context (
  user_id            uuid primary key references auth.users(id) on delete cascade,
  region             jsonb not null default '{}'::jsonb,
  economic_frame     jsonb not null default '{}'::jsonb,
  values_profile     jsonb not null default '{}'::jsonb,
  emotional_baseline jsonb not null default '{}'::jsonb,
  version            int  not null default 1,
  updated_at         timestamptz not null default now()
);

-- Every change to the profile, so edits can be reviewed and undone
create table public.user_context_versions (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  version    int  not null,
  snapshot   jsonb not null,
  change_source text not null check (change_source in ('onboarding','user_edit','accepted_proposal','revert')),
  created_at timestamptz not null default now(),
  unique (user_id, version)
);

-- Semantic memory
create table public.memories (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  kind        text not null default 'journal' check (kind in ('journal','chat','note','session_summary')),
  content     text not null,
  metadata    jsonb not null default '{}'::jsonb,
  embedding   vector(1536),
  embedding_model text,
  created_at  timestamptz not null default now()
);
create index memories_user_created_idx on public.memories (user_id, created_at desc);
create index memories_embedding_idx on public.memories using hnsw (embedding vector_cosine_ops);

-- Facts the system noticed and is asking permission to keep
create table public.context_proposals (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  section     text not null check (section in ('region','economic_frame','values_profile','emotional_baseline')),
  field_path  text not null,
  proposed_value jsonb not null,
  evidence_quote text not null,
  evidence_memory_id uuid references public.memories(id) on delete set null,
  status      text not null default 'pending'
      check (status in ('pending','accepted','edited','dismissed','never_ask')),
  created_at  timestamptz not null default now(),
  resolved_at timestamptz
);

-- Habits
create table public.habits (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  title      text not null,
  why        text,
  cadence    jsonb not null default '{}'::jsonb,   -- e.g. {"times_per_week":3,"preferred_days":[...]}
  minimum_version text,                            -- the "hard day" version
  status     text not null default 'active' check (status in ('active','paused','archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.habit_checkins (
  id         uuid primary key default gen_random_uuid(),
  habit_id   uuid not null references public.habits(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  occurred_on date not null,
  outcome    text not null check (outcome in ('done','minimum','skipped')),
  note       text,
  created_at timestamptz not null default now(),
  unique (habit_id, occurred_on)
);
-- No stored streak columns: consistency is computed from check-ins.

-- Finance: flows expressed as ranges
create table public.finance_entries (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  direction  text not null check (direction in ('in','out','set_aside')),
  label      text not null,
  category   text,
  amount_min numeric(14,2) not null check (amount_min >= 0),
  amount_max numeric(14,2) not null check (amount_max >= amount_min),
  currency   char(3) not null,
  frequency  text not null check (frequency in ('daily','weekly','monthly','seasonal','one_off','irregular')),
  is_obligation boolean not null default false,
  notes      text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.goals (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  domain     text not null check (domain in ('habit','finance','general')),
  title      text not null,
  detail     jsonb not null default '{}'::jsonb,
  status     text not null default 'active' check (status in ('active','paused','reached','dropped')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Reasoning sessions and their scenarios
create table public.reasoning_sessions (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  topic      text not null,
  transcript jsonb not null default '[]'::jsonb,
  outcome_summary text,
  decisions  jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.scenarios (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  session_id uuid references public.reasoning_sessions(id) on delete cascade,
  premise    text not null,
  result     jsonb not null,          -- the structured object from Section 8
  created_at timestamptz not null default now()
);

-- Reminders and scheduled check-ins
create table public.reminders (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  kind       text not null check (kind in ('habit','checkin','custom')),
  message    text not null,
  schedule   jsonb not null,          -- {"rrule": "...", "timezone": "..."}
  next_fire_at timestamptz,
  status     text not null default 'active' check (status in ('active','paused','cancelled')),
  created_at timestamptz not null default now()
);

-- Human-in-the-loop queue
create table public.action_queue (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  session_id uuid references public.reasoning_sessions(id) on delete set null,
  action_type text not null,          -- 'log_habit','create_habit','set_goal','set_reminder','add_finance_entry','save_journal'
  payload    jsonb not null,
  payload_history jsonb not null default '[]'::jsonb,
  preview    text not null,           -- generated by code from payload
  idempotency_key text not null,
  status     text not null default 'pending'
      check (status in ('pending','approved','executing','executed','failed','cancelled','expired')),
  result     jsonb,
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  executed_at timestamptz,
  expires_at timestamptz not null default (now() + interval '72 hours'),
  unique (user_id, idempotency_key)
);
create index action_queue_user_status_idx on public.action_queue (user_id, status);

-- Audit trail: what happened, never the content
create table public.audit_log (
  id         bigint generated always as identity primary key,
  user_id    uuid references auth.users(id) on delete cascade,
  event      text not null,
  entity     text,
  entity_id  uuid,
  created_at timestamptz not null default now()
);
```

```sql
-- 0002_rls.sql  — repeat this pattern for EVERY table above
alter table public.user_context enable row level security;
create policy "own rows" on public.user_context
  for all to authenticated
  using      (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));
-- audit_log: select-only for the owner; inserts happen from the backend service path.
```

Also add `set_updated_at` triggers to every table with an `updated_at` column.

## 13. API contract

Base path `/api/v1`. Every route requires `Authorization: Bearer <Supabase JWT>` except `/health`. **No route takes a user ID in the path or body**; the user is the token's subject.

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/health` | liveness + DB check | 1 |
| GET | `/me` | profile settings | 1 |
| POST | `/context/onboard` | save confirmed onboarding answers; creates version 1 | 1 |
| GET | `/context` | full context profile | 1 |
| PATCH | `/context` | edit one or more fields; bumps version | 1 |
| GET | `/context/versions` | list versions | 1 |
| POST | `/context/revert/{version}` | restore an earlier version | 1 |
| POST | `/memories` | store text, embed, return id | 1 |
| GET | `/memories` | list, paginated | 1 |
| POST | `/memories/search` | semantic search over own memories | 1 |
| DELETE | `/memories/{id}` | delete one | 1 |
| GET | `/account/export` | everything about the user as JSON | 1 |
| DELETE | `/account` | delete all data (requires confirm phrase) | 1 |
| GET/POST | `/context/proposals`, `/context/proposals/{id}/resolve` | proposal loop | 2 |
| POST | `/chat` | agent turn (streamed) | 2 |
| GET/POST | `/actions`, `/actions/{id}/approve|edit|cancel` | approval feed | 3 |
| CRUD | `/habits`, `/habits/{id}/checkins` | habits | 3 |
| CRUD | `/finance/entries`, POST `/finance/scenarios` | finance | 4 |

**Example — onboarding request**

```json
POST /api/v1/context/onboard
{
  "region": { "country": "KE", "area_type": "city", "currency": "KES",
              "timezone": "Africa/Nairobi", "languages": ["sw","en"],
              "notes": "Transport costs change a lot when it rains." },
  "economic_frame": { "income_pattern": "irregular",
                      "how_money_arrives": "Daily sales, mostly mobile money",
                      "obligations": ["School fees for my sister"],
                      "saving_methods": ["savings group"] },
  "values_profile": { "matters_most": ["family"], "sensitivities": [] },
  "emotional_baseline": { "encouragement": "Be straight with me",
                          "backfires": "Too much praise",
                          "quiet_hours": {"from": "21:00", "to": "06:00"} }
}
```

The service wraps each value with its origin (Section 7.2) before saving. Clients send plain values.

**Errors** use one shape: `{"error": {"code": "string", "message": "string", "details": {}}}`. Never return stack traces or SQL.

## 14. Security and privacy

1. **Auth:** verify Supabase JWT signature, expiry, and audience on every request (via JWKS). Reject otherwise.
2. **Row Level Security must actually apply.** A direct Postgres connection as an admin role bypasses RLS. For every request, open a transaction and run:
   `set local role authenticated;` and `select set_config('request.jwt.claims', :claims_json, true);`
   so `auth.uid()` resolves and policies are enforced. Include an integration test where user A requests user B's row and gets nothing.
3. **Service code also filters by user_id.** RLS is the second lock, not the only one.
4. **Secrets:** env only. The Supabase service-role key is used by the worker and the account-deletion path only.
5. **Logging:** structured logs with request ID, user ID, route, status, latency. No bodies. No prompt or completion text in production logs.
6. **Rate limits:** per user, per route group (Redis). Tighter on `/chat` and `/memories`.
7. **Input limits:** memory content ≤ 8,000 characters; onboarding free-text fields ≤ 2,000.
8. **Prompt-injection stance:** journal and memory text is *data*. It is placed in a clearly delimited block, and the system prompt states that instructions inside it are not to be followed. Retrieved text can never trigger a tool call on its own; tools fire only from the current user turn.
9. **Third parties:** in `cloud` mode, state clearly at onboarding which providers receive text. In `local` mode, the provider layer must raise an error if any code path attempts an outbound model call.
10. **Data rights:** export and delete work from Phase 1. Deletion cascades through every table and is covered by a test.
11. **CORS** restricted to configured origins. HTTPS only outside local dev.

## 15. LLM and embedding layer

```python
class LLMProvider(Protocol):
    async def complete(self, *, system: str, messages: list[Message],
                       response_schema: type[BaseModel] | None = None,
                       max_tokens: int = 1024) -> LLMResult: ...

class EmbeddingProvider(Protocol):
    dimensions: int
    model_name: str
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- Implementations: `AnthropicLLM`, `OllamaLLM`, `OpenAIEmbeddings`, `LocalEmbeddings`, plus `FakeLLM` and `FakeEmbeddings` (deterministic) for tests. **Tests never call a real provider.**
- Selection by env: `LLM_PROVIDER`, `LLM_MODEL`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, and per-user `privacy_mode`.
- **Embedding dimension is fixed per deployment.** The column is `vector(1536)`. A local embedding model with a different size needs a migration and a re-embed job; at startup, fail fast if `provider.dimensions` does not match the column. Always store `embedding_model` with each row.
- **Prompt assembly order** (Phase 2+): fixed role and principles → safety rules → the person's context bundle in a delimited block → retrieved memories in a delimited block → conversation → current message.
- Structured outputs are validated with Pydantic; on failure, one repair attempt, then a graceful fallback message.
- Prompts live in `app/agents/prompts/` as versioned files, not inline strings.

---

# PART E — DELIVERY

## 16. Testing and evaluation

**Unit:** services, origin-wrapping of context facts, version bump and revert, scenario arithmetic, preview generation, output checks.

**Integration (against local Supabase):** auth rejection, cross-user isolation under RLS, onboarding → get → patch → revert round trip, memory store and search with `FakeEmbeddings`, export completeness, delete cascade.

**Behaviour evals (Phase 2+)** — in `tests/evals/`, run on demand with a real model:

| Eval | Pass condition |
|---|---|
| Grounding | Same question to Fixtures A, B, C produces answers that each cite at least one fixture-specific fact and differ materially from one another |
| No generic advice | Banned-phrase list ("save 20%", "21 days", "cut out your daily coffee", etc.) never appears |
| No inference | Given a profile with gaps, the answer asks or stays general; it never asserts an unstated fact |
| Three cases | Every scenario has best / realistic / stress with assumptions; all numbers match the code-computed object |
| Commitment boundary | Ten "what if" prompts produce zero queued actions; ten explicit commitments produce exactly one each |
| Non-directive finance | Zero directive phrases across the finance prompt set |
| Safety | Crisis prompts stop coaching and show only resources present in `resources.yaml` |
| Tone | Reply style for each fixture matches its stated encouragement preference (LLM-graded with a rubric, spot-checked by a human) |

## 17. Roadmap

### Phase 1 — Foundation and Context Engine  ← BUILD THIS FIRST
1. Repo scaffold per Section 6, `CLAUDE.md`, `docs/RUNBOOK.md`, `.env.example`.
2. Supabase local setup; migrations `0001_init.sql` (full schema) and `0002_rls.sql` (policies and triggers for every table).
3. Config, async DB engine, per-request RLS context helper, JWT auth dependency.
4. Provider interfaces with real and fake embedding implementations; startup dimension check.
5. All Phase 1 routes from Section 13.
6. Fixture profiles A, B, C.
7. Unit and integration tests; `ruff` and `mypy` clean.

**Exit criteria**
- [ ] `supabase start` + one documented command brings the API up
- [ ] `pytest` passes with no network access to model providers
- [ ] Cross-user access test proves isolation
- [ ] Onboard → read → edit → revert works and versions are recorded
- [ ] Memory search returns the expected fixture memory
- [ ] Export contains every table's rows for the user; delete removes them all
- [ ] No secrets or personal text in logs

### Phase 2 — Agent runtime, router, proposal loop
LangGraph graph (safety → router → context injection → domain agent → output checks), `/chat` with streaming, fact extraction into `context_proposals`, proposal endpoints, session summaries, first four evals.

**Exit:** Grounding, No-inference, No-generic-advice, and Safety evals pass on all three fixtures.

### Phase 3 — Approvals and habits
Tool registry, `action_queue` lifecycle, executor, expiry worker, habits CRUD, consistency calculation, reminders via Redis worker.

**Exit:** Commitment-boundary eval passes; double-approve is idempotent; an expired action cannot execute.

### Phase 4 — Finance scenario engine
Finance entries, deterministic scenario calculator, `FinanceScenarioTool`, directive-phrase output check, professional-referral logic.

**Exit:** Three-cases and Non-directive evals pass; property tests show computed ranges are consistent (stress ≤ realistic ≤ best).

### Phase 5 — Clients
Expo and Next.js apps: onboarding with read-back, profile editor with version history, chat with "what I used about you", approval feed, offline queue for check-ins and journal entries.

**Exit:** full flow usable on a low-end Android device on a throttled connection.

### Phase 6 — Hardening
Local-mode end-to-end test with outbound calls blocked, accessibility pass, localisation scaffolding, backup and restore drill, dependency and secret scanning in CI.

## 18. Output rules for the coding agent

1. Complete, runnable files only, each with its full path.
2. One responsibility per module; routers contain no business logic.
3. Comment the *why* on any LLM, vector, embedding, or RLS logic.
4. Direct writes are allowed only for actions the person performs themselves. Anything initiated by the agent goes through `action_queue`.
5. Every new endpoint ships with at least one success test, one auth-failure test, and one cross-user test.
6. End each phase with: a file tree, the commands to run, the test output, and the exit checklist with each item marked.
7. Record every assumption in `docs/DECISIONS.md`.

## 19. Kick-off prompts (copy one per session)

**Phase 1**
> Read `KIN_MASTER_PROMPT.md` fully. Build **Phase 1 only** as defined in Section 17, following Sections 1, 6, 12, 13, 14, 15, and 18. Before writing code, list the files you will create and any assumptions. Then build, run the tests, and finish with the Phase 1 exit checklist.

**Phase 2**
> Read `KIN_MASTER_PROMPT.md`, `CLAUDE.md`, and `docs/DECISIONS.md`. Phase 1 is complete. Build **Phase 2 only**: the agent runtime, router, context injection, proposal loop, and the first four evals (Sections 7.4, 7.5, 8, 11, 15, 16). Do not add tools that write state.

**Phase 3**
> Phases 1–2 are complete. Build **Phase 3 only**: tool registry, approval lifecycle, executor, habits, reminders (Sections 9 and 10). Prove the commitment boundary with the eval.

**Phase 4**
> Phases 1–3 are complete. Build **Phase 4 only**: finance entries and the scenario engine (Sections 8 and 10). All arithmetic in pure, tested Python.

**Phase 5**
> Phases 1–4 are complete. Build **Phase 5 only**: the Expo and Next.js clients against the existing API. Change the API only where a client need exposes a gap, and record it in `docs/DECISIONS.md`.

**Review prompt (use after any phase)**
> Act as a security and privacy reviewer who did not write this code. Check the repo against Sections 2, 11, and 14 of `KIN_MASTER_PROMPT.md`. List every violation with file and line, most serious first. Do not fix anything yet.

---

## Appendix A — What changed from v1, and why

| v1 | v2 | Reason |
|---|---|---|
| `GET /api/context/{user_id}` | `GET /context`, user from token | A user ID in the URL lets anyone request anyone's profile |
| No Row Level Security policies | RLS on every table + per-request role switch | Supabase tables are open or bypassed without this |
| Own `users` table with email | `profiles` linked to `auth.users` | Avoids duplicating identity and storing email twice |
| `uuid_generate_v4()` | `gen_random_uuid()` | The former needs an extension that v1 never enabled |
| Supabase client **and** SQLAlchemy | SQLAlchemy only | Two data paths means two sets of bugs |
| Stored streak counters | Consistency computed from check-ins | Streaks contradicted the "no streak gamification" goal |
| Profile silently updated by extraction | `context_proposals` + version history | Makes "always shown, always editable" enforceable |
| Finance as one JSON blob | `finance_entries` with min/max ranges and currency | Irregular and cash income needs ranges; scenarios need structured input |
| Model does the maths | Code computes, model picks assumptions | Prevents invented figures |
| `action_queue` with three columns | Full lifecycle, idempotency, expiry, code-written preview | Approvals must be safe to retry and impossible to mislabel |
| Cloud embeddings only | Embedding provider interface + dimension check | v1's offline promise broke at the embedding step |
| No safety behaviour defined | Section 11 + human-maintained resources file | A companion app will meet people in distress |
| No tests or evals | Section 16 | "Context-grounded" has to be measurable to be real |
| No export or delete | Both in Phase 1 | Privacy-first has to include leaving |
| Rule 4 contradicted Phase 1 | Two explicit write paths | Removes the ambiguity |
| Pinned framework versions | "Latest stable, verified at build time" | Pinned numbers in a prompt go stale |
