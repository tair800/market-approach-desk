"""The read API the console reads. **Every endpoint here is a read.**

An earlier version of this docstring described three demonstration-control endpoints that answer
404 outside demo mode. They do not exist and never did; a reviewer of the console caught the
paragraph describing functionality this module does not have, which is exactly what CLAUDE.md rule 8
forbids. Corrected rather than implemented: the controls were not needed, and the honest fix for a
promise nothing kept is to stop making it.

**No endpoint lets a caller approach a carrier**, and that is the load-bearing property. The only
path to a send is a scheduler tick, because that is the path the claim transaction protects. An
endpoint that sent one outside it would be a second dispatch route, and the claim of ADR-001 would
be false the moment it existed.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from market_approach_desk.config import Settings
from market_approach_desk.db.engine import build_engine
from market_approach_desk.db.models import (
    ApproachAttempt,
    AuditEvent,
    CarrierReply,
    Market,
    MarketApproach,
    Placement,
)
from market_approach_desk.domain.identity import ApproachState

__all__ = ["create_app"]


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarketView(_View):
    id: uuid.UUID
    name: str
    underwriter: str
    within_placing_authority: bool


class ApproachView(_View):
    """One cell of the placement-by-carrier matrix the console renders."""

    id: uuid.UUID
    market: MarketView
    stage: str
    state: str
    attempt_count: int
    blocked_reason: str | None
    due_at: dt.datetime | None
    follow_up_at: dt.datetime | None
    sent_at: dt.datetime | None
    #: True when a follow-up is due and nothing has answered. The console colours on this rather
    #: than recomputing a date in the browser, so one clock decides.
    follow_up_overdue: bool
    reply_classification: str | None
    reply_abstained: bool


class PlacementView(_View):
    id: uuid.UUID
    reference: str
    insured_name: str
    class_of_business: str
    handler: str
    inception_on: dt.date
    approaches: list[ApproachView]


class AuditView(_View):
    occurred_at: dt.datetime
    verb: str
    identity: str
    actor: str
    detail: str | None


class HealthView(_View):
    status: str
    service: str
    version: str


class MetaView(_View):
    version: str
    demo_mode: bool
    #: The commit actually running, so a claim about what is deployed can be checked rather than
    #: assumed. Empty when the platform sets no revision variable.
    revision: str


def _engine(request: Request) -> AsyncEngine:
    engine = request.app.state.engine
    assert isinstance(engine, AsyncEngine)
    return engine


EngineDep = Annotated[AsyncEngine, Depends(_engine)]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = build_engine(resolved)
        app.state.settings = resolved
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(
        title="market-approach-desk",
        version="0.1.0",
        docs_url=None if resolved.environment == "production" else "/docs",
        lifespan=lifespan,
    )

    # Fail-closed: an empty allowlist installs no middleware at all, so no browser origin is
    # permitted. The console reaches this API server-side and needs none.
    if resolved.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_allow_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    @app.get("/healthz", response_model=HealthView)
    async def healthz() -> HealthView:
        """Liveness. Touches nothing external, so a dependency outage cannot restart the process."""
        return HealthView(status="alive", service="market-approach-desk", version="0.1.0")

    @app.get("/readyz")
    async def readyz(engine: EngineDep) -> dict[str, Any]:
        """Readiness. Answers for the database, because without it nothing here can serve."""
        try:
            async with engine.connect() as connection:
                await connection.execute(select(1))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "not_ready", "postgres": "unreachable"},
            ) from None
        return {"status": "ready", "postgres": "healthy"}

    @app.get("/api/v1/meta", response_model=MetaView)
    async def meta() -> MetaView:
        import os

        for name in ("RENDER_GIT_COMMIT", "VERCEL_GIT_COMMIT_SHA", "GIT_COMMIT_SHA"):
            revision = os.environ.get(name)
            if revision:
                break
        else:
            revision = ""
        return MetaView(version="0.1.0", demo_mode=resolved.demo_mode, revision=revision)

    @app.get("/api/v1/placements", response_model=list[PlacementView])
    async def placements(engine: EngineDep) -> list[PlacementView]:
        """The board: every placement with its carrier panel and the state of each approach."""
        now = dt.datetime.now(dt.UTC)
        async with AsyncSession(engine) as session:
            rows = (
                (await session.execute(select(Placement).order_by(Placement.reference)))
                .scalars()
                .all()
            )
            markets = {
                market.id: market
                for market in (await session.execute(select(Market))).scalars().all()
            }
            approaches = (await session.execute(select(MarketApproach))).scalars().all()
            replies = {
                reply.approach_id: reply
                for reply in (await session.execute(select(CarrierReply))).scalars().all()
            }

        by_placement: dict[uuid.UUID, list[ApproachView]] = {}
        for approach in approaches:
            market = markets.get(approach.market_id)
            if market is None:  # pragma: no cover - foreign key makes this unreachable
                continue
            reply = replies.get(approach.id)
            by_placement.setdefault(approach.placement_id, []).append(
                ApproachView(
                    id=approach.id,
                    market=MarketView(
                        id=market.id,
                        name=market.name,
                        underwriter=market.underwriter,
                        within_placing_authority=market.within_placing_authority,
                    ),
                    stage=approach.stage,
                    state=approach.state,
                    attempt_count=approach.attempt_count,
                    blocked_reason=approach.blocked_reason,
                    due_at=approach.due_at,
                    follow_up_at=approach.follow_up_at,
                    sent_at=approach.sent_at,
                    follow_up_overdue=(
                        approach.follow_up_at is not None
                        and approach.follow_up_at <= now
                        and approach.state == ApproachState.SENT.value
                    ),
                    reply_classification=reply.classification if reply else None,
                    reply_abstained=bool(reply.abstained) if reply else False,
                )
            )

        return [
            PlacementView(
                id=placement.id,
                reference=placement.reference,
                insured_name=placement.insured_name,
                class_of_business=placement.class_of_business,
                handler=placement.handler,
                inception_on=placement.inception_on,
                approaches=sorted(by_placement.get(placement.id, []), key=lambda a: a.market.name),
            )
            for placement in rows
        ]

    @app.get("/api/v1/audit", response_model=list[AuditView])
    async def audit(engine: EngineDep, limit: int = 100) -> list[AuditView]:
        """The append-only trail, newest first.

        The answer to the question that gets asked when a market is blocked: who approached this
        carrier, and when.
        """
        async with AsyncSession(engine) as session:
            rows = (
                (
                    await session.execute(
                        select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            AuditView(
                occurred_at=row.occurred_at,
                verb=row.verb,
                identity=row.identity,
                actor=row.actor,
                detail=row.detail,
            )
            for row in rows
        ]

    @app.get("/api/v1/stats")
    async def stats(engine: EngineDep) -> dict[str, Any]:
        """Counts the console shows above the board, computed in the database not the browser."""
        async with AsyncSession(engine) as session:
            counted = (
                await session.execute(
                    select(MarketApproach.state, func.count()).group_by(MarketApproach.state)
                )
            ).all()
            by_state: dict[str, int] = dict(counted)  # type: ignore[arg-type]
            attempts = (
                await session.execute(select(func.count()).select_from(ApproachAttempt))
            ).scalar_one()
        return {"by_state": by_state, "attempts": attempts}

    return app
