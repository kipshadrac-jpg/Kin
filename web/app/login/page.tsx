"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ErrorText, Field, inputCls, Note, Page, Title } from "@/components/ui";
import { signIn, signUp } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "up") await signUp(email.trim(), password);
      else await signIn(email.trim(), password);
      router.replace("/");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page>
      <p className="text-[15px] text-muted">{process.env.NEXT_PUBLIC_APP_NAME || "Kin"}</p>
      <Title>{mode === "in" ? "Welcome back." : "Let's get you set up."}</Title>
      <p className="mt-3 text-[17px] text-muted">A companion for habits, money decisions and daily life — built around what you tell it, nothing else.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        <Field label="Email">
          <input className={inputCls} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" hint={mode === "up" ? "At least 8 characters." : undefined}>
          <input
            className={inputCls}
            type="password"
            minLength={mode === "up" ? 8 : undefined}
            autoComplete={mode === "up" ? "new-password" : "current-password"}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <ErrorText>{error}</ErrorText>
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "One moment…" : mode === "in" ? "Sign in" : "Create account"}
        </Button>
      </form>
      <button className="mt-6 w-full text-center text-[16px] text-muted underline" onClick={() => setMode(mode === "in" ? "up" : "in")}>
        {mode === "in" ? "New here? Create an account" : "Already have an account? Sign in"}
      </button>
      <div className="mt-10">
        <Note>Your answers stay yours: you can see, change, export or delete everything at any time.</Note>
      </div>
    </Page>
  );
}
