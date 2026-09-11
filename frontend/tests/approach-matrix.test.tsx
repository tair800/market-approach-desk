import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { ApproachMatrix, ApproachRow } from "@/components/ApproachMatrix";

import { approach } from "./fixtures";

function renderRow(node: ReactNode) {
  return render(
    <table>
      <tbody>{node}</tbody>
    </table>,
  );
}

describe("the approach row", () => {
  it("flags a late chase, and only when the server says it is late", () => {
    renderRow(<ApproachRow approach={approach({ follow_up_overdue: true })} />);

    const row = screen.getByTestId("approach-row");
    expect(row).toHaveAttribute("data-overdue", "true");
    expect(row).toHaveClass("row-overdue");
    expect(within(row).getByTestId("overdue-flag")).toHaveTextContent("overdue · 2026-09-04 09:00Z");
  });

  it("shows the follow-up time plainly when nothing is late", () => {
    renderRow(<ApproachRow approach={approach({ follow_up_overdue: false })} />);

    const row = screen.getByTestId("approach-row");
    expect(row).not.toHaveClass("row-overdue");
    expect(within(row).queryByTestId("overdue-flag")).toBeNull();
    expect(row).toHaveTextContent("2026-09-04 09:00Z");
  });

  it("shows the refusal reason on a blocked approach", () => {
    renderRow(
      <ApproachRow
        approach={approach({
          state: "blocked",
          blocked_reason: "declined at initial within the 30-day cooling period",
          sent_at: null,
        })}
      />,
    );

    expect(screen.getByTestId("blocked-reason")).toHaveTextContent("cooling period");
    expect(screen.getByText("blocked")).toHaveAttribute("data-state", "blocked");
  });

  it("marks a carrier outside placing authority", () => {
    renderRow(
      <ApproachRow
        approach={approach({
          market: {
            id: "m",
            name: "Harbour Lane Re",
            underwriter: "T. Vance",
            within_placing_authority: false,
          },
        })}
      />,
    );

    expect(screen.getByText("outside authority")).toBeInTheDocument();
  });

  it("shows an abstention next to the classification, never instead of it", () => {
    renderRow(
      <ApproachRow
        approach={approach({
          state: "replied",
          reply_classification: "unclear",
          reply_abstained: true,
        })}
      />,
    );

    expect(screen.getByText("unclear")).toHaveAttribute("data-reply", "unclear");
    expect(screen.getByTestId("abstained-marker")).toBeInTheDocument();
  });
});

describe("the matrix", () => {
  it("keeps one carrier's two stages as two rows", () => {
    render(
      <ApproachMatrix
        approaches={[
          approach({ id: "a1", stage: "initial", state: "blocked" }),
          approach({ id: "a2", stage: "revised_terms", state: "sent" }),
        ]}
      />,
    );

    expect(screen.getAllByTestId("approach-row")).toHaveLength(2);
    expect(screen.getByText("revised terms")).toBeInTheDocument();
  });

  it("says so when a placement has no panel yet", () => {
    render(<ApproachMatrix approaches={[]} />);
    expect(screen.getByTestId("no-approaches")).toHaveTextContent("No carriers on the panel");
  });
});
