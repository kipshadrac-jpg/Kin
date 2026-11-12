"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AuthGate, useMe } from "@/components/AuthGate";
import { ScenarioCard, type Scenario } from "@/components/ScenarioCard";
import { Button, Card, Chip, Eyebrow, inputCls, Note, Page, Title } from "@/components/ui";
import { api, chatStream } from "@/lib/api";

type Turn = {
  role: "user" | "assistant";
  content: string;
  context_used?: { ref: string; label: string }[];
  gaps?: string[];
  scenario?: Scenario | null;
  action?: { id: string; preview: string } | null;
  support?: { name: string; contact: string }[];
};

function Think() {
  const { me } = useMe();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [sessions, setSessions] = useState<any[]>([]);
  const [showPast, setShowPast] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, stage]);

  async function send(text?: string) {
    const message = (text ?? input).trim();
    if (!message || stage) return;
    setInput("");
    setError("");
    setTurns((t) => [...t, { role: "user", content: message }]);
    setStage("Checking in");
    try {
      await chatStream(message, sessionId, (ev) => {
        if (ev.type === "status") setStage(ev.label);
        if (ev.type === "error") setError(ev.message);
        if (ev.type === "message") {
          setSessionId(ev.session_id);
          setTurns((t) => [
            ...t,
            { role: "assistant", content: ev.reply, context_used: ev.context_used, gaps: ev.gaps, scenario: ev.scenario, action: ev.action, support: ev.support },
          ]);
        }
      });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setStage(null);
    }
  }

  async function openPast() {
    setShowPast((v) => !v);
    if (!showPast) setSessions(await api<any[]>("/chat/sessions").catch(() => []));
  }

  async function loadSession(id: string) {
    const s = await api<any>(`/chat/sessions/${id}`);
    setSessionId(id);
    setTurns(s.transcript.map((m: any) => ({ role: m.role, content: m.content, context_used: m.context_used })));
    setShowPast(false);
  }

  return (
    <Page>
      <div className="flex items-start justify-between">
        <div>
          <Eyebrow>Think it through</Eyebrow>
          <Title>{turns.length ? "Thinking together." : "What's on your mind?"}</Title>
        </div>
        <div className="flex gap-3 pt-2 text-[15px] text-muted">
          {turns.length > 0 && (
            <button className="underline" onClick={() => { setTurns([]); setSessionId(null); }}>
              New
            </button>
          )}
          <button className="underline" onClick={openPast}>
            Past
          </button>
        </div>
      </div>

      {showPast && (
        <Card className="mt-4">
          {sessions.length === 0 ? (
            <Note>No past conversations yet.</Note>
          ) : (
            <ul className="divide-y divide-line">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button className="w-full py-3 text-left" onClick={() => loadSession(s.id)}>
                    <p className="font-medium">{s.topic}</p>
                    {s.outcome_summary && <p className="text-sm text-muted">{s.outcome_summary}</p>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {me && !me.providers.chat_ready && (
        <Card tone="soft" className="mt-6">
          <Note>The thinking part of Kin isn&apos;t set up on this server yet (no model key). Everything else works.</Note>
        </Card>
      )}

      {turns.length === 0 && (
        <div className="mt-6 flex flex-wrap gap-2">
          {[
            "What if I set aside 300 a week for 12 weeks?",
            "I want to start exercising but I'm always tired",
            "Help me plan a calmer week",
          ].map((s) => (
            <Chip key={s} onClick={() => send(s)}>
              {s}
            </Chip>
          ))}
        </div>
      )}

      <div className="mt-6 space-y-5" aria-live="polite">
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="ml-10 rounded-[24px] rounded-br-md bg-ink px-5 py-3.5 text-[17px] text-on-ink">
              {t.content}
            </div>
          ) : (
            <div key={i} className="space-y-3">
              <Card>
                <p className="whitespace-pre-line text-[17px] leading-relaxed">{t.content}</p>
                {!!t.support?.length && (
                  <ul className="mt-4 space-y-2">
                    {t.support.map((s) => (
                      <li key={s.name} className="rounded-2xl bg-soft px-4 py-3">
                        <p className="font-medium">{s.name}</p>
                        <p className="text-[18px] tabular-nums">{s.contact}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              {t.scenario && <ScenarioCard s={t.scenario} onKeepThinking={() => document.querySelector("textarea")?.focus()} />}
              {t.action && (
                <Card tone="soft">
                  <p className="text-[15px] text-muted">Waiting for your OK</p>
                  <p className="mt-1 text-[18px] font-medium">{t.action.preview}</p>
                  <Link href="/" className="mt-2 inline-block text-[15px] underline">
                    Review on Today
                  </Link>
                </Card>
              )}
              {!!t.context_used?.length && (
                <details className="px-1">
                  <summary className="cursor-pointer text-[15px] text-muted">What I used about you</summary>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {t.context_used.map((c) => (
                      <Chip key={c.ref}>{c.label}</Chip>
                    ))}
                  </div>
                </details>
              )}
              {!!t.gaps?.length && <p className="px-1 text-sm text-muted">Not in your profile yet: {t.gaps.join(", ")}.</p>}
            </div>
          ),
        )}
        {stage && <p className="px-1 text-[15px] text-muted">{stage}…</p>}
        {error && (
          <p role="alert" className="px-1 text-[15px] text-danger">
            {error}
          </p>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="fixed inset-x-0 bottom-[84px] z-10 mx-auto max-w-xl px-4"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <div className="flex items-end gap-2 rounded-[24px] bg-surface p-2 shadow-[0_2px_16px_rgba(0,0,0,.06)]">
          <textarea
            className={`${inputCls} min-h-12 resize-none border-0`}
            rows={1}
            maxLength={4000}
            placeholder="Think out loud. Nothing is saved as a plan unless you say so."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <Button type="submit" disabled={!input.trim() || !!stage} className="shrink-0">
            Send
          </Button>
        </div>
      </form>
      <div className="h-24" />
    </Page>
  );
}

export default function ThinkPage() {
  return (
    <AuthGate>
      <Think />
    </AuthGate>
  );
}
