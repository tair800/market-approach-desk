import type { ReactNode } from "react";

import { ApproachStateBadge, ReplyBadge } from "@/components/Badge";
import { formatInstant, stageLabel } from "@/lib/states";
import type { ApproachView } from "@/lib/types";

/**
 * The placement × carrier matrix: one row per approach, which is one carrier at one stage.
 *
 * A carrier can legitimately appear twice — once at `initial`, once at `revised_terms` — because
 * the stage is part of the business identity. The stage column is therefore not decoration; it is
 * the reason two rows for one carrier are not a duplicate.
 */

export function ApproachRow({ approach }: { approach: ApproachView }): ReactNode {
  const { market } = approach;
  return (
    <tr
      className={approach.follow_up_overdue ? "row-overdue" : undefined}
      data-testid="approach-row"
      data-overdue={approach.follow_up_overdue ? "true" : "false"}
    >
      <td>
        <div className="font-medium text-text">{market.name}</div>
        <div className="text-dim">
          {market.underwriter}
          {market.within_placing_authority ? null : (
            <span
              className="ml-1.5 text-[#f0bd6a]"
              title="Outside this desk's placing authority. An approach here needs sign-off."
            >
              outside authority
            </span>
          )}
        </div>
      </td>
      <td className="text-muted whitespace-nowrap">{stageLabel(approach.stage)}</td>
      <td>
        <ApproachStateBadge state={approach.state} />
      </td>
      <td className="text-muted tabular-nums" title="Send attempts recorded for this approach">
        {approach.attempt_count}
      </td>
      <td className="mono text-muted whitespace-nowrap">{formatInstant(approach.due_at)}</td>
      <td className="mono text-muted whitespace-nowrap">{formatInstant(approach.sent_at)}</td>
      <td className="mono whitespace-nowrap">
        {approach.follow_up_overdue ? (
          <span className="font-semibold text-[#f2b756]" data-testid="overdue-flag">
            overdue · {formatInstant(approach.follow_up_at)}
          </span>
        ) : (
          <span className="text-muted">{formatInstant(approach.follow_up_at)}</span>
        )}
      </td>
      <td>
        <ReplyBadge
          classification={approach.reply_classification}
          abstained={approach.reply_abstained}
        />
      </td>
      <td className="text-muted">
        {approach.blocked_reason ? (
          <span data-testid="blocked-reason" title="Refused inside the claim transaction.">
            {approach.blocked_reason}
          </span>
        ) : (
          <span className="text-dim">—</span>
        )}
      </td>
    </tr>
  );
}

export function ApproachMatrix({ approaches }: { approaches: ApproachView[] }): ReactNode {
  if (approaches.length === 0) {
    return (
      <p className="px-4 py-4 text-muted" data-testid="no-approaches">
        No carriers on the panel for this placement yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="matrix">
        <thead>
          <tr>
            <th scope="col">Carrier</th>
            <th scope="col">Stage</th>
            <th scope="col">State</th>
            <th scope="col" title="Send attempts recorded for this approach">
              Att
            </th>
            <th scope="col">Due</th>
            <th scope="col">Sent</th>
            <th scope="col">Follow-up</th>
            <th scope="col">Reply</th>
            <th scope="col">Note</th>
          </tr>
        </thead>
        <tbody>
          {approaches.map((approach) => (
            <ApproachRow key={approach.id} approach={approach} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
