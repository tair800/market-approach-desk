"""`python -m market_approach_desk.demo` — reset and seed the local database.

Deliberately a module rather than an endpoint: seeding wipes tables, and the thing that wipes
tables should be run by a person at a shell, not reachable over HTTP.
"""

from __future__ import annotations

import asyncio

from market_approach_desk.config import Settings
from market_approach_desk.db.engine import build_engine
from market_approach_desk.demo.seed import reset, seed


async def _main() -> None:
    settings = Settings()
    dsn = settings.postgres_dsn.get_secret_value()
    # Refuse anything that is not obviously a throwaway database. Named hosts only: a check on the
    # port would be weaker, because a real database can live on any port.
    if "localhost" not in dsn and "127.0.0.1" not in dsn:
        raise SystemExit(
            "refusing to reset a database that is not local: seeding deletes every row, and the "
            "only safe target is a disposable one"
        )
    engine = build_engine(settings)
    try:
        await reset(engine)
        await seed(engine)
        print("seeded: 1 placement, 5 carriers, 5 approaches")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
