"""Typed configuration. Every value arrives from the environment; none is invented here."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    """What the service needs to start.

    ``extra="forbid"`` so a misspelled variable fails at startup rather than being silently ignored
    — the failure mode where a setting looks configured and is not.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAD_", env_file=".env", extra="forbid", case_sensitive=False
    )

    postgres_dsn: SecretStr = Field(
        default=SecretStr("postgresql://mad:mad_local_dev@localhost:15433/mad"),
        description="PostgreSQL DSN. A secret because it carries a password.",
    )

    environment: str = Field(default="local", pattern="^(local|ci|staging|production)$")

    #: Publishes the comparison endpoint that runs both arms. Off outside the demonstration: it
    #: seeds and resets data, which is not something a production deployment should offer.
    demo_mode: bool = Field(default=False)

    #: Fail-closed. An empty list means no browser origin may call the API directly, which is
    #: correct when the console reaches it server-side.
    cors_allow_origins: list[str] = Field(default_factory=list)
