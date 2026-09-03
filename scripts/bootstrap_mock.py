"""Prepare a database for the mock stack (PRD §17 definition of done, no network):
migrate -> generate the mock universe -> signals -> scores -> backtest -> agents.

    SIGNALALPHA_DATABASE_URL=embedded python scripts/bootstrap_mock.py [--as-of 2026-08-31]
"""

from __future__ import annotations

import argparse
import time
from datetime import date

from alembic import command
from alembic.config import Config

from agents.pipeline import run_agents
from backtesting.engine import month_ends, run_backtest
from data.mock.generator import MockDataExistsError, generate_mock_universe
from data.storage import get_object_store
from database.engine import get_engine, resolve_database_url, session_scope
from database.pit import PointInTimeSession
from scoring.pipeline import run_scores
from signals.runner import detect_universe_signals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 8, 31))
    parser.add_argument("--skip-agents", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    t0 = time.time()

    cfg = Config("database/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", resolve_database_url())
    command.upgrade(cfg, "head")
    print(f"[{time.time() - t0:5.0f}s] migrated")
    get_engine()

    with session_scope() as session:
        try:
            report = generate_mock_universe(session, get_object_store(), replace=args.replace)
            n = report.counts.get("companies")
            print(f"[{time.time() - t0:5.0f}s] mock universe: {n} companies")
        except MockDataExistsError:
            print(f"[{time.time() - t0:5.0f}s] mock universe already present")
    with session_scope() as session:
        results = detect_universe_signals(session, as_of=args.as_of, is_mock=True)
        created = sum(len(r.created) for r in results.values())
        print(f"[{time.time() - t0:5.0f}s] signals: {created} new")
    with session_scope() as session:
        for on in month_ends(date(2024, 6, 1), args.as_of, step_months=3):
            run_scores(session, as_of=on, is_mock=True)
        run_scores(session, as_of=args.as_of, is_mock=True)
        print(f"[{time.time() - t0:5.0f}s] scores")
    with session_scope() as session:
        score_dates = month_ends(date(2024, 6, 1), args.as_of, step_months=3)
        bt = run_backtest(
            session,
            as_of=args.as_of,
            is_mock=True,
            since=date(2023, 6, 30),
            score_dates=score_dates,
        )
        print(f"[{time.time() - t0:5.0f}s] backtest run {bt.run_id}: {bt.n_events} event-horizons")
    if not args.skip_agents:
        with session_scope() as session:
            pit = PointInTimeSession(session, args.as_of, is_mock=True)
            done = 0
            for company in pit.companies():
                if company.delisted_on is not None:
                    continue
                steps = run_agents(session, company, args.as_of, is_mock=True)
                done += sum(1 for s in steps if s["status"] == "completed")
            print(f"[{time.time() - t0:5.0f}s] agents: {done} completed steps")
    print("done")


if __name__ == "__main__":
    main()
