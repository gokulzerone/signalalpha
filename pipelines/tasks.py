"""Celery tasks. Idempotent by design: the research pipeline re-runs signals and scores
without creating duplicates, and agent runs are cached by their input hash."""

from __future__ import annotations

from database.engine import session_scope
from pipelines.celery_app import celery_app
from pipelines.research import execute_run


@celery_app.task(name="research.run", queue="agents")
def research_task(run_id: str, agents: list[str] | None = None) -> str:
    with session_scope() as session:
        run = execute_run(session, run_id, agents=agents)
        return run.status.value


@celery_app.task(name="investigate.run", queue="agents")
def investigation_task(investigation_id: str) -> str:
    from investigations.runner import run_investigation

    with session_scope() as session:
        return run_investigation(session, investigation_id).status.value


@celery_app.task(name="ingest.eod_prices", queue="ingest")
def eod_prices_task(trade_date: str | None = None) -> dict[str, int]:
    """Daily EOD prices for the live universe (feature-flagged)."""
    from datetime import date

    from data.fetchers.settings import IngestionFlags, load_sources
    from data.fetchers.transport import HttpTransport
    from data.ingest import (
        FeatureDisabledError,
        ingest_eod_prices,
        previous_trading_day,
        sync_live_universe,
    )
    from data.storage import get_object_store

    flags = IngestionFlags()
    if not flags.live_eod_prices:
        raise FeatureDisabledError("SIGNALALPHA_LIVE_EOD_PRICES is off")
    on = date.fromisoformat(trade_date) if trade_date else previous_trading_day()
    with session_scope() as session:
        companies = sync_live_universe(session)
        report = ingest_eod_prices(
            session,
            get_object_store(),
            HttpTransport(load_sources(), flags.contact),
            on,
            flags=flags,
            companies=companies,
        )
        return {"rows": report.rows, "skipped": report.skipped}


@celery_app.task(name="ingest.nse_announcements", queue="ingest")
def announcements_task(days: int = 7) -> dict[str, int]:
    """NSE announcements for every live company (feature-flagged)."""
    from datetime import date, timedelta

    from data.fetchers.settings import IngestionFlags, load_sources
    from data.fetchers.transport import HttpTransport
    from data.ingest import FeatureDisabledError, ingest_announcements, sync_live_universe
    from data.storage import get_object_store

    flags = IngestionFlags()
    if not flags.live_nse_announcements:
        raise FeatureDisabledError("SIGNALALPHA_LIVE_NSE_ANNOUNCEMENTS is off")
    total = 0
    with session_scope() as session:
        transport = HttpTransport(load_sources(), flags.contact)
        for company in sync_live_universe(session).values():
            total += ingest_announcements(
                session,
                get_object_store(),
                transport,
                company,
                date.today() - timedelta(days=days),
                flags=flags,
            ).rows
    return {"rows": total}
