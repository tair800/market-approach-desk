"use client";

import type { ReactNode } from "react";

import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/panels";
import { RefreshBar } from "@/components/RefreshBar";
import { formatInstant } from "@/lib/states";
import type { AuditView } from "@/lib/types";
import { useConsoleResource } from "@/lib/use-console";

/**
 * The append-only trail, newest first.
 *
 * The identity column is the point of the screen: it answers "who approached this carrier, when"
 * for one `placement/market/stage`, which is the question asked after a market is blocked.
 */

export function AuditTrailView({ events }: { events: AuditView[] }): ReactNode {
  if (events.length === 0) {
    return (
      <EmptyPanel title="Nothing recorded yet.">
        The trail fills as the scheduler claims, sends and classifies. It is append-only: no entry
        here is ever edited or removed.
      </EmptyPanel>
    );
  }

  return (
    <div className="panel overflow-x-auto" data-testid="audit-table">
      <table className="matrix">
        <thead>
          <tr>
            <th scope="col">Occurred (UTC)</th>
            <th scope="col">Verb</th>
            <th scope="col">Actor</th>
            <th scope="col">Business identity</th>
            <th scope="col">Detail</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event, index) => (
            <tr key={`${event.occurred_at}-${event.identity}-${index}`} data-testid="audit-row">
              <td className="mono text-muted whitespace-nowrap">
                {formatInstant(event.occurred_at)}
              </td>
              <td className="font-medium whitespace-nowrap">{event.verb}</td>
              <td className="text-muted whitespace-nowrap">{event.actor}</td>
              <td className="mono text-dim">{event.identity}</td>
              <td className="text-muted">{event.detail ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AuditTrail(): ReactNode {
  const { resource, reload, reloading } = useConsoleResource<AuditView[]>("/api/console/audit");

  return (
    <div className="flex flex-col gap-4">
      <RefreshBar
        loadedAt={resource.status === "ready" ? resource.loadedAt : null}
        reloading={reloading}
        onReload={reload}
      />
      {resource.status === "loading" ? <LoadingPanel label="the audit trail" /> : null}
      {resource.status === "failed" ? <ErrorPanel error={resource.error} onRetry={reload} /> : null}
      {resource.status === "ready" ? <AuditTrailView events={resource.data} /> : null}
    </div>
  );
}
