"use client";

import type { ReactNode } from "react";

import { ApproachMatrix } from "@/components/ApproachMatrix";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/panels";
import { RefreshBar } from "@/components/RefreshBar";
import { StatsStrip } from "@/components/StatsStrip";
import { formatDate } from "@/lib/states";
import type { PlacementView } from "@/lib/types";
import { useConsoleResource } from "@/lib/use-console";

function PlacementPanel({ placement }: { placement: PlacementView }): ReactNode {
  const overdue = placement.approaches.filter((approach) => approach.follow_up_overdue).length;
  const blocked = placement.approaches.filter((approach) => approach.state === "blocked").length;

  return (
    <section className="panel" data-testid="placement-panel">
      <header className="panel-head flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-2.5">
        <h2 className="font-semibold">
          <span className="mono text-accent">{placement.reference}</span>
          <span className="text-dim mx-2">·</span>
          {placement.insured_name}
        </h2>
        <span className="text-muted">{placement.class_of_business}</span>
        <span className="text-dim">handler {placement.handler}</span>
        <span className="text-dim">inception {formatDate(placement.inception_on)}</span>
        <span className="ml-auto flex items-center gap-3 tabular-nums">
          <span className="text-muted">
            {placement.approaches.length}{" "}
            {placement.approaches.length === 1 ? "carrier" : "carriers"}
          </span>
          {overdue > 0 ? (
            <span className="font-semibold text-[#f2b756]">{overdue} overdue</span>
          ) : null}
          {blocked > 0 ? (
            <span className="font-semibold text-[#ff8f9b]">{blocked} blocked</span>
          ) : null}
        </span>
      </header>
      <ApproachMatrix approaches={placement.approaches} />
    </section>
  );
}

/** Pure, so the empty board and a populated one can both be asserted without a network. */
export function BoardView({ placements }: { placements: PlacementView[] }): ReactNode {
  if (placements.length === 0) {
    return (
      <EmptyPanel title="No placements on the desk.">
        The API answered, and it has nothing to show. Seed the demonstration data with{" "}
        <code className="mono text-text">make demo</code>, or wait for a placement to be opened.
      </EmptyPanel>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {placements.map((placement) => (
        <PlacementPanel key={placement.id} placement={placement} />
      ))}
    </div>
  );
}

export function Board(): ReactNode {
  const { resource, reload, reloading } = useConsoleResource<PlacementView[]>(
    "/api/console/placements",
  );

  return (
    <div className="flex flex-col gap-4">
      <StatsStrip />
      <RefreshBar
        loadedAt={resource.status === "ready" ? resource.loadedAt : null}
        reloading={reloading}
        onReload={reload}
      />
      {resource.status === "loading" ? <LoadingPanel label="the board" /> : null}
      {resource.status === "failed" ? <ErrorPanel error={resource.error} onRetry={reload} /> : null}
      {resource.status === "ready" ? <BoardView placements={resource.data} /> : null}
    </div>
  );
}
