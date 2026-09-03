"""Shared fixtures: an embedded PostgreSQL 16 + pgvector instance migrated with Alembic.

Every test runs inside a transaction that is rolled back, so tests never see each other's
rows. No Docker or external network is required (PRD §14).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from database.embedded import EmbeddedPostgres

if TYPE_CHECKING:
    from data.mock.generator import GenerationReport
    from data.storage import LocalObjectStore

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "database" / "alembic.ini"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ROOT / "database" / "migrations"))
    os.environ["SIGNALALPHA_DATABASE_URL"] = url
    return cfg


@pytest.fixture(scope="session")
def embedded_pg(tmp_path_factory: pytest.TempPathFactory) -> Iterator[EmbeddedPostgres]:
    pg = EmbeddedPostgres(tmp_path_factory.mktemp("pgdata"))
    try:
        yield pg
    finally:
        pg.cleanup()


@pytest.fixture(scope="session")
def database_url(embedded_pg: EmbeddedPostgres) -> str:
    url = embedded_pg.create_database("signalalpha_test")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url, future=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        sess = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield sess
        finally:
            sess.close()
            transaction.rollback()


# ----------------------------------------------------------------- mock universe
# A second database holding the generated mock universe, committed once per test session and
# shared read-only by the signal, score, backtest and API tests.


@pytest.fixture(scope="session")
def mock_database_url(embedded_pg: EmbeddedPostgres) -> str:
    url = embedded_pg.create_database("signalalpha_mock")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
def mock_engine(mock_database_url: str) -> Iterator[Engine]:
    eng = create_engine(mock_database_url, future=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(scope="session")
def mock_store(tmp_path_factory: pytest.TempPathFactory) -> LocalObjectStore:
    from data.storage import LocalObjectStore

    return LocalObjectStore(tmp_path_factory.mktemp("objects"))


@pytest.fixture(scope="session")
def mock_universe(mock_engine: Engine, mock_store: LocalObjectStore) -> GenerationReport:
    from data.mock.generator import generate_mock_universe

    with Session(mock_engine, expire_on_commit=False) as sess:
        report = generate_mock_universe(sess, mock_store)
        sess.commit()
    return report


@pytest.fixture
def mock_session(mock_engine: Engine, mock_universe: GenerationReport) -> Iterator[Session]:
    with mock_engine.connect() as connection:
        transaction = connection.begin()
        sess = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield sess
        finally:
            sess.close()
            transaction.rollback()
