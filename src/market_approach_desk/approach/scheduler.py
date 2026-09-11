"""One bounded scheduler tick: claim, then send what was claimed.

**Not a daemon.** It does a finite amount of work and returns. What drives it — a test, a cron
entry, an operator — is a deployment decision this module does not take.

The shape is the whole point of the comparison with the n8n arm, so it is worth being explicit
about the ordering:

1. **Claim inside one transaction**, with every eligibility rule evaluated there, and commit.
2. **Then send**, outside that transaction, against the claims it returned.
3. **Then record the outcome** in a second transaction.

The n8n arm does read → decide → send → write with no transaction anywhere, which is why a second
execution can read the same due-set while the first is between its send and its write. Step 1 above
closes that window: by the time this scheduler sends, the row is already `claimed` and is invisible
to every other scheduler.

**The send is outside the claim transaction on purpose.** Holding a database transaction open
across a network call makes the second scheduler wait rather than skip, which looks safer and
quietly converts two workers into one. It also means a slow carrier holds a row lock, which is the
long-running-lock problem wearing a different hat.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from market_approach_desk.approach.claim import ClaimOutcome, claim_due_approaches, record_event
from market_approach_desk.db.models import ApproachAttempt, MarketApproach
from market_approach_desk.domain.identity import ApproachState
from market_approach_desk.domain.receiver import CarrierReceiver, ReceiverError

__all__ = ["TickReport", "run_tick"]

#: How long after a send an underwriter is chased. A business default, overridable per placement in
#: a later increment; hard-coded here rather than invented as configuration nothing reads yet.
FOLLOW_UP_AFTER = dt.timedelta(days=3)

#: Sends per approach before it is dead-lettered. Small and bounded: an irreversible commercial act
#: does not get an unbounded retry loop.
MAX_ATTEMPTS = 3


@dataclasses.dataclass(frozen=True, slots=True)
class TickReport:
    """What one tick did. Counts rather than prose, because a test asserts on them."""

    claimed: int
    sent: int
    blocked: int
    failed: int

    @property
    def total(self) -> int:
        return self.claimed + self.blocked


async def run_tick(
    engine: AsyncEngine,
    *,
    receiver: CarrierReceiver,
    now: dt.datetime,
    actor: str = "scheduler",
    limit: int = 32,
    on_claimed: object = None,
) -> TickReport:
    """Claim and send one bounded batch.

    ``on_claimed`` is an awaitable hook invoked **after the claim transaction commits and before any
    send**. It exists for one reason: the kill test has to force two ticks to overlap at exactly
    that point, deterministically, rather than sleeping and hoping the scheduler cooperates. It is
    ``None`` in every production path and a test is the only caller that passes one.
    """
    async with AsyncSession(engine) as session, session.begin():
        outcomes = await claim_due_approaches(session, now=now, actor=actor, limit=limit)

    if on_claimed is not None:
        await on_claimed(outcomes)  # type: ignore[operator]

    sendable = [outcome for outcome in outcomes if outcome.may_send]
    blocked = len(outcomes) - len(sendable)

    sent = failed = 0
    for outcome in sendable:
        if await _send_one(engine, outcome, receiver=receiver, now=now, actor=actor):
            sent += 1
        else:
            failed += 1

    return TickReport(claimed=len(sendable), sent=sent, blocked=blocked, failed=failed)


async def _send_one(
    engine: AsyncEngine,
    outcome: ClaimOutcome,
    *,
    receiver: CarrierReceiver,
    now: dt.datetime,
    actor: str,
) -> bool:
    """Send one claimed approach, recording the attempt before the send and the result after.

    The attempt row is committed **first**, so a crash between it and the send leaves evidence that
    a send may have happened. The alternative — record afterwards — loses exactly the case that
    matters, because the process that would have written the record is the one that died.
    """
    async with AsyncSession(engine) as session, session.begin():
        approach = await session.get(MarketApproach, outcome.approach_id)
        if approach is None:  # pragma: no cover - the row was deleted under us
            return False
        approach.attempt_count += 1
        attempt_no = approach.attempt_count
        session.add(
            ApproachAttempt(
                approach_id=approach.id, attempt_no=attempt_no, started_at=now, outcome=None
            )
        )

    try:
        receiver.approach(
            identity=str(outcome.identity), idempotency_key=outcome.idempotency_key, arm="python"
        )
    except ReceiverError as refused:
        await _record_failure(
            engine, outcome, attempt_no, now=now, actor=actor, detail=str(refused)
        )
        return False

    async with AsyncSession(engine) as session, session.begin():
        approach = await session.get(MarketApproach, outcome.approach_id)
        if approach is None:  # pragma: no cover
            return False
        approach.state = ApproachState.SENT.value
        approach.sent_at = now
        approach.follow_up_at = now + FOLLOW_UP_AFTER
        approach.due_at = None
        attempt = await _attempt(session, outcome.approach_id, attempt_no)
        if attempt is not None:
            attempt.outcome = "accepted"
        await record_event(session, verb="sent", identity=str(outcome.identity), actor=actor)
    return True


async def _record_failure(
    engine: AsyncEngine,
    outcome: ClaimOutcome,
    attempt_no: int,
    *,
    now: dt.datetime,
    actor: str,
    detail: str,
) -> None:
    """A refused send: schedule another attempt, or dead-letter once the bound is reached.

    The row goes back to ``retrying`` with a ``due_at``, which is what makes it visible to a later
    tick. Exhaustion is ``dead_lettered`` and **not** scheduled: nothing automatic touches it again,
    because an irreversible act that has failed three times is a question for a person.
    """
    async with AsyncSession(engine) as session, session.begin():
        approach = await session.get(MarketApproach, outcome.approach_id)
        if approach is None:  # pragma: no cover
            return
        attempt = await _attempt(session, outcome.approach_id, attempt_no)
        if attempt is not None:
            attempt.outcome = "refused"
            attempt.detail = detail

        if approach.attempt_count >= MAX_ATTEMPTS:
            approach.state = ApproachState.DEAD_LETTERED.value
            approach.due_at = None
            verb = "dead_lettered"
        else:
            approach.state = ApproachState.RETRYING.value
            # Exponential, and bounded by MAX_ATTEMPTS rather than by a clock: two bounds on an
            # irreversible act would be belt and braces, one is enough while the act is an email.
            approach.due_at = now + dt.timedelta(minutes=2**approach.attempt_count)
            verb = "send_failed"
        await record_event(
            session, verb=verb, identity=str(outcome.identity), actor=actor, detail=detail
        )


async def _attempt(
    session: AsyncSession, approach_id: object, attempt_no: int
) -> ApproachAttempt | None:
    return (
        await session.execute(
            select(ApproachAttempt).where(
                ApproachAttempt.approach_id == approach_id,
                ApproachAttempt.attempt_no == attempt_no,
            )
        )
    ).scalar_one_or_none()
