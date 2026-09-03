"""Embedded PostgreSQL for local development and tests (no Docker required)."""

from __future__ import annotations

from pathlib import Path

from pgserver.postgres_server import get_server


class EmbeddedPostgres:
    """Owns a pgserver instance and exposes a SQLAlchemy URL with the psycopg driver."""

    def __init__(self, data_dir: Path) -> None:
        data_dir.parent.mkdir(parents=True, exist_ok=True)
        self._server = get_server(str(data_dir))

    @property
    def url(self) -> str:
        raw: str = self._server.get_uri()
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)

    def create_database(self, name: str) -> str:
        """Create a fresh database (dropping any existing one) and return its URL."""
        import psycopg

        with psycopg.connect(self._server.get_uri(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
            conn.execute(f'CREATE DATABASE "{name}"')
        return self.url.replace("/postgres?", f"/{name}?", 1)

    def cleanup(self) -> None:
        self._server.cleanup()
