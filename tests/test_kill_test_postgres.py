"""**The kill test.** Declared in ADR-001 before any implementation; run here against both arms.

One placement, one carrier, one stage. Two scheduler executions forced to overlap at exactly the
point where the failure lives, and both arms measured with the same instrument: the fake carrier
receiver, which counts what *arrives* rather than what either arm believes it sent.

**The overlap is forced, never waited for.** Two threads and a sleep would make this test a
coin-toss that happens to be passing on the machine it was written on. The barrier makes it a
statement about the code.

Expected, and stated before it was known:

===========  ====================================================
Arm          approaches observed at the receiver for one identity
===========  ====================================================
n8n          more than one
Python       exactly one
===========  ====================================================
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib
from collections.abc import AsyncIterator, Sequence

import pytest
import pytest_asyncio
from n8n.simulator import run_workflow_pair
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from market_approach_desk.approach.claim import claim_due_approaches
from market_approach_desk.approach.scheduler import run_tick
from market_approach_desk.config import Settings
from market_approach_desk.db.engine import async_dsn
from market_approach_desk.demo.seed import RACE_MARKET, SEED_EPOCH, reset, seed
from market_approach_desk.domain.identity import ApproachIdentity, Stage
from market_approach_desk.domain.receiver import CarrierReceiver

pytestmark = pytest.mark.integration

#: Where the comparison result is written for the console to render. A JSON file rather than a
#: screenshot, so the console shows the run that actually happened rather than a picture of one.
RESULT_PATH = pathlib.Path(__file__).resolve().parents[1] / "docs" / "killtest.json"


def _settings() -> Settings:
    return Settings()


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(async_dsn(_settings()), poolclass=NullPool)
    try:
        yield created
    finally:
        await created.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean(engine: AsyncEngine) -> AsyncIterator[None]:
    await reset(engine)
    await seed(engine)
    yield


def _race_identity() -> ApproachIdentity:
    """The one cell of the matrix both arms race on, computed the same way the seeder did."""
    from market_approach_desk.demo.seed import _id

    return ApproachIdentity(
        placement_id=_id("placement", "PL-2026-0417"),
        market_id=_id("market", RACE_MARKET),
        stage=Stage.INITIAL,
    )


@pytest.mark.asyncio
async def test_the_python_arm_approaches_each_carrier_once_under_overlapping_ticks(
    engine: AsyncEngine,
) -> None:
    """Two ticks, forced to overlap at the claim boundary. The carrier must see one approach.

    The barrier releases the second tick only once the first has *committed its claim and not yet
    sent* — the exact window the n8n arm loses in. If the Python arm duplicates here, the claim of
    ADR-001 is false and the arm is wrong; the test is not to be adjusted.
    """
    receiver = CarrierReceiver()
    identity = str(_race_identity())
    first_claimed = asyncio.Event()
    second_finished = asyncio.Event()

    async def hold_after_claim(_outcomes: Sequence[object]) -> None:
        """Let the second tick run to completion while the first is between claim and send."""
        first_claimed.set()
        await asyncio.wait_for(second_finished.wait(), timeout=30)

    async def second() -> None:
        await asyncio.wait_for(first_claimed.wait(), timeout=30)
        try:
            await run_tick(engine, receiver=receiver, now=SEED_EPOCH, actor="scheduler-b")
        finally:
            second_finished.set()

    await asyncio.gather(
        run_tick(
            engine,
            receiver=receiver,
            now=SEED_EPOCH,
            actor="scheduler-a",
            on_claimed=hold_after_claim,
        ),
        second(),
    )

    observed = receiver.count_for(identity)
    assert observed == 1, (
        f"the carrier saw {observed} approaches for {identity}: the market was approached twice "
        "and that is the irreversible commercial loss this project exists to prevent"
    )
    assert receiver.duplicates() == {}, f"duplicates across the panel: {receiver.duplicates()}"


@pytest.mark.asyncio
async def test_the_n8n_arm_duplicates_under_the_same_overlap(engine: AsyncEngine) -> None:
    """The baseline, under the same harness. **If this passes, the comparison collapses.**

    ADR-001 says so in as many words: an n8n arm that cannot be made to duplicate would make this
    repository an ordinary CRUD workflow, and the honest response would be to replace the project
    rather than to soften the test.
    """
    receiver = CarrierReceiver()
    identity = str(_race_identity())

    await run_workflow_pair(engine, receiver=receiver, now=SEED_EPOCH, identity=identity)

    observed = receiver.count_for(identity)
    assert observed > 1, (
        f"the n8n arm approached {identity} only {observed} time(s) under a forced overlap. "
        "The graduation story rests on this failing; if it genuinely cannot fail, ADR-001 says to "
        "replace the project rather than weaken the test"
    )


@pytest.mark.asyncio
async def test_both_arms_together_and_the_result_is_written_for_the_console(
    engine: AsyncEngine,
) -> None:
    """Run both under one harness and publish the numbers the README and the console quote.

    Written by the test that measured it, so the figure a reader sees is the figure a run produced.
    A hand-typed comparison table is a claim; this is a measurement.
    """
    identity = str(_race_identity())

    n8n_receiver = CarrierReceiver()
    await run_workflow_pair(engine, receiver=n8n_receiver, now=SEED_EPOCH, identity=identity)

    await reset(engine)
    await seed(engine)

    python_receiver = CarrierReceiver()
    first_claimed = asyncio.Event()
    second_finished = asyncio.Event()

    async def hold_after_claim(_outcomes: Sequence[object]) -> None:
        first_claimed.set()
        await asyncio.wait_for(second_finished.wait(), timeout=30)

    async def second() -> None:
        await asyncio.wait_for(first_claimed.wait(), timeout=30)
        try:
            await run_tick(engine, receiver=python_receiver, now=SEED_EPOCH, actor="scheduler-b")
        finally:
            second_finished.set()

    await asyncio.gather(
        run_tick(
            engine,
            receiver=python_receiver,
            now=SEED_EPOCH,
            actor="scheduler-a",
            on_claimed=hold_after_claim,
        ),
        second(),
    )

    result: dict[str, object] = {
        "identity": identity,
        "n8n": {
            "observed": n8n_receiver.count_for(identity),
            "distinct_keys": n8n_receiver.distinct_keys_for(identity),
        },
        "python": {
            "observed": python_receiver.count_for(identity),
            "distinct_keys": python_receiver.distinct_keys_for(identity),
        },
        "ran_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")

    assert n8n_receiver.count_for(identity) > 1
    assert python_receiver.count_for(identity) == 1

    # Also copy it where the console reads it, when the console exists. Skipped silently rather
    # than failing: the backend test must not depend on a frontend directory being present.
    console = RESULT_PATH.parents[1] / "frontend" / "public" / "killtest.json"
    if console.parent.exists():
        console.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")


@pytest.mark.asyncio
async def test_skip_locked_is_what_does_the_work_not_the_cleared_due_at(
    engine: AsyncEngine,
) -> None:
    """**Does the Python arm pass for the right reason?**

    The claim does two things: it takes a row lock *and* sets ``due_at = NULL``. The kill test above
    releases the second tick after the first has committed, so by then the row is not due for either
    reason — meaning that test would pass identically with ``SKIP LOCKED`` deleted. A mechanism a
    test cannot distinguish from its own absence is a mechanism that test is not proving, and the
    README names this one specifically.

    So the overlap is forced one layer earlier: two claim transactions run concurrently and
    **neither commits**, so the cleared ``due_at`` is invisible to the other session and the row
    lock is the only thing left that can decide. Verified falsifiable by deleting the
    ``with_for_update(skip_locked=True)`` clause and watching this go red.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    claimed_by: list[str] = []

    async def claimer(name: str, *, hold: bool) -> None:
        async with AsyncSession(engine) as session, session.begin():
            outcomes = await claim_due_approaches(session, now=SEED_EPOCH, actor=name)
            if any(outcome.may_send for outcome in outcomes):
                claimed_by.append(name)
            if hold:
                started.set()
                await asyncio.wait_for(release.wait(), timeout=30)

    async def second() -> None:
        await asyncio.wait_for(started.wait(), timeout=30)
        try:
            await claimer("b", hold=False)
        finally:
            release.set()

    await asyncio.gather(claimer("a", hold=True), second())

    assert claimed_by == ["a"], (
        f"both sessions claimed the same approach ({claimed_by}): SELECT … FOR UPDATE SKIP LOCKED "
        "is not doing the work the README says it does, and the headline kill test was passing on "
        "the cleared due_at alone"
    )


@pytest.mark.asyncio
async def test_the_deploy_bootstrap_seeds_an_empty_database_once_and_never_again(
    engine: AsyncEngine,
) -> None:
    """The deployed demonstration runs on every boot. It must be a no-op on every boot but one.

    `deployment/entrypoint.sh` calls ``python -m market_approach_desk.demo.bootstrap`` after
    ``alembic upgrade head``, so this code runs on the first deploy, on every redeploy, and on
    every restart the platform decides to perform. The dangerous version of that hook is
    ``reset() + seed()``: it would work perfectly and silently wipe the board every time the free
    instance woke up. So the property under test is not *does it seed* — it is **does the second
    run write nothing at all**, measured by comparing every table before and after.
    """
    from market_approach_desk.demo.seed import bootstrap

    async def rows() -> dict[str, int]:
        counts: dict[str, int] = {}
        async with AsyncSession(engine) as session:
            for table in ("placement", "market", "market_approach", "carrier_reply"):
                counts[table] = (
                    await session.execute(sa_text(f"SELECT count(*) FROM {table}"))
                ).scalar_one()
        return counts

    # The autouse fixture leaves a seeded database; empty it so the first branch is the real one.
    await reset(engine)
    assert await rows() == dict.fromkeys(
        ("placement", "market", "market_approach", "carrier_reply"), 0
    )

    assert await bootstrap(engine) is True, "an empty database was not seeded"
    after_first = await rows()
    assert after_first["market_approach"] > 0, "bootstrap reported success and seeded nothing"

    assert await bootstrap(engine) is False, "a populated database was seeded a second time"
    assert await rows() == after_first, (
        "the second bootstrap changed the database: a redeploy or a restart would not be a no-op, "
        "and the deployed demonstration would reset under a visitor"
    )
