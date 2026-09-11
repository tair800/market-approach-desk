import type { ReactNode } from "react";

import type { ConsoleError } from "@/lib/types";

/**
 * The three things a screen can be when it is not showing data.
 *
 * Shared so that an outage looks the same on every screen, and so that no screen invents a fourth
 * way of saying "nothing here".
 */

export function LoadingPanel({ label }: { label: string }): ReactNode {
  return (
    <div
      className="panel px-4 py-6 text-muted"
      role="status"
      aria-live="polite"
      data-testid="loading-panel"
    >
      Loading {label}…
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
  timeout: "The API is up but slow to answer. Try again shortly.",
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
