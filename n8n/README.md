# The n8n arm

The baseline half of the comparison in [`../DECISIONS.md`](../DECISIONS.md) ADR-001. It is a
scheduled market-approach workflow of the shape a competent automation engineer ships, and it is
here to be beaten fairly or not at all.

**It is not a straw man, and that is a rule rather than an aspiration.** Every eligibility rule the
Python arm enforces is enforced here. The send carries the *same* idempotency key the Python arm
computes, from the same three business facts, verified byte-for-byte before any comparison runs. The
workflow logs an audit event for every send and every failure. Nothing has been left out to make it
lose. If it could be made safe without leaving n8n, that would be the finding, and it would be
published.

---

## Contents

| File | What it is |
|---|---|
| `market-approach.workflow.json` | The workflow itself: 17 nodes, importable into a real n8n. |
| `simulator.py` | A node-by-node model of that workflow running under n8n's execution model, against the same PostgreSQL the shipped arm uses. This is what makes the comparison reproducible in CI. |
| `docker-compose.yml` | A local n8n on `127.0.0.1:5678`, so you can import the JSON and look at it. |

---

## What the workflow does

Every five minutes: read the approaches that are due, and for each one decide whether the carrier
may be approached, send the approach, record that it was sent, and schedule the chase.

| # | Node | Type | What it does |
|---|---|---|---|
| 1 | Schedule Trigger | `scheduleTrigger` | Fires every 5 minutes. |
| 2 | Read Due Approaches | `postgres` | `SELECT` over `market_approach` joined to `placement` and `market`: eligible, due, with the conflict flags computed in SQL. |
| 3 | Loop Over Approaches | `splitInBatches` | `batchSize: 1` — one approach at a time. |
| 4 | Eligible To Approach? | `if` | State is still `eligible`, the carrier is within placing authority, and it has not declined in the last 90 days. |
| 5 | Skip Ineligible Approach | `noOp` | The false branch. |
| 6 | Compute Business Identity | `set` | Builds `placement/market/stage` and the hash payload. |
| 7 | Derive Idempotency Key | `crypto` | SHA-256 of that payload. |
| 8 | Send Approach To Carrier | `httpRequest` | `POST` with `Idempotency-Key`. **Irreversible.** `retryOnFail`, 3 tries, error output wired. |
| 9 | Mark Approach Sent | `postgres` | `UPDATE … SET state = 'sent'`. |
| 10 | Log Approach Sent | `postgres` | `INSERT INTO audit_event`. |
| 11 | Schedule Follow-Up | `postgres` | `UPDATE … SET follow_up_at = NOW() + 5 days`. |
| 12 | Inception Within 14 Days? | `if` | Urgent placements get a same-day chase. |
| 13 | Wait Before Chase | `wait` | Two hours, then node 14. |
| 14 | Send Chase To Carrier | `httpRequest` | The chase. |
| 15 | Record Send Failure | `postgres` | Error output: back to `retrying`, due again in 15 minutes. |
| 16 | Log Send Failure | `postgres` | `INSERT INTO audit_event`. |
| 17 | Pass Complete | `noOp` | The loop's done output. |

The SQL is written against **this repository's migrated schema**, not a sketch of one — the same
`market_approach`, `placement`, `market`, `carrier_reply` and `audit_event` tables the shipped arm
uses. Both arms read and write the same rows in the same database. The store is not a variable in
this experiment; the execution model is the only thing that differs, which is the only arrangement
under which the comparison means anything.

---

## Running it for real

The workflow is the artefact you can check for yourself. The simulator is an argument about it; this
is the thing itself.

```bash
# 1. the database both arms share, from the repository root
docker compose up -d
uv run alembic upgrade head
uv run python -m market_approach_desk.demo         # reset and seed the disposable local database

# 2. a local n8n
cd n8n && docker compose up -d                    # http://127.0.0.1:5678
```

Then, in the n8n editor:

1. **Import** `market-approach.workflow.json` (Workflows → ⋯ → Import from File).
2. **Create a Postgres credential** named `Market Approach Desk Postgres` pointing at
   `host.docker.internal:15433`, database `mad`. The JSON ships a placeholder credential id, so n8n
   will ask you to pick one on each Postgres node — that is expected, and it is why no credential
   id or password appears in this repository.
3. **Set `CARRIER_ENDPOINT`** in `n8n/docker-compose.yml` (or a git-ignored `n8n/.env`) to an HTTP
   endpoint you control. There is no carrier service in this repository to point it at: the fake
   receiver is an in-process Python object, which is precisely how both arms are measured through
   one instrument rather than two sockets.

Nothing here talks to a real mail provider, a real carrier or a real underwriter, and no address in
this repository resolves anywhere.

---

## How the comparison actually runs

`simulator.py` executes the same node sequence, in the same order, issuing the same statements
against the same database. The kill test calls it:

```python
from n8n.simulator import run_workflow_pair

await run_workflow_pair(engine, receiver=receiver, now=SEED_EPOCH, identity=identity)
```

Two executions are forced to overlap with an `asyncio.Event` barrier: **both must have read the
due-set before either is allowed to write state back.** Never a sleep. A harness that slept and
hoped would produce a number that depends on machine load, and a number that depends on machine load
is not evidence. If the barrier is never satisfied the run fails loudly rather than reporting a
reassuring zero — *no duplicate* and *the race never happened* must never look the same.

The same guard covers the fixtures. If neither execution's due-set contained the identity under
test, the run raises `RaceNotRunError` instead of returning. **The two most different outcomes in
this project otherwise produce almost the same number**: a safe arm reports one approach at the
receiver, and an arm that never found the row reports zero — which reads as *even safer*. An empty
database, a stale fixture or a clock the wrong side of `due_at` would publish itself as a
reliability result. That failure was not hypothetical; it happened during development, and the guard
exists because of it.

### What the simulator models faithfully, and what it does not

**This paragraph matters more than the rest of this file.** The baseline is modelled rather than
driven, and that is a real weakening of the evidence. What follows is the whole of it.

**Modelled faithfully:**

- An execution reads its work at the start and carries each item as a **detached snapshot**. No
  later node re-reads the row, because no n8n node would.
- **No lock spans executions.** n8n offers a concurrency *limit*, which bounds how many executions
  run; it has no equivalent of `SELECT … FOR UPDATE SKIP LOCKED`, which bounds what each one may
  claim. Those are different guarantees and only the second prevents this failure.
- **No transaction spans read → send → write.** Each Postgres node runs one statement in its own
  session and commits it. Each statement is atomic; the sequence is not.
- **The state write happens after the irreversible act**, because the write is what records it.
- Per-item commit granularity through `Loop Over Approaches` with `batchSize: 1`.
- The HTTP node's error output, routing a refusal to `Record Send Failure` and `Log Send Failure`.
- The identity and the idempotency key, computed through the shipped domain module so both arms are
  measured with one instrument. `verify_key_fidelity()` refuses to run a race if they ever diverge.

**Not modelled, and therefore not evidence of anything:**

- **`Retry On Fail`.** The JSON sets it, three tries, on both HTTP nodes. The simulator sends once
  and routes a refusal straight to the error output.
- **Wait-node resumption.** The simulator records the suspension and abandons the branch. It never
  resumes, so `Send Chase To Carrier` never executes there.
- **Mid-batch crash.** The execution hook *can* raise, which is what a crash between two nodes looks
  like. No scenario in this repository does that.
- **Queue mode, worker crash recovery, execution pruning, real expression evaluation, credential
  handling, and the HTTP transport itself.** The send goes to the shared in-process receiver.
- **`NOW()` versus a pinned instant.** The exported workflow uses `NOW()`; the simulator binds the
  tick instant so a test can pin time. The statements are otherwise the ones in the JSON.

---

## The measured result

One placement, one carrier (`Thames Underwriting`), stage `initial`. Two scheduler executions forced
to overlap. Counted at the receiver, which is where an underwriter's mailbox would be — never from
either arm's own tables, because a system that grades itself from its own records is measuring its
bookkeeping.

| | Approaches the carrier observed | Distinct idempotency keys |
|---|---|---|
| **n8n arm** | **2** | 1 |
| Python arm | 1 | 1 |

Across the whole pass, two executions produced **four** sends for **two** eligible identities — both
were double-approached, not just the one under test.

**The two duplicate sends carried the same idempotency key.** That is stated plainly because it
bounds the claim: a receiver that deduplicated on that header could in principle have collapsed
them. An underwriter's mailbox has no such feature, which is why the fake receiver does not either.
So the honest reading is *the duplicate was not suppressed, and over this transport nothing would
have suppressed it* — not *no mechanism could ever have*. The distinction is the difference between
a recoverable failure and an unrecoverable one, and the receiver reports both numbers so a reader
can see which this is.

A common n8n idiom scopes the request id to the execution (`{{ $execution.id }}`) instead. The
simulator models that variant too — **it is not what the shipped JSON does** — and under it the two
sends carry **two** distinct keys, at which point no receiver-side feature could have helped. The
shipped workflow deliberately uses the stronger of the two.

The published pair of numbers is written by `tests/test_kill_test_postgres.py` into
`docs/killtest.json` when the integration suite runs, so the figures a reader sees come from a run
rather than from this file. Reproduce the baseline half directly with:

```bash
docker compose up -d          # repository root
python -m n8n.simulator       # prints what the carrier observed
```

---

## The six failure modes

The blueprint names six. **This repository proves one.** The other five are analysed — reasoned
about from the workflow and from n8n's documented behaviour — and are recorded here as analysis. An
analysed failure mode is not evidence, and nothing in this repository may present it as one.

| # | Failure mode | Status | What closes it in the Python arm |
|---|---|---|---|
| 1 | **Overlapping schedule executions claim the same due-set** | ✅ **DEMONSTRATED** — 2 approaches observed at the receiver for one `(placement, market, stage)`, under a forced barrier, reproducibly | Eligibility is evaluated *inside* a claim transaction using `SELECT … FOR UPDATE SKIP LOCKED`, behind a unique constraint on the business identity |
| 2 | Mid-batch crash with no per-item commit boundary re-sends the batch | ⚠️ **ANALYSED — NOT PROVEN** | An attempt row is written *before* the send, so an interrupted send is visible as in-flight rather than as never-attempted |
| 3 | `Retry On Fail` replays a send that already landed | ⚠️ **ANALYSED — NOT PROVEN**, and the blueprint's wording does not hold verbatim here | See below |
| 4 | No dead-letter path, so a stalled placement is invisible | ⚠️ **ANALYSED — NOT PROVEN** | Bounded retries, then a dead-letter state a person is required to resolve |
| 5 | No shared state across workflows, so two chases approach the same carrier | ⚠️ **ANALYSED — NOT PROVEN** | One state machine over one row; a chase is not a second workflow with its own idea of the world |
| 6 | Wait-node timer loss across restart | ⚠️ **ANALYSED — NOT PROVEN** | The chase is a `follow_up_at` column read by the scheduler, not a timer held in a process |

### On failure mode 3, specifically

The blueprint states this one as *"the mail call carries no idempotency key."* **In this workflow it
does** — nodes 6 and 7 exist precisely to compute one, and it is the same key the Python arm uses.
The baseline was built past the blueprint's description of it, and saying so is the point: a
baseline improved until it still fails is worth something, and a baseline described as worse than it
is, is worth nothing.

What remains of the mode is narrower and still real: an identity-derived key only helps against a
receiver that honours it. Against email — the actual transport for a market approach — there is no
such header and no such behaviour, so a retried send is a second email. That is an argument, not a
measurement, and it is filed as analysis.

### On failure mode 4, specifically

The workflow is not silent about failures. `Record Send Failure` sets the row back to `retrying` and
`Log Send Failure` writes an audit event. What is missing is everything after that: nothing bounds
how many times a row comes back round, nothing gives up, nothing escalates, and nothing distinguishes
a row that has failed forty times from one that has failed once. A retry loop with no floor is not a
dead-letter path — it is a stalled placement that looks busy.

---

## Why the failure is the execution model, not the builder

There is no version of this workflow in which the eligibility check is *inside* the claim, because
n8n has no claim to put it inside. `Eligible To Approach?` re-asserts the state — which is exactly
what a careful builder does — and reads a snapshot detached three nodes earlier. `Mark Approach Sent`
runs after the send because it is recording the send. Adding `AND state = 'eligible'` to that
`UPDATE` would change nothing that matters: by then the email has arrived, and a guard there could
only make the table disagree with the underwriter's inbox, which is the quieter failure rather than
the smaller one.

That is the whole finding. Not *n8n is bad* — the workflow above is a reasonable piece of
engineering and would run a real desk adequately for a long time. The finding is that **a workflow
engine without a claim boundary cannot make an irreversible act happen at most once**, and that the
cost of finding this out in production is a market that cannot be re-approached.
