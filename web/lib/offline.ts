"use client";

/**
 * Offline-tolerant writes (principle 9): habit check-ins and journal entries
 * are saved on the phone first and sent when the connection comes back.
 */
import { api, ApiError } from "./api";

const KEY = "kin.outbox";

export type Outgoing = { id: string; path: string; method: string; json: unknown; label: string; at: number };

function load(): Outgoing[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "[]");
  } catch {
    return [];
  }
}

function save(items: Outgoing[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    /* storage full or blocked */
  }
  window.dispatchEvent(new Event("kin-outbox"));
}

export function pendingCount(): number {
  return load().length;
}

/** Try now; if offline, keep it and send later. Returns true if sent now. */
export async function sendOrQueue(path: string, method: string, json: unknown, label: string): Promise<boolean> {
  try {
    await api(path, { method, json });
    return true;
  } catch (e) {
    if (e instanceof ApiError && e.code === "offline") {
      save([...load(), { id: crypto.randomUUID(), path, method, json, label, at: Date.now() }]);
      return false;
    }
    throw e;
  }
}

let flushing = false;

export async function flushOutbox(): Promise<number> {
  if (flushing) return 0;
  flushing = true;
  let sent = 0;
  try {
    for (const item of load()) {
      try {
        await api(item.path, { method: item.method, json: item.json });
      } catch (e) {
        if (e instanceof ApiError && e.code === "offline") break;
        // Server refused it (e.g. habit deleted): drop it rather than retry forever.
      }
      save(load().filter((x) => x.id !== item.id));
      sent++;
    }
  } finally {
    flushing = false;
  }
  return sent;
}

export function startOutboxSync() {
  window.addEventListener("online", () => void flushOutbox());
  void flushOutbox();
}
