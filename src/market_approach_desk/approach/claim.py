"""The claim transaction. **This is the mechanism ADR-001's claim rests on.**

The n8n arm fails because its execution reads the due-set, decides eligibility, sends, and only then
writes state — four steps with no transaction around them, so a second execution can read the same
due-set while the first is between its send and its write. Nothing about that is an n8n bug; it is
what a visual workflow runner does.

This module closes it with two things that must happen together:

1. **`SELECT … FOR UPDATE SKIP LOCKED`** — a second scheduler running concurrently does not see a
   row the first has claimed. It skips it rather than blocking, so the two schedulers share the
   queue instead of serialising on it.
2. **Every eligibility rule evaluated inside that same transaction.** A rule evaluated before the
   claim is a rule evaluated against state that may already have changed — which is the n8n failure
   reproduced one layer down, and is the mistake this module is most likely to be edited into.

The unique constraint on the business identity sits underneath both, but as a **schema invariant
rather than a third runtime check**, and a reviewer was right to make this precise. It guarantees
exactly one row per `(placement_id, market_id, stage)`, which is what makes locking one row
equivalent to claiming the approach — without it, two rows for one identity would be two locks and
`SKIP LOCKED` would not help. Nothing in this repository inserts a `MarketApproach` at run time;
only the seeder does. So the constraint is never *exercised* by either arm and is not what refuses
the race the kill test measures. The claim transaction is.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from market_approach_desk.db.models import AuditEvent, CarrierReply, Market, MarketApproach
from market_approach_desk.domain.identity import (
    TERMINAL_STATES,
    ApproachIdentity,
    ApproachState,
    Stage,
)
from market_approach_desk.replies.schema import ReplyClass

__all__ = ["BlockReason", "ClaimOutcome", "claim_due_approaches", "record_event"]

#: How long a decline keeps a carrier off-limits for the same placement. A business rule with a
#: business reason: re-approaching a carrier that declined last week reads as not having listened.
DECLINE_COOLING_DAYS: Final = 30


class BlockReason:
    """Why an approach was refused. Strings rather than an enum because they are for a human.

    Each one is a conflict rule from the blueprint, and each is evaluated **inside** the claim.
    """

    ALREADY_APPROACHED: Final = "this carrier has already been approached for this risk and stage"
    RECENTLY_DECLINED: Final = "this carrier declined this risk within the cooling period"
    OUTSIDE_AUTHORITY: Final = "this carrier is outside the broker's placing authority"


@dataclasses.dataclass(frozen=True, slots=True)
class ClaimOutcome:
    """What one claim attempt produced. A refusal is an outcome, not an absence."""

    approach_id: uuid.UUID
    identity: ApproachIdentity
    idempotency_key: str
    #: ``None`` when the approach was claimed and may be sent. A string when it was refused, and
    #: the string is the reason a person will read.
    blocked_reason: str | None

    @property
    def may_send(self) -> bool:
        return self.blocked_reason is None


async def record_event(
    session: AsyncSession, *, verb: str, identity: str, actor: str, detail: str | None = None
) -> None:
    """Append one audit row. Inside the caller's transaction, deliberately.

    An event committed separately from the thing it describes can survive a rollback of that thing,
    and a trail that records approaches which did not happen is worse than no trail.
    """
    session.add(AuditEvent(verb=verb, identity=identity, actor=actor, detail=detail))


async def claim_due_approaches(
    session: AsyncSession,
    *,
    now: dt.datetime,
    actor: str,
    limit: int = 32,
) -> Sequence[ClaimOutcome]:
    """Claim every due approach this scheduler can take, and decide eligibility while holding them.

    **The caller must not have started sending anything.** This function runs in one transaction
    and the caller commits it; the sends happen afterwards, against the claims it returns. Holding
    the transaction open across a network call would be the long-running lock that makes the second
    scheduler wait instead of skipping — which looks correct and destroys the throughput the
    ``SKIP LOCKED`` was for.

    ``now`` is a parameter rather than a clock reading, so a test can force two schedulers to agree
    on the time and the race is about locking rather than about timing.
    """
    due = (
        (
            await session.execute(
                select(MarketApproach)
                .where(
                    MarketApproach.state.in_(
                        [ApproachState.ELIGIBLE.value, ApproachState.RETRYING.value]
                    ),
                    MarketApproach.due_at.is_not(None),
                    MarketApproach.due_at <= now,
                )
                .order_by(MarketApproach.due_at)
                .limit(limit)
                # The whole mechanism, in one clause. `skip_locked` rather than plain FOR UPDATE:
                # a second scheduler must move on to other work, not queue behind this one.
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    outcomes: list[ClaimOutcome] = []
    for approach in due:
        identity = ApproachIdentity(
            placement_id=approach.placement_id,
            market_id=approach.market_id,
            stage=Stage(approach.stage),
        )
        reason = await _conflict_for(session, approach, identity, now=now)

        if reason is not None:
            approach.state = ApproachState.BLOCKED.value
            approach.blocked_reason = reason
            approach.due_at = None
            await record_event(
                session, verb="blocked", identity=str(identity), actor=actor, detail=reason
            )
        else:
            approach.state = ApproachState.CLAIMED.value
            # Cleared while the row is claimed so that a second scheduler, arriving after this
            # transaction commits, does not see it as due at all. Belt and braces with SKIP LOCKED:
            # one covers the concurrent window, the other the window after it.
            approach.due_at = None
            await record_event(session, verb="claimed", identity=str(identity), actor=actor)

        outcomes.append(
            ClaimOutcome(
                approach_id=approach.id,
                identity=identity,
                idempotency_key=approach.idempotency_key,
                blocked_reason=reason,
            )
        )

    return outcomes


async def _conflict_for(
    session: AsyncSession,
    approach: MarketApproach,
    identity: ApproachIdentity,
    *,
    now: dt.datetime,
) -> str | None:
    """Every conflict rule, evaluated against state read inside the claim transaction.

    Ordered from the cheapest and most decisive downwards, and each returns the reason rather than
    a boolean: "blocked" without a reason is a support ticket.
    """
    # 1. Already approached at this stage.
    #
    #    **This branch is unreachable today, and saying so is better than implying otherwise.**
    #    `uq_market_approach_business_identity` makes a second row for one identity impossible, so
    #    a query for "another row with my identity in a terminal state" can never match. A reviewer
    #    found it advertised as a live rule.
    #
    #    Kept rather than deleted because it is the rule that has to exist the moment an approach
    #    can be created at run time — today only the seeder inserts one — and because deleting it
    #    would leave the reader to rediscover why the constraint alone is sufficient. It is free:
    #    one indexed lookup that returns nothing.
    already = (
        await session.execute(
            select(MarketApproach.id).where(
                MarketApproach.placement_id == identity.placement_id,
                MarketApproach.market_id == identity.market_id,
                MarketApproach.stage == identity.stage.value,
                MarketApproach.id != approach.id,
                MarketApproach.state.in_([state.value for state in TERMINAL_STATES]),
            )
        )
    ).first()
    if already is not None:
        return BlockReason.ALREADY_APPROACHED

    # 2. Outside placing authority. Read here rather than cached on the approach, because authority
    #    is a fact about the relationship and can change between scheduling and sending.
    market = await session.get(Market, identity.market_id)
    if market is not None and not market.within_placing_authority:
        return BlockReason.OUTSIDE_AUTHORITY

    # 3. Declined this risk recently, at any stage. Deliberately wider than the business identity:
    #    the cooling period is about the relationship with the carrier, not about one presentation.
    #    A decline is a *classification on a reply*, not a state on the approach: an approach that
    #    was replied to is not necessarily an approach that was refused, and treating the two as the
    #    same would block a carrier who asked a question.
    cooling_since = now - dt.timedelta(days=DECLINE_COOLING_DAYS)
    declined = (
        await session.execute(
            select(CarrierReply.id)
            .join(MarketApproach, CarrierReply.approach_id == MarketApproach.id)
            .where(
                MarketApproach.placement_id == identity.placement_id,
                MarketApproach.market_id == identity.market_id,
                MarketApproach.id != approach.id,
                CarrierReply.classification == ReplyClass.DECLINED.value,
                CarrierReply.received_at >= cooling_since,
            )
        )
    ).first()
    if declined is not None:
        return BlockReason.RECENTLY_DECLINED

    return None
