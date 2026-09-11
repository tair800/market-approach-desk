"""Turning a configured DSN into one SQLAlchemy asyncpg can actually connect with.

The normalisation below is not hypothetical tidiness. A managed PostgreSQL provider issues a URL
ending ``?sslmode=require&channel_binding=require``, and pasted in verbatim it produces a service
that **reports itself healthy and cannot serve a request**: a direct ``asyncpg.connect(dsn)`` parses
the URL itself and understands ``sslmode``, while SQLAlchemy's asyncpg dialect splits the query
string into *keyword arguments* and calls a function whose signature has no place to put them.

Unrecognised parameters are **kept**, not dropped. Silently discarding a future provider's required
option would fail with no error at all, which is worse than the failure this fixes.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from market_approach_desk.config import Settings

__all__ = ["async_dsn", "build_engine"]

#: ``sslmode`` values that mean "use TLS". asyncpg spells the same idea ``ssl``.
_TLS_MODES: Final = frozenset({"require", "verify-ca", "verify-full"})

#: Dropped outright: asyncpg negotiates SCRAM channel binding itself and has no connect argument
#: for it, so forwarding the parameter is a guaranteed ``TypeError``.
_UNSUPPORTED: Final = frozenset({"channel_binding"})

#: A pooled endpoint runs pgBouncer in transaction mode, which does not keep a prepared statement
#: across checkouts. Caching them there produces intermittent errors under load and nowhere else.
_POOLED_MARKER: Final = "-pooler."


def async_dsn(settings: Settings) -> str:
    """The DSN with the asyncpg driver and a query string asyncpg can accept."""
    raw = settings.postgres_dsn.get_secret_value()
    parts = urlsplit(raw)
    scheme = "postgresql+asyncpg" if "+" not in parts.scheme else parts.scheme
    query = _normalise(parts.query, host=parts.hostname or "")
    return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))


def _normalise(query: str, *, host: str) -> str:
    pairs = parse_qsl(query, keep_blank_values=True)
    out: list[tuple[str, str]] = []
    for key, value in pairs:
        if key in _UNSUPPORTED:
            continue
        if key == "sslmode":
            if value in _TLS_MODES:
                out.append(("ssl", "require"))
            # `disable`/`allow`/`prefer` mean "do not insist", which is asyncpg's default. Emitting
            # nothing is the faithful translation; emitting `ssl=disable` would be a demand.
            continue
        out.append((key, value))

    if _POOLED_MARKER in host and not any(k == "prepared_statement_cache_size" for k, _ in out):
        out.append(("prepared_statement_cache_size", "0"))
    return urlencode(out)


def build_engine(settings: Settings) -> AsyncEngine:
    """One engine for the process.

    ``pool_pre_ping`` because a free-tier database suspends when idle and hands back a connection
    that looks alive and is not.
    """
    return create_async_engine(async_dsn(settings), pool_pre_ping=True, future=True)
