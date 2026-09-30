import { WAKE_REQUEST_TIMEOUT_MS, proxy } from "@/lib/backend";

export const dynamic = "force-dynamic";

// A sleeping free-tier API is woken only by a request that waits for it; see `lib/backend.ts`.
// Vercel's Hobby plan allows a function 60 seconds when this is set.
export const maxDuration = 60;

export async function GET(): Promise<Response> {
  return proxy("health", WAKE_REQUEST_TIMEOUT_MS);
}
