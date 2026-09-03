"""Database settings.

`SIGNALALPHA_DATABASE_URL` selects the database. The special value ``embedded`` starts a
local PostgreSQL 16 + pgvector server (via ``pgserver``) under ``SIGNALALPHA_EMBEDDED_PG_DIR``
so that development and CI need no Docker. Production uses a normal PostgreSQL URL.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNALALPHA_", extra="ignore")

    database_url: str = "embedded"
    embedded_pg_dir: Path = Path.home() / ".signalalpha" / "pgdata"
    """Kept outside the repository: the Unix socket path must be short and space-free."""
    echo_sql: bool = False


def get_settings() -> DatabaseSettings:
    return DatabaseSettings()
