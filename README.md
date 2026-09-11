# market-approach-desk

**An insurance broker approaches a panel of carriers to place a risk. Approaching the same carrier
twice for the same risk *blocks the market* — the underwriter declines to re-quote, the account is
deprioritised, and the placement can be lost. There is no retraction: an email that reached an
underwriter has reached them.**

This repository ships **two implementations of the same workflow** — a realistic n8n one and a typed
Python one — against **one fault harness** and **one fake carrier receiver**. The comparison is the
point.

---

## The measured result

One placement, one carrier, one stage. Two scheduler executions forced to overlap at the moment the
failure lives, and both arms measured at the receiver — never by asking either arm what it thinks it
did.

| Arm | Approaches the carrier observed | Distinct idempotency keys |
|---|---|---|
| **n8n** | **2** | 1 |
| **Python** | **1** | 1 |

Measured on 2026-09-11. Regenerate with `make killtest`; the numbers above are written by the test
that measured them into [`docs/killtest.json`](docs/killtest.json), and CI re-runs it on every push.

**Be precise about what the n8n failure is.** Both of its sends carry the *same* idempotency key, so
a receiver that deduplicated on that header could have collapsed them. An underwriter's mailbox has
no such feature — which is why the receiver does not either, by default. The commercial failure is
real: two emails arrived.

### Why the n8n arm duplicates

The workflow does what a competent automation engineer would build:

```
Schedule Trigger → read due approaches → filter eligible → HTTP send → write state back
```

There is no transaction around those steps and no lock across executions, so a second scheduled
execution reads the due-set while the first is **between its send and its write**. Both see the same
approach as eligible. Both send. That is not an n8n bug — it is what a visual workflow runner does,
and it is invisible until the day two executions overlap.

### What the Python arm does instead

```
claim (ONE transaction: SELECT … FOR UPDATE SKIP LOCKED + every eligibility rule) → commit
   → send → record outcome
```

Three mechanisms, and each covers what the others cannot:

1. **`SELECT … FOR UPDATE SKIP LOCKED`** — a concurrent scheduler does not see a claimed row. It
   skips rather than blocks, so two workers share the queue instead of serialising on it.
2. **Every eligibility rule evaluated *inside* that transaction.** A rule evaluated before the claim
   is a rule evaluated against state that may already have changed — the n8n failure, one layer
   down.
3. **A unique constraint on `(placement_id, market_id, stage)`** underneath both, as the thing that
   cannot be argued with.

**The send is deliberately outside the claim transaction.** Holding a database transaction open
across a network call makes the second scheduler wait instead of skip, which looks safer and quietly
converts two workers into one.

### Why `stage` is in the business identity

A carrier that declined the initial presentation may legitimately be approached again on revised
terms. Keying on `(placement, market)` alone would forbid that — and a tool that forbids legitimate
work gets routed around in a spreadsheet, where nothing is recorded at all.

---

## Where AI is allowed, and where it is forbidden

**Allowed:** classifying an inbound underwriter reply into a closed set —
`interested` · `declined` · `needs_information` · `referred` · `unclear` — with abstention.

**Forbidden, structurally rather than by policy.** The classifier's response type carries no
identifier, no state, no permission flag and no numeric field. A model therefore *cannot express*
"approach this carrier", "this is allowed", or "retry" — so no caller downstream can act on it. A
guard test walks the response schema and fails the build if such a field appears.

The one thing a classification changes: a reply classified `declined` starts a thirty-day cooling
period. That is a rule a person wrote, evaluated inside the claim transaction, applied to a
classification a person can see and correct on the reply itself.

**Live model quality is NOT MEASURED.** The shipped package contains no HTTP client and cannot reach
a provider — a guard test enforces it. What ships is a port plus a deterministic stand-in whose
`model_id` is `stand-in` and whose rationale opens by saying no model produced it.

---

## Run it

```bash
make db-up && make demo    # PostgreSQL, migrations, and the seeded board
make api                   # the API on :8000
make killtest              # THE COMPARISON: both arms, one harness
```

```bash
cd frontend && npm install && npm run dev    # the operator console on :3000
```

The n8n workflow is importable and runnable for real:

```bash
cd n8n && docker compose up -d    # n8n on :5678, then import market-approach.workflow.json
```

---

## What you are looking at

| | |
|---|---|
| **Board** | placements, the carrier approach matrix, state per carrier, overdue follow-ups, reply classification, block reasons |
| **Comparison** | the kill-test result, rendered from the run that produced it |
| **Audit** | the append-only trail — who approached this carrier, and when |

---

## Honest limits

- **One failure mode is proven; five are analysed.** The portfolio blueprint names six ways the n8n
  arm can fail. This repository demonstrates **overlapping schedule executions** deterministically.
  The other five are analysed in [`n8n/README.md`](n8n/README.md) and are labelled as analysed —
  an analysed failure mode is not evidence.
- **Not exactly-once delivery.** The claim is *at most one accepted business approach per
  `(placement, market, stage)` under the tested contract*, measured at the receiver. Email delivery
  is not exactly-once and this repository never says it is.
- **No live model has been called.** See above.
- **The carrier receiver is in-process.** It stands where an underwriter's mailbox would; there is
  no real mail provider in this repository, so a deployment cannot accidentally acquire one.

---

## Documents

| File | Purpose |
|---|---|
| [`DECISIONS.md`](DECISIONS.md) | ADR-001: the claim and the kill test, **declared before implementation** |
| [`CLAUDE.md`](CLAUDE.md) | the operating rules this repository is built under |
| [`n8n/README.md`](n8n/README.md) | the baseline workflow, and its six failure modes |
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | what exists, what is verified, what is not |
