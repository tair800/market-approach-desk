"use client";

import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

import type { ConsoleError } from "@/lib/types";
import { WAKE_HINT_MS, subscribeWake, wakeState } from "@/lib/wake";

/**
 * The things a screen can be when it is not showing data.
 *
 * Shared so that an outage looks the same on every screen, and so that no screen invents another
 * way of saying "nothing here". Waking is its own state: a free-tier API starting up is neither an
 * empty desk nor a failure, and the console says which one it is looking at.
 */

/** Seconds since `since`, ticking once a second while mounted. */
function useSecondsSince(since: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, []);
  return since === null ? 0 : Math.max(0, Math.floor((now - since) / 1000));
}

export function LoadingPanel({ label }: { label: string }): ReactNode {
  const [mountedAt] = useState(() => Date.now());
  const seconds = useSecondsSince(mountedAt);
  return (
    <div
      className="panel px-4 py-6 text-muted"
      role="status"
      aria-live="polite"
      data-testid="loading-panel"
    >
      Loading {label}…
      {seconds * 1000 >= WAKE_HINT_MS ? (
        <p className="text-dim mt-1">
          If the public demo has been idle, its API may be waking up. That can take up to about a
          minute.
        </p>
      ) : null}
    </div>
  );
}

/**
 * The API is starting after free-tier sleep, and the console is waiting for it automatically.
 *
 * Says what is happening, how long it has taken, and that nothing needs to be done. It does not
 * show a retry button: the wait continues by itself, and a button would suggest the visitor has to
 * do something to make the demo work.
 */
export function WakingPanel({ label }: { label: string }): ReactNode {
  const wake = useSyncExternalStore(subscribeWake, wakeState, wakeState);
  const seconds = useSecondsSince(wake.startedAt);
  return (
    <div
      className="panel px-4 py-5"
      role="status"
      aria-live="polite"
      data-testid="waking-panel"
    >
      <p className="font-semibold text-text">Starting the public demo…</p>
      <p className="mt-1 max-w-2xl text-muted">
        The demo&apos;s API runs on a free tier that sleeps after about fifteen minutes without
        visitors and can take up to a minute to wake. {label} will load here as soon as it answers —
        there is nothing you need to do.
      </p>
      <p className="text-dim mt-2 tabular-nums">Waiting for the API · {seconds}s</p>
    </div>
  );
}

export function EmptyPanel({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}): ReactNode {
  return (
    <div className="panel px-4 py-6" data-testid="empty-panel">
      <p className="font-semibold text-text">{title}</p>
      {children ? <div className="mt-1 max-w-2xl text-muted">{children}</div> : null}
    </div>
  );
}

const REMEDY: Record<ConsoleError["kind"], string> = {
  unconfigured: "Set APPROACH_API_BASE_URL in the console environment and reload.",
  unreachable: "Start the API, or check that the console is pointed at the right address.",
  timeout:
    "Free-tier hosting occasionally takes longer than usual to answer. Try again in a minute.",
  upstream: "The API answered with an error. Its logs will say why.",
  malformed: "The address answered, but not with this API's JSON. Check the base URL.",
};

/**
 * A failure an operator can act on.
 *
 * No status code as a headline, no upstream body, no stack. The route handler has already refused
 * to forward the API's own error text; this renders the sentence it produced instead.
 */
export function ErrorPanel({
  error,
  onRetry,
}: {
  error: ConsoleError;
  onRetry?: () => void;
}): ReactNode {
  return (
    <div className="panel px-4 py-5" role="alert" data-testid="error-panel">
      <p className="font-semibold text-text">The console cannot show this right now.</p>
      <p className="mt-1 text-muted">{error.message}</p>
      <p className="mt-1 text-dim">{REMEDY[error.kind] ?? REMEDY.upstream}</p>
      {onRetry ? (
        <button type="button" className="btn mt-3" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}
