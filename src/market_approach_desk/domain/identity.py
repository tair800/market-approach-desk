"""The business identity of an approach, and the states it may be in.

Everything in this repository turns on one question: *have we already approached this carrier for
this risk?* The answer has to be the same however many times it is asked, by however many
schedulers, so the identity is a pure function of three facts about the business and of nothing
else.

**Nothing here reads a clock, a retry counter, a hostname or a process id.** Two runs that mean the
same approach produce the same key, which is what lets a database constraint decide the question
instead of application discipline deciding it.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import uuid
from typing import Final

__all__ = [
    "TERMINAL_STATES",
    "ApproachIdentity",
    "ApproachState",
    "Stage",
    "idempotency_key",
]


class Stage(enum.StrEnum):
    """How far into the placement an approach sits.

    **Part of the business identity, and that is a domain decision rather than a hedge.** A carrier
    that declined the initial presentation may legitimately be approached again on revised terms —
    a different risk presentation and a different question. Keying on placement and market alone
    would forbid that, and a tool that forbids legitimate work gets routed around in a spreadsheet
    where nothing is recorded at all.
    """

    #: The first approach with the original presentation.
    INITIAL = "initial"

    #: A second approach after the presentation materially changed.
    REVISED_TERMS = "revised_terms"

    #: Approaching for a share of a risk another carrier has already led.
    FOLLOW_LINE = "follow_line"


class ApproachState(enum.StrEnum):
    """Where one approach has got to. Deliberately few, and each one is a different fact.

    The distinction that matters commercially is between :attr:`CLAIMED` and :attr:`SENT`. A claim
    is a reservation this system made and can release; a send is an email an underwriter has
    received and nobody can recall. They are separate states because they are separately
    irreversible, and the harness counts the second.
    """

    #: Eligible, nothing reserved. Not a row: the absence of one.
    ELIGIBLE = "eligible"

    #: Reserved by a scheduler inside a claim transaction. No email exists yet.
    CLAIMED = "claimed"

    #: The carrier receiver accepted it. **Irreversible.**
    SENT = "sent"

    #: The send failed in a way that is safe to retry, and is scheduled to be.
    RETRYING = "retrying"

    #: An underwriter answered. The reply's classification lives on the reply, not here.
    REPLIED = "replied"

    #: Refused before any send, by a conflict rule evaluated inside the claim.
    BLOCKED = "blocked"

    #: Retries are exhausted. A person looks at it; nothing automatic will.
    DEAD_LETTERED = "dead_lettered"


#: States from which no further send may be made for this identity.
#:
#: ``BLOCKED`` is here because a refusal is a decision, not a gap — re-running the scheduler must
#: not quietly reconsider it.
TERMINAL_STATES: Final[frozenset[ApproachState]] = frozenset(
    {ApproachState.SENT, ApproachState.REPLIED, ApproachState.BLOCKED, ApproachState.DEAD_LETTERED}
)

#: Separates this project's hashes from every other sha256 in the system. Domain separation is
#: cheap, and its absence is the kind of thing nobody notices until two unrelated values compare
#: equal.
_HASH_DOMAIN: Final = "mad.approach-identity.v1"


@dataclasses.dataclass(frozen=True, slots=True)
class ApproachIdentity:
    """The three facts that decide whether two approaches are the same approach.

    Frozen, because an identity that can be edited after a uniqueness check has been performed is
    not an identity.
    """

    placement_id: uuid.UUID
    market_id: uuid.UUID
    stage: Stage

    def __str__(self) -> str:
        return f"{self.placement_id}/{self.market_id}/{self.stage.value}"


def idempotency_key(identity: ApproachIdentity) -> str:
    """A stable key for the outbound send, derived from the business identity and nothing else.

    Handed to the carrier receiver so that a retry of an *accepted* approach is recognisably the
    same send rather than a second one. It is deliberately **not** what prevents the duplicate —
    the claim transaction is — because a receiver that ignores the header would then be the only
    thing standing between a broker and a blocked market. (An earlier version of this sentence said
    the database *constraint* prevents it. The constraint guarantees one row per identity, which is
    what makes locking a row mean something; it never fires at run time, because nothing but the
    seeder inserts an approach.)

    Derived rather than random for the reason the whole project exists: a key that changed between
    two runs of the same work would make two approaches look like two pieces of work.
    """
    payload = f"{_HASH_DOMAIN}|{identity.placement_id}|{identity.market_id}|{identity.stage.value}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
