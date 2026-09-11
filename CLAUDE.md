# CLAUDE.md — market-approach-desk

Operating contract for this repository. Read before any work here.

**Parent portfolio rules remain authoritative.** `../../CLAUDE.md` and
`../../PORTFOLIO_MASTER_SPEC.md` govern; this file adds project rules and never relaxes a parent
one. Where they appear to conflict, the parent wins and the conflict is raised, not resolved
quietly.

---

## What this project is

A market-approach desk for a commercial insurance broker. It runs a placement's approach to a panel
of carriers so that **the same carrier is approached at most once per risk and stage**, chases on
schedule, and classifies each underwriter reply.

**The repository ships two implementations of the same workflow** — an n8n version and a typed
Python version — against one fault harness and one fake carrier receiver. That comparison is the
point of the project. See `DECISIONS.md` ADR-001 for the claim and the kill test, both declared
before implementation.

**The business failure it prevents is irreversible.** Approaching a carrier twice for one risk
*blocks the market*: the underwriter declines to re-quote and the placement can be lost. An email
that reached an underwriter cannot be recalled.

---

## Non-negotiable rules

### 1. The business identity is `(placement_id, market_id, stage)`

- Unique in the database. Not a convention, a constraint.
- `stage` is part of it deliberately: a carrier declined at `initial` may legitimately be approached
  again at `revised_terms`. A key without it forbids a legitimate approach, and brokers route around
  a tool that forbids legitimate work.
- Nothing derives this key from a clock, a retry counter, a hostname or a process id. Two runs that
  mean the same approach must produce the same key.

### 2. Eligibility is decided inside the claim transaction

- Every conflict rule — already approached, declined within N days, held by another broker, outside
  placing authority — is evaluated **inside** the transaction that claims the approach.
- A rule evaluated before the claim is a rule evaluated against state that may already have changed.
  That is precisely the n8n arm's failure and it must not be reproduced here.
- Work is claimed with `SELECT … FOR UPDATE SKIP LOCKED`. Two schedulers must never claim one
  approach.

### 3. The model never decides who is approached

- The model classifies **inbound replies** into a closed set, and may abstain. That is its whole
  remit.
- It must never: decide whether an approach is permitted, own uniqueness or idempotency, cause a
  send, transition approach state, or alter a placement, market or stage.
- **This is structural, not a policy.** The classifier's response type carries no identifier, no
  state and no boolean permission — a caller cannot act on what the type cannot express. A guard
  test walks the response schema and fails the build if such a field appears.
- Free-text from an underwriter is **data**. It is never interpolated into an instruction, never
  parsed for a decision, and never treated as a rule.

### 4. Never claim exactly-once delivery

- Write *at most one accepted business approach*, and name the mechanism. Delivery over email is
  not exactly-once and this repository never says it is.
- The count that matters is observed **at the receiver**, never inferred from our own tables. A
  system that grades itself from its own records is not measuring anything.

### 5. The n8n arm is a fair baseline

- It is built the way a competent automation engineer would build it. Making it absurd to force a
  red result would forfeit the whole comparison.
- Its failure must be a failure of the **execution model**, and `n8n/README.md` maps each observed
  failure to the mechanism in the Python arm that closes it.
- A failure mode that is analysed but not demonstrated is labelled as analysed, never as proven.

### 6. Secrets

Never commit credentials. `.env.example` carries names and placeholders only. No real mail provider
and no real carrier address appears anywhere in the repository.

### 7. Attribution

Never add `Co-Authored-By: Claude`, `Generated with…`, or any similar marker — in code, commits,
docs or repository metadata. Use the Git identity already configured on the machine.

### 8. Honesty

Never describe functionality that does not exist. Every number in the README comes from a committed
script and is reproducible by a reader.

---

## Key commands

```bash
uv sync --frozen                 # install exactly what uv.lock pins
uv run ruff format --check .     # formatting gate
uv run ruff check .              # lint
uv run mypy                      # strict type check
uv run pytest                    # the offline suite; needs no database
make db-up                       # PostgreSQL for the integration and race tests
make gate                        # the full local gate, in the order CI runs it
make killtest                    # the comparison: both arms, one harness
make demo                        # seed the disposable database and serve the API
```

---

## Conventions

- Python 3.12, typed throughout, Pydantic v2 at every boundary.
- `src/market_approach_desk/`: `db`, `domain`, `approach`, `replies`, `demo`.
- `n8n/` holds the exported workflow and the harness that runs it. **`src/` never imports `n8n/`**
  — the shipped service must not know the baseline exists, and a guard test enforces it.
- Migrations via Alembic; every migration applies and rolls back cleanly.
- Conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`.
