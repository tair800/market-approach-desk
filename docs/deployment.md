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

**Not yet deployed.** Creating the Render service and the Neon database is owner account action. The
blueprint and the Dockerfile are verified; the deploy step needs an account.
