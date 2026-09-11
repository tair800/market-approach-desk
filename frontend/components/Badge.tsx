import type { ReactNode } from "react";

import { approachStateBadge, replyClassBadge } from "@/lib/states";

export function ApproachStateBadge({ state }: { state: string }): ReactNode {
  const spec = approachStateBadge(state);
  return (
    <span className={spec.className} title={spec.title} data-state={state}>
      {spec.label}
    </span>
  );
}

export function ReplyBadge({
  classification,
  abstained,
}: {
  classification: string | null;
  abstained: boolean;
}): ReactNode {
  if (classification === null) {
    return <span className="text-dim">—</span>;
  }
  const spec = replyClassBadge(classification);
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={spec.className} title={spec.title} data-reply={classification}>
        {spec.label}
      </span>
      {abstained ? (
        <span
          className="badge badge-abstained"
          title="The model declined to judge. A person decides this one."
          data-testid="abstained-marker"
        >
          abstained
        </span>
      ) : null}
    </span>
  );
}
