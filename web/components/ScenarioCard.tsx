"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, Chip, ErrorText } from "./ui";

export type Scenario = {
  id: string;
  kind: "set_aside" | "cash_flow";
  premise: string;
  currency: string;
  amount_per_period?: number;
  period?: string;
  horizon_periods?: number;
  horizon_weeks?: number;
  cases: { name: "best" | "realistic" | "stress"; assumptions: string[]; outcome_range: [number, number]; periods_hit?: [number, number] }[];
  context_used_labels?: string[];
  unknowns: string[];
};

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
const range = ([a, b]: [number, number]) => (a === b ? fmt(a) : `${fmt(a)} – ${fmt(b)}`);

/** Ranges, not single numbers (principle 4). Every figure here was computed by code on the server. */
export function ScenarioCard({ s, onGoal, onKeepThinking }: { s: Scenario; onGoal?: () => void; onKeepThinking?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [queued, setQueued] = useState(false);
  const order = ["best", "realistic", "stress"] as const;
  const cases = order.map((n) => s.cases.find((c) => c.name === n)!).filter(Boolean);
  const all = cases.flatMap((c) => c.outcome_range);
  const lo = Math.min(0, ...all);
  const hi = Math.max(...all, 1);
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const unit = s.period ?? "week";

  const label = (c: (typeof cases)[number]) => {
    const hit = c.periods_hit;
    if (c.name === "best") return s.kind === "set_aside" ? `If every ${unit} works out` : "If things go well";
    const span = hit ? ` · ${hit[0] === hit[1] ? hit[0] : `${hit[0]} to ${hit[1]}`} ${unit}s` : "";
    return c.name === "realistic" ? `Most likely${span}` : `In a hard stretch${span}`;
  };

  async function makeGoal() {
    setBusy(true);
    setError("");
    try {
      await api(`/finance/scenarios/${s.id}/make-goal`, { method: "POST" });
      setQueued(true);
      onGoal?.();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <div className="space-y-6">
          {cases.map((c) => (
            <div key={c.name}>
              <div className="flex items-start justify-between gap-4">
                <p className={`text-[18px] leading-snug ${c.name === "realistic" ? "font-semibold" : "text-muted"}`}>{label(c)}</p>
                <p className={`shrink-0 text-right tabular-nums ${c.name === "realistic" ? "text-[26px] font-semibold" : "text-[20px]"}`}>
                  {range(c.outcome_range)}
                </p>
              </div>
              <div className="relative mt-3 h-6 rounded-full bg-track">
                <span
                  className={`absolute top-0 h-6 rounded-full ${c.name === "realistic" ? "bg-ink" : "bg-accent"}`}
                  style={{
                    left: `${Math.min(pos(c.outcome_range[0]), 94)}%`,
                    width: `${Math.max(pos(c.outcome_range[1]) - pos(c.outcome_range[0]), 6)}%`,
                  }}
                />
              </div>
              <p className="mt-2 text-sm text-muted">{c.assumptions.join(" · ")}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-sm text-muted">Amounts in {s.currency === "XXX" ? "your currency" : s.currency}.</p>
      </Card>

      {!!s.context_used_labels?.length && (
        <Card tone="soft">
          <p className="text-[17px] font-medium">What I used about you</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {s.context_used_labels.map((l) => (
              <Chip key={l}>{l}</Chip>
            ))}
          </div>
        </Card>
      )}
      {!!s.unknowns.length && <p className="text-[15px] text-muted">Not known yet: {s.unknowns.join("; ")}.</p>}
      <p className="text-[16px] text-muted">These are ranges, not advice. Nothing is saved yet.</p>
      <ErrorText>{error}</ErrorText>
      {s.kind === "set_aside" &&
        (queued ? (
          <p className="text-[16px] font-medium">Added to Today for your OK. Nothing changes until you approve it.</p>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <Button disabled={busy} onClick={makeGoal}>
              Make this my goal
            </Button>
            <Button variant="outline" onClick={onKeepThinking}>
              Keep thinking
            </Button>
          </div>
        ))}
    </div>
  );
}
