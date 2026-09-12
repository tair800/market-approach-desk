# PROJECT_STATUS — market-approach-desk

Resume point for every session. Read after `CLAUDE.md`, then `git status` and recent commits.

**Current status: the claim is proven.** ADR-001's kill test was declared before any implementation
and both arms now run under it. The n8n arm duplicates under overlapping scheduler executions; the
Python arm does not.

---

## The measurement

| Arm | Approaches observed at the receiver | Distinct idempotency keys |
|---|---|---|
| n8n | **2** | 1 |
| Python | **1** | 1 |

Written by the test that measured it to `docs/killtest.json`, re-run by `make killtest` and by CI on
every push. Never hand-typed.

**The precise reading.** Both n8n sends carry the same idempotency key, so a receiver that
deduplicated on that header could have collapsed them. An underwriter's mailbox has no such feature,
which is why the fake receiver does not have one either by default — a receiver that silently
absorbed the second approach would hide the failure this project exists to demonstrate.

---

## What exists and is verified

| Item | State | Evidence |
|---|---|---|
| Business identity `(placement, market, stage)` | **DONE** | Unique constraint `uq_market_approach_business_identity`; key derived from those three facts and nothing time-, host- or attempt-dependent; pinned by a test |
| Claim transaction | **DONE** | `SELECT … FOR UPDATE SKIP LOCKED` with every conflict rule evaluated inside it; `approach/claim.py` |
| Kill test | **PASSED** | 6 tests against real PostgreSQL, two scheduler executions forced to overlap with a barrier rather than a sleep |
| Schema and migrations | **DONE** | Applies, rolls back to base and re-applies cleanly; verified locally and in CI |
| Reply classification boundary | **DONE (stand-in only)** | Closed five-value vocabulary with abstention; response type carries no identifier, state, permission or numeric field, asserted by a guard that walks the schema |
| Operator console | **DONE** | Board, comparison and audit screens; `npm run build` and 23 Vitest tests pass; the API address is server-side only and does not reach the browser |
| n8n workflow | **DONE** | Importable JSON plus a faithful execution simulator that makes the race deterministic |
| Offline suite | **DONE** | 12 tests, no database and no credential |

---

## What is deliberately not claimed

| Claim | State | Why |
|---|---|---|
| **Live model quality, cost, latency** | **NOT MEASURED** | No model has been called: nothing under `src/` imports an HTTP client or a provider SDK, the deployment carries no provider credential, and no evaluation artefact is committed. The only classifier implementation is a declared stand-in whose rationale says no model produced it, and nothing on the demo or deployed path calls even that. A guard test checks the package's imports against a ban list — see *Known issues* for what that list does and does not catch. |
| **Exactly-once delivery** | **Not claimed** | Email is not exactly-once. The claim is *at most one accepted business approach per identity under the tested contract*, measured at the receiver. |
| **Five of the six n8n failure modes** | **Analysed, not proven** | The blueprint names six. One — overlapping schedule executions — is demonstrated deterministically. The rest are written up in `n8n/README.md` and labelled as analysed. An analysed failure mode is not evidence. |
| **Recovery from a dead scheduler** | **Not implemented** | A claim committed with `due_at` cleared is invisible to every later tick; there is no lease and no stale-claim sweep, so a scheduler that dies between claiming and sending strands that approach until a person looks. The direction is the safe one — not sent rather than sent twice — and the row shows as `claimed` on the board. |
| **Deployment** | **Live** | Console on Vercel at <https://market-approach-desk.vercel.app>, API on Render at <https://market-approach-desk-api.onrender.com>, PostgreSQL on Neon — all free tier. `/readyz` reaches the database and `/api/v1/meta` reports the deployed revision. See [`docs/deployment.md`](docs/deployment.md). |

---

## Known issues and findings

**The no-HTTP-client guard bans names, and the ban list has holes.** Found by an adversarial review
during the deployment pass, by executing the real test function against copies of the package with
one extra import added. Three things are true at once and only the first was being stated:

1. **The fact holds.** Nothing under `src/` imports an HTTP client or a provider SDK — the only
   match for a network-shaped name is `urllib.parse` in `db/engine.py`, which is string
   manipulation. Runtime dependencies are FastAPI, uvicorn, pydantic, SQLAlchemy, Alembic and
   asyncpg; `httpx` is in the dev group only. No provider credential exists in the deployment and
   no evaluation artefact is committed.
2. **The guard is narrower than the claim it was cited for.** `_DIALS` bans `urllib.request`,
   `urllib.error`, `http.client`, `httpx`, `requests`, `aiohttp` and `socket`. It does **not** ban
   `openai`, `anthropic` or `urllib3`, so adding any of those three leaves the build green.
3. **`ast.ImportFrom` is handled structurally wrongly.** It collects `[node.module or ""]` and never
   looks at `node.names`, so `from urllib import request` and `from http import client` reach
   exactly the modules `_DIALS` names and pass anyway. `importlib.import_module("httpx")` is
   likewise invisible, which is the ordinary limit of an AST guard.

So the honest statement is *the package imports no HTTP client, and a guard test checks the spelling
of a ban list* — not *a guard test makes it impossible*. **Recorded rather than fixed:** the project
is frozen at this commit and this is not a deployment fault. Closing it means adding the three
missing names, reading `node.names` on `ImportFrom`, and pinning both with a test that adds each
banned import to a scratch copy and asserts the guard goes red.

**Nothing on the demo or deployed path classifies anything.** `StandInClassifier` is defined in
`replies/classify.py` and constructed in exactly two places, both in `tests/test_boundaries.py`.
No module under `src/` or `n8n/` builds or calls it, and the seeder writes its carrier reply with
`classification = None`. Earlier wording here said *the classifier that runs is a declared
stand-in*, which implies one runs; none does.

**A docstring described endpoints that do not exist.** `api.py` opened by describing three
demonstration-control endpoints answering 404 outside demo mode. No such endpoints were ever
written. Found by a reviewer of the console, not by a test, and corrected by deleting the claim
rather than by building the endpoints — the controls were not needed. It is the exact failure
CLAUDE.md rule 8 names, and it survived because prose is not type-checked.

**`reset()` by `DELETE` left rows behind between tests.** The first version deleted from six tables
in dependency order. Two tests running in sequence against one database then hit a duplicate primary
key on the next seed, and the symptom surfaced two tests later as *"the race produced no
approaches"* — which sends you to the wrong module entirely. Replaced with a single
`TRUNCATE … RESTART IDENTITY CASCADE`: one statement, one transaction, no window in which half the
tables are empty.

**The main kill test could not tell `SKIP LOCKED` from the cleared `due_at`.** The claim does both:
it takes a row lock *and* sets `due_at = NULL`. The kill test releases the second tick after the
first has committed, so by then the row is not due for either reason — and the test would have
passed identically with the lock deleted. A mechanism a test cannot distinguish from its absence is
a mechanism that test is not proving.

`test_skip_locked_is_what_does_the_work_not_the_cleared_due_at` forces the overlap one layer
earlier: two claim transactions run concurrently and **neither commits**, so the cleared `due_at` is
invisible to the other session and only the lock can decide. Verified falsifiable by deleting the
`with_for_update(skip_locked=True)` clause and watching it go red, then restoring it.

**Three of the first guard tests were wrong in the same way.** A substring scan banned `id` and fired
on `confidence`; another banned the whole `urllib` package and fired on `urllib.parse`, which is
string manipulation the DSN normaliser legitimately uses. Both now match word parts and named
modules. A guard that trips on an innocent case is a guard people learn to wave through, and the
next one it fires on will be real.
