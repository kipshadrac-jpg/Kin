"use client";

/**
 * Talks to two things on the same domain:
 *   /auth/v1  -> Supabase GoTrue (sign up, sign in, refresh)
 *   /api/v1   -> the Kin API
 * Tokens live in localStorage on this device only.
 */

const AUTH = "/auth/v1";
const API = "/api/v1";
const KEY = "kin.session";

export type Session = { access_token: string; refresh_token: string; expires_at: number; email?: string };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

function read(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function write(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: session lasts for this tab only */
  }
}

export function getSession(): Session | null {
  return read();
}

function fromAuthResponse(body: any): Session {
  return {
    access_token: body.access_token,
    refresh_token: body.refresh_token,
    expires_at: body.expires_at ?? Math.floor(Date.now() / 1000) + (body.expires_in ?? 3600),
    email: body.user?.email,
  };
}

async function authCall(path: string, payload: unknown): Promise<any> {
  let r: Response;
  try {
    r = await fetch(AUTH + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError(0, "offline", "You seem to be offline.");
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = body.msg || body.error_description || body.message || "That didn't work. Check and try again.";
    throw new ApiError(r.status, body.error_code || "auth_error", msg);
  }
  return body;
}

export async function signUp(email: string, password: string): Promise<Session> {
  const body = await authCall("/signup", { email, password });
  if (!body.access_token) throw new ApiError(400, "confirm_email", "Check your email to confirm your account, then sign in.");
  const s = fromAuthResponse(body);
  write(s);
  return s;
}

export async function signIn(email: string, password: string): Promise<Session> {
  const s = fromAuthResponse(await authCall("/token?grant_type=password", { email, password }));
  write(s);
  return s;
}

let refreshing: Promise<Session | null> | null = null;

async function refresh(): Promise<Session | null> {
  const s = read();
  if (!s) return null;
  if (!refreshing) {
    refreshing = authCall("/token?grant_type=refresh_token", { refresh_token: s.refresh_token })
      .then((b) => {
        const ns = { ...fromAuthResponse(b), email: s.email };
        write(ns);
        return ns;
      })
      .catch((e: ApiError) => {
        if (e.status >= 400 && e.status < 500) write(null);
        return null;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

async function token(): Promise<string | null> {
  let s = read();
  if (!s) return null;
  if (s.expires_at - 60 < Date.now() / 1000) s = await refresh();
  return s?.access_token ?? null;
}

export function signOut() {
  const s = read();
  write(null);
  if (s) fetch(AUTH + "/logout", { method: "POST", headers: { Authorization: `Bearer ${s.access_token}` } }).catch(() => {});
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const t = await token();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (t) headers.Authorization = `Bearer ${t}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  let r: Response;
  try {
    r = await fetch(API + path, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "offline", "You seem to be offline.");
  }
  if (r.status === 401 && t) {
    const ns = await refresh();
    if (ns) return api<T>(path, init);
    if (typeof window !== "undefined") window.location.href = "/login/";
  }
  if (r.status === 204) return undefined as T;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = data?.error ?? {};
    throw new ApiError(r.status, e.code ?? "error", e.message ?? "Something went wrong", e.details);
  }
  return data as T;
}

/** POST /chat as a Server-Sent Event stream. */
export async function chatStream(
  message: string,
  sessionId: string | null,
  onEvent: (ev: any) => void,
): Promise<void> {
  const t = await token();
  let r: Response;
  try {
    r = await fetch(API + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${t}` },
      body: JSON.stringify({ message, session_id: sessionId, stream: true }),
    });
  } catch {
    throw new ApiError(0, "offline", "You seem to be offline.");
  }
  if (!r.ok || !r.body) {
    const data = await r.json().catch(() => ({}));
    throw new ApiError(r.status, data?.error?.code ?? "error", data?.error?.message ?? "Something went wrong");
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}
