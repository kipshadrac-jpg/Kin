"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { sendOrQueue } from "@/lib/offline";
import { Button, Card, Chip, ErrorText, inputCls } from "./ui";

export type Action = { id: string; action_type: string; payload: Record<string, any>; preview: string; status: string; expires_at: string };
export type Proposal = { id: string; section: string; field_path: string; proposed_value: any; evidence_quote: string };

const KIND_LABEL: Record<string, string> = {
  set_reminder: "Reminder", set_goal: "Goal", create_habit: "New habit", log_habit: "Check-in",
  add_finance_entry: "Money entry", save_journal: "Journal entry",
};
const DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
const DAY_SHORT: Record<string, string> = { MO: "Mon", TU: "Tue", WE: "Wed", TH: "Thu", FR: "Fri", SA: "Sat", SU: "Sun" };

function splitPreview(a: Action): [string, string] {
  if (a.action_type === "set_goal" && a.payload.horizon_periods) {
    const m = a.preview.match(/^(.*) for (\d+ \w+)$/);
    if (m) return [m[1], `For ${m[2]}${a.payload.scenario_id ? ", from your what-if" : ""}`];
  }
  const parts = a.preview.split(" · ");
  return [parts[0], parts.slice(1).join(" · ")];
}

/** One card, one decision (Section 9.2). The text is the server's code-written preview. */
export function ActionCard({ action, onDone }: { action: Action; onDone: () => void }) {
  const [editing, setEditing] = useState(false);
  const [payload, setPayload] = useState<Record<string, any>>(action.payload);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [title, sub] = splitPreview(action);

  async function run(path: string, json?: unknown) {
    setBusy(true);
    setError("");
    try {
      await api(`/actions/${action.id}/${path}`, { method: "POST", json });
      onDone();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <p className="text-[15px] font-medium text-muted">{KIND_LABEL[action.action_type] ?? "Action"}</p>
      <p className="mt-1 text-[22px] font-semibold leading-snug">{title}</p>
      {sub && <p className="mt-1 text-[17px] text-muted">{sub}</p>}
      {editing && <PayloadEditor type={action.action_type} payload={payload} onChange={setPayload} />}
      <ErrorText>{error}</ErrorText>
      <div className="mt-4 grid grid-cols-3 gap-3">
        {editing ? (
          <>
            <Button disabled={busy} onClick={() => run("edit", { payload }).then(() => setEditing(false))}>
              Save
            </Button>
            <Button variant="outline" onClick={() => { setEditing(false); setPayload(action.payload); }}>
              Back
            </Button>
          </>
        ) : (
          <>
            <Button disabled={busy} onClick={() => run("approve")}>
              Approve
            </Button>
            <Button variant="outline" disabled={busy} onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => run("cancel")}>
              Cancel
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}

function PayloadEditor({ type, payload, onChange }: { type: string; payload: Record<string, any>; onChange: (p: Record<string, any>) => void }) {
  const set = (k: string, v: any) => onChange({ ...payload, [k]: v });
  const text = (k: string, label: string) =>
    k in payload || ["message", "title", "label", "content"].includes(k) ? (
      <label key={k} className="block">
        <span className="mb-1 block text-sm text-muted">{label}</span>
        <input className={inputCls} value={payload[k] ?? ""} onChange={(e) => set(k, e.target.value)} />
      </label>
    ) : null;
  const num = (k: string, label: string) =>
    k in payload ? (
      <label key={k} className="block">
        <span className="mb-1 block text-sm text-muted">{label}</span>
        <input className={inputCls} inputMode="decimal" value={payload[k] ?? ""} onChange={(e) => set(k, e.target.value === "" ? null : Number(e.target.value))} />
      </label>
    ) : null;
  return (
    <div className="mt-4 space-y-3">
      {type === "set_reminder" && (
        <>
          {text("message", "What")}
          <div className="flex flex-wrap gap-2">
            {DAYS.map((d) => {
              const on = (payload.days ?? []).includes(d);
              return (
                <Chip key={d} active={on} onClick={() => set("days", on ? payload.days.filter((x: string) => x !== d) : [...(payload.days ?? []), d])}>
                  {DAY_SHORT[d]}
                </Chip>
              );
            })}
          </div>
          <input type="time" className={inputCls} value={payload.time} onChange={(e) => set("time", e.target.value)} />
        </>
      )}
      {type === "set_goal" && [text("title", "Goal"), num("amount_per_period", "Amount each time"), num("horizon_periods", "How many times")]}
      {type === "create_habit" && [text("title", "Habit"), text("minimum_version", "Hard-day version")]}
      {type === "add_finance_entry" && [text("label", "What"), num("amount_min", "From"), num("amount_max", "To")]}
      {type === "save_journal" && (
        <textarea className={inputCls} rows={4} value={payload.content} onChange={(e) => set("content", e.target.value)} />
      )}
      {type === "log_habit" && (
        <div className="flex gap-2">
          {["done", "minimum", "skipped"].map((o) => (
            <Chip key={o} active={payload.outcome === o} onClick={() => set("outcome", o)}>
              {o === "minimum" ? "Short version" : o[0].toUpperCase() + o.slice(1)}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

export function ProposalCard({ p, onDone }: { p: Proposal; onDone: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(p.proposed_value));
  const [error, setError] = useState("");

  async function resolve(decision: string, edited_value?: string) {
    setError("");
    try {
      await api(`/context/proposals/${p.id}/resolve`, { method: "POST", json: { decision, edited_value } });
      onDone();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <Card tone="soft">
      <p className="text-[15px] font-medium text-muted">About you</p>
      <p className="mt-1 text-[22px] font-semibold leading-snug">Add this to your profile?</p>
      <p className="mt-1 text-[17px] text-muted">You wrote: “{p.evidence_quote}”</p>
      <p className="mt-2 text-[16px]">
        I&apos;d keep: <span className="font-medium">{String(p.proposed_value)}</span>
      </p>
      {editing && <input className={`${inputCls} mt-3`} value={value} onChange={(e) => setValue(e.target.value)} />}
      <ErrorText>{error}</ErrorText>
      <div className="mt-4 grid grid-cols-3 gap-3">
        {editing ? (
          <>
            <Button onClick={() => resolve("edit", value)}>Save</Button>
            <Button variant="soft" onClick={() => setEditing(false)}>
              Back
            </Button>
          </>
        ) : (
          <>
            <Button onClick={() => resolve("accept")}>Add</Button>
            <Button variant="soft" onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Button variant="ghost" className="text-ink" onClick={() => resolve("not_now")}>
              Not now
            </Button>
          </>
        )}
      </div>
      <button className="mt-3 text-sm text-muted underline" onClick={() => resolve("never_ask")}>
        Never ask about this
      </button>
    </Card>
  );
}

export type Habit = {
  id: string; title: string; minimum_version: string | null; status: string; needs_review: boolean; today: string | null;
  consistency: { label: string; count: number; days: { date: string; outcome: string | null }[] };
};

export function HabitCard({ h, today, onChange }: { h: Habit; today: string; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [queued, setQueued] = useState<string | null>(null);
  const state = queued ?? h.today;

  async function log(outcome: "done" | "minimum") {
    setBusy(true);
    try {
      const sent = await sendOrQueue(`/habits/${h.id}/checkins`, "POST", { occurred_on: today, outcome }, h.title);
      if (sent) onChange();
      else setQueued(outcome);
    } finally {
      setBusy(false);
    }
  }
  async function undo() {
    setBusy(true);
    try {
      await api(`/habits/${h.id}/checkins/${today}`, { method: "DELETE" });
      setQueued(null);
      onChange();
    } finally {
      setBusy(false);
    }
  }
  async function setStatus(status: string) {
    await api(`/habits/${h.id}`, { method: "PATCH", json: { status } });
    onChange();
  }

  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[22px] font-semibold leading-snug">{h.title}</p>
        <p className="shrink-0 text-[15px] text-muted">{h.consistency.label}</p>
      </div>
      <div className="mt-3 grid grid-cols-7 gap-2" aria-label={h.consistency.label}>
        {h.consistency.days.map((d, i) => {
          const isToday = i === h.consistency.days.length - 1;
          const filled = (isToday ? state : d.outcome) === "done" || (isToday ? state : d.outcome) === "minimum";
          return (
            <span
              key={d.date}
              className={`h-3 rounded-full ${filled ? "bg-ink" : "bg-track"} ${isToday ? "outline-2 outline-offset-1 outline-ink" : ""}`}
            />
          );
        })}
      </div>
      {h.needs_review ? (
        <div className="mt-4">
          <p className="text-[16px] text-muted">It&apos;s been a couple of weeks. Does this habit still fit your life right now?</p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Button onClick={() => log("minimum")}>Keep it</Button>
            <Button variant="outline" onClick={() => setStatus("paused")}>
              Pause it
            </Button>
          </div>
        </div>
      ) : state ? (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-[16px] text-muted">
            {state === "minimum" ? "Short version done today." : "Done today."}
            {queued && " Will sync when you're back online."}
          </p>
          {!queued && (
            <button className="text-[15px] text-muted underline" disabled={busy} onClick={undo}>
              Undo
            </button>
          )}
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-[1.4fr_1fr] gap-3">
          <Button disabled={busy} onClick={() => log("done")}>
            Done
          </Button>
          <Button variant="outline" disabled={busy} onClick={() => log("minimum")}>
            {h.minimum_version || "Short version"}
          </Button>
        </div>
      )}
    </Card>
  );
}
