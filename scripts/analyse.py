"""Run the analysis pipeline over either dataset: signals -> scores -> backtest -> agents.

    python scripts/analyse.py --dataset live --as-of 2026-09-03

Every stage is idempotent, so this can be re-run after new data lands. It never fetches:
ingestion is a separate, feature-flagged step (scripts/sync_live.py).
"""

from __future__ import annotations

import argparse
import time
from datetime import date

from sqlalchemy import func, select

from agents.pipeline import run_agents
from backtesting.engine import month_ends, run_backtest
from database.engine import session_scope
from database.models import Company, Financial
from database.pit import PointInTimeSession
from scoring.pipeline import run_scores
from signals.runner import detect_universe_signals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["mock", "live"], default="live")
    ap.add_argument("--as-of", type=date.fromisoformat, required=True)
    ap.add_argument(
        "--score-from",
        type=date.fromisoformat,
        default=None,
        help="also score month ends from this date",
    )
    ap.add_argument(
        "--agents-as-of",
        type=date.fromisoformat,
        default=None,
        help="date to run agents at (default: --as-of)",
    )
    ap.add_argument("--skip-agents", action="store_true")
    ap.add_argument("--skip-backtest", action="store_true")
    args = ap.parse_args()
    is_mock = args.dataset == "mock"
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:6.0f}s] {msg}", flush=True)

    with session_scope() as session:
        results = detect_universe_signals(session, as_of=args.as_of, is_mock=is_mock)
        log(
            f"signals: {sum(len(r.created) for r in results.values())} new across {len(results)} companies"
        )

    dates = month_ends(args.score_from, args.as_of, step_months=1) if args.score_from else []
    with session_scope() as session:
        for on in [*dates, args.as_of]:
            run = run_scores(session, as_of=on, is_mock=is_mock)
            session.commit()
        log(f"scores: {len(dates) + 1} dates, {run.rows_written} rows on the last")

    if not args.skip_backtest:
        with session_scope() as session:
            since = args.score_from or (args.as_of.replace(year=args.as_of.year - 1))
            report = run_backtest(
                session, as_of=args.as_of, is_mock=is_mock, since=since, score_dates=dates or None
            )
            log(
                f"backtest run {report.run_id}: {report.n_events} event-horizons, {len(report.groups)} groups"
            )

    if not args.skip_agents:
        agents_as_of = args.agents_as_of or args.as_of
        with session_scope() as session:
            pit = PointInTimeSession(session, agents_as_of, is_mock=is_mock)
            # Only companies whose fundamentals the agents can actually read.
            have = {
                cid
                for (cid,) in session.execute(
                    select(Financial.company_id)
                    .where(Financial.is_mock.is_(is_mock))
                    .group_by(Financial.company_id)
                    .having(func.count(Financial.id) >= 4)
                ).all()
            }
            targets = [c for c in pit.companies() if c.id in have and c.delisted_on is None]
        done = failed = 0
        for company in targets:
            with session_scope() as session:
                fresh = session.get(Company, company.id)
                assert fresh is not None
                steps = run_agents(session, fresh, agents_as_of, is_mock=is_mock)
            done += sum(1 for s in steps if s["status"] == "completed")
            failed += sum(1 for s in steps if s["status"] == "failed")
        log(
            f"agents at {agents_as_of}: {done} steps completed, {failed} failed, across {len(targets)} companies"
        )
    log("done")


if __name__ == "__main__":
    main()
