"""CLI: ``python -m data.mock generate [--replace] [--seed N]``."""

from __future__ import annotations

import argparse
import time

from data.mock.generator import generate_mock_universe
from data.storage import get_object_store
from database.engine import session_scope


def main() -> None:
    parser = argparse.ArgumentParser(prog="data.mock")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="generate the mock universe into the configured database")
    gen.add_argument("--replace", action="store_true", help="delete existing mock data first")
    gen.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    if args.command == "generate":
        started = time.time()
        with session_scope() as session:
            kwargs = {"seed": args.seed} if args.seed is not None else {}
            report = generate_mock_universe(
                session, get_object_store(), replace=args.replace, **kwargs
            )
        for key, value in sorted(report.counts.items()):
            print(f"{key:>22}: {value}")
        print(f"seed {report.seed}, {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
