# Console

The operator console for the market-approach desk. Three screens, no more:

| Screen | Path | What it answers |
| --- | --- | --- |
| Board | `/` | Every placement, and the state of every carrier approach behind it. |
| Comparison | `/comparison` | What the carrier receiver observed under overlapping ticks, per arm. |
| Audit | `/audit` | Who approached which carrier, when, against which business identity. |

Next.js 15 (App Router), React 19, TypeScript strict, Tailwind 4. No client state library, no chart
library, no component framework: the whole console is a board, two tables and a comparison.

## Running it

```bash
npm install
cp .env.example .env.local     # then point APPROACH_API_BASE_URL at the API
npm run dev                    # http://localhost:3000
npm run build                  # production build, type-checked
npm test                       # vitest
```

## The API address never reaches the browser

`APPROACH_API_BASE_URL` is read in exactly one module, `lib/backend.ts`, which imports
`server-only` — importing it from a client component is a build failure rather than a leak. It is
not prefixed `NEXT_PUBLIC_` and must never be listed under `env` in `next.config.ts`; either would
inline it into the client bundle.

The browser only ever names a same-origin path. Four route handlers under `app/api/console/` proxy
an allowlist of four upstream reads:

```
/api/console/placements  ->  GET /api/v1/placements
/api/console/audit       ->  GET /api/v1/audit?limit=100
/api/console/stats       ->  GET /api/v1/stats
/api/console/meta        ->  GET /api/v1/meta
```

The allowlist is the point: the proxy cannot be pointed at an arbitrary upstream path. On failure it
returns `{"error": {"kind", "message"}}` and forwards **no** upstream body — a misconfigured API's
stack trace or connection string would otherwise reach the browser through it.

## The comparison screen's input

`/comparison` renders `public/killtest.json`, which `make killtest` writes. The file is **not
committed**: a checked-in result would be a number the console asserts rather than one a run
measured. Absent, the screen says the test has not been run. Present but malformed, it says that
instead of rendering a headline figure from a partial object.

```json
{
  "identity": "<placement>/<market>/<stage>",
  "n8n":    { "observed": 0, "distinct_keys": 0 },
  "python": { "observed": 0, "distinct_keys": 0 },
  "ran_at": "2026-01-01T00:00:00Z"
}
```

`observed` is the number of approaches the fake carrier receiver accepted; `distinct_keys` is the
number of distinct business identities among them. Their difference is the duplicate count the
screen shows, and the whole claim in ADR-001 is that it is zero for the Python arm.

## Deployment

`vercel.json` pins `fra1`. Set `APPROACH_API_BASE_URL` as a Vercel environment variable — a plain
one, not one exposed to the browser.
