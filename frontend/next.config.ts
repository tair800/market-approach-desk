import type { NextConfig } from "next";

/**
 * Deliberately small.
 *
 * `APPROACH_API_BASE_URL` is **not** listed under `env` and must never be: anything placed there is
 * inlined into the client bundle at build time. The console reaches the API only from route
 * handlers under `app/api/console/`, which run on the server.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
