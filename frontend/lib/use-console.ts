"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ConsoleError } from "@/lib/types";

/**
 * One way to load one same-origin console resource.
 *
 * Every screen loads through this so that loading, empty and failure look the same everywhere. The
 * browser only ever names a `/api/console/*` path: the API's address stays on the server.
 */

export type Resource<T> =
  | { status: "loading" }
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
        };
      }
    }
  }
  return GENERIC_FAILURE;
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
        const response = await fetch(path, { cache: "no-store" });
        const payload: unknown = await response.json().catch(() => null);
        if (token !== generation.current) {
          return;
        }
        if (!response.ok) {
          setResource({ status: "failed", error: readError(payload) });
          return;
        }
        setResource({ status: "ready", data: payload as T, loadedAt: new Date() });
      } catch {
        if (token === generation.current) {
          setResource({ status: "failed", error: GENERIC_FAILURE });
        }
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
