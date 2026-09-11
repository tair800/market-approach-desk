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

**Not yet deployed.** Creating the Neon database, the Render service and the Vercel project is owner
account action, and nothing in this repository can perform it.

What is verified, locally and end to end against the real image:

| Step | Evidence |
|---|---|
| Image builds | `docker build -t mad-api:deploy .` succeeds from a clean context |
| Migrations apply on boot | `Running upgrade  -> 8c024e94d080, approach schema` in the container log |
| Demonstration seeds once | boot 1 `seeded the demonstration`; boot 2 `already populated; nothing written` |
| The four routes the console reads | `/api/v1/placements`, `/api/v1/audit`, `/api/v1/stats`, `/api/v1/meta` all answer 200 against the bootstrapped database |
| Liveness and readiness | `/healthz` and `/readyz` answer 200; `/readyz` reaches PostgreSQL |

`/api/v1/meta` reports `revision` from `RENDER_GIT_COMMIT`, which Render sets and a local `docker
run` does not — so it is empty locally and populated once deployed.
