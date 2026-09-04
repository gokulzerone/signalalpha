"""Load real NSE data for a live universe (PRD §15 step 10).

    SIGNALALPHA_LIVE_EOD_PRICES=true SIGNALALPHA_LIVE_FINANCIAL_RESULTS=true \
    SIGNALALPHA_LIVE_NSE_ANNOUNCEMENTS=true \
    python scripts/sync_live.py --price-days 400 --universe 40

Steps, each idempotent and skippable:
  1. listed equities   -> live company rows
  2. daily bhavcopy    -> prices for every tracked company (one file per trading day)
  3. candidate pick    -> liquidity floor and traded-value ranking from the prices just loaded
  4. quarterly results -> XBRL financials per candidate (this is what fundamental signals need)
  5. announcements     -> the index-wide feed, filtered to the universe
  6. universe snapshot -> market cap from price x shares, cap band and liquidity applied
Signals, scores and agents then run over the live dataset exactly as they do over the mock one.
"""

from __future__ import annotations

import argparse
import statistics
import time
from datetime import date, timedelta

from sqlalchemy import func, select

from data.fetchers.settings import IngestionFlags, load_sources
from data.live import (
    client,
    ingest_announcements_feed,
    ingest_equity_list,
    ingest_prices_for_date,
    ingest_results_for_symbol,
)
from data.storage import get_object_store
from database.engine import session_scope
from database.models import Company, Financial, Price
from database.universe import build_universe_snapshots, load_universe_config


def trading_days(end: date, count: int) -> list[date]:
    out: list[date] = []
    d = end
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest real NSE data.")
    ap.add_argument(
        "--price-days", type=int, default=400, help="calendar-ish trading days of price history"
    )
    ap.add_argument(
        "--universe", type=int, default=40, help="how many companies to load fundamentals for"
    )
    ap.add_argument("--quarters", type=int, default=9, help="quarters of results per company")
    ap.add_argument("--as-of", type=date.fromisoformat, default=None)
    ap.add_argument("--skip-prices", action="store_true")
    ap.add_argument("--skip-results", action="store_true")
    ap.add_argument(
        "--announcement-days", type=int, default=90, help="days of announcement history"
    )
    ap.add_argument(
        "--max-turnover",
        type=float,
        default=2.5e8,
        help="upper daily traded-value bound for candidates (Rs)",
    )
    args = ap.parse_args()

    flags = IngestionFlags()
    if not flags.any_live:
        raise SystemExit(
            "No live source is enabled. Set SIGNALALPHA_LIVE_* flags; see docs/SOURCES.md."
        )
    as_of = args.as_of or date.today()
    registry = load_sources()
    store = get_object_store()
    nse = client(registry, flags)
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:6.0f}s] {msg}", flush=True)

    with session_scope() as session:
        companies = ingest_equity_list(session, store, nse, registry=registry)
        log(f"listed equities: {len(companies)} NSE 'EQ' companies")

    if not args.skip_prices and flags.live_eod_prices:
        days = trading_days(as_of, args.price_days)
        with session_scope() as session:
            companies = {
                c.ticker: c
                for c in session.scalars(select(Company).where(Company.is_mock.is_(False))).all()
            }
            loaded = skipped = 0
            for i, day in enumerate(days, 1):
                rep = ingest_prices_for_date(
                    session, store, nse, day, companies, flags=flags, registry=registry
                )
                loaded += rep.rows
                skipped += rep.skipped
                if i % 25 == 0 or i == len(days):
                    session.commit()
                    log(
                        f"prices {i}/{len(days)} days · {loaded} rows · {skipped} days without a file"
                    )
        log("prices done")

    # Candidates: the most traded names that clear the liquidity floor, from prices we hold.
    config = load_universe_config()
    with session_scope() as session:
        recent = as_of - timedelta(days=45)
        rows = session.execute(
            select(Price.company_id, func.count(Price.id), func.avg(Price.traded_value))
            .where(Price.is_mock.is_(False), Price.trade_date >= recent)
            .group_by(Price.company_id)
        ).all()
        liquid = [
            (cid, float(avg))
            for cid, n, avg in rows
            if n >= 10 and float(avg) >= float(config.liquidity_floor_inr)
        ]
        liquid.sort(key=lambda x: x[1])
        # Small caps are the product's subject, so prefer the thin end of the liquid range.
        chosen = [cid for cid, _ in liquid[: args.universe]]
        tickers = (
            dict(
                session.execute(
                    select(Company.id, Company.ticker).where(Company.id.in_(chosen))
                ).all()
            )
            if chosen
            else {}
        )
        log(
            f"candidates: {len(liquid)} names clear the liquidity floor; taking the {len(chosen)} smallest by traded value"
        )

    if not args.skip_results and flags.live_financial_results and chosen:
        for i, cid in enumerate(chosen, 1):
            with session_scope() as session:
                company = session.get(Company, cid)
                if company is None:
                    continue
                rep = ingest_results_for_symbol(
                    session,
                    store,
                    nse,
                    company,
                    quarters=args.quarters,
                    flags=flags,
                    registry=registry,
                )
            if i % 5 == 0 or i == len(chosen):
                log(f"results {i}/{len(chosen)} · last {tickers.get(cid, cid)}: {rep.line()}")

    if flags.live_nse_announcements:
        with session_scope() as session:
            companies = {
                c.ticker: c
                for c in session.scalars(select(Company).where(Company.is_mock.is_(False))).all()
            }
            rep = ingest_announcements_feed(
                session, store, nse, companies, flags=flags, registry=registry
            )
        log(rep.line())

    with session_scope() as session:
        n_fin = (
            session.scalar(select(func.count(Financial.id)).where(Financial.is_mock.is_(False)))
            or 0
        )
        with_fin = (
            session.scalar(
                select(func.count(func.distinct(Financial.company_id))).where(
                    Financial.is_mock.is_(False)
                )
            )
            or 0
        )
        dates = sorted(
            {
                d
                for (d,) in session.execute(
                    select(func.distinct(Price.trade_date)).where(Price.is_mock.is_(False))
                ).all()
            }
        )
        # Month ends plus the latest trading day, so the universe is versioned over time.
        by_month: dict[tuple[int, int], date] = {}
        for d in dates:
            by_month[(d.year, d.month)] = max(by_month.get((d.year, d.month), d), d)
        snapshot_dates = sorted({*by_month.values(), dates[-1]})[-24:] if dates else []
        n = build_universe_snapshots(
            session, is_mock=False, snapshot_dates=snapshot_dates, config=config
        )
        log(
            f"universe: {n} snapshots over {len(snapshot_dates)} dates · {with_fin} companies with financials · {n_fin} financial rows"
        )
        in_band = session.execute(
            select(func.count()).select_from(
                select(Company.id)
                .join(Financial, Financial.company_id == Company.id)
                .where(Financial.is_mock.is_(False))
                .distinct()
                .subquery()
            )
        ).scalar()
        log(
            f"done. {in_band} live companies carry fundamentals; median price history {statistics.median([len(dates)]) if dates else 0} days"
        )


if __name__ == "__main__":
    main()
