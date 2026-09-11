"""A node-by-node model of ``market-approach.workflow.json`` running under n8n's execution model.

Why a model exists at all
-------------------------

The comparison in ADR-001 has to be runnable by a stranger: ``make killtest``, one command, the same
numbers every time. Driving a real n8n instance from a test would make the result depend on a
container, a credential and a scheduler, and a result nobody can reproduce is an anecdote. So the
baseline arm is **modelled** rather than driven, and that is a real weakening of the evidence which
belongs here rather than in a footnote: **this module is an argument about n8n's execution model,
checked against the exported workflow — not a recording of n8n running.** The exported JSON is the
artefact a reader imports and runs for themselves, and ``README.md`` says how.

Two things keep the argument honest. The module is small enough to audit line by line, and it runs
against **the same PostgreSQL database, the same schema and the same seeded rows as the Python
arm**, issuing the statements the workflow's Postgres nodes issue. The store is not a variable in
this experiment. The execution model is the only thing that differs, which is the only way the
comparison means anything.

The n8n semantics this module *does* model
------------------------------------------

1. **An execution reads its work at the start and then carries items as a detached snapshot.** The
   Postgres node emits plain JSON items; no later node re-reads the row. A row another execution
   changed in the meantime is not noticed, because nothing in n8n would notice.
2. **No lock spans executions.** Two overlapping scheduler ticks both read the same due-set. n8n
   offers a concurrency *limit*, which bounds how many executions run at once; it has no equivalent
   of ``SELECT … FOR UPDATE SKIP LOCKED``, which bounds what each one may claim. Those are different
   guarantees and only the second prevents this failure.
3. **No transaction spans read → send → write.** Every Postgres node runs its own statement in its
   own session, exactly as this module does. Each statement is atomic; the sequence is not, and
   there is no node that could make it so.
4. **The state write happens after the irreversible act.** ``Mark Approach Sent`` runs after
   ``Send Approach To Carrier`` — it must, because it is recording the send. Everything between the
   read and that write is a window in which another execution sees an unclaimed row.
5. **Per-item looping through ``Loop Over Approaches``**, so the commit granularity here is the
   workflow's: one item, with no boundary either side of it.
6. **The HTTP node's error output**, routing a refused send to ``Record Send Failure`` and
   ``Log Send Failure`` rather than aborting the pass.

What this module deliberately does **not** model
------------------------------------------------

Naming these matters more than listing what is modelled, because an unnamed gap reads as a claim:

- **Retry On Fail.** The JSON sets ``retryOnFail`` with three tries on both HTTP nodes; this module
  sends once and routes a refusal straight to the error output. Modelling the replay would move the
  duplicate count for a reason unrelated to the claim under test, so that failure mode is
  **analysed in ``README.md`` and not counted here**.
- **Wait-node resumption.** ``Wait Before Chase`` serialises an execution to disk and resumes it
  hours later. This module records the suspension and abandons the branch. It never resumes, so the
  chase send and the timer-loss-across-restart failure mode are **not** exercised.
- **Mid-batch crash.** :class:`ExecutionHook` may raise, which is what a crash between two nodes
  looks like from the outside, and a caller is free to use it that way. **No such scenario ships
  here and no result is claimed from one.**
- **Queue mode, worker recovery, execution pruning, real expression evaluation, credential
  handling, and the HTTP transport itself** — the send goes to the in-process
  :class:`~.receiver.CarrierReceiver` both arms share, because the measurement has to be identical
  even where the transport is not.
- **``NOW()`` versus a pinned instant.** The exported workflow uses PostgreSQL's ``NOW()``; this
  module binds the tick instant so a test can pin time and get the same answer twice. The
  statements are otherwise the ones in the JSON.

Measurement
-----------

Both arms build the identity with :class:`~.identity.ApproachIdentity`, derive the outbound key with
:func:`~.identity.idempotency_key`, and send through the same
:class:`~.receiver.CarrierReceiver`. :func:`verify_key_fidelity` proves the workflow's
Set-plus-Crypto pair computes the byte-identical key before any race runs, so a difference in the
observed counts is a difference in behaviour and never in bookkeeping.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import enum
import hashlib
import uuid
from collections.abc import Iterator, Sequence
from typing import Any, Final, Protocol, cast

from sqlalchemy import BindParameter, CursorResult, DateTime, bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from market_approach_desk.domain.identity import (
    ApproachIdentity,
    ApproachState,
    Stage,
    idempotency_key,
)
from market_approach_desk.domain.receiver import CarrierReceiver, ReceiverError

__all__ = [
    "ACTOR",
    "ARM",
    "IDEMPOTENCY_PAYLOAD_EXPRESSION",
    "IDENTITY_EXPRESSION",
    "NODE_SEQUENCE",
    "DueItem",
    "ExecutionHook",
    "IdempotencyKeyStrategy",
    "N8nWorkflowExecution",
    "NodeEvent",
    "NodeOutcome",
    "OverlapResult",
    "RaceNotRunError",
    "n8n_idempotency_payload",
    "parse_identity",
    "run_overlapping_executions",
    "run_workflow_pair",
    "verify_key_fidelity",
]

#: Stamped on everything this arm sends. The receiver records it as provenance and never branches
#: on it — both arms are graded by the same object with the same rules.
ARM: Final = "n8n"

#: Who the audit rows say did it. The baseline has one actor because n8n executions are anonymous
#: to the database: nothing in an n8n Postgres node knows which execution it belongs to.
ACTOR: Final = "n8n-scheduler"

# --- Node names, spelled exactly as ``market-approach.workflow.json`` spells them ---------------
#
# Constants rather than literals so a node renamed in one place and not the other breaks a test
# instead of quietly making the trace describe a workflow that no longer exists.

NODE_SCHEDULE_TRIGGER: Final = "Schedule Trigger"
NODE_READ_DUE_APPROACHES: Final = "Read Due Approaches"
NODE_LOOP_OVER_APPROACHES: Final = "Loop Over Approaches"
NODE_ELIGIBLE_TO_APPROACH: Final = "Eligible To Approach?"
NODE_SKIP_INELIGIBLE: Final = "Skip Ineligible Approach"
NODE_COMPUTE_IDENTITY: Final = "Compute Business Identity"
NODE_DERIVE_KEY: Final = "Derive Idempotency Key"
NODE_SEND_APPROACH: Final = "Send Approach To Carrier"
NODE_MARK_SENT: Final = "Mark Approach Sent"
NODE_LOG_SENT: Final = "Log Approach Sent"
NODE_SCHEDULE_FOLLOW_UP: Final = "Schedule Follow-Up"
NODE_INCEPTION_IMMINENT: Final = "Inception Within 14 Days?"
NODE_WAIT_BEFORE_CHASE: Final = "Wait Before Chase"
NODE_RECORD_SEND_FAILURE: Final = "Record Send Failure"
NODE_LOG_SEND_FAILURE: Final = "Log Send Failure"
NODE_PASS_COMPLETE: Final = "Pass Complete"

#: Every node this module can execute, in connection order. ``Send Chase To Carrier`` is absent on
#: purpose: it sits behind ``Wait Before Chase``, which this module never resumes.
NODE_SEQUENCE: Final[tuple[str, ...]] = (
    NODE_SCHEDULE_TRIGGER,
    NODE_READ_DUE_APPROACHES,
    NODE_LOOP_OVER_APPROACHES,
    NODE_ELIGIBLE_TO_APPROACH,
    NODE_SKIP_INELIGIBLE,
    NODE_COMPUTE_IDENTITY,
    NODE_DERIVE_KEY,
    NODE_SEND_APPROACH,
    NODE_MARK_SENT,
    NODE_LOG_SENT,
    NODE_SCHEDULE_FOLLOW_UP,
    NODE_INCEPTION_IMMINENT,
    NODE_WAIT_BEFORE_CHASE,
    NODE_RECORD_SEND_FAILURE,
    NODE_LOG_SEND_FAILURE,
    NODE_PASS_COMPLETE,
)

# --- The expressions the workflow evaluates, quoted here so drift is visible -------------------

#: The literal ``identity`` assignment in ``Compute Business Identity``.
IDENTITY_EXPRESSION: Final = "={{ $json.placement_id }}/{{ $json.market_id }}/{{ $json.stage }}"

#: The literal ``idempotency_payload`` assignment, which ``Derive Idempotency Key`` then SHA-256s.
#: Its domain prefix is copied from :mod:`market_approach_desk.domain.identity`, and
#: :func:`verify_key_fidelity` is what stops the copy rotting.
IDEMPOTENCY_PAYLOAD_EXPRESSION: Final = (
    "=mad.approach-identity.v1|{{ $json.placement_id }}|{{ $json.market_id }}|{{ $json.stage }}"
)

_HASH_DOMAIN: Final = "mad.approach-identity.v1"

#: How long an execution waits at the barrier before giving up. Generous, because it should never
#: be reached — it exists so a broken harness fails a CI job instead of hanging one.
_BARRIER_TIMEOUT_SECONDS: Final = 30.0

#: ``Loop Over Approaches`` runs ``batchSize: 1``.
_BATCH_SIZE: Final = 1

#: The interval in ``Schedule Follow-Up``.
_FOLLOW_UP_DAYS: Final = 5

#: Terminal-ish states the workflow's own IF re-asserts against. Kept as a tuple of the domain
#: enum's values so a new state cannot be added to the domain and silently ignored here.
_SENDABLE_STATE: Final = ApproachState.ELIGIBLE.value

# --- The statements the Postgres nodes issue ---------------------------------------------------
#
# Written out as SQL rather than built with the ORM. The baseline's Postgres nodes send strings,
# and an ORM here would quietly acquire identity-mapping and unit-of-work behaviour that n8n does
# not have — which would hand the baseline a guarantee it cannot actually get.

_SQL_READ_DUE: Final = """
SELECT a.id                                                 AS approach_id,
       a.placement_id,
       a.market_id,
       a.stage,
       a.state,
       a.attempt_count,
       p.reference                                          AS placement_reference,
       m.name                                               AS market_name,
       m.contact_email                                      AS underwriter_email,
       m.within_placing_authority                           AS within_placing_authority,
       (p.inception_on <= CAST(:now AS date) + INTERVAL '14 days') AS inception_imminent,
       EXISTS (
           SELECT 1
           FROM market_approach declined
           JOIN carrier_reply reply ON reply.approach_id = declined.id
           WHERE declined.placement_id = a.placement_id
             AND declined.market_id    = a.market_id
             AND reply.classification  = 'declined'
             AND reply.received_at     > :now - INTERVAL '90 days'
       )                                                    AS declined_within_window
FROM market_approach a
JOIN placement p ON p.id = a.placement_id
JOIN market    m ON m.id = a.market_id
WHERE a.state    = 'eligible'
  AND a.due_at IS NOT NULL
  AND a.due_at  <= :now
ORDER BY a.due_at, a.id
LIMIT 50
"""

_SQL_MARK_SENT: Final = """
UPDATE market_approach
SET state           = 'sent',
    sent_at         = :now,
    attempt_count   = attempt_count + 1,
    due_at          = NULL,
    idempotency_key = :key
WHERE id = :approach_id
"""

_SQL_LOG_EVENT: Final = """
INSERT INTO audit_event (id, occurred_at, verb, identity, actor, detail)
VALUES (gen_random_uuid(), :now, :verb, :identity, :actor, :detail)
"""

_SQL_SCHEDULE_FOLLOW_UP: Final = """
UPDATE market_approach
SET follow_up_at = :follow_up_at
WHERE id = :approach_id
"""

_SQL_RECORD_FAILURE: Final = """
UPDATE market_approach
SET state         = 'retrying',
    attempt_count = attempt_count + 1,
    due_at        = :retry_at
WHERE id = :approach_id
"""


def _timestamp(name: str) -> BindParameter[dt.datetime]:
    """A ``timestamptz`` bind parameter.

    Typed explicitly because asyncpg refuses a parameter whose type PostgreSQL cannot infer — and
    ``CAST(:now AS date)`` in the read query is exactly such a position. The failure is an opaque
    *could not determine data type* at run time, so it is pinned here rather than discovered later.
    """
    return bindparam(name, type_=DateTime(timezone=True))


def n8n_idempotency_payload(identity: ApproachIdentity) -> str:
    """The exact string ``Compute Business Identity`` builds for the Crypto node to hash.

    Spelled out in Python so :func:`verify_key_fidelity` can check it against the domain function
    the shipped arm uses. Two arms computing *nearly* the same key would be the worst available
    outcome: the receiver would report two distinct keys, the comparison would look decisive, and
    the difference would be a typo in a workflow expression rather than anything about n8n.
    """
    return f"{_HASH_DOMAIN}|{identity.placement_id}|{identity.market_id}|{identity.stage.value}"


def verify_key_fidelity(identity: ApproachIdentity) -> None:
    """Raise unless the workflow's key and the domain's key are byte-identical.

    Called before every race. Cheap, and it turns a silent measurement bug into a loud failure at
    the one point the whole comparison rests on.
    """
    modelled = hashlib.sha256(n8n_idempotency_payload(identity).encode("utf-8")).hexdigest()
    canonical = idempotency_key(identity)
    if modelled != canonical:
        raise AssertionError(
            "the modelled n8n idempotency key has drifted from the domain's, so the two arms are "
            "no longer measured with the same instrument and the comparison is void until the "
            f"Crypto node's payload is corrected. modelled={modelled} canonical={canonical}"
        )


def parse_identity(value: str) -> ApproachIdentity:
    """Rebuild an :class:`ApproachIdentity` from its ``placement/market/stage`` string form.

    The kill test hands the identity across as a string, because that is the form the receiver
    counts in. Parsing it back is what lets :func:`verify_key_fidelity` run against the identity
    actually being raced rather than against one this module invented.
    """
    parts = value.split("/")
    if len(parts) != 3:
        raise ValueError(
            f"{value!r} is not a business identity: expected placement/market/stage, and an "
            "identity that cannot be parsed cannot be verified against the domain's key"
        )
    return ApproachIdentity(
        placement_id=uuid.UUID(parts[0]), market_id=uuid.UUID(parts[1]), stage=Stage(parts[2])
    )


class IdempotencyKeyStrategy(enum.StrEnum):
    """Which key the send carries. The shipped JSON uses the first; the second is more common.

    The distinction decides whether a duplicate is *recoverable in principle*. Two approaches under
    one key could be collapsed by a receiver that deduplicates. Two approaches under two keys are
    two pieces of work, and no receiver-side feature could ever have saved them. ADR-001 asks for
    both numbers precisely because they are different failures.
    """

    #: What ``market-approach.workflow.json`` does: SHA-256 over the business identity, identical to
    #: the Python arm's. The strongest key obtainable without leaving n8n, and it is given to the
    #: baseline deliberately — a baseline handicapped at the start proves nothing.
    BUSINESS_IDENTITY = "business_identity"

    #: The widespread idiom of scoping a request id to the execution (``{{ $execution.id }}``).
    #: **Not what the shipped workflow does.** Modelled because it is what most real builds do, and
    #: because it shows the duplicate becoming unrecoverable rather than merely unsuppressed.
    EXECUTION_SCOPED = "execution_scoped"


class NodeOutcome(enum.StrEnum):
    """What happened at one node, as an n8n execution log would show it."""

    #: The node ran and passed its item on.
    EXECUTED = "executed"

    #: An IF sent the item down the branch that does nothing further.
    SKIPPED = "skipped"

    #: The HTTP node's second output fired.
    ERROR_OUTPUT = "error_output"

    #: A Wait node put the execution to disk. This module never resumes one.
    SUSPENDED = "suspended"


@dataclasses.dataclass(frozen=True, slots=True)
class NodeEvent:
    """One line of the execution trace. Carries no timing, so assertions on it are stable."""

    execution_id: str
    node: str
    outcome: NodeOutcome
    detail: str = ""


class ExecutionHook(Protocol):
    """Awaited after every node, so a caller can interleave executions on purpose.

    The point is that the race in ADR-001 is **forced, never awaited into existence**. A harness
    that sleeps and hopes produces a result that depends on machine load, and a result that depends
    on machine load is not evidence of anything.

    A hook may also raise, which is what a crash between two nodes looks like. Nothing in this
    repository does that, and no result is claimed from it.
    """

    async def __call__(self, *, node: str, execution_id: str) -> None: ...


async def _no_hook(*, node: str, execution_id: str) -> None:
    """The default: run straight through, interleaving nothing."""


@dataclasses.dataclass(frozen=True, slots=True)
class DueItem:
    """One n8n item as ``Read Due Approaches`` emits it.

    **Frozen, and that is the most important line in the module.** An n8n item is a detached copy of
    what the query returned; once the Postgres node has emitted it, nothing downstream re-reads the
    row, so a change another execution makes in between is invisible to every later node. Handing
    around a live ORM object would accidentally grant the baseline a consistency guarantee n8n does
    not have, and would rig the comparison in n8n's favour through an implementation detail.
    """

    approach_id: uuid.UUID
    placement_id: uuid.UUID
    market_id: uuid.UUID
    stage: Stage
    state: str
    attempt_count: int
    placement_reference: str
    market_name: str
    underwriter_email: str
    within_placing_authority: bool
    inception_imminent: bool
    declined_within_window: bool


class _ReadBarrier:
    """Holds every execution at ``Read Due Approaches`` until all of them have read.

    An :class:`asyncio.Event` rather than a sleep, and that is the whole design: the overlap
    ADR-001 describes becomes a **precondition of the run** instead of something the run might get
    lucky and observe. If the barrier is never satisfied the wait times out and the run fails
    loudly, because *no duplicate* and *the race never happened* must never produce the same output.
    """

    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._arrived = 0
        self._released = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived >= self._parties:
            self._released.set()
        await asyncio.wait_for(self._released.wait(), timeout=_BARRIER_TIMEOUT_SECONDS)


class N8nWorkflowExecution:
    """One execution of ``market-approach.workflow.json`` against a real database.

    An instance is one scheduler tick. Two instances sharing an engine and a
    :class:`~.receiver.CarrierReceiver` are two overlapping ticks, which is the entire experiment.

    **Every node opens its own session and commits it before the next node starts.** That is not a
    convenience; it is the semantic under test. There is no n8n node that opens a transaction at
    the read and commits it after the write, so there must be none here.
    """

    def __init__(
        self,
        *,
        execution_id: str,
        engine: AsyncEngine,
        receiver: CarrierReceiver,
        now: dt.datetime,
        hook: ExecutionHook = _no_hook,
        key_strategy: IdempotencyKeyStrategy = IdempotencyKeyStrategy.BUSINESS_IDENTITY,
    ) -> None:
        self._execution_id = execution_id
        self._engine = engine
        self._receiver = receiver
        self._now = now
        self._hook = hook
        self._key_strategy = key_strategy
        self._trace: list[NodeEvent] = []

    @property
    def trace(self) -> tuple[NodeEvent, ...]:
        return tuple(self._trace)

    async def run(self) -> tuple[NodeEvent, ...]:
        """Execute the workflow once and return its trace."""
        await self._emit(NODE_SCHEDULE_TRIGGER, NodeOutcome.EXECUTED, "tick")
        due = await self._read_due_approaches()
        for batch in self._loop_over_approaches(due):
            await self._emit(
                NODE_LOOP_OVER_APPROACHES, NodeOutcome.EXECUTED, f"{len(batch)} item(s)"
            )
            for item in batch:
                await self._process_item(item)
        await self._emit(NODE_PASS_COMPLETE, NodeOutcome.EXECUTED, f"{len(due)} item(s) read")
        return self.trace

    # --- nodes ---------------------------------------------------------------------------------

    async def _read_due_approaches(self) -> tuple[DueItem, ...]:
        """``Read Due Approaches``. Its own session, closed before anything is sent."""
        statement = text(_SQL_READ_DUE).bindparams(_timestamp("now"))
        async with AsyncSession(self._engine) as session:
            result = await session.execute(statement, {"now": self._now})
            rows = result.mappings().all()
        due = tuple(
            DueItem(
                approach_id=_as_uuid(row["approach_id"]),
                placement_id=_as_uuid(row["placement_id"]),
                market_id=_as_uuid(row["market_id"]),
                stage=Stage(str(row["stage"])),
                state=str(row["state"]),
                attempt_count=int(row["attempt_count"]),
                placement_reference=str(row["placement_reference"]),
                market_name=str(row["market_name"]),
                underwriter_email=str(row["underwriter_email"]),
                within_placing_authority=bool(row["within_placing_authority"]),
                inception_imminent=bool(row["inception_imminent"]),
                declined_within_window=bool(row["declined_within_window"]),
            )
            for row in rows
        )
        await self._emit(NODE_READ_DUE_APPROACHES, NodeOutcome.EXECUTED, f"{len(due)} row(s)")
        return due

    def _loop_over_approaches(self, due: Sequence[DueItem]) -> Iterator[tuple[DueItem, ...]]:
        """``Loop Over Approaches`` with ``batchSize: 1``.

        Yielding one item at a time is not cosmetic. It fixes the commit granularity of the pass at
        exactly one item with no boundary either side, which is what makes a crash mid-pass leave
        the table describing a different world than the underwriters' inboxes do.
        """
        for start in range(0, len(due), _BATCH_SIZE):
            yield tuple(due[start : start + _BATCH_SIZE])

    async def _process_item(self, item: DueItem) -> None:
        if not await self._eligible_to_approach(item):
            return
        identity = await self._compute_business_identity(item)
        key = await self._derive_idempotency_key(identity)
        if not await self._send_approach_to_carrier(item, identity, key):
            return
        await self._mark_approach_sent(item, key)
        await self._log_approach_sent(item, identity)
        await self._schedule_follow_up(item)
        await self._inception_within_14_days(item)

    async def _eligible_to_approach(self, item: DueItem) -> bool:
        """``Eligible To Approach?`` — the conflict rules, evaluated against the snapshot.

        **This is the defect, and nobody made a mistake to produce it.** The IF re-asserts the
        state, which is exactly what a careful builder does; it reads ``item``, and ``item`` was
        detached at ``Read Due Approaches``. There is nowhere in *this workflow's shape* to put this
        test that would be *inside* a claim, because its read is a plain ``SELECT`` — a claiming
        ``UPDATE … RETURNING`` in that same Postgres node would change that, and is not modelled
        here (see ``README.md``, "Why the failure is the shape") — so an execution that has
        already sent is invisible here. The Python arm answers the same questions inside the
        transaction that reserves the row, and that single difference is the whole comparison.
        """
        eligible = (
            item.state == _SENDABLE_STATE
            and item.within_placing_authority
            and not item.declined_within_window
        )
        await self._emit(
            NODE_ELIGIBLE_TO_APPROACH,
            NodeOutcome.EXECUTED,
            f"{'true' if eligible else 'false'} branch: {item.market_name}",
        )
        if not eligible:
            await self._emit(NODE_SKIP_INELIGIBLE, NodeOutcome.SKIPPED, item.market_name)
        return eligible

    async def _compute_business_identity(self, item: DueItem) -> ApproachIdentity:
        """``Compute Business Identity``: the Set node, built from the shared domain type.

        The Set node concatenates three fields; this constructs :class:`ApproachIdentity` and takes
        its ``__str__``. Same three fields, same separator — and using the shared type means a
        change to the domain's identity cannot leave the baseline quietly measuring something else.
        """
        identity = ApproachIdentity(
            placement_id=item.placement_id, market_id=item.market_id, stage=item.stage
        )
        await self._emit(NODE_COMPUTE_IDENTITY, NodeOutcome.EXECUTED, str(identity))
        return identity

    async def _derive_idempotency_key(self, identity: ApproachIdentity) -> str:
        """``Derive Idempotency Key``: the Crypto node's SHA-256 over the payload string."""
        if self._key_strategy is IdempotencyKeyStrategy.BUSINESS_IDENTITY:
            key = idempotency_key(identity)
        else:
            scoped = f"{n8n_idempotency_payload(identity)}|execution:{self._execution_id}"
            key = hashlib.sha256(scoped.encode("utf-8")).hexdigest()
        await self._emit(
            NODE_DERIVE_KEY, NodeOutcome.EXECUTED, f"{self._key_strategy.value}:{key[:12]}"
        )
        return key

    async def _send_approach_to_carrier(
        self, item: DueItem, identity: ApproachIdentity, key: str
    ) -> bool:
        """``Send Approach To Carrier``. True if the main output fired, False for the error output.

        **The irreversible act, and nothing has been written down yet.** Not because the workflow
        is ordered badly — it is ordered the only way it can be, since the write records the send —
        but because n8n has no way to reserve the row first and release the reservation if the send
        fails. Retry On Fail is not modelled; see the module docstring.
        """
        try:
            self._receiver.approach(identity=str(identity), idempotency_key=key, arm=ARM)
        except ReceiverError as error:
            await self._emit(NODE_SEND_APPROACH, NodeOutcome.ERROR_OUTPUT, str(error))
            await self._record_send_failure(item)
            await self._log_send_failure(item, identity, str(error))
            return False
        await self._emit(NODE_SEND_APPROACH, NodeOutcome.EXECUTED, item.underwriter_email)
        return True

    async def _mark_approach_sent(self, item: DueItem, key: str) -> None:
        """``Mark Approach Sent``.

        **There is no ``AND state = 'eligible'`` in the predicate, and adding one would not help.**
        By the time this statement runs the approach has already reached the carrier. A guard here
        could only make the table disagree with the underwriter's inbox, which is the quieter
        failure rather than the smaller one.
        """
        affected = await self._execute(
            _SQL_MARK_SENT,
            {"approach_id": item.approach_id, "key": key, "now": self._now},
            timestamps=("now",),
        )
        await self._emit(NODE_MARK_SENT, NodeOutcome.EXECUTED, f"{affected} row(s)")

    async def _log_approach_sent(self, item: DueItem, identity: ApproachIdentity) -> None:
        """``Log Approach Sent``. The baseline does keep an audit trail — that is not what it lacks.

        Two overlapping executions write two ``sent`` rows for one identity, which is a faithful
        record of what happened and no help at all: the trail is written after the email, so it
        documents the blocked market rather than preventing it.
        """
        await self._log_event("sent", identity, f"sent to {item.underwriter_email}")
        await self._emit(NODE_LOG_SENT, NodeOutcome.EXECUTED, str(identity))

    async def _schedule_follow_up(self, item: DueItem) -> None:
        """``Schedule Follow-Up``.

        The chase timer is a column on the approach, so a second execution simply overwrites it.
        No conflict, no error, no signal — the same shape of silence as the duplicate send, in a
        place where it costs nothing.
        """
        affected = await self._execute(
            _SQL_SCHEDULE_FOLLOW_UP,
            {
                "approach_id": item.approach_id,
                "follow_up_at": self._now + dt.timedelta(days=_FOLLOW_UP_DAYS),
            },
            timestamps=("follow_up_at",),
        )
        await self._emit(NODE_SCHEDULE_FOLLOW_UP, NodeOutcome.EXECUTED, f"{affected} row(s)")

    async def _inception_within_14_days(self, item: DueItem) -> None:
        """``Inception Within 14 Days?`` and, on its true branch, ``Wait Before Chase``.

        The wait is recorded and then abandoned. n8n would serialise the execution to disk and
        resume it hours later; this module has no scheduler and does not pretend to have one. The
        chase send therefore never happens here and nothing in this repository claims it does.
        """
        if not item.inception_imminent:
            await self._emit(NODE_INCEPTION_IMMINENT, NodeOutcome.EXECUTED, "false branch")
            return
        await self._emit(NODE_INCEPTION_IMMINENT, NodeOutcome.EXECUTED, "true branch")
        await self._emit(NODE_WAIT_BEFORE_CHASE, NodeOutcome.SUSPENDED, "resumption not modelled")

    async def _record_send_failure(self, item: DueItem) -> None:
        """``Record Send Failure``: back to ``retrying``, due again shortly.

        Which is a *re-schedule*, not a dead-letter path. Nothing counts how many times this row has
        come back round, and nothing ever gives up on it — see ``README.md``.
        """
        affected = await self._execute(
            _SQL_RECORD_FAILURE,
            {"approach_id": item.approach_id, "retry_at": self._now + dt.timedelta(minutes=15)},
            timestamps=("retry_at",),
        )
        await self._emit(NODE_RECORD_SEND_FAILURE, NodeOutcome.EXECUTED, f"{affected} row(s)")

    async def _log_send_failure(
        self, item: DueItem, identity: ApproachIdentity, detail: str
    ) -> None:
        """``Log Send Failure``."""
        await self._log_event("send_failed", identity, detail)
        await self._emit(NODE_LOG_SEND_FAILURE, NodeOutcome.EXECUTED, item.market_name)

    # --- plumbing ------------------------------------------------------------------------------

    async def _log_event(self, verb: str, identity: ApproachIdentity, detail: str) -> None:
        await self._execute(
            _SQL_LOG_EVENT,
            {
                "now": self._now,
                "verb": verb,
                "identity": str(identity),
                "actor": ACTOR,
                "detail": detail,
            },
            timestamps=("now",),
        )

    async def _execute(
        self,
        statement: str,
        parameters: dict[str, object],
        *,
        timestamps: tuple[str, ...] = (),
    ) -> int:
        """Run one statement in its own session and commit it. One node, one transaction.

        Deliberately the *only* way this class touches the database, so no future edit can
        accidentally widen a transaction across two nodes and hand the baseline a guarantee n8n
        never offered it.
        """
        prepared = text(statement).bindparams(*(_timestamp(name) for name in timestamps))
        async with AsyncSession(self._engine) as session, session.begin():
            result = await session.execute(prepared, parameters)
            # `Result` is the declared return type and only a `CursorResult` carries `rowcount`;
            # every statement routed through here is DML, so the narrowing is sound and is written
            # as a cast rather than silenced with an ignore comment.
            return int(cast("CursorResult[Any]", result).rowcount)

    async def _emit(self, node: str, outcome: NodeOutcome, detail: str = "") -> None:
        self._trace.append(
            NodeEvent(execution_id=self._execution_id, node=node, outcome=outcome, detail=detail)
        )
        await self._hook(node=node, execution_id=self._execution_id)


def _as_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


@dataclasses.dataclass(frozen=True, slots=True)
class OverlapResult:
    """What the carrier observed after overlapping executions, plus the traces that produced it.

    Both :attr:`approaches_observed` and :attr:`distinct_idempotency_keys` are reported because
    ADR-001 requires both: the first says the market was approached twice, the second says whether
    any receiver could ever have collapsed them.
    """

    identity: str
    executions: int
    key_strategy: IdempotencyKeyStrategy
    approaches_observed: int
    distinct_idempotency_keys: int
    duplicates: dict[str, int]

    #: How many executions actually reached the raced identity. Reported so a reader can tell a
    #: **safe** result from a result that measured nothing at all — see :class:`RaceNotRunError`.
    executions_that_reached_the_identity: int

    traces: tuple[tuple[NodeEvent, ...], ...]


class RaceNotRunError(RuntimeError):
    """The overlap ran but never touched the identity under test, so nothing was measured.

    **This exists because the two most different outcomes in this project produce the same number.**
    A safe arm reports one approach at the receiver; an arm that never found the row reports zero,
    and zero reads as *even safer*. A harness that returned quietly here would let an empty
    database, a stale fixture or a clock the wrong side of ``due_at`` publish themselves as a
    reliability result. So the run fails instead, and says which of the two it was.
    """


async def run_overlapping_executions(
    engine: AsyncEngine,
    *,
    receiver: CarrierReceiver,
    now: dt.datetime,
    identity: str,
    executions: int = 2,
    key_strategy: IdempotencyKeyStrategy = IdempotencyKeyStrategy.BUSINESS_IDENTITY,
) -> OverlapResult:
    """Force ``executions`` scheduler ticks to overlap over one due-set, and report what arrived.

    Every execution blocks after ``Read Due Approaches`` until all of them have read, so the
    interleaving is a precondition rather than a hope. The executions then run to completion with
    nothing coordinating them, because nothing in n8n would.
    """
    verify_key_fidelity(parse_identity(identity))

    barrier = _ReadBarrier(executions)

    async def interleave_after_read(*, node: str, execution_id: str) -> None:
        if node == NODE_READ_DUE_APPROACHES:
            await barrier.wait()

    runs = [
        N8nWorkflowExecution(
            execution_id=f"n8n-exec-{index}",
            engine=engine,
            receiver=receiver,
            now=now,
            hook=interleave_after_read,
            key_strategy=key_strategy,
        )
        for index in range(executions)
    ]
    traces = await asyncio.gather(*(run.run() for run in runs))

    reached = sum(
        1
        for trace in traces
        if any(event.node == NODE_COMPUTE_IDENTITY and event.detail == identity for event in trace)
    )
    if reached == 0:
        raise RaceNotRunError(
            f"no execution reached {identity}: it was not in the due-set either tick read, so "
            "this run measured nothing. Seed the fixtures and check that the approach is still "
            "'eligible' with due_at at or before the tick instant. A zero reported here would "
            "otherwise look like the safest possible result."
        )

    return OverlapResult(
        identity=identity,
        executions=executions,
        key_strategy=key_strategy,
        approaches_observed=receiver.count_for(identity),
        distinct_idempotency_keys=receiver.distinct_keys_for(identity),
        duplicates=receiver.duplicates(),
        executions_that_reached_the_identity=reached,
        traces=tuple(traces),
    )


async def run_workflow_pair(
    engine: AsyncEngine,
    *,
    receiver: CarrierReceiver,
    now: dt.datetime,
    identity: str,
) -> None:
    """Two overlapping n8n executions over one due-set. **The baseline half of the kill test.**

    The entry point ADR-001's harness calls. It returns nothing on purpose: the count that decides
    the comparison is read from the receiver, never reported by the arm that did the sending. An
    arm that told you how many approaches it made would be grading its own bookkeeping.
    """
    await run_overlapping_executions(
        engine, receiver=receiver, now=now, identity=identity, executions=2
    )


# --- the standalone demonstration --------------------------------------------------------------


def _print_result(result: OverlapResult) -> None:
    """Print the numbers, labelled so none of them can be read as a different number.

    ``approaches for the raced identity`` is the figure ADR-001 asserts on. The other identity
    counted below belongs to the second carrier that was also due in the same pass, and it is shown
    because the failure is not confined to the row under test — every due approach is duplicated.
    """
    duplicated = ", ".join(
        f"market {identity.rsplit('/', 2)[-2][:8]} x{count}"
        for identity, count in sorted(result.duplicates.items())
    )
    print(f"  key strategy ...................... {result.key_strategy.value}")
    print(f"  overlapping executions ............ {result.executions}")
    print(f"  of which reached the identity ..... {result.executions_that_reached_the_identity}")
    print(f"  approaches for the raced identity . {result.approaches_observed}")
    print(f"  distinct idempotency keys ......... {result.distinct_idempotency_keys}")
    print(f"  identities approached >1 time ..... {len(result.duplicates)} [{duplicated or '-'}]")


async def _demonstrate() -> None:
    """Seed the local database, race two ticks, and print what the carrier observed.

    Run with ``python -m n8n.simulator`` from the repository root, with the compose stack up. It
    resets and re-seeds, so it may only ever point at the disposable local database.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from market_approach_desk.config import Settings
    from market_approach_desk.db.engine import async_dsn
    from market_approach_desk.demo.seed import RACE_MARKET, SEED_EPOCH, reset, seed

    # ``NullPool`` because each node opens and closes its own session. A pooled engine would hand
    # the two ticks the same connection, serialise them, and quietly undo the overlap this exists
    # to create — a demonstration that passed for the wrong reason.
    engine = create_async_engine(async_dsn(Settings()), poolclass=NullPool)
    try:
        race = _race_identity()
        print("n8n baseline - overlapping schedule executions over one due-set")
        print(f"one placement, one market ({RACE_MARKET}), one stage")
        print("both ticks read the due-set before either writes state back\n")
        print(f"identity: {race}\n")

        for strategy in IdempotencyKeyStrategy:
            await reset(engine)
            await seed(engine)
            receiver = CarrierReceiver()
            try:
                result = await run_overlapping_executions(
                    engine,
                    receiver=receiver,
                    now=SEED_EPOCH,
                    identity=race,
                    key_strategy=strategy,
                )
            except RaceNotRunError as error:
                # Reported as a failed measurement rather than a safe result, and as a message
                # rather than a traceback: the usual cause is something else resetting the same
                # database mid-run, which is an operator problem and not a defect to debug.
                print(f"MEASUREMENT FAILED ({strategy.value}): {error}")
                raise SystemExit(1) from error
            label = (
                "as shipped in market-approach.workflow.json"
                if strategy is IdempotencyKeyStrategy.BUSINESS_IDENTITY
                else "variant, NOT in the shipped JSON - the common execution-scoped idiom"
            )
            print(f"{label}:")
            _print_result(result)
            print()
            if strategy is IdempotencyKeyStrategy.BUSINESS_IDENTITY:
                _verdict(result)
    finally:
        await engine.dispose()


def _race_identity() -> str:
    """The identity the demonstration races on, derived the way the seeder derived it.

    Recomputed from the seeder's own identifier helper rather than pasted as a literal, so a change
    to the fixtures moves the demonstration with them instead of leaving it racing a row that no
    longer exists and reporting a reassuring zero. Reaching for the seeder's private helper is
    deliberate and confined to this demonstration path: the alternative is a hard-coded UUID that
    can go stale silently, which is the worse of the two.
    """
    from market_approach_desk.demo.seed import RACE_MARKET, _id

    return str(
        ApproachIdentity(
            placement_id=_id("placement", "PL-2026-0417"),
            market_id=_id("market", RACE_MARKET),
            stage=Stage.INITIAL,
        )
    )


def _verdict(result: OverlapResult) -> None:
    print("verdict:")
    if result.approaches_observed > 1:
        print(
            f"  the carrier was approached {result.approaches_observed} times for one "
            "(placement, market, stage). The market is blocked.\n"
        )
    else:
        print(
            "  the carrier was approached at most once. The n8n arm did NOT duplicate under this "
            "harness, which refutes the premise of ADR-001 and has to be reported as such rather "
            "than tuned away.\n"
        )


def main() -> None:
    asyncio.run(_demonstrate())


if __name__ == "__main__":
    main()
