import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Board } from "@/components/Board";
import { LoadingPanel } from "@/components/panels";
import { resetWake } from "@/lib/wake";
import type { PlacementView } from "@/lib/types";
import { approach } from "./fixtures";

function placement(): PlacementView {
  return {
    id: "placement-1",
    reference: "PL-TEST-0001",
    insured_name: "Test Insured",
    class_of_business: "Marine cargo",
    handler: "test.handler",
    inception_on: "2026-10-01",
    approaches: [approach()],
  };
}

/**
 * A free-tier API that is waking must read as "starting", not as a failure — and the wait must
 * end: with the real board once the API answers its health check, or with an honest error once the
 * limit passes. Nothing here may put data on screen that the API did not return.
 */

vi.mock("server-only", () => ({}));

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const WAKING = {
  error: { kind: "upstream", message: "The API answered 429.", retryable: true },
};

/** Route the console's own endpoints to scripted answers, counting calls per path. */
function scriptedConsole(script: Record<string, (call: number) => Response>) {
  const calls: Record<string, number> = {};
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://console.test").pathname;
    calls[path] = (calls[path] ?? 0) + 1;
    const answer = script[path];
    return answer ? answer(calls[path]) : reply(404, null);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  resetWake();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("a sleeping demo API", () => {
  it("asks the health check first, shows a starting state, then shows the real board", async () => {
    const calls = scriptedConsole({
      "/api/console/health": (n) => (n < 3 ? reply(502, WAKING) : reply(200, { status: "alive" })),
      "/api/console/placements": () => reply(200, []),
      "/api/console/stats": () => reply(200, { by_state: {}, attempts: 0 }),
    });

    render(<Board />);
    await advance(0);

    // No data read is sent to an API that has not answered its health check.
    expect(calls["/api/console/placements"]).toBeUndefined();
    expect(screen.getByTestId("loading-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("error-panel")).toBeNull();

    await advance(4_000);
    expect(screen.getByTestId("waking-panel")).toHaveTextContent("Starting the public demo");
    expect(screen.getByText("Counts load when the demo API is awake.")).toBeInTheDocument();

    await advance(6_000);

    // The board the API actually returned: empty, and explained as empty.
    expect(screen.getByTestId("empty-panel")).toHaveTextContent("No placements on the desk.");
    expect(screen.queryByTestId("waking-panel")).toBeNull();
    expect(screen.queryByTestId("error-panel")).toBeNull();
    // One shared watcher for the whole page, and one read per panel once it answered.
    expect(calls["/api/console/health"]).toBe(3);
    expect(calls["/api/console/placements"]).toBe(1);
  });

  it("costs one quick health check when the API is already awake", async () => {
    const calls = scriptedConsole({
      "/api/console/health": () => reply(200, { status: "alive" }),
      "/api/console/placements": () => reply(200, [placement()]),
      "/api/console/stats": () => reply(200, { by_state: {}, attempts: 0 }),
    });

    render(<Board />);
    await advance(0);

    expect(screen.getByTestId("placement-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("waking-panel")).toBeNull();
    expect(calls["/api/console/health"]).toBe(1);
  });

  it("gives up after two and a half minutes with an honest error and a way to try again", async () => {
    const calls = scriptedConsole({
      "/api/console/health": () => reply(502, WAKING),
      "/api/console/placements": () => reply(200, []),
      "/api/console/stats": () => reply(200, { by_state: {}, attempts: 0 }),
    });

    render(<Board />);
    await advance(0);
    await advance(149_000);
    expect(screen.getByTestId("waking-panel")).toBeInTheDocument();

    await advance(5_000);
    const alert = screen.getByTestId("error-panel");
    expect(alert).toHaveTextContent("did not wake within two and a half minutes");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    // Nothing was read from an API that never answered, and nothing was substituted.
    expect(calls["/api/console/placements"]).toBeUndefined();

    // Bounded: no health check is sent once the limit has passed.
    const sent = calls["/api/console/health"];
    await advance(30_000);
    expect(calls["/api/console/health"]).toBe(sent);
  });

  it("does not wait when waiting cannot help, and shows the configuration error at once", async () => {
    const unconfigured = reply(503, {
      error: { kind: "unconfigured", message: "The console has no API address." },
    });
    const calls = scriptedConsole({
      "/api/console/health": () => unconfigured.clone(),
      "/api/console/placements": () => unconfigured.clone(),
      "/api/console/stats": () => unconfigured.clone(),
    });

    render(<Board />);
    await advance(0);

    expect(screen.getByTestId("error-panel")).toHaveTextContent("The console has no API address.");
    expect(calls["/api/console/health"]).toBe(1);
  });
});

describe("a slow first answer", () => {
  it("mentions that the demo API may be waking once loading takes a few seconds", async () => {
    render(<LoadingPanel label="the board" />);
    expect(screen.getByTestId("loading-panel")).not.toHaveTextContent("waking up");

    await advance(4_000);
    expect(screen.getByTestId("loading-panel")).toHaveTextContent("may be waking up");
  });
});

describe("the console's proxy", () => {
  it("marks a host's 429 and 503 as retryable and a 404 as not", async () => {
    vi.stubEnv("APPROACH_API_BASE_URL", "https://api.example.test");
    const { proxy } = await import("@/lib/backend");

    vi.stubGlobal("fetch", vi.fn(async () => new Response("waking", { status: 503 })));
    const waking = await (await proxy("health")).json();
    expect(waking.error).toMatchObject({ kind: "upstream", retryable: true });

    // Render's edge answered 429 to the console for several minutes of a real cold start.
    vi.stubGlobal("fetch", vi.fn(async () => new Response("slow down", { status: 429 })));
    const throttled = await (await proxy("health")).json();
    expect(throttled.error).toMatchObject({ kind: "upstream", retryable: true });

    vi.stubGlobal("fetch", vi.fn(async () => new Response("missing", { status: 404 })));
    const missing = await (await proxy("health")).json();
    expect(missing.error).toMatchObject({ kind: "upstream", retryable: false });

    vi.unstubAllEnvs();
  });

  it("gives the health check a long enough wait to ride out a cold start", async () => {
    const { WAKE_REQUEST_TIMEOUT_MS } = await import("@/lib/backend");
    const route = await import("@/app/api/console/health/route");
    expect(WAKE_REQUEST_TIMEOUT_MS).toBe(55_000);
    expect(route.maxDuration).toBe(60);
  });
});
