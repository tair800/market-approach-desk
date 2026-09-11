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
| **Live model quality, cost, latency** | **NOT MEASURED** | The shipped package contains no HTTP client and cannot dial a provider; a guard test enforces it. The classifier that runs is a declared stand-in whose rationale says no model produced it. |
| **Exactly-once delivery** | **Not claimed** | Email is not exactly-once. The claim is *at most one accepted business approach per identity under the tested contract*, measured at the receiver. |
| **Five of the six n8n failure modes** | **Analysed, not proven** | The blueprint names six. One — overlapping schedule executions — is demonstrated deterministically. The rest are written up in `n8n/README.md` and labelled as analysed. An analysed failure mode is not evidence. |
| **Deployment** | **Not yet deployed** | The stack runs locally via Docker Compose. |

---

## Known issues and findings

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
