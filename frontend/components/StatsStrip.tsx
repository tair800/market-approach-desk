"use client";

import type { ReactNode } from "react";

import { approachStateBadge, knownApproachStates } from "@/lib/states";
import type { StatsView } from "@/lib/types";
import { useConsoleResource } from "@/lib/use-console";

/**
 * Counts across the whole desk, computed in the database.
 *
 * It loads separately from the board on purpose: a failed count must not blank the placements. A
 * broker can work from the board without the totals; they cannot work from the totals alone.
 */

export function StatsStripView({ stats }: { stats: StatsView }): ReactNode {
  const states = knownApproachStates().filter((state) => (stats.by_state[state] ?? 0) > 0);
  const total = Object.values(stats.by_state).reduce((sum, count) => sum + count, 0);

  return (
    <div
      className="panel flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5"
      data-testid="stats-strip"
    >
      <span className="text-dim text-[10px] font-semibold tracking-[0.08em] uppercase">
        Approaches
      </span>
      <span className="tabular-nums">
        <span className="font-semibold">{total}</span> <span className="text-muted">total</span>
      </span>
      {states.map((state) => (
        <span key={state} className="inline-flex items-center gap-1.5 tabular-nums">
          <span className={approachStateBadge(state).className}>
            {approachStateBadge(state).label}
          </span>
          <span className="font-semibold">{stats.by_state[state]}</span>
        </span>
      ))}
      <span className="tabular-nums" title="Rows in the attempt log, including retries.">
        <span className="font-semibold">{stats.attempts}</span>{" "}
        <span className="text-muted">send attempts</span>
      </span>
    </div>
  );
}

export function StatsStrip(): ReactNode {
  const { resource } = useConsoleResource<StatsView>("/api/console/stats");

  if (resource.status === "loading") {
    return <div className="panel px-4 py-2.5 text-dim">Counting approaches…</div>;
  }
  if (resource.status === "failed") {
    return <div className="panel px-4 py-2.5 text-dim">Counts unavailable.</div>;
  }
  return <StatsStripView stats={resource.data} />;
}
