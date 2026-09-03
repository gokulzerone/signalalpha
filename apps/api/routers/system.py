"""System endpoints (PRD §10): data quality, signal performance."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from apps.api.deps import PitDep
from apps.api.envelope import wrap
from apps.api.schemas import DataQualityRow, Envelope, PerformanceOut, PerformanceRow
from database.models import BacktestRun, Company, DataQuality, ScorePerformance, SignalPerformance

router = APIRouter(tags=["system"])


@router.get("/data-quality", response_model=Envelope[list[DataQualityRow]])
def data_quality(pit: PitDep) -> Envelope[list[DataQualityRow]]:
    tickers = {c.id: c.ticker for c in pit.companies()}
    rows = pit.session.scalars(
        select(DataQuality)
        .where(DataQuality.is_mock == pit.is_mock)
        .order_by(DataQuality.company_id, DataQuality.source)
    ).all()
    return wrap(
        pit,
        [
            DataQualityRow(
                company_id=r.company_id,
                ticker=tickers.get(r.company_id) if r.company_id else None,
                source=r.source.value,
                last_fetch_at=r.last_fetch_at,
                last_success_at=r.last_success_at,
                latest_public_at=r.latest_public_at,
                fetch_failure_count=r.fetch_failure_count,
                parse_failure_count=r.parse_failure_count,
                last_error=r.last_error,
            )
            for r in rows
        ],
    )


def _latest_run(pit: PitDep) -> BacktestRun | None:
    return pit.session.scalars(
        select(BacktestRun)
        .where(BacktestRun.is_mock == pit.is_mock, BacktestRun.as_of <= pit.as_of_date)
        .order_by(BacktestRun.as_of.desc(), BacktestRun.id.desc())
    ).first()


@router.get("/signals/performance", response_model=Envelope[PerformanceOut])
def signal_performance(pit: PitDep) -> Envelope[PerformanceOut]:
    run = _latest_run(pit)
    if run is None:
        return wrap(
            pit, PerformanceOut(backtest_run_id=None, as_of=None, config_version=None, rows=[])
        )
    rows = pit.session.scalars(
        select(SignalPerformance)
        .where(SignalPerformance.backtest_run_id == run.id)
        .order_by(
            SignalPerformance.signal_type, SignalPerformance.decile, SignalPerformance.horizon_days
        )
    ).all()
    from datetime import datetime

    from database.pit import IST

    return wrap(
        pit,
        PerformanceOut(
            backtest_run_id=run.id,
            as_of=datetime.combine(run.as_of, datetime.min.time(), tzinfo=IST),
            config_version=run.config_version,
            rows=[
                PerformanceRow(
                    subject=r.signal_type,
                    decile=r.decile,
                    horizon_days=r.horizon_days,
                    n=r.n,
                    low_sample=r.low_sample,
                    stats=r.stats,
                )
                for r in rows
            ],
        ),
    )


@router.get("/scores/performance", response_model=Envelope[PerformanceOut])
def score_performance(pit: PitDep) -> Envelope[PerformanceOut]:
    run = _latest_run(pit)
    if run is None:
        return wrap(
            pit, PerformanceOut(backtest_run_id=None, as_of=None, config_version=None, rows=[])
        )
    rows = pit.session.scalars(
        select(ScorePerformance)
        .where(ScorePerformance.backtest_run_id == run.id)
        .order_by(
            ScorePerformance.score_type, ScorePerformance.decile, ScorePerformance.horizon_days
        )
    ).all()
    from datetime import datetime

    from database.pit import IST

    return wrap(
        pit,
        PerformanceOut(
            backtest_run_id=run.id,
            as_of=datetime.combine(run.as_of, datetime.min.time(), tzinfo=IST),
            config_version=run.config_version,
            rows=[
                PerformanceRow(
                    subject=r.score_type,
                    decile=r.decile,
                    horizon_days=r.horizon_days,
                    n=r.n,
                    low_sample=r.low_sample,
                    stats=r.stats,
                )
                for r in rows
            ],
        ),
    )


def _unused(_: type[Company]) -> None:
    return None
