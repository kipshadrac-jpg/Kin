-- 0001_init.sql — full Kin schema (Section 12 of KIN_MASTER_PROMPT.md)
-- pgvector lives in the `extensions` schema, as Supabase recommends.
create extension if not exists vector with schema extensions;

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
  embedding   extensions.vector(1536),
  embedding_model text,
  created_at  timestamptz not null default now()
);
create index memories_user_created_idx on public.memories (user_id, created_at desc);
create index memories_embedding_idx on public.memories using hnsw (embedding extensions.vector_cosine_ops);

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
create index context_proposals_user_status_idx on public.context_proposals (user_id, status);

-- Habits
create table public.habits (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  title      text not null,
  why        text,
  cadence    jsonb not null default '{}'::jsonb,
  minimum_version text,
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
  result     jsonb not null,
  created_at timestamptz not null default now()
);

-- Reminders and scheduled check-ins
create table public.reminders (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  kind       text not null check (kind in ('habit','checkin','custom')),
  message    text not null,
  schedule   jsonb not null,
  next_fire_at timestamptz,
  status     text not null default 'active' check (status in ('active','paused','cancelled')),
  created_at timestamptz not null default now()
);

-- Human-in-the-loop queue
create table public.action_queue (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  session_id uuid references public.reasoning_sessions(id) on delete set null,
  action_type text not null,
  payload    jsonb not null,
  payload_history jsonb not null default '[]'::jsonb,
  preview    text not null,
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
