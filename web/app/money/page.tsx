"use client";

import { useCallback, useEffect, useState } from "react";
import { AuthGate } from "@/components/AuthGate";
import { ScenarioCard, type Scenario } from "@/components/ScenarioCard";
import { Button, Card, Chip, ErrorText, Eyebrow, Field, inputCls, Note, Page, Title } from "@/components/ui";
import { api } from "@/lib/api";

type Entry = {
  id: string; direction: "in" | "out" | "set_aside"; label: string; amount_min: string; amount_max: string;
  currency: string; frequency: string; is_obligation: boolean;
};
const PERIODS = ["day", "week", "month"] as const;
const FREQ = ["daily", "weekly", "monthly", "irregular", "seasonal", "one_off"];
const fmt = (v: string | number) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });

function Money() {
  const [amount, setAmount] = useState("");
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("week");
  const [horizon, setHorizon] = useState("12");
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [goals, setGoals] = useState<any[]>([]);
  const [currency, setCurrency] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    const [e, g, ctx] = await Promise.all([api<Entry[]>("/finance/entries"), api<any[]>("/finance/goals"), api<any>("/context")]);
    setEntries(e);
    setGoals(g);
    setCurrency(ctx.region?.currency?.value ?? "");
  }, []);
  useEffect(() => {
    void load().catch(() => {});
  }, [load]);

  async function runWhatIf(kind: "set_aside" | "cash_flow") {
    setBusy(true);
    setError("");
    setScenario(null);
    try {
      const json =
        kind === "set_aside"
          ? { kind, amount_per_period: Number(amount), period, horizon_periods: Number(horizon) }
          : { kind, period: "week", horizon_periods: 4 };
      setScenario(await api<Scenario>("/finance/scenarios", { method: "POST", json }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page>
      <Eyebrow>What if</Eyebrow>
      {scenario ? (
        <>
          <Title>
            {scenario.kind === "set_aside"
              ? `I set aside ${currency || ""} ${fmt(scenario.amount_per_period ?? 0)} a ${scenario.period} for ${scenario.horizon_periods} ${scenario.period}s?`
              : `The next ${scenario.horizon_weeks} weeks, left over after what goes out`}
          </Title>
          <div className="mt-6">
            <ScenarioCard s={scenario} onGoal={load} onKeepThinking={() => setScenario(null)} />
          </div>
        </>
      ) : (
        <>
          <Title>Try a number. Nothing is saved.</Title>
          <Card className="mt-6">
            <div className="space-y-4">
              <Field label={`If I set aside${currency ? ` (${currency})` : ""}`}>
                <input className={inputCls} inputMode="decimal" placeholder="300" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} />
              </Field>
              <div className="flex gap-2">
                {PERIODS.map((p) => (
                  <Chip key={p} active={period === p} onClick={() => setPeriod(p)}>
                    a {p}
                  </Chip>
                ))}
              </div>
              <Field label={`For how many ${period}s?`}>
                <input className={inputCls} inputMode="numeric" value={horizon} onChange={(e) => setHorizon(e.target.value.replace(/\D/g, ""))} />
              </Field>
              <ErrorText>{error}</ErrorText>
              <Button className="w-full" disabled={busy || !Number(amount) || !Number(horizon)} onClick={() => runWhatIf("set_aside")}>
                {busy ? "Working it out…" : "Show me the range"}
              </Button>
            </div>
          </Card>
        </>
      )}

      <section className="mt-10 space-y-4">
        <div className="flex items-center justify-between">
          <Eyebrow>What comes in and goes out</Eyebrow>
          <button className="text-[15px] text-muted underline" onClick={() => setAdding((v) => !v)}>
            {adding ? "Close" : "Add"}
          </button>
        </div>
        {adding && <AddEntry currency={currency} onDone={() => { setAdding(false); void load(); }} />}
        {entries.length === 0 && !adding && (
          <Card>
            <Note>Add rough ranges — &ldquo;between 500 and 1,500 a day&rdquo; is perfect. No bank account needed.</Note>
          </Card>
        )}
        {entries.map((e) => (
          <Card key={e.id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[18px] font-medium">{e.label}</p>
                <p className="text-[15px] text-muted">
                  {e.direction === "in" ? "Comes in" : e.direction === "out" ? "Goes out" : "Set aside"} · {e.frequency.replace("_", " ")}
                  {e.is_obligation ? " · commitment" : ""}
                </p>
              </div>
              <p className="shrink-0 text-right text-[18px] tabular-nums">
                {e.currency} {e.amount_min === e.amount_max ? fmt(e.amount_min) : `${fmt(e.amount_min)}–${fmt(e.amount_max)}`}
              </p>
            </div>
            <button
              className="mt-2 text-sm text-muted underline"
              onClick={async () => {
                await api(`/finance/entries/${e.id}`, { method: "DELETE" });
                void load();
              }}
            >
              Remove
            </button>
          </Card>
        ))}
        {entries.length > 0 && (
          <Button variant="outline" className="w-full" disabled={busy} onClick={() => runWhatIf("cash_flow")}>
            How might the next 4 weeks look?
          </Button>
        )}
      </section>

      {goals.length > 0 && (
        <section className="mt-10 space-y-3">
          <Eyebrow>Goals you approved</Eyebrow>
          {goals.map((g) => (
            <Card key={g.id} tone="soft">
              <p className="text-[18px] font-medium">{g.title}</p>
            </Card>
          ))}
        </section>
      )}
      <div className="mt-8">
        <Note>Kin lays out tradeoffs, not instructions. For loans, contracts, tax or insurance, talk to a licensed adviser.</Note>
      </div>
    </Page>
  );
}

function AddEntry({ currency, onDone }: { currency: string; onDone: () => void }) {
  const [f, setF] = useState({ direction: "in", label: "", amount_min: "", amount_max: "", frequency: "weekly", is_obligation: false, currency });
  const [error, setError] = useState("");
  const set = (p: Partial<typeof f>) => setF({ ...f, ...p });
  return (
    <Card>
      <div className="space-y-4">
        <div className="flex gap-2">
          {[["in", "Comes in"], ["out", "Goes out"], ["set_aside", "Set aside"]].map(([v, l]) => (
            <Chip key={v} active={f.direction === v} onClick={() => set({ direction: v })}>
              {l}
            </Chip>
          ))}
        </div>
        <Field label="What is it?">
          <input className={inputCls} placeholder="Daily sales, rent, chama…" value={f.label} onChange={(e) => set({ label: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="From">
            <input className={inputCls} inputMode="decimal" value={f.amount_min} onChange={(e) => set({ amount_min: e.target.value.replace(/[^\d.]/g, "") })} />
          </Field>
          <Field label="To">
            <input className={inputCls} inputMode="decimal" placeholder="same" value={f.amount_max} onChange={(e) => set({ amount_max: e.target.value.replace(/[^\d.]/g, "") })} />
          </Field>
        </div>
        <div className="flex flex-wrap gap-2">
          {FREQ.map((q) => (
            <Chip key={q} active={f.frequency === q} onClick={() => set({ frequency: q })}>
              {q.replace("_", " ")}
            </Chip>
          ))}
        </div>
        <Field label="Currency">
          <input className={inputCls} maxLength={3} value={f.currency} onChange={(e) => set({ currency: e.target.value.toUpperCase() })} />
        </Field>
        {f.direction !== "in" && (
          <label className="flex items-center gap-3 text-[16px]">
            <input type="checkbox" className="h-5 w-5" checked={f.is_obligation} onChange={(e) => set({ is_obligation: e.target.checked })} />
            This is a commitment (family, fees, rent) — never treat it as cuttable
          </label>
        )}
        <ErrorText>{error}</ErrorText>
        <Button
          className="w-full"
          disabled={!f.label || !f.amount_min || f.currency.length !== 3}
          onClick={async () => {
            setError("");
            try {
              await api("/finance/entries", {
                method: "POST",
                json: { ...f, amount_min: Number(f.amount_min), amount_max: Number(f.amount_max || f.amount_min) },
              });
              onDone();
            } catch (e: any) {
              setError(e.message);
            }
          }}
        >
          Save
        </Button>
      </div>
    </Card>
  );
}

export default function MoneyPage() {
  return (
    <AuthGate>
      <Money />
    </AuthGate>
  );
}
