"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ConsoleError } from "@/lib/types";
import {
  WAKE_FAILED,
  WAKE_HINT_MS,
  isRetryable,
  markAsleep,
  waitForBackend,
  wakeState,
} from "@/lib/wake";

/**
 * One way to load one same-origin console resource.
 *
 * Every screen loads through this so that loading, empty and failure look the same everywhere. The
 * browser only ever names a `/api/console/*` path: the API's address stays on the server.
 *
 * Until the API has answered its health check once on this page, a resource asks the page's one
 * shared watcher (`lib/wake.ts`) first. A sleeping free-tier instance then receives one patient
 * request that wakes it, rather than a burst of short reads that are each abandoned before it
 * starts. If the check takes more than a few seconds the resource shows `waking`; once it answers,
 * the resource reads its data. A later read that fails as if the API had gone back to sleep waits
 * the same way. Every wait is bounded; past it, the real failure is shown.
 */

export type Resource<T> =
  | { status: "loading" }
  | { status: "waking" }
  | { status: "ready"; data: T; loadedAt: Date }
  | { status: "failed"; error: ConsoleError };

const GENERIC_FAILURE: ConsoleError = {
  kind: "unreachable",
  message: "The console could not reach its own server. Check the network and reload.",
};

function readError(payload: unknown): ConsoleError {
  if (typeof payload === "object" && payload !== null && "error" in payload) {
    const error = (payload as { error: unknown }).error;
    if (typeof error === "object" && error !== null) {
      const shaped = error as Record<string, unknown>;
      if (typeof shaped.message === "string") {
        return {
          kind: (shaped.kind as ConsoleError["kind"]) ?? "upstream",
          message: shaped.message,
          retryable: shaped.retryable === true,
        };
      }
    }
  }
  return GENERIC_FAILURE;
}

type Attempt<T> = { ok: true; data: T } | { ok: false; error: ConsoleError };

async function attempt<T>(path: string): Promise<Attempt<T>> {
  try {
    const response = await fetch(path, { cache: "no-store" });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) return { ok: false, error: readError(payload) };
    return { ok: true, data: payload as T };
  } catch {
    return { ok: false, error: GENERIC_FAILURE };
  }
}

export function useConsoleResource<T>(path: string): {
  resource: Resource<T>;
  reload: () => void;
  reloading: boolean;
} {
  const [resource, setResource] = useState<Resource<T>>({ status: "loading" });
  const [reloading, setReloading] = useState(false);
  const generation = useRef(0);

  const load = useCallback(
    async (isReload: boolean) => {
      const token = ++generation.current;
      if (isReload) {
        setReloading(true);
      } else {
        setResource({ status: "loading" });
      }
      try {
        if (wakeState().phase !== "awake") {
          const notice = setTimeout(() => {
            if (token === generation.current) {
              setResource({ status: "waking" });
            }
          }, WAKE_HINT_MS);
          const outcome = await waitForBackend();
          clearTimeout(notice);
          if (token !== generation.current) {
            return;
          }
          if (outcome === "gave-up") {
            setResource({ status: "failed", error: WAKE_FAILED });
            return;
          }
        }
        let result = await attempt<T>(path);
        if (token !== generation.current) {
          return;
        }
        if (!result.ok && isRetryable(result.error)) {
          setResource({ status: "waking" });
          markAsleep();
          const outcome = await waitForBackend();
          if (token !== generation.current) {
            return;
          }
          if (outcome === "awake") {
            result = await attempt<T>(path);
            if (token !== generation.current) {
              return;
            }
          } else if (outcome === "gave-up") {
            result = { ok: false, error: WAKE_FAILED };
          }
        }
        if (!result.ok) {
          setResource({ status: "failed", error: result.error });
          return;
        }
        setResource({ status: "ready", data: result.data, loadedAt: new Date() });
      } finally {
        if (token === generation.current) {
          setReloading(false);
        }
      }
    },
    [path],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const reload = useCallback(() => {
    void load(true);
  }, [load]);

  return { resource, reload, reloading };
}
