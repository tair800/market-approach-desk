import type { ReactNode } from "react";

import { AuditTrail } from "@/components/AuditTrail";

export default function AuditPage(): ReactNode {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-base font-semibold">Audit</h1>
        <p className="text-muted mt-0.5 max-w-3xl">
          Append-only, newest first. Every claim, send, retry and classification against the business
          identity it touched. This is the record consulted after a market is blocked, so nothing in
          it is edited or removed.
        </p>
      </div>
      <AuditTrail />
    </div>
  );
}
