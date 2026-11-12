"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AuthGate, useMe } from "@/components/AuthGate";
import { Button, Card, ErrorText, Eyebrow, Field, inputCls, Note, Page, Title } from "@/components/ui";
import { api, signOut } from "@/lib/api";
import { sendOrQueue } from "@/lib/offline";

type Fact = { value: any; source: string; stated_at: string };
type Ctx = Record<"region" | "economic_frame" | "values_profile" | "emotional_baseline", Record<string, Fact>> & { version: number };

const SECTIONS: [keyof Omit<Ctx, "version">, string, [string, string, "text" | "list"][]][] = [
  ["region", "Where you live", [["country", "Country code", "text"], ["area_type", "Kind of place", "text"], ["currency", "Currency", "text"], ["timezone", "Time zone", "text"], ["languages", "Languages", "list"], ["notes", "About where you live", "text"]]],
  ["economic_frame", "Money", [["income_pattern", "How steady", "text"], ["how_money_arrives", "How money arrives", "text"], ["stability", "Week to week", "text"], ["obligations", "Who or what you support", "list"], ["saving_methods", "How you save", "list"]]],
  ["values_profile", "What matters", [["matters_most", "Matters most", "list"], ["non_negotiables", "Non-negotiables", "list"], ["sensitivities", "Never suggest", "list"], ["aspirations", "Working towards", "list"]]],
  ["emotional_baseline", "Encouragement", [["encouragement", "What helps", "text"], ["backfires", "What backfires", "text"], ["preferred_tone", "Tone", "text"], ["checkin_times", "Check-in times", "list"]]],
];
const SOURCE: Record<string, string> = { onboarding: "you said at the start", user_edit: "you edited", accepted_proposal: "you added from a suggestion" };

function show(v: any) {
  if (Array.isArray(v)) return v.join(", ");
  if (v && typeof v === "object") return `${v.from}–${v.to}`;
  return String(v).replace(/_/g, " ");
}

function MePage() {
  const { me, reload } = useMe();
  const router = useRouter();
  const [ctx, setCtx] = useState<Ctx | null>(null);
  const [versions, setVersions] = useState<any[]>([]);
  const [journal, setJournal] = useState<any[]>([]);
  const [entry, setEntry] = useState("");
  const [note, setNote] = useState("");
  const [showVersions, setShowVersions] = useState(false);

  const load = useCallback(async () => {
    const [c, v, j] = await Promise.all([api<Ctx>("/context"), api<any[]>("/context/versions"), api<any[]>("/memories?kind=journal&limit=20")]);
    setCtx(c);
    setVersions(v);
    setJournal(j);
  }, []);
  useEffect(() => {
    void load().catch(() => {});
  }, [load]);

  async function saveJournal() {
    const content = entry.trim();
    if (!content) return;
    const sent = await sendOrQueue("/memories", "POST", { content, kind: "journal" }, "Journal entry");
    setEntry("");
    setNote(sent ? "Saved." : "Saved on this phone. It will sync when you're back online.");
    if (sent) void load();
  }

  async function exportAll() {
    const data = await api("/account/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `kin-export-${new Date().toISOString().slice(0, 10)}.json` });
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Page>
      <Eyebrow>{me?.email}</Eyebrow>
      <Title>What I know about you.</Title>
      <p className="mt-3 text-[17px] text-muted">Only what you told me. Change or remove anything.</p>

      <div className="mt-6 space-y-4">
        {ctx &&
          SECTIONS.map(([key, title, fields]) => (
            <Card key={key}>
              <p className="text-[20px] font-semibold">{title}</p>
              <div className="mt-3 divide-y divide-line">
                {fields.map(([f, label, kind]) => (
                  <FactRow key={f} section={key} field={f} label={label} kind={kind} fact={ctx[key]?.[f]} onSaved={load} />
                ))}
              </div>
            </Card>
          ))}
      </div>

      <section className="mt-6">
        <button className="text-[15px] text-muted underline" onClick={() => setShowVersions((v) => !v)}>
          {showVersions ? "Hide history" : `Change history (${versions.length})`}
        </button>
        {showVersions && (
          <Card className="mt-3">
            <ul className="divide-y divide-line">
              {versions.map((v, i) => (
                <li key={v.version} className="flex items-center justify-between py-3">
                  <div>
                    <p className="font-medium">Version {v.version}</p>
                    <p className="text-sm text-muted">
                      {v.change_source.replace("_", " ")} · {new Date(v.created_at).toLocaleString()}
                    </p>
                  </div>
                  {i > 0 && (
                    <Button
                      variant="outline"
                      className="min-h-10 text-[15px]"
                      onClick={async () => {
                        await api(`/context/revert/${v.version}`, { method: "POST" });
                        void load();
                      }}
                    >
                      Restore
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>

      <section className="mt-10 space-y-4">
        <Eyebrow>Journal</Eyebrow>
        <Card>
          <textarea className={inputCls} rows={4} maxLength={8000} placeholder="What's on your mind today?" value={entry} onChange={(e) => setEntry(e.target.value)} />
          <div className="mt-3 flex items-center justify-between gap-3">
            <Note>{note || "Kin may suggest adding lasting facts to your profile. You decide."}</Note>
            <Button disabled={!entry.trim()} onClick={saveJournal}>
              Save
            </Button>
          </div>
        </Card>
        {journal.map((j) => (
          <Card key={j.id}>
            <p className="text-sm text-muted">{new Date(j.created_at).toLocaleString()}</p>
            <p className="mt-1 whitespace-pre-line text-[16px]">{j.content}</p>
            <button
              className="mt-2 text-sm text-muted underline"
              onClick={async () => {
                await api(`/memories/${j.id}`, { method: "DELETE" });
                void load();
              }}
            >
              Delete
            </button>
          </Card>
        ))}
      </section>

      <section className="mt-10 space-y-4">
        <Eyebrow>Privacy</Eyebrow>
        <Card>
          <p className="text-[18px] font-medium">Where your words go</p>
          <p className="mt-2 text-[15px] text-muted">
            {me?.privacy_mode === "local"
              ? "Local mode: nothing you write is sent to an outside AI service."
              : `Cloud mode: chat goes to ${me?.providers.cloud_llm ?? "no outside service"}${me?.providers.cloud_embeddings ? `; journal search uses ${me.providers.cloud_embeddings}` : ""}.`}
          </p>
          {!me?.providers.local_available && me?.privacy_mode !== "local" && (
            <p className="mt-2 text-sm text-muted">This server has no local model, so in local mode the Think tab won&apos;t answer.</p>
          )}
          <Button
            variant="outline"
            className="mt-4 w-full"
            onClick={async () => {
              await api("/me", { method: "PATCH", json: { privacy_mode: me?.privacy_mode === "local" ? "cloud" : "local" } });
              await reload();
            }}
          >
            Switch to {me?.privacy_mode === "local" ? "cloud" : "local"} mode
          </Button>
        </Card>
        <Card>
          <p className="text-[18px] font-medium">Your data</p>
          <div className="mt-4 grid gap-3">
            <Button variant="outline" onClick={exportAll}>
              Download everything (JSON)
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                signOut();
                router.replace("/login/");
              }}
            >
              Sign out
            </Button>
          </div>
          <DeleteAccount onDeleted={() => { signOut(); router.replace("/login/"); }} />
        </Card>
      </section>
    </Page>
  );
}

function FactRow({ section, field, label, kind, fact, onSaved }: { section: string; field: string; label: string; kind: "text" | "list"; fact?: Fact; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");

  async function save(v: any) {
    setError("");
    try {
      await api("/context", { method: "PATCH", json: { [section]: { [field]: v } } });
      setEditing(false);
      onSaved();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-muted">{label}</p>
          {!editing && <p className="text-[16px]">{fact ? show(fact.value) : <span className="text-muted">Not shared</span>}</p>}
          {!editing && fact && <p className="text-xs text-muted">{SOURCE[fact.source] ?? fact.source}</p>}
        </div>
        {!editing && (
          <button
            className="shrink-0 text-[15px] text-muted underline"
            onClick={() => {
              setValue(fact ? (Array.isArray(fact.value) ? fact.value.join("\n") : show(fact.value)) : "");
              setEditing(true);
            }}
          >
            {fact ? "Change" : "Add"}
          </button>
        )}
      </div>
      {editing && (
        <div className="mt-2 space-y-2">
          {kind === "list" ? (
            <textarea className={inputCls} rows={3} placeholder="One per line" value={value} onChange={(e) => setValue(e.target.value)} />
          ) : (
            <input className={inputCls} value={value} onChange={(e) => setValue(e.target.value)} />
          )}
          <ErrorText>{error}</ErrorText>
          <div className="flex gap-2">
            <Button className="min-h-10 text-[15px]" onClick={() => save(kind === "list" ? value.split("\n").map((x) => x.trim()).filter(Boolean) : value.trim())}>
              Save
            </Button>
            {fact && (
              <Button variant="outline" className="min-h-10 text-[15px]" onClick={() => save(null)}>
                Remove
              </Button>
            )}
            <Button variant="ghost" className="min-h-10 text-[15px]" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function DeleteAccount({ onDeleted }: { onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const [error, setError] = useState("");
  if (!open)
    return (
      <button className="mt-5 text-[15px] text-danger underline" onClick={() => setOpen(true)}>
        Delete my account and everything in it
      </button>
    );
  return (
    <div className="mt-5 space-y-3">
      <Field label='Type "delete everything" to confirm' hint="This cannot be undone.">
        <input className={inputCls} value={phrase} onChange={(e) => setPhrase(e.target.value)} />
      </Field>
      <ErrorText>{error}</ErrorText>
      <Button
        className="w-full !bg-danger !text-white"
        disabled={phrase.trim().toLowerCase() !== "delete everything"}
        onClick={async () => {
          try {
            await api("/account", { method: "DELETE", json: { confirm: phrase } });
            onDeleted();
          } catch (e: any) {
            setError(e.message);
          }
        }}
      >
        Delete everything
      </Button>
    </div>
  );
}

export default function Me() {
  return (
    <AuthGate>
      <MePage />
    </AuthGate>
  );
}
