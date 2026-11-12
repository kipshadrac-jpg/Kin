"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AuthGate, useMe } from "@/components/AuthGate";
import { Button, Card, Chip, ErrorText, Eyebrow, Field, inputCls, Note, Page, Title } from "@/components/ui";
import { api } from "@/lib/api";

/** Conversational onboarding (Section 7.3): open questions, every step skippable,
 *  progress saved on the phone so it can be resumed, and a read-back screen.
 *  Nothing is saved as the profile until the person confirms. */

const COUNTRIES: [string, string, string][] = [
  ["KE", "Kenya", "KES"], ["UG", "Uganda", "UGX"], ["TZ", "Tanzania", "TZS"], ["RW", "Rwanda", "RWF"],
  ["ET", "Ethiopia", "ETB"], ["NG", "Nigeria", "NGN"], ["GH", "Ghana", "GHS"], ["ZA", "South Africa", "ZAR"],
  ["ZM", "Zambia", "ZMW"], ["ZW", "Zimbabwe", "USD"], ["EG", "Egypt", "EGP"], ["MA", "Morocco", "MAD"],
  ["SN", "Senegal", "XOF"], ["CM", "Cameroon", "XAF"], ["IN", "India", "INR"], ["PK", "Pakistan", "PKR"],
  ["BD", "Bangladesh", "BDT"], ["PH", "Philippines", "PHP"], ["ID", "Indonesia", "IDR"], ["BR", "Brazil", "BRL"],
  ["MX", "Mexico", "MXN"], ["US", "United States", "USD"], ["CA", "Canada", "CAD"], ["GB", "United Kingdom", "GBP"],
  ["IE", "Ireland", "EUR"], ["DE", "Germany", "EUR"], ["FR", "France", "EUR"], ["AE", "UAE", "AED"],
  ["SA", "Saudi Arabia", "SAR"], ["AU", "Australia", "AUD"],
];
const SAVING = ["Bank", "Mobile wallet", "Savings group", "At home", "Not currently"];
const INCOME: [string, string][] = [
  ["regular", "Regular"], ["irregular", "Changes a lot"], ["cash", "Mostly cash"], ["mixed", "A mix"],
  ["none", "No income of my own"], ["prefer_not_to_say", "Prefer not to say"],
];
const AREA: [string, string][] = [["city", "City"], ["town", "Town"], ["rural", "Rural"], ["prefer_not_to_say", "Prefer not to say"]];

type Draft = {
  step: number;
  country: string; area_type: string; currency: string; timezone: string; languages: string; region_notes: string;
  income_pattern: string; how_money_arrives: string; stability: string;
  obligations: string; saving_methods: string[];
  matters_most: string; sensitivities: string; aspirations: string;
  encouragement: string; backfires: string; quiet_from: string; quiet_to: string;
};

const EMPTY: Draft = {
  step: 0, country: "", area_type: "", currency: "", timezone: "", languages: "", region_notes: "",
  income_pattern: "", how_money_arrives: "", stability: "", obligations: "", saving_methods: [],
  matters_most: "", sensitivities: "", aspirations: "", encouragement: "", backfires: "", quiet_from: "", quiet_to: "",
};
const KEY = "kin.onboarding";
const lines = (s: string) => s.split(/\n|;/).map((x) => x.trim()).filter(Boolean);

function toPayload(d: Draft) {
  const clean = (o: Record<string, unknown>) =>
    Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v != null && !(Array.isArray(v) && !v.length)));
  return {
    region: clean({
      country: d.country, area_type: d.area_type, currency: d.currency, timezone: d.timezone,
      languages: lines(d.languages.replace(/,/g, ";")), notes: d.region_notes.trim(),
    }),
    economic_frame: clean({
      income_pattern: d.income_pattern, how_money_arrives: d.how_money_arrives.trim(), stability: d.stability.trim(),
      obligations: lines(d.obligations), saving_methods: d.saving_methods,
    }),
    values_profile: clean({
      matters_most: lines(d.matters_most), sensitivities: lines(d.sensitivities), aspirations: lines(d.aspirations),
    }),
    emotional_baseline: clean({
      encouragement: d.encouragement.trim(), backfires: d.backfires.trim(),
      quiet_hours: d.quiet_from && d.quiet_to ? { from: d.quiet_from, to: d.quiet_to } : null,
    }),
  };
}

function Onboarding() {
  const router = useRouter();
  const { me } = useMe();
  const [d, setD] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(KEY);
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      setD(saved ? { ...EMPTY, ...JSON.parse(saved) } : { ...EMPTY, timezone: tz });
    } catch {
      /* fresh start */
    }
  }, []);

  const set = (patch: Partial<Draft>) =>
    setD((prev) => {
      const next = { ...prev, ...patch };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  const go = (step: number) => {
    set({ step });
    window.scrollTo(0, 0);
  };

  const steps = 7;
  const payload = useMemo(() => toPayload(d), [d]);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await api("/context/onboard", { method: "POST", json: payload });
      localStorage.removeItem(KEY);
      router.replace("/");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const Nav = ({ next = d.step + 1 }: { next?: number }) => (
    <div className="mt-8 flex gap-3">
      {d.step > 0 && (
        <Button variant="outline" onClick={() => go(d.step - 1)}>
          Back
        </Button>
      )}
      <Button className="flex-1" onClick={() => go(next)}>
        Continue
      </Button>
      <Button variant="ghost" onClick={() => go(next)}>
        Skip
      </Button>
    </div>
  );

  return (
    <Page>
      {d.step < steps && <Eyebrow>{d.step === 0 ? "Welcome" : `${d.step} of ${steps - 1}`}</Eyebrow>}

      {d.step === 0 && (
        <>
          <Title>A few questions, all skippable.</Title>
          <div className="mt-5 space-y-4 text-[17px] text-muted">
            <p>I&apos;ll only use what you tell me. I won&apos;t guess things about you from your name, where you live or your language.</p>
            <p>You can see, change or delete anything later in “Me”.</p>
          </div>
          <Card className="mt-6">
            <p className="font-medium">Who receives your words</p>
            <p className="mt-2 text-[15px] text-muted">
              {me?.providers.cloud_llm
                ? `To think things through, your messages and the parts of your profile they need are sent to ${me.providers.cloud_llm}.`
                : "This server has no cloud model set up."}{" "}
              {me?.providers.cloud_embeddings
                ? `Journal entries are sent to ${me.providers.cloud_embeddings} to make them searchable.`
                : "Journal search runs on this server; journal text isn't sent anywhere for it."}
            </p>
          </Card>
          <Nav />
        </>
      )}

      {d.step === 1 && (
        <>
          <Title>Where do you live?</Title>
          <div className="mt-6 space-y-5">
            <Field label="Country">
              <select
                className={inputCls}
                value={d.country}
                onChange={(e) => {
                  const c = COUNTRIES.find(([code]) => code === e.target.value);
                  set({ country: e.target.value, currency: c?.[2] ?? d.currency });
                }}
              >
                <option value="">Prefer not to say</option>
                {COUNTRIES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </Field>
            <div>
              <p className="mb-2 text-[15px] font-medium">What kind of place?</p>
              <div className="flex flex-wrap gap-2">
                {AREA.map(([v, l]) => (
                  <Chip key={v} active={d.area_type === v} onClick={() => set({ area_type: d.area_type === v ? "" : v })}>
                    {l}
                  </Chip>
                ))}
              </div>
            </div>
            <Field label="Currency you use" hint="Three letters, like KES or USD.">
              <input className={inputCls} maxLength={3} value={d.currency} onChange={(e) => set({ currency: e.target.value.toUpperCase().replace(/[^A-Z]/g, "") })} />
            </Field>
            <Field label="Languages you're comfortable in">
              <input className={inputCls} placeholder="e.g. Swahili, English" value={d.languages} onChange={(e) => set({ languages: e.target.value })} />
            </Field>
            <Field label="Anything worth knowing about where you live?">
              <textarea className={inputCls} rows={3} maxLength={2000} placeholder="e.g. Transport costs jump when it rains." value={d.region_notes} onChange={(e) => set({ region_notes: e.target.value })} />
            </Field>
          </div>
          <Nav />
        </>
      )}

      {d.step === 2 && (
        <>
          <Title>How does money usually reach you?</Title>
          <div className="mt-6 space-y-5">
            <Field label="In your own words">
              <textarea className={inputCls} rows={3} maxLength={2000} placeholder="e.g. Daily sales, mostly mobile money" value={d.how_money_arrives} onChange={(e) => set({ how_money_arrives: e.target.value })} />
            </Field>
            <div>
              <p className="mb-2 text-[15px] font-medium">How steady is it?</p>
              <div className="flex flex-wrap gap-2">
                {INCOME.map(([v, l]) => (
                  <Chip key={v} active={d.income_pattern === v} onClick={() => set({ income_pattern: d.income_pattern === v ? "" : v })}>
                    {l}
                  </Chip>
                ))}
              </div>
            </div>
            <Field label="How does that feel, week to week?">
              <input className={inputCls} maxLength={2000} value={d.stability} onChange={(e) => set({ stability: e.target.value })} />
            </Field>
          </div>
          <Nav />
        </>
      )}

      {d.step === 3 && (
        <>
          <Title>Who or what do you support?</Title>
          <div className="mt-6 space-y-5">
            <Field label="One per line" hint="I'll treat these as fixed and never suggest cutting them.">
              <textarea className={inputCls} rows={3} placeholder={"School fees for my sister\nRent"} value={d.obligations} onChange={(e) => set({ obligations: e.target.value })} />
            </Field>
            <div>
              <p className="mb-2 text-[15px] font-medium">How do you save today?</p>
              <div className="flex flex-wrap gap-2">
                {SAVING.map((s) => {
                  const on = d.saving_methods.includes(s);
                  return (
                    <Chip key={s} active={on} onClick={() => set({ saving_methods: on ? d.saving_methods.filter((x) => x !== s) : [...d.saving_methods, s] })}>
                      {s}
                    </Chip>
                  );
                })}
              </div>
            </div>
          </div>
          <Nav />
        </>
      )}

      {d.step === 4 && (
        <>
          <Title>What matters most to you?</Title>
          <div className="mt-6 space-y-5">
            <Field label="One per line">
              <textarea className={inputCls} rows={3} placeholder={"Family\nFinishing my course"} value={d.matters_most} onChange={(e) => set({ matters_most: e.target.value })} />
            </Field>
            <Field label="What are you working towards?">
              <textarea className={inputCls} rows={2} value={d.aspirations} onChange={(e) => set({ aspirations: e.target.value })} />
            </Field>
            <Field label="Anything I should never suggest?">
              <textarea className={inputCls} rows={2} placeholder="e.g. Don't tell me to cut what I send home" value={d.sensitivities} onChange={(e) => set({ sensitivities: e.target.value })} />
            </Field>
          </div>
          <Nav />
        </>
      )}

      {d.step === 5 && (
        <>
          <Title>What does encouragement feel like to you?</Title>
          <div className="mt-6 space-y-5">
            <Field label="What helps">
              <textarea className={inputCls} rows={2} placeholder="e.g. Be straight with me, no cheerleading" value={d.encouragement} onChange={(e) => set({ encouragement: e.target.value })} />
            </Field>
            <Field label="What backfires">
              <textarea className={inputCls} rows={2} placeholder="e.g. Too much praise" value={d.backfires} onChange={(e) => set({ backfires: e.target.value })} />
            </Field>
          </div>
          <Nav />
        </>
      )}

      {d.step === 6 && (
        <>
          <Title>When should I stay quiet?</Title>
          <div className="mt-6 grid grid-cols-2 gap-3">
            <Field label="From">
              <input type="time" className={inputCls} value={d.quiet_from} onChange={(e) => set({ quiet_from: e.target.value })} />
            </Field>
            <Field label="Until">
              <input type="time" className={inputCls} value={d.quiet_to} onChange={(e) => set({ quiet_to: e.target.value })} />
            </Field>
          </div>
          <Nav />
        </>
      )}

      {d.step >= steps && (
        <>
          <Eyebrow>Read-back</Eyebrow>
          <Title>Here&apos;s what I understood.</Title>
          <p className="mt-3 text-[17px] text-muted">Change anything before I keep it.</p>
          <div className="mt-6 space-y-3">
            <ReadBack title="Where you live" items={payload.region} onEdit={() => go(1)} />
            <ReadBack title="Money" items={payload.economic_frame} onEdit={() => go(2)} />
            <ReadBack title="What matters" items={payload.values_profile} onEdit={() => go(4)} />
            <ReadBack title="Encouragement" items={payload.emotional_baseline} onEdit={() => go(5)} />
          </div>
          <ErrorText>{error}</ErrorText>
          <div className="mt-8 flex gap-3">
            <Button variant="outline" onClick={() => go(1)}>
              Start over
            </Button>
            <Button className="flex-1" onClick={confirm} disabled={busy}>
              {busy ? "Saving…" : "This is right"}
            </Button>
          </div>
          <div className="mt-4">
            <Note>Skipped questions stay blank. I&apos;ll ask, or stay general, instead of guessing.</Note>
          </div>
        </>
      )}
    </Page>
  );
}

const LABELS: Record<string, string> = {
  country: "Country", area_type: "Kind of place", currency: "Currency", timezone: "Time zone", languages: "Languages",
  notes: "About where you live", income_pattern: "How steady", how_money_arrives: "How money arrives",
  stability: "Week to week", obligations: "You support", saving_methods: "You save with",
  matters_most: "Matters most", sensitivities: "Never suggest", aspirations: "Working towards",
  encouragement: "What helps", backfires: "What backfires", quiet_hours: "Quiet hours",
};

function show(v: unknown): string {
  if (Array.isArray(v)) return v.join(", ");
  if (v && typeof v === "object") return `${(v as any).from}–${(v as any).to}`;
  return String(v).replace(/_/g, " ");
}

function ReadBack({ title, items, onEdit }: { title: string; items: Record<string, unknown>; onEdit: () => void }) {
  const entries = Object.entries(items);
  return (
    <Card>
      <div className="flex items-center justify-between">
        <p className="font-semibold">{title}</p>
        <button className="text-[15px] text-muted underline" onClick={onEdit}>
          Change
        </button>
      </div>
      {entries.length === 0 ? (
        <p className="mt-2 text-[15px] text-muted">Skipped</p>
      ) : (
        <dl className="mt-2 space-y-1.5">
          {entries.map(([k, v]) => (
            <div key={k} className="text-[15px]">
              <dt className="inline text-muted">{LABELS[k] ?? k}: </dt>
              <dd className="inline">{show(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}

export default function OnboardingPage() {
  return (
    <AuthGate nav={false} allowNotOnboarded>
      <Onboarding />
    </AuthGate>
  );
}
