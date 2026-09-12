# Deployment

Two audiences, two shapes, and they are not the same thing.

## 1. The SME deliverable — a single Docker host

This is what the project is *for*. A 10–30 person broker runs one host:

```bash
docker compose up -d          # PostgreSQL
docker build -t mad-api .     # the API
docker run -p 8000:8000 -e MAD_POSTGRES_DSN=... mad-api
cd frontend && npm run build && npm start
```

Verified locally: the image builds, `alembic upgrade head` runs in the entrypoint, and the container
answers `/healthz`, `/readyz` and `/api/v1/stats` against a real database.

No mail provider is configured and none can be: there is no real carrier transport in this
repository, so a deployment cannot accidentally acquire one.

## 2. The public demonstration — free tiers

| Layer | Service | Plan | Region |
|---|---|---|---|
| Console | Vercel | Hobby | `fra1` |
| API | Render Web Service (Docker) | Free | Frankfurt |
| PostgreSQL | Neon | Free | `eu-central-1` |

**Render's own free PostgreSQL is deliberately not used**: it expires after 30 days, which would
take the demonstration down on a schedule. Neon's free tier does not expire.

### Migrations run at container start, and that is a property of the plan

Render's free instance type has no release or pre-deploy hook — that is a paid feature. So the
choice is migrate-on-boot or migrate-by-hand, and migrate-on-boot is taken.

The usual objection to migrating on boot is that a process doing it races every other replica for
the same DDL. **It does not apply here for one specific reason: the free plan runs exactly one
instance.** Scale this to two and the race returns immediately. Recorded as a limitation rather than
resolved, because resolving it means paying for a release hook.

A failed migration stops the container (`set -e`), the deploy stays unhealthy, and the app never
serves against a schema it does not expect.

### The demonstration data is seeded on boot too, and only into an empty database

`alembic upgrade head` creates the schema and leaves it empty, so a fresh Neon database would serve
a board with nothing on it. The entrypoint therefore also runs
`python -m market_approach_desk.demo.bootstrap`, gated on `MAD_DEMO_MODE=true`.

**It is deliberately not the `python -m market_approach_desk.demo` path.** That one is
`reset()` + `seed()`, which `TRUNCATE`s every table — which is why it refuses any DSN that is not
`localhost`. A boot hook doing that would work perfectly and wipe the board every time Render woke
the free instance from sleep. `bootstrap()` instead counts `market_approach` and returns without
writing if any row exists; it contains no `DELETE` and no `TRUNCATE` on any path.

Verified by booting the image twice against one database: the first boot logged
`seeded the demonstration`, the second logged `already populated; nothing written`, and
`/api/v1/stats` was byte-identical across both. Pinned by
`test_the_deploy_bootstrap_seeds_an_empty_database_once_and_never_again`, which compares every table
before and after the second call and was verified to go red when `bootstrap` is mutated into the
reset-every-boot version.

The seeded board is five approaches across one placement, with an empty audit trail — the scheduler
has not run yet, and the console's audit screen renders its empty state, which is exactly what the
committed screenshot shows.

### Owner-set configuration, by name

No value appears in this repository.

**Render** (`sync: false` in `render.yaml`, so Render prompts and encrypts):

| Name | What it is |
|---|---|
| `MAD_POSTGRES_DSN` | The Neon connection string. |

Everything else Render needs is in `render.yaml` and is not secret.

**Vercel:**

| Name | Value |
|---|---|
| `APPROACH_API_BASE_URL` | The Render service URL, no trailing slash. |

### The DSN normalisation, and why it exists before it was needed

Neon issues a connection string ending `?sslmode=require&channel_binding=require`. Pasted in
verbatim it produces a deployment that **reports itself healthy and cannot serve a request**: a
direct `asyncpg.connect(dsn)` parses the URL itself and understands `sslmode`, while SQLAlchemy's
asyncpg dialect splits the query string into keyword arguments that `asyncpg.connect` has no
signature for. `db/engine.py` normalises it, and unrecognised parameters are kept rather than
dropped.

## 3. n8n

**n8n is not hosted for the public demonstration**, and paying for n8n Cloud for a portfolio project
would be a poor trade. What ships instead:

- `n8n/market-approach.workflow.json` — importable into any n8n instance;
- `n8n/docker-compose.yml` — runs a real n8n locally on :5678;
- a faithful execution simulator, so the race is reproducible in CI with no n8n instance at all.

The comparison screen therefore renders a **measured result** written by the kill test, not a live
n8n instance. That is stated on the screen itself, with the timestamp of the run.

## Status

**Deployed and live.**

| Layer | URL | Service | Plan | Region |
|---|---|---|---|---|
| Console | <https://market-approach-desk.vercel.app> | Vercel | Hobby | `fra1` |
| API | <https://market-approach-desk-api.onrender.com> | Render Web Service (Docker) | Free | Frankfurt |
| PostgreSQL | not public | Neon project `market-approach-desk`, database `mad`, PostgreSQL 16 | Free | `aws-eu-central-1` |

The Render service is Blueprint-managed from `render.yaml` on `main`, so every value except
`MAD_POSTGRES_DSN` comes from the committed file. The Vercel project builds from the `frontend`
root directory with `APPROACH_API_BASE_URL` pointing at the Render URL and nothing else set.

The Neon connection string is the **direct** endpoint, not the `-pooler` one, pasted verbatim
including `?sslmode=require&channel_binding=require`; `db/engine.py` normalises it. It exists only
in Render's encrypted environment — not in this repository, not in any log, and not in any build
output.

### What the first boot did, observed in the Render log

```
applying migrations...
INFO [alembic.runtime.migration] Running upgrade  -> 8c024e94d080, approach schema
bootstrapping the demonstration...
seeded the demonstration
starting api on port 10000
INFO: Application startup complete.
==> Your service is live
```

### Verified against the public URLs

| Check | Result |
|---|---|
| `GET /healthz` | `200` `{"status":"alive","service":"market-approach-desk","version":"0.1.0"}` |
| `GET /readyz` | `200` `{"status":"ready","postgres":"healthy"}` — the deployed process reaches Neon |
| `GET /api/v1/meta` | `200` `demo_mode: true`, `revision: 9ca8d6d…` from `RENDER_GIT_COMMIT` |
| `GET /api/v1/stats` | `200` `{"by_state":{"eligible":2,"sent":1,"replied":1,"blocked":1},"attempts":0}` |
| `GET /api/v1/audit` | `200` `[]` — no scheduler execution has run, so the trail is empty |
| `GET /api/v1/placements` | `200` — `PL-2026-0417`, Harbour Logistics Group, five carriers |
| Console `/`, `/comparison`, `/audit` | `200`, and each renders from the API through the same-origin proxy |
| No credential in the browser | the served HTML and all nine JS chunks contain no DSN, no Neon host and no `onrender.com` address; the only match for `APPROACH_API_BASE_URL` is the variable *name* inside an error-hint string |

`/readyz` is the check that matters here, not `/healthz`. `/healthz` deliberately touches nothing
external, so it would answer `200` even against an unreachable database — and `MAD_POSTGRES_DSN`
has a localhost default, which means a misspelled variable name would produce a service that looks
healthy and serves nothing. `/readyz` reaching PostgreSQL is what proves the deployed process is
talking to Neon.

### Free-tier limitations, stated plainly

- **Cold start.** The Render free instance spins down when idle; the first request after that
  delays by roughly 50 seconds. Neon's free compute also scales to zero and wakes in a second or
  two (`Database spun up in 1.58 sec` on first use).
- **One instance.** The free plan runs exactly one, which is the only reason migrate-on-boot is
  safe here. See above.
- **No release hook.** A paid feature, which is why migrations run in the entrypoint.
