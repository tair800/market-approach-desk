"use client";

import type { ReactNode } from "react";

import type { MetaView } from "@/lib/types";
import { useConsoleResource } from "@/lib/use-console";

/**
 * What is actually running, in the header.
 *
 * The revision is shown so a claim about what is deployed can be checked rather than assumed, and
 * `demo mode` is shown because a visitor is entitled to know that the data in front of them is
 * seeded rather than a broker's real panel.
 */
export function MetaStrip(): ReactNode {
  const { resource } = useConsoleResource<MetaView>("/api/console/meta");

  if (resource.status !== "ready") {
    return <span className="text-dim" data-testid="meta-strip" />;
  }

  const { version, demo_mode, revision } = resource.data;
  return (
    <span className="text-dim flex items-center gap-3" data-testid="meta-strip">
      <span className="mono">v{version}</span>
      {demo_mode ? (
        <span className="badge badge-eligible" title="Seeded demonstration data, not a live panel.">
          demo data
        </span>
      ) : null}
      {revision ? <span className="mono">{revision.slice(0, 7)}</span> : null}
    </span>
  );
}
