"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getSession } from "@/lib/api";
import { startOutboxSync } from "@/lib/offline";
import { BottomNav } from "./ui";

export type Me = {
  user_id: string;
  email: string | null;
  display_name: string | null;
  privacy_mode: "cloud" | "local";
  onboarding_state: string;
  app_name: string;
  providers: { cloud_llm: string | null; cloud_embeddings: string | null; local_available: boolean; chat_ready: boolean };
};

const MeCtx = createContext<{ me: Me | null; reload: () => Promise<void> }>({ me: null, reload: async () => {} });
export const useMe = () => useContext(MeCtx);

/** Wraps every signed-in screen: no session -> /login, not onboarded -> /onboarding. */
export function AuthGate({ children, nav = true, allowNotOnboarded = false }: { children: ReactNode; nav?: boolean; allowNotOnboarded?: boolean }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const m = await api<Me>("/me");
      setMe(m);
      if (m.onboarding_state !== "complete" && !allowNotOnboarded) router.replace("/onboarding/");
    } catch (e: any) {
      if (e?.status === 401) router.replace("/login/");
      else setFailed(e?.message ?? "Could not load");
    }
  }, [router, allowNotOnboarded]);

  useEffect(() => {
    if (!getSession()) {
      router.replace("/login/");
      return;
    }
    void reload();
    startOutboxSync();
  }, [reload, router]);

  if (failed)
    return (
      <div className="p-8 text-center text-muted">
        <p>{failed}</p>
        <button className="mt-4 underline" onClick={() => location.reload()}>
          Try again
        </button>
      </div>
    );
  if (!me) return <div className="p-8 text-center text-muted">Loading…</div>;
  return (
    <MeCtx.Provider value={{ me, reload }}>
      {children}
      {nav && <BottomNav />}
    </MeCtx.Provider>
  );
}
