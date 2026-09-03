"""CLI: ``python -m scoring run --as-of YYYY-MM-DD [--dataset mock|live]``."""

from __future__ import annotations

import argparse
from datetime import date

from database.engine import session_scope
from scoring.pipeline import run_scores


def main() -> None:
    parser = argparse.ArgumentParser(prog="scoring")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--as-of", type=date.fromisoformat, required=True)
    run.add_argument("--dataset", choices=["mock", "live"], default="mock")
    args = parser.parse_args()
    with session_scope() as session:
        result = run_scores(session, as_of=args.as_of, is_mock=args.dataset == "mock")
        summary = f"scored {len(result.results)} companies as of {result.as_of}"
        print(f"{summary}: {result.rows_written} rows")


if __name__ == "__main__":
    main()
