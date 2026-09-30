"use client";

/**
 * Waiting out a sleeping free-tier API: once per page, for a bounded time, and never by pretending.
 *
 * The public demo's API runs on a free tier that stops after roughly fifteen minutes without
 * traffic and takes up to about a minute to answer again. While it starts, the console's route
 * handlers time out or see its host answer 502/503/504. That is the API waking, not an outage, and
 * rendering it as an error tells a visitor the demo is broken when it is only asleep.
 *
 * So the first retryable failure starts one shared watcher that polls the API's health check
 * through the console's own `/api/console/health` route. Every panel on the page waits on the same
 * watcher, so a page load sends one poll rather than one per panel. It gives up after
 * `WAKE_LIMIT_MS` and says so. It never substitutes data: once it gives up, the ordinary error
 * panel takes over, and a panel only ever shows what the API actually returned.
 */

import type { ConsoleError } from "@/lib/types";

/** The longest the console waits for the API to wake before it reports an honest failure. */
export const WAKE_LIMIT_MS = 120_000;
/** The pause between health checks. Each check is itself bounded by the route's own timeout. */
export const WAKE_POLL_MS = 3_000;
/** After this long, a loading panel says the API may be waking rather than just "loading". */
export const WAKE_HINT_MS = 4_000;

export type WakePhase = "idle" | "waking" | "awake" | "gave-up";

export interface WakeState {
  phase: WakePhase;
  /** When the current wait began, from `Date.now()`; null when nothing is being waited on. */
  startedAt: number | null;
}

/** How the wait ended: the API answered, the limit passed, or waiting cannot help. */
export type WakeOutcome = "awake" | "gave-up" | "not-retryable";

let state: WakeState = { phase: "idle", startedAt: null };
let pending: Promise<WakeOutcome> | null = null;
const listeners = new Set<() => void>();

function publish(next: WakeState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function subscribeWake(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function wakeState(): WakeState {
  return state;
}

export function isRetryable(error: ConsoleError): boolean {
  return error.retryable === true;
}

/** The failure a panel shows once the wake limit has passed. */
export const WAKE_FAILED: ConsoleError = {
  kind: "timeout",
  message: "The public demo's API did not wake within two minutes.",
};

const pause = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function checkHealth(): Promise<"up" | "waking" | "not-retryable"> {
  try {
    const response = await fetch("/api/console/health", { cache: "no-store" });
    if (response.ok) return "up";
    const payload: unknown = await response.json().catch(() => null);
    const error =
      typeof payload === "object" && payload !== null && "error" in payload
        ? ((payload as { error: ConsoleError }).error ?? null)
        : null;
    return error !== null && isRetryable(error) ? "waking" : "not-retryable";
  } catch {
    // The console's own server did not answer: a network blip, which waiting can fix.
    return "waking";
  }
}

/**
 * Wait until the API answers its health check, sharing one watcher across every caller.
 *
 * Resolves `"awake"` as soon as the check passes, `"gave-up"` once `WAKE_LIMIT_MS` has passed, and
 * `"not-retryable"` when the check fails in a way no amount of waiting fixes — no API address
 * configured, for instance — so the caller shows its real error at once.
 */
export function waitForBackend(): Promise<WakeOutcome> {
  if (state.phase === "awake") return Promise.resolve("awake");
  if (pending !== null) return pending;

  const startedAt = Date.now();
  publish({ phase: "waking", startedAt });
  pending = (async (): Promise<WakeOutcome> => {
    try {
      while (Date.now() - startedAt < WAKE_LIMIT_MS) {
        const health = await checkHealth();
        if (health === "up") {
          publish({ phase: "awake", startedAt });
          return "awake";
        }
        if (health === "not-retryable") {
          publish({ phase: "idle", startedAt: null });
          return "not-retryable";
        }
        await pause(WAKE_POLL_MS);
      }
      publish({ phase: "gave-up", startedAt });
      return "gave-up";
    } finally {
      pending = null;
    }
  })();
  return pending;
}

/** A request failed as if the API were asleep again: the next wait starts a fresh window. */
export function markAsleep(): void {
  if (pending === null && state.phase !== "waking") publish({ phase: "idle", startedAt: null });
}

/** Forget any wait in progress. Tests use this so that each starts from a sleeping API. */
export function resetWake(): void {
  pending = null;
  publish({ phase: "idle", startedAt: null });
}
