from __future__ import annotations

import random

from backtesting.stats import event_stats, max_drawdown, portfolio_stats, spearman


def test_event_stats_hand_checked() -> None:
    s = event_stats([0.10, -0.05, 0.20, 0.0], [0.08, -0.07, 0.15, -0.01], [0.9, 0.2, 1.0, 0.4])
    assert s.n == 4 and s.hit_rate == 0.5
    assert abs(s.mean_return - 0.0625) < 1e-12  # type: ignore[operator]
    assert abs(s.mean_excess - 0.0375) < 1e-12  # type: ignore[operator]
    assert abs(s.median_excess - 0.035) < 1e-12  # type: ignore[operator]
    assert s.ci_low is not None and s.ci_high is not None and s.ci_low < s.mean_excess < s.ci_high  # type: ignore[operator]
    assert s.information_coefficient is not None and s.information_coefficient > 0.9
    assert event_stats([], []).n == 0


def test_spearman() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert spearman([1, 1, 1], [1, 2, 3]) is None
    assert spearman([1, 2], [1, 2]) is None


def test_max_drawdown() -> None:
    assert max_drawdown([0.1, -0.5, 0.2]) == -0.5
    assert max_drawdown([0.01, 0.01]) == 0.0


def test_portfolio_stats() -> None:
    p = portfolio_stats([0.01] * 252, [0.0] * 252, [0.1] * 252)
    assert p.trading_days == 252 and p.volatility == 0.0 and p.sharpe is None
    assert p.annual_return is not None and abs(p.annual_return - (1.01**252 - 1)) < 1e-9
    assert p.turnover == 0.1 * 252 and p.cost_drag == 0.0
    q = portfolio_stats([0.02, -0.01, 0.005], [0.001, 0.0, 0.001], [0.0] * 3)
    assert (
        q.sharpe is not None
        and q.sortino is not None
        and q.max_drawdown is not None
        and q.max_drawdown <= 0
    )


def test_zero_effect_universe_is_consistent_with_zero() -> None:
    """PRD §14: a universe with no effect produces statistics consistent with zero."""
    rng = random.Random(1)
    excess = [rng.gauss(0, 0.05) for _ in range(400)]
    s = event_stats(excess, excess)
    assert s.ci_low is not None and s.ci_high is not None and s.ci_low < 0 < s.ci_high
    assert abs(s.hit_rate - 0.5) < 0.1  # type: ignore[operator]


def test_planted_effect_is_recovered() -> None:
    rng = random.Random(2)
    excess = [0.08 + rng.gauss(0, 0.05) for _ in range(200)]
    s = event_stats(excess, excess)
    assert s.ci_low is not None and s.ci_low > 0.05 and s.hit_rate > 0.8  # type: ignore[operator]
