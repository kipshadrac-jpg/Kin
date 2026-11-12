-- 0002_rls.sql — Row Level Security, grants, triggers.
--
-- Roles used by Kin (login roles with passwords are created by the bootstrap
-- step, never in a migration, because passwords are secrets):
--   authenticated  Supabase's role for a signed-in person. The API switches to it
--                  per request (`set local role authenticated`) so RLS applies.
--   kin_agent      NOLOGIN. The agent runtime switches to it. It can READ the
--                  person's rows but may only INSERT into action_queue,
--                  context_proposals, reasoning_sessions, scenarios and memories.
--                  It cannot write habits, finance, goals, reminders or the profile.
--                  This enforces "the agent has no credentials that write domain
--                  tables" in the database itself, not just in Python.
--   kin_api        LOGIN, no BYPASSRLS, member of authenticated + kin_agent.
--   kin_worker     LOGIN, BYPASSRLS, narrow grants (expiry + reminders + extraction).

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kin_agent') then
    create role kin_agent nologin noinherit;
  end if;
end $$;

grant usage on schema public to authenticated, kin_agent;
grant usage on schema extensions to authenticated, kin_agent;
grant usage on schema auth to kin_agent;
grant execute on function auth.uid() to kin_agent;

-- Start from nothing, then grant exactly what each role needs.
revoke all on all tables in schema public from anon, authenticated, kin_agent;
revoke all on all tables in schema public from public;

grant select, insert, update, delete on
  public.profiles, public.user_context, public.memories, public.context_proposals,
  public.habits, public.habit_checkins, public.finance_entries, public.goals,
  public.reasoning_sessions, public.scenarios, public.reminders, public.action_queue
to authenticated;
grant select, insert, delete on public.user_context_versions to authenticated;
grant select on public.audit_log to authenticated;

grant select on
  public.profiles, public.user_context, public.user_context_versions, public.memories,
  public.context_proposals, public.habits, public.habit_checkins, public.finance_entries,
  public.goals, public.reasoning_sessions, public.scenarios, public.reminders, public.action_queue
to kin_agent;
grant insert on public.action_queue, public.context_proposals, public.scenarios, public.memories to kin_agent;
-- The agent may replace its own session summaries (restricted below to that kind only).
grant delete on public.memories to kin_agent;
grant insert, update on public.reasoning_sessions to kin_agent;

-- RLS: the same "own rows" policy on every table, for both roles.
do $$
declare t text;
begin
  foreach t in array array[
    'profiles','user_context','user_context_versions','memories','context_proposals',
    'habits','habit_checkins','finance_entries','goals','reasoning_sessions','scenarios',
    'reminders','action_queue'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format($p$create policy "own rows" on public.%I
        for all to authenticated, kin_agent
        using (user_id = (select auth.uid()))
        with check (user_id = (select auth.uid()))$p$, t);
  end loop;
end $$;

-- The agent can delete a memory only if it is a session summary it wrote.
create policy "agent deletes only session summaries" on public.memories
  as restrictive for delete to kin_agent
  using (kind = 'session_summary');

-- audit_log: select-only for the owner; inserts go through kin_audit().
alter table public.audit_log enable row level security;
alter table public.audit_log force row level security;
create policy "own rows read" on public.audit_log
  for select to authenticated
  using (user_id = (select auth.uid()));

-- Backend service path for audit inserts. SECURITY DEFINER so a signed-in
-- request can record an event without having INSERT on audit_log; the user id
-- always comes from the verified JWT claims, never from an argument.
create or replace function public.kin_audit(p_event text, p_entity text, p_entity_id uuid)
returns void language sql security definer set search_path = public as $$
  insert into public.audit_log (user_id, event, entity, entity_id)
  values (auth.uid(), p_event, p_entity, p_entity_id);
$$;
revoke all on function public.kin_audit(text, text, uuid) from public;
grant execute on function public.kin_audit(text, text, uuid) to authenticated, kin_agent;

-- updated_at triggers
do $$
declare t text;
begin
  foreach t in array array['profiles','user_context','habits','finance_entries','goals','reasoning_sessions'] loop
    execute format('create trigger set_updated_at before update on public.%I
                    for each row execute function public.set_updated_at()', t);
  end loop;
end $$;
