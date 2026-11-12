"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AuthGate } from "@/components/AuthGate";
import { ActionCard, HabitCard, ProposalCard, type Action, type Habit, type Proposal } from "@/components/cards";
import { Button, Card, Eyebrow, Field, inputCls, Note, Page, Title } from "@/components/ui";
import { api } from "@/lib/api";
import { pendingCount } from "@/lib/offline";

const MOODS = ["Heavy", "Okay", "Good"] as const;

function Today() {
  const [actions, setActions] = useState<Action[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [habits, setHabits] = useState<Habit[]>([]);
  const [today, setToday] = useState("");
  const [reminders, setReminders] = useState<any[]>([]);
  const [mood, setMood] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [outbox, setOutbox] = useState(0);

  const load = useCallback(async () => {
    const [a, p, h, r] = await Promise.all([
      api<Action[]>("/actions?status=pending"),
      api<Proposal[]>("/context/proposals"),
      api<{ today: string; habits: Habit[] }>("/habits"),
      api<any[]>("/reminders"),
    ]);
    setActions(a);
    setProposals(p);
    setHabits(h.habits.filter((x) => x.status === "active"));
    setToday(h.today);
    setReminders(r);
    try {
      setMood(localStorage.getItem(`kin.mood.${h.today}`));
    } catch {}
  }, []);

  useEffect(() => {
    void load().catch(() => {});
    const upd = () => setOutbox(pendingCount());
    upd();
    window.addEventListener("kin-outbox", upd);
    return () => window.removeEventListener("kin-outbox", upd);
  }, [load]);

  async function pickMood(m: string) {
    setMood(m);
    try {
      localStorage.setItem(`kin.mood.${today}`, m);
    } catch {}
    await api("/memories", { method: "POST", json: { kind: "note", content: `How today is going: ${m.toLowerCase()}`, metadata: { type: "mood", date: today } } }).catch(() => {});
  }

  const dateLabel = today
    ? new Date(today + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })
    : "";
  const waiting = actions.length + proposals.length;
  const dueToday = reminders.filter((r) => r.next_fire_at && r.next_fire_at.slice(0, 10) === today);
  const best = habits.reduce<Habit | null>((b, h) => (!b || h.consistency.count > b.consistency.count ? h : b), null);

  return (
    <Page>
      <Eyebrow>{dateLabel}</Eyebrow>
      <Title>Small steps count today.</Title>

      <Card className="mt-6">
        <p className="text-[20px] font-medium">How is today going?</p>
        <div className="mt-4 grid grid-cols-3 gap-3">
          {MOODS.map((m) => (
            <Button key={m} variant={mood === m ? "primary" : "outline"} onClick={() => pickMood(m)} aria-pressed={mood === m}>
              {m}
            </Button>
          ))}
        </div>
      </Card>

      {waiting > 0 && (
        <section className="mt-8 space-y-4">
          <Eyebrow>{waiting === 1 ? "1 thing waiting for you" : `${waiting} things waiting for you`}</Eyebrow>
          <h2 className="text-[28px] font-bold">Your call.</h2>
          {actions.map((a) => (
            <ActionCard key={a.id} action={a} onDone={load} />
          ))}
          {proposals.map((p) => (
            <ProposalCard key={p.id} p={p} onDone={load} />
          ))}
          <Note>Nothing changes until you approve it.</Note>
        </section>
      )}

      <section className="mt-8 space-y-4">
        <div className="flex items-center justify-between">
          <Eyebrow>Your habits</Eyebrow>
          <button className="text-[15px] text-muted underline" onClick={() => setAdding((v) => !v)}>
            {adding ? "Close" : "Add a habit"}
          </button>
        </div>
        {adding && <AddHabit onDone={() => { setAdding(false); void load(); }} />}
        {habits.length === 0 && !adding && (
          <Card>
            <p className="text-[17px] text-muted">
              No habits yet. Add one here, or talk it through in <Link href="/think/" className="underline">Think</Link> first.
            </p>
          </Card>
        )}
        {habits.map((h) => (
          <HabitCard key={h.id} h={h} today={today} onChange={load} />
        ))}
        {outbox > 0 && <Note>{outbox} saved on this phone, will send when you&apos;re back online.</Note>}
      </section>

      {dueToday.length > 0 && (
        <section className="mt-8 space-y-3">
          <Eyebrow>Later today</Eyebrow>
          {dueToday.map((r) => (
            <Card key={r.id}>
              <p className="text-[18px] font-medium">{r.message}</p>
              <p className="text-[15px] text-muted">
                {new Date(r.next_fire_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
              </p>
            </Card>
          ))}
        </section>
      )}

      {best && best.consistency.count >= 3 && (
        <Card tone="soft" className="mt-8">
          <p className="text-[20px] font-medium">
            {best.consistency.count} of the last 7 days: {best.title.toLowerCase()}.
          </p>
          <p className="mt-1 text-[17px] text-muted">Is there someone you would like to tell?</p>
        </Card>
      )}
    </Page>
  );
}

function AddHabit({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [min, setMin] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Card>
      <div className="space-y-4">
        <Field label="Habit">
          <input className={inputCls} placeholder="Walk 20 minutes" value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Hard-day version" hint="The smallest version that still counts.">
          <input className={inputCls} placeholder="5 min version" value={min} onChange={(e) => setMin(e.target.value)} />
        </Field>
        <Button
          className="w-full"
          disabled={!title.trim() || busy}
          onClick={async () => {
            setBusy(true);
            await api("/habits", { method: "POST", json: { title: title.trim(), minimum_version: min.trim() || null } });
            onDone();
          }}
        >
          Add habit
        </Button>
      </div>
    </Card>
  );
}

export default function TodayPage() {
  return (
    <AuthGate>
      <Today />
    </AuthGate>
  );
}
