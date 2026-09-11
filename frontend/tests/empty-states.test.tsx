import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuditTrailView } from "@/components/AuditTrail";
import { BoardView } from "@/components/Board";
import { KillTestPanel } from "@/components/KillTestPanel";
import { ErrorPanel } from "@/components/panels";

/**
 * Nothing-to-show is a state the console has to render as deliberately as a full board. Each of
 * these is reachable on a fresh clone, and each has to explain itself rather than look broken.
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("empty screens", () => {
  it("explains an empty board instead of showing a blank page", () => {
    render(<BoardView placements={[]} />);
    expect(screen.getByTestId("empty-panel")).toHaveTextContent("No placements on the desk.");
    expect(screen.getByText("make demo")).toBeInTheDocument();
  });

  it("explains an empty audit trail", () => {
    render(<AuditTrailView events={[]} />);
    expect(screen.getByTestId("empty-panel")).toHaveTextContent("Nothing recorded yet.");
  });
});

describe("an unreachable backend", () => {
  it("reads as an outage with a remedy, never as a stack trace", () => {
    render(
      <ErrorPanel
        error={{ kind: "unreachable", message: "The API is not reachable from the console right now." }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The console cannot show this right now.",
    );
    expect(screen.getByText(/Start the API/)).toBeInTheDocument();
  });

  it("names the missing configuration when there is no API address at all", () => {
    render(
      <ErrorPanel
        error={{ kind: "unconfigured", message: "The console has no API address." }}
      />,
    );

    expect(screen.getByText(/APPROACH_API_BASE_URL/)).toBeInTheDocument();
  });
});

describe("the comparison screen before a run", () => {
  it("says the kill test has not been run when public/killtest.json is absent", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 404 })),
    );

    render(<KillTestPanel />);

    expect(
      await screen.findByText(/kill test has not been run in this checkout/i),
    ).toBeInTheDocument();
    expect(screen.getByText("make killtest")).toBeInTheDocument();
  });

  it("refuses to render a result of the wrong shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ identity: "p/m/initial", n8n: { observed: 2 } }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );

    render(<KillTestPanel />);

    expect(await screen.findByText(/could not be read/i)).toBeInTheDocument();
  });

  it("renders both arms and names the duplicate once a run has published a result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              identity: "p-1/m-1/initial",
              n8n: { observed: 2, distinct_keys: 1 },
              python: { observed: 1, distinct_keys: 1 },
              ran_at: "2026-09-11T18:30:00Z",
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
      ),
    );

    render(<KillTestPanel />);

    expect(await screen.findByTestId("killtest-view")).toBeInTheDocument();
    expect(screen.getByTestId("duplicates-n8n")).toHaveTextContent("1");
    expect(screen.getByTestId("duplicates-python")).toHaveTextContent("0");
    expect(screen.getByTestId("verdict-n8n")).toHaveTextContent("Market blocked");
    expect(screen.getByTestId("verdict-python")).toHaveTextContent(
      "At most one approach per identity",
    );
    expect(screen.getByText("p-1/m-1/initial")).toBeInTheDocument();
  });
});
