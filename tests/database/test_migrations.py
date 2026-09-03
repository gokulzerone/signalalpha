from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from database.embedded import EmbeddedPostgres
from database.models import Base
from tests.conftest import alembic_config


def test_migrations_round_trip_and_match_models(embedded_pg: EmbeddedPostgres) -> None:
    url = embedded_pg.create_database("signalalpha_migrations")
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    engine = create_engine(url, future=True)
    try:
        names = set(inspect(engine).get_table_names())
        assert set(Base.metadata.tables) <= names
        with engine.connect() as conn:
            fns = (
                conn.execute(text("SELECT proname FROM pg_proc WHERE proname LIKE 'sa_%_as_of'"))
                .scalars()
                .all()
            )
            assert set(fns) == {
                "sa_financials_as_of",
                "sa_shareholdings_as_of",
                "sa_universe_as_of",
                "sa_prices_as_of",
            }
            ext = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'")).scalar()
            assert ext == 1
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            assert compare_metadata(ctx, Base.metadata) == [], "models and migrations diverged"
        command.downgrade(cfg, "base")
        assert not (set(Base.metadata.tables) & set(inspect(engine).get_table_names()))
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()
