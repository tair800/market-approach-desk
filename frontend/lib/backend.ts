import "server-only";

import { NextResponse } from "next/server";

import type { ConsoleError } from "@/lib/types";

/**
 * The one place the backend URL is read, and the one place it is allowed to be read.
 *
 * `server-only` is imported above so that importing this module from a client component is a build
 * error rather than a leaked base URL. The console never ships the address of the API to a browser:
 * every request the browser makes goes to a same-origin `/api/console/*` handler, which calls this.
 */

const REQUEST_TIMEOUT_MS = 8_000;

/** Exactly the paths the console needs. An allowlist, so this can never become an open proxy. */
export const CONSOLE_ROUTES = {
  placements: "/api/v1/placements",
  audit: "/api/v1/audit?limit=100",
  stats: "/api/v1/stats",
  meta: "/api/v1/meta",
} as const;

export type ConsoleRoute = keyof typeof CONSOLE_ROUTES;

function baseUrl(): string | null {
  const raw = process.env.APPROACH_API_BASE_URL?.trim();
  if (!raw) {
    return null;
  }
  return raw.replace(/\/+$/, "");
}

function fail(error: ConsoleError, status: number): NextResponse {
  return NextResponse.json({ error }, { status });
}

/**
 * Fetch one allowlisted upstream path and hand it back unchanged, or hand back a described failure.
 *
 * No upstream body is ever forwarded on an error path. A stack trace or a connection string from a
 * misconfigured API would otherwise reach the browser through this handler, and the console's job
 * is to stay calm about an outage, not to narrate it.
 */
export async function proxy(route: ConsoleRoute): Promise<NextResponse> {
  const base = baseUrl();
  if (base === null) {
    return fail(
      {
        kind: "unconfigured",
        message:
          "The console has no API address. Set APPROACH_API_BASE_URL in the console environment.",
      },
      503,
    );
  }

  let response: Response;
  try {
    response = await fetch(`${base}${CONSOLE_ROUTES[route]}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (cause) {
    const timedOut = cause instanceof DOMException && cause.name === "TimeoutError";
    return fail(
      timedOut
        ? {
            kind: "timeout",
            message: `The API did not answer within ${REQUEST_TIMEOUT_MS / 1000} seconds.`,
          }
        : {
            kind: "unreachable",
            message: "The API is not reachable from the console right now.",
          },
      504,
    );
  }

  if (!response.ok) {
    return fail(
      {
        kind: "upstream",
        message: `The API answered ${response.status}.`,
      },
      502,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return fail(
      { kind: "malformed", message: "The API answered with something that is not JSON." },
      502,
    );
  }

  return NextResponse.json(payload, {
    status: 200,
    headers: { "cache-control": "no-store" },
  });
}
