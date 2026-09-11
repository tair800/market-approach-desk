"""The schema. Small on purpose — every table here earns its place in the claim of ADR-001.

The constraint that matters is on :class:`MarketApproach`: one row per
``(placement_id, market_id, stage)``. Everything else in this module exists to make that row
meaningful or to record what happened around it.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "ApproachAttempt",
    "AuditEvent",
    "Base",
    "CarrierReply",
    "Market",
    "MarketApproach",
    "Placement",
]


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Placement(Base):
    """One commercial risk being placed into the market."""

    __tablename__ = "placement"

    id: Mapped[uuid.UUID] = _pk()
    reference: Mapped[str] = mapped_column(String(64), unique=True)
    insured_name: Mapped[str] = mapped_column(String(200))
    class_of_business: Mapped[str] = mapped_column(String(80))
    inception_on: Mapped[dt.date] = mapped_column()
    #: The broker handling it. A string rather than a table: this repository has no user directory
    #: and inventing one would be a table nothing reads.
    handler: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Market(Base):
    """A carrier, and the underwriter contact the approach is addressed to."""

    __tablename__ = "market"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(160), unique=True)
    underwriter: Mapped[str] = mapped_column(String(160))
    #: Fictional throughout the fixtures. A real address in a public repository would be a
    #: disclosure, and a portfolio project has no business holding one.
    contact_email: Mapped[str] = mapped_column(String(200))
    #: Whether this broker is authorised to place with this carrier at all. Evaluated inside the
    #: claim transaction, like every other conflict rule.
    within_placing_authority: Mapped[bool] = mapped_column(default=True)


class MarketApproach(Base):
    """**The row the whole project is about.** One approach to one carrier for one risk and stage.

    The unique constraint is the mechanism, not a tidiness measure: it is what makes a second
    scheduler's attempt to create the same approach fail at the database rather than succeed
    quietly. Application code cannot be relied on to notice a race it is itself running in.
    """

    __tablename__ = "market_approach"
    __table_args__ = (
        # ADR-001's business identity. `stage` is in the key deliberately — see
        # `domain/identity.py` for why a carrier may be re-approached at a later stage.
        UniqueConstraint(
            "placement_id", "market_id", "stage", name="uq_market_approach_business_identity"
        ),
        # The claim query filters on these three, and the race test drives enough rows through it
        # that a sequential scan would change what the test is measuring.
        Index("ix_market_approach_due", "state", "due_at"),
        CheckConstraint("attempt_count >= 0", name="ck_market_approach_attempts_non_negative"),
    )

    id: Mapped[uuid.UUID] = _pk()
    placement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("placement.id", ondelete="CASCADE"))
    market_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("market.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32))

    state: Mapped[str] = mapped_column(String(32))
    #: Derived from the business identity and nothing else, so a retry of one approach is
    #: recognisably the same send rather than a second one.
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)

    #: When the scheduler may next look at this row. Null means "not scheduled".
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: When an underwriter should be chased if they have not replied.
    follow_up_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Why a `blocked` approach was refused. Free text for a human; nothing branches on it.
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApproachAttempt(Base):
    """One outbound send attempt. Written **before** the send, so a crash mid-send is visible.

    Separate from the approach because they answer different questions: the approach says whether
    this carrier has been approached, the attempt says what we tried and when. Collapsing them
    would lose the second the moment a retry succeeded.
    """

    __tablename__ = "approach_attempt"
    __table_args__ = (UniqueConstraint("approach_id", "attempt_no", name="uq_approach_attempt_no"),)

    id: Mapped[uuid.UUID] = _pk()
    approach_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_approach.id", ondelete="CASCADE")
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    #: ``accepted``, ``refused`` or ``unknown``. Null while the attempt is in flight, which is the
    #: state a crash leaves behind and the only honest reading of it.
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class CarrierReply(Base):
    """An underwriter's answer, and what the classifier made of it.

    The classification is stored beside the raw text, never instead of it. A model's reading of a
    reply is provenance; the reply is the evidence, and a human who disagrees needs the original.
    """

    __tablename__ = "carrier_reply"

    id: Mapped[uuid.UUID] = _pk()
    approach_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_approach.id", ondelete="CASCADE")
    )
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    body: Mapped[str] = mapped_column(Text)

    #: One of the closed vocabulary in `replies/schema.py`. Null until classified.
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: True when the model declined to classify. An abstention is an answer, and it must be
    #: distinguishable from "not classified yet" — which is why this is not inferred from a null.
    abstained: Mapped[bool] = mapped_column(default=False)
    #: Which model, so a stored classification can be attributed. `stand-in` when no model ran.
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    """Append-only. Every approach-affecting action leaves one.

    No update, no delete. The trail is what lets a broker answer "who approached this carrier, and
    when" months later, which is the question that gets asked when a market is blocked.
    """

    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = _pk()
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    #: ``claimed``, ``sent``, ``blocked``, ``send_failed``, ``replied``, ``classified``.
    verb: Mapped[str] = mapped_column(String(32))
    #: The business identity as a string, so the trail survives a row being deleted.
    identity: Mapped[str] = mapped_column(String(160))
    actor: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
