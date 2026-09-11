# Decisions

Why this repository is shaped the way it is. Written as it is built, and never rewritten to look
tidier afterwards — a decision that turned out wrong is corrected with a new entry, not edited.

---

## ADR-001 — The reliability claim, and the kill test that can refute it

**Status:** accepted. **Date:** 2026-09-11, **before any implementation.** The test below is
declared first on purpose: a kill test written after the code is a description of what the code
does.

### The commercial failure this prevents

A broker placing a commercial risk approaches a panel of carriers. Approaching **the same carrier
twice for the same risk at the same stage** is an industry-named, irreversible loss — it *blocks
the market*. The underwriter declines to re-quote, deprioritises the account, and the placement can
be lost. There is no retraction: an email that reached an underwriter has reached them.

### The claim

> **Under overlapping scheduler executions over one due-set, the Python arm causes the external
> carrier receiver to observe at most one approach per `(placement, market, stage)`. The n8n arm
> does not.**

Three things that claim deliberately does **not** say:

- **Not "exactly once".** Delivery is not guaranteed; a send that fails is retried and may be
  observed twice by a receiver that also fails to acknowledge. The claim is about *accepted
  business approaches* — rows the system commits to — and it is measured at the receiver, not in
  our own tables.
- **Not "n8n is bad".** The n8n arm is built the way a competent automation engineer would build
  it, and its failure is a property of the execution model, not of the builder. If it can be made
  safe inside n8n without leaving n8n, that is a result worth publishing and it will be published.
- **Not a claim about every n8n failure mode.** The blueprint names six. This repository proves
  **one** deterministically and documents the rest as analysed, with the distinction visible in the
  README. An analysed-but-unproven failure mode is not evidence.

### The business identity

`(placement_id, market_id, stage)`, unique in the database.

`stage` is in the key and that is a domain decision, not a hedge. A carrier declined at `initial`
may legitimately be approached again at `revised_terms` — different risk presentation, different
question. Keying on `(placement, market)` alone would forbid a legitimate second approach and the
system would be wrong in the expensive direction: brokers would work around it, outside the tool,
where nothing is recorded.

### The kill test, declared now

**Setup.** One placement, one market, one stage, eligible for approach. Identical fixtures for both
arms. One fake carrier receiver that counts what it observes, keyed on business identity.

**Execution.** Two scheduler ticks forced to overlap — both must observe the due-set before either
records completion. Forced with an explicit barrier, never by sleeping and hoping.

**Expected:**

| Arm | Approaches observed at the receiver for one identity |
|---|---|
| n8n | **more than one** |
| Python | **exactly one** |

**If the n8n arm cannot be made to duplicate under this harness**, the graduation story collapses
and this repository is an ordinary CRUD workflow. The blueprint says to replace it, and that would
be the honest outcome — recorded here before it is known which way it goes.

**The test may not be weakened after implementation.** If the Python arm fails it, the Python arm
is wrong.

### The mechanism the Python arm will use, and what it will not use

The minimum that supports the claim:

- a unique constraint on the business identity;
- a claim transaction using `SELECT … FOR UPDATE SKIP LOCKED`, with the eligibility rules evaluated
  **inside** it — a rule evaluated before the claim is a rule evaluated against state that may
  already have changed;
- an explicit approach state machine;
- an idempotency key on the outbound send, so a retry of an accepted approach is the same send.

**No transactional outbox.** Project 1 needed one because the ledger effect and the state change
had to commit together across a process boundary. Here the irreversible act is an email, the
receiver is queried directly by the test, and an outbox would be architecture imported for its own
sake. If the kill test shows it is needed, it gets added and this paragraph is corrected.

### Where the model is allowed, and where it is forbidden

**Allowed:** classifying an inbound underwriter reply into a closed set, with abstention.

**Forbidden, structurally rather than by policy:** deciding whether an approach may happen, owning
uniqueness or idempotency, causing a send, mutating commercial identity, or transitioning approach
state. The classifier's output type contains no identifier and no state — it cannot express those
things, so no caller can act on them.

---
