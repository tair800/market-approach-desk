"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ConsoleError } from "@/lib/types";
import { WAKE_FAILED, isRetryable, markAsleep, waitForBackend } from "@/lib/wake";

/**
 * One way to load one same-origin console resource.
 *
 * Every screen loads through this so that loading, empty and failure look the same everywhere. The
 * browser only ever names a `/api/console/*` path: the API's address stays on the server.
 *
 * A failure that means "the free-tier API is still waking" is not shown as a failure. The resource
 * goes to `waking`, waits on the page's one shared watcher (`lib/wake.ts`), and asks again once the
 * API answers its health check. The wait is bounded; past it, the real failure is shown.
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
