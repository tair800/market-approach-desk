"""`python -m market_approach_desk.demo.bootstrap` — seed a deployed demonstration, once.

Separate from :mod:`market_approach_desk.demo` because the two do different things and only one of
them is safe to run automatically. That module resets and seeds, which truncates every table, and it
refuses any DSN that is not local for exactly that reason. This one **never deletes anything**: it
seeds an empty database and returns, so a restart, a redeploy or a scale event is a no-op.
"""

from __future__ import annotations

import asyncio

from market_approach_desk.config import Settings
from market_approach_desk.db.engine import build_engine
from market_approach_desk.demo.seed import bootstrap


async def _main() -> None:
    settings = Settings()
    if not settings.demo_mode:
        print("demo mode is off; nothing seeded")
        return
    engine = build_engine(settings)
    try:
        seeded = await bootstrap(engine)
        print("seeded the demonstration" if seeded else "already populated; nothing written")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
