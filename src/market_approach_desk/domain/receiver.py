"""The fake carrier receiver: the one instrument both arms are measured with.

**This is the only place the kill test reads its numbers from.** Neither arm is allowed to report
how many approaches it made — a system that grades itself from its own tables is measuring its
bookkeeping, not its behaviour. The receiver stands where the underwriter's mailbox would, counts
what actually arrives, and both arms are graded against the same object.

It deliberately **does not** deduplicate by default. A receiver that silently absorbed a second
approach would hide exactly the failure this project exists to demonstrate, and would let the n8n
arm look safe for a reason that has nothing to do with n8n. Suppression is available, off by
default, and a test that turns it on has to say why.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import Counter

__all__ = ["Approached", "CarrierReceiver", "ReceiverError"]


class ReceiverError(RuntimeError):
    """The receiver refused. Used by the harness to make a send fail on purpose."""


@dataclasses.dataclass(frozen=True, slots=True)
class Approached:
    """One approach as the carrier saw it. The business identity, and how it was labelled."""

    #: ``placement/market/stage`` — the same string both arms compute independently.
    identity: str

    #: The key the sender attached. Recorded so a test can tell a *retry* of one approach from a
    #: *second* approach: same key is a retry, different key is a duplicate.
    idempotency_key: str

    #: Which arm sent it. Provenance only; the receiver treats both identically.
    arm: str


class CarrierReceiver:
    """Counts approaches, keyed on business identity. Thread-safe, because the harness is not.

    The n8n arm's race is reproduced with real concurrency, so the counter has to survive it. A
    receiver that lost a count under contention would understate the very failure it exists to
    observe.
    """

    def __init__(self, *, suppress_duplicate_keys: bool = False) -> None:
        #: When true the receiver refuses a repeat of an idempotency key it has already accepted.
        #: **Off by default.** A real underwriter's mailbox has no such feature, and turning it on
        #: by default would let either arm pass for a reason unrelated to its own design.
        self._suppress = suppress_duplicate_keys
        self._lock = threading.Lock()
        self._received: list[Approached] = []
        self._keys: set[str] = set()
        self.refusals = 0

    def approach(self, *, identity: str, idempotency_key: str, arm: str) -> None:
        """Accept one approach, or refuse it if suppression is on and the key is a repeat."""
        with self._lock:
            if self._suppress and idempotency_key in self._keys:
                self.refusals += 1
                return
            self._keys.add(idempotency_key)
            self._received.append(
                Approached(identity=identity, idempotency_key=idempotency_key, arm=arm)
            )

    @property
    def received(self) -> tuple[Approached, ...]:
        with self._lock:
            return tuple(self._received)

    def count_for(self, identity: str) -> int:
        """How many approaches this carrier saw for one business identity.

        **The number the kill test asserts on.** More than one means the market was approached
        twice, whatever either arm believes it did.
        """
        with self._lock:
            return sum(1 for item in self._received if item.identity == identity)

    def duplicates(self) -> dict[str, int]:
        """Every identity seen more than once, and how many times. Empty is the safe answer."""
        with self._lock:
            counted = Counter(item.identity for item in self._received)
        return {identity: n for identity, n in counted.items() if n > 1}

    def distinct_keys_for(self, identity: str) -> int:
        """Distinct idempotency keys seen for one identity.

        Two approaches carrying **one** key is a retry the receiver could in principle collapse.
        Two approaches carrying **two** keys is a second piece of work, and no receiver-side
        feature could ever have saved it. The kill test reports both, because they are different
        failures and only the second is unrecoverable.
        """
        with self._lock:
            return len(
                {item.idempotency_key for item in self._received if item.identity == identity}
            )
