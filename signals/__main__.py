"""CLI: ``python -m signals run --as-of YYYY-MM-DD [--dataset mock|live] [--ticker T]``."""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import select

from database.engine import session_scope
from database.models import Company
from signals.runner import detect_company_signals, detect_universe_signals


def main() -> None:
    parser = argparse.ArgumentParser(prog="signals")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--as-of", type=date.fromisoformat, required=True)
    run.add_argument("--dataset", choices=["mock", "live"], default="mock")
    run.add_argument("--ticker", default=None)
    args = parser.parse_args()
    is_mock = args.dataset == "mock"
    with session_scope() as session:
        if args.ticker:
            company = session.scalars(select(Company).where(Company.ticker == args.ticker)).one()
            results = {
                company.id: detect_company_signals(
                    session, company, as_of=args.as_of, is_mock=is_mock
                )
            }
        else:
            results = detect_universe_signals(session, as_of=args.as_of, is_mock=is_mock)
        total = sum(len(r.created) for r in results.values())
        for cid, r in results.items():
            print(
                f"company {cid}: {len(r.created)} new signals "
                f"({r.duplicates_skipped} already present)"
            )
        print(f"total new signals: {total}")


if __name__ == "__main__":
    main()
