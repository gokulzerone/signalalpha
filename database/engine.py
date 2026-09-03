"""Engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from database.settings import get_settings


@lru_cache(maxsize=1)
def _embedded(data_dir: Path) -> str:
    from database.embedded import EmbeddedPostgres

    return EmbeddedPostgres(data_dir).url


def resolve_database_url() -> str:
    settings = get_settings()
    if settings.database_url == "embedded":
        return _embedded(settings.embedded_pg_dir)
    return settings.database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(resolve_database_url(), echo=get_settings().echo_sql, future=True)


def get_sessionmaker(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    session = get_sessionmaker(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
