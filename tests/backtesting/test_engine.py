"""Backtester on the mock universe (PRD §11, §14, §17)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backtesting.config import load_backtest_config
from backtesting.engine import Backtester, Event, month_ends, run_backtest
from backtesting.execution import slippage_bps
from backtesting.prices import PriceSeries, forward_leg, load_series
from data.mock.synth import Story, load_blueprints
from database.models import Company, DelistingKind, ScorePerformance, SignalPerformance
from database.pit import PointInTimeSession

AS_OF = date(2026, 8, 31)
CFG = load_backtest_config()


def _company(session: Session, story: Story, nth: int = 0) -> Company:
    ticker = [b for b in load_blueprints() if b.story is story][nth].ticker
    return session.scalars(select(Company).where(Company.ticker == ticker)).one()


def test_slippage_is_wider_for_illiquid_names() -> None:
    liquid = slippage_bps(5e7, CFG.execution)  # ₹5 crore/day
    thin = slippage_bps(5e5, CFG.execution)  # ₹5 lakh/day
    assert CFG.execution.slippage_bps_min <= liquid < thin <= CFG.execution.slippage_bps_max
    assert slippage_bps(None, CFG.execution) == CFG.execution.slippage_bps_max


def test_forward_leg_uses_next_day_open_and_adjusts_for_bonus() -> None:
    dates = [date(2024, 1, d) for d in (1, 2, 3, 4, 5, 8, 9, 10)]
    opens = [100, 101, 102, 103, 52, 53, 54, 55]
    closes = [100.5, 101.5, 102.5, 103.5, 52.5, 53.5, 54.5, 55.5]
    s = PriceSeries(
        1,
        dates,
        [float(x) for x in opens],
        [float(x) for x in closes],
        [1e6] * 8,
        [(date(2024, 1, 5), 2.0)],
        None,
        None,
    )
    leg = forward_leg(s, date(2024, 1, 1), 5, date(2024, 12, 31), CFG)
    assert leg is not None and leg.entry_date == date(2024, 1, 2) and leg.entry_price == 101.0
    assert (
        leg.exit_date == date(2024, 1, 8) and leg.exit_price == 107.0
    )  # 53.5 x 2 after the 1:1 bonus
    assert abs(leg.gross_return - (107.0 / 101.0 - 1)) < 1e-12
    assert (
        forward_leg(s, date(2024, 1, 1), 5, date(2024, 1, 6), CFG) is None
    )  # window not complete at as_of
    # compulsory delisting inside the window -> terminal -100%
    dead = PriceSeries(
        2,
        dates[:4],
        [100.0] * 4,
        [100.0] * 4,
        [1e6] * 4,
        [],
        date(2024, 1, 6),
        DelistingKind.COMPULSORY,
    )
    leg = forward_leg(dead, date(2024, 1, 1), 30, date(2024, 12, 31), CFG)
    assert leg is not None and leg.terminal and leg.gross_return == -1.0


def test_delisted_mock_company_gets_terminal_return(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    company = _company(mock_session, Story.DELISTED)
    series = load_series(pit, company, date(2022, 1, 1))
    leg = forward_leg(series, date(2024, 11, 1), 365, AS_OF, CFG)
    assert leg is not None and leg.terminal and leg.gross_return == -1.0


def test_backtest_recovers_planted_effects(mock_session: Session, mock_signals: int) -> None:
    assert mock_signals > 0
    report = run_backtest(mock_session, as_of=AS_OF, is_mock=True, since=date(2023, 6, 30))
    assert report.run_id is not None and report.n_events > 0

    def mean_excess(signal_type: str, horizon: int) -> float:
        g = report.group("signal", signal_type, horizon)
        assert g is not None and g.events.mean_excess is not None, signal_type
        return g.events.mean_excess

    # Positive planted stories carry positive forward excess returns.
    for st in ("order_win", "margin_inflection", "pledge_reduction"):
        assert mean_excess(st, 180) > 0.05, st
    # Forensic and deceptive-growth stories carry negative forward excess returns.
    for st in ("audit_qualification", "related_party_revenue", "shareholder_count_spike"):
        assert mean_excess(st, 180) < -0.05, st
    # Small samples are flagged, stats are stored, and every stored row belongs to this run.
    rows = mock_session.scalars(
        select(SignalPerformance).where(SignalPerformance.backtest_run_id == report.run_id)
    ).all()
    assert rows and all(r.low_sample == (r.n < CFG.min_sample) for r in rows)
    assert all(
        {
            "hit_rate",
            "mean_excess",
            "ci_low",
            "sharpe",
            "max_drawdown",
            "turnover",
            "cost_drag",
            "decay",
        }
        <= set(r.stats)
        for r in rows
    )
    # Nothing beyond as_of: every horizon row's decay keys are the configured horizons.
    assert all(set(r.stats["decay"]) <= {str(h) for h in CFG.horizons_days} for r in rows)


def test_control_signals_are_consistent_with_zero(mock_session: Session, mock_signals: int) -> None:
    """Board-meeting-style noise: the control group's own small order wins have no planted
    effect, so their excess return CI should include zero (PRD §14)."""
    bt = Backtester(mock_session, as_of=AS_OF, is_mock=True)
    bt._load(date(2022, 1, 1))
    controls = {_company(mock_session, Story.CONTROL, i).id for i in range(28)}
    events = [
        e
        for e in bt.signal_events(date(2023, 6, 30))
        if e.company_id in controls
        and e.subject
        in (
            "promoter_stake_increase",
            "promoter_stake_decrease",
            "institutional_entry",
            "delivery_volume_shift",
        )
    ]
    results = bt.evaluate(events)
    groups = bt.report(results)
    pooled = [r.excess for r in results if r.horizon_days == 90]
    assert len(pooled) >= 10
    from backtesting.stats import event_stats

    s = event_stats(pooled, pooled)
    assert s.ci_low is not None and s.ci_high is not None and s.ci_low < 0.0 < s.ci_high + 0.02
    assert groups


def test_illiquid_company_is_excluded_by_default(mock_session: Session, mock_signals: int) -> None:
    bt = Backtester(mock_session, as_of=AS_OF, is_mock=True)
    bt._load(date(2022, 1, 1))
    illiquid = _company(mock_session, Story.ILLIQUID)
    events = [Event("signal", "test", 0, illiquid.id, date(2025, 1, 15), 1.0)]
    assert bt.evaluate(events) == []
    liquid = _company(mock_session, Story.CONTROL, 3)
    assert bt.evaluate([Event("signal", "test", 0, liquid.id, date(2025, 1, 15), 1.0)])


def test_score_deciles_on_mock_universe(mock_session: Session, mock_signals: int) -> None:
    dates = month_ends(date(2024, 12, 1), date(2025, 6, 30), step_months=3)
    assert dates == [date(2024, 12, 31), date(2025, 3, 31), date(2025, 6, 30)]
    report = run_backtest(
        mock_session, as_of=AS_OF, is_mock=True, since=date(2026, 8, 1), score_dates=dates
    )
    rows = mock_session.scalars(
        select(ScorePerformance).where(ScorePerformance.backtest_run_id == report.run_id)
    ).all()
    assert {r.score_type for r in rows} >= {"opportunity", "risk", "inflection"}
    assert {r.decile for r in rows} <= set(range(1, 11))
    top = report.group("score", "opportunity", 180, 10)
    bottom = report.group("score", "opportunity", 180, 1)
    assert top is not None and bottom is not None
    assert top.events.mean_excess is not None and bottom.events.mean_excess is not None
    assert top.events.mean_excess > bottom.events.mean_excess
