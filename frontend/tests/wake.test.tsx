import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Board } from "@/components/Board";
import { LoadingPanel } from "@/components/panels";
import { resetWake } from "@/lib/wake";

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
  error: { kind: "timeout", message: "The API did not answer within 8 seconds.", retryable: true },
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
  it("shows a starting state, waits it out, then shows the real board with no error", async () => {
    const calls = scriptedConsole({
      "/api/console/placements": (n) => (n === 1 ? reply(504, WAKING) : reply(200, [])),
      "/api/console/stats": (n) =>
        n === 1 ? reply(504, WAKING) : reply(200, { by_state: {}, attempts: 0 }),
      "/api/console/health": (n) => (n < 3 ? reply(504, WAKING) : reply(200, { status: "ok" })),
    });

    render(<Board />);
    await advance(0);

    expect(screen.getByTestId("waking-panel")).toHaveTextContent("Starting the public demo");
    expect(screen.getByText("Counts load when the demo API is awake.")).toBeInTheDocument();
    expect(screen.queryByTestId("error-panel")).toBeNull();

    await advance(5_000);
    expect(screen.getByTestId("waking-panel")).toHaveTextContent("Waiting for the API · 5s");

    await advance(5_000);

    // The board the API actually returned: empty, and explained as empty.
    expect(screen.getByTestId("empty-panel")).toHaveTextContent("No placements on the desk.");
    expect(screen.queryByTestId("waking-panel")).toBeNull();
    expect(screen.queryByTestId("error-panel")).toBeNull();
    // One shared watcher for the whole page, not one per panel.
    expect(calls["/api/console/health"]).toBe(3);
    expect(calls["/api/console/placements"]).toBe(2);
  });

  it("gives up after two and a half minutes with an honest error and a way to try again", async () => {
    const calls = scriptedConsole({
      "/api/console/placements": () => reply(504, WAKING),
      "/api/console/stats": () => reply(504, WAKING),
      "/api/console/health": () => reply(504, WAKING),
    });

    render(<Board />);
    await advance(0);
    await advance(149_000);
    expect(screen.getByTestId("waking-panel")).toBeInTheDocument();

    await advance(5_000);
    const alert = screen.getByTestId("error-panel");
    expect(alert).toHaveTextContent("did not wake within two and a half minutes");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();

    // Bounded: no health check is sent once the limit has passed.
    const sent = calls["/api/console/health"];
    await advance(30_000);
    expect(calls["/api/console/health"]).toBe(sent);
  });

  it("does not wait when waiting cannot help, and shows the configuration error at once", async () => {
    const calls = scriptedConsole({
      "/api/console/placements": () =>
        reply(503, {
          error: { kind: "unconfigured", message: "The console has no API address." },
        }),
      "/api/console/stats": () => reply(200, { by_state: {}, attempts: 0 }),
    });

    render(<Board />);
    await advance(0);

    expect(screen.getByTestId("error-panel")).toHaveTextContent("The console has no API address.");
    expect(calls["/api/console/health"]).toBeUndefined();
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
});
