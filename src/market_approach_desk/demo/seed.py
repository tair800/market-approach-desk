"""Deterministic synthetic data for the demonstration and the tests.

Everything here is invented. No real insured, no real carrier, no real underwriter, no real address
— a portfolio repository has no business holding any of those, and a fixture that looked real would
be the disclosure nobody meant to make.

**Deterministic on purpose.** The identifiers are UUID5 over fixed names, so the same seed produces
the same rows on every machine. A race test whose fixtures differ between runs is a race test whose
failures cannot be compared.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from market_approach_desk.db.models import CarrierReply, Market, MarketApproach, Placement
from market_approach_desk.domain.identity import (
    ApproachIdentity,
    ApproachState,
    Stage,
    idempotency_key,
)

__all__ = ["RACE_MARKET", "SEED_EPOCH", "reset", "seed"]

#: A fixed instant, so `due_at` and `follow_up_at` are reproducible and a follow-up is reliably
#: overdue in the demonstration rather than overdue only on some days.
SEED_EPOCH: Final = dt.datetime(2026, 9, 1, 9, 0, tzinfo=dt.UTC)

_NAMESPACE: Final = uuid.UUID("5f2a3c18-91d4-4a2e-9d71-1c2b4f6e8a30")

#: The carrier the kill test races on. Named here rather than in the test so the demonstration and
#: the test agree on which cell of the matrix to look at.
RACE_MARKET: Final = "Thames Underwriting"

_MARKETS: Final = (
    # name, underwriter, within placing authority
    (RACE_MARKET, "J. Okonjo", True),
    ("Northgate Speciality", "R. Vasquez", True),
    ("Kestrel Mutual", "A. Lindqvist", True),
    ("Pellworth Re", "M. Haddad", True),
    # Deliberately outside authority, so the "blocked" path is visible on the board without
    # anyone having to make something fail.
    ("Brightwater Assurance", "C. Adeyemi", False),
)


def _id(kind: str, name: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{kind}:{name}")


#: Every table the demonstration and the tests write. Listed rather than discovered, so adding a
#: table is a decision about whether a reset should empty it.
_TABLES: Final = (
    "audit_event",
    "carrier_reply",
    "approach_attempt",
    "market_approach",
    "placement",
    "market",
)


async def reset(engine: AsyncEngine) -> None:
    """Empty every table this project writes, leaving the schema alone.

    ``TRUNCATE … CASCADE`` in one statement rather than six ``DELETE``s, and that was a correction
    rather than a preference. The delete version left rows behind when two tests ran against the
    same database in sequence — the next seed then hit a duplicate primary key, and the failure
    surfaced two tests later as "the race produced no approaches", which is the kind of symptom that
    sends you looking at the wrong module entirely.

    One statement is also one transaction: there is no window in which half the tables are empty.
    """
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))


async def seed(engine: AsyncEngine, *, now: dt.datetime = SEED_EPOCH) -> None:
    """One placement, five carriers, and every state a reviewer should be able to see.

    The board is built to be read in under two minutes, so it deliberately contains one of each
    interesting thing rather than a realistic volume of one thing: a sent approach with a reply, a
    sent approach whose follow-up is overdue, a blocked approach with its reason, one still eligible
    — and the carrier the kill test races on, left eligible so the race has something to race for.
    """
    placement_id = _id("placement", "PL-2026-0417")

    async with AsyncSession(engine) as session, session.begin():
        session.add(
            Placement(
                id=placement_id,
                reference="PL-2026-0417",
                insured_name="Harbour Logistics Group",
                class_of_business="Marine cargo",
                inception_on=dt.date(2026, 10, 1),
                handler="placement.handler",
            )
        )
        for name, underwriter, authorised in _MARKETS:
            session.add(
                Market(
                    id=_id("market", name),
                    name=name,
                    underwriter=underwriter,
                    contact_email=f"{underwriter.split('.')[-1].strip().lower()}@example.invalid",
                    within_placing_authority=authorised,
                )
            )

    async with AsyncSession(engine) as session, session.begin():
        for name, _, authorised in _MARKETS:
            market_id = _id("market", name)
            identity = ApproachIdentity(
                placement_id=placement_id, market_id=market_id, stage=Stage.INITIAL
            )
            approach = MarketApproach(
                id=_id("approach", name),
                placement_id=placement_id,
                market_id=market_id,
                stage=Stage.INITIAL.value,
                idempotency_key=idempotency_key(identity),
                state=ApproachState.ELIGIBLE.value,
                due_at=now,
                attempt_count=0,
            )

            if name == "Northgate Speciality":
                # Sent, and answered. The reply carries a classification so the console has
                # something to render in that column.
                approach.state = ApproachState.REPLIED.value
                approach.sent_at = now - dt.timedelta(days=6)
                approach.due_at = None
                approach.attempt_count = 1
                session.add(approach)
                # Flushed before the reply is added. The unit of work orders inserts by table
                # dependency, but the reply is created from `approach.id` in the same block, and
                # making the ordering explicit is cheaper than relying on it.
                await session.flush()
                session.add(
                    CarrierReply(
                        approach_id=approach.id,
                        received_at=now - dt.timedelta(days=4),
                        body=(
                            "Thanks for the submission. We can look at this but we'd need the "
                            "current loss record and confirmation of the warehouse sprinkler "
                            "certification before we could put terms up."
                        ),
                        classification=None,
                        abstained=False,
                    )
                )
                continue

            if name == "Kestrel Mutual":
                # Sent, no answer, and the follow-up is already due — the overdue chase state.
                approach.state = ApproachState.SENT.value
                approach.sent_at = now - dt.timedelta(days=9)
                approach.follow_up_at = now - dt.timedelta(days=6)
                approach.due_at = None
                approach.attempt_count = 1
                session.add(approach)
                continue

            if not authorised:
                # The blocked path, with its reason, so a reader sees a refusal is a decision.
                approach.state = ApproachState.BLOCKED.value
                approach.blocked_reason = "this carrier is outside the broker's placing authority"
                approach.due_at = None
                session.add(approach)
                continue

            # Thames (the race target) and Pellworth stay eligible and due.
            session.add(approach)
