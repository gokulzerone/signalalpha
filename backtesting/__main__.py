"""CLI: ``python -m backtesting run --as-of DATE [--since DATE] [--scores-from DATE]``."""

from __future__ import annotations

import argparse
from datetime import date

from backtesting.engine import month_ends, run_backtest
from database.engine import session_scope


def main() -> None:
    parser = argparse.ArgumentParser(prog="backtesting")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--as-of", type=date.fromisoformat, required=True)
    run.add_argument("--since", type=date.fromisoformat, default=None)
    run.add_argument(
        "--scores-from",
        type=date.fromisoformat,
        default=None,
        help="monthly score deciles from this date",
    )
    run.add_argument("--dataset", choices=["mock", "live"], default="mock")
    args = parser.parse_args()
    score_dates = month_ends(args.scores_from, args.as_of) if args.scores_from else None
    with session_scope() as session:
        report = run_backtest(
            session,
            as_of=args.as_of,
            is_mock=args.dataset == "mock",
            since=args.since,
            score_dates=score_dates,
        )
        print(f"run {report.run_id}: {report.n_events} event-horizons, {len(report.groups)} groups")
        for g in report.groups:
            if g.horizon_days == 180:
                flag = " (low sample)" if g.low_sample else ""
                line = f"  {g.kind:6} {g.subject:32} d{g.bucket:<2} n={g.events.n:4}"
                print(f"{line} mean_excess={g.events.mean_excess!s:>8}{flag}")


if __name__ == "__main__":
    main()
