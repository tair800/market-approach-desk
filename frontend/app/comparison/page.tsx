import type { ReactNode } from "react";

import { KillTestPanel } from "@/components/KillTestPanel";

export default function ComparisonPage(): ReactNode {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-base font-semibold">Comparison — two arms, one harness</h1>
        <p className="text-muted mt-0.5 max-w-3xl">
          Two scheduler ticks are forced to overlap over one due-set: both observe it before either
          records completion, held by an explicit barrier rather than by sleeping and hoping. The
          same fixtures, the same fake carrier receiver, one business identity. The receiver counts
          what it saw.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel px-4 py-3.5">
          <h2 className="font-semibold">Why the n8n arm duplicates</h2>
          <p className="text-muted mt-1">
            Its execution is four steps in a row: read the due-set, decide eligibility, send, then
            write the result back. Nothing holds a transaction across them, so the second execution
            reads the same due-set before the first has written anything to it. Both executions see
            an approach that looks eligible, both decide it is, and both send. The eligibility rule
            was correct — it was just evaluated against state that had already changed by the time
            the send happened. The email cannot be recalled, and the market is blocked.
          </p>
        </section>
        <section className="panel px-4 py-3.5">
          <h2 className="font-semibold">What the Python arm does instead</h2>
          <p className="text-muted mt-1">
            It claims the approach inside one transaction, selecting the due row with{" "}
            <code className="mono text-text">SELECT … FOR UPDATE SKIP LOCKED</code> so a second
            scheduler skips it rather than queuing behind it, and it evaluates{" "}
            <span className="text-text">every</span> eligibility rule inside that transaction —
            already approached, declined within the cooling period, held by another broker, outside
            placing authority. A rule evaluated before the claim is a rule evaluated against state
            that may already have changed. A unique constraint on{" "}
            <code className="mono text-text">(placement, market, stage)</code> is the backstop, not
            the plan.
          </p>
        </section>
      </div>

      <KillTestPanel />

      <p className="text-dim max-w-3xl">
        The claim is <span className="text-muted">at most one accepted business approach</span>, not
        exactly-once delivery. Email is not exactly-once and this console never says it is: a send
        that fails is retried and a receiver that fails to acknowledge may see it twice. What is
        measured here is the number of approaches the receiver accepted for one identity.
      </p>
    </div>
  );
}
