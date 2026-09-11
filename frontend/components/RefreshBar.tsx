"use client";

import type { ReactNode } from "react";

import { formatInstant } from "@/lib/states";

/**
 * Refresh on demand, and say when the data on screen was read.
 *
 * The board does not poll. A desk view that changes under the operator's cursor while they are
 * reading a row is worse than a stale one they can see the age of.
 */
export function RefreshBar({
  loadedAt,
  reloading,
  onReload,
}: {
  loadedAt: Date | null;
  reloading: boolean;
  onReload: () => void;
}): ReactNode {
  return (
    <div className="flex items-center gap-3" data-testid="refresh-bar">
      <button type="button" className="btn" onClick={onReload} disabled={reloading}>
        {reloading ? "Refreshing…" : "Refresh"}
      </button>
      <span className="text-dim">
        {loadedAt ? `read ${formatInstant(loadedAt.toISOString())}` : "not read yet"}
      </span>
    </div>
  );
}
