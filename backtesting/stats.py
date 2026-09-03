"""Pure statistics for backtest reports (PRD §11). No database access."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class EventStats:
    n: int
    hit_rate: float | None
    mean_return: float | None
    mean_excess: float | None
    median_excess: float | None
    ci_low: float | None
    ci_high: float | None
    information_coefficient: float | None

    def to_json(self) -> dict[str, Any]:
        return self.__dict__.copy()


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 3 or len(x) != len(y):
        return None
    rx = _ranks(x)
    ry = _ranks(y)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _ranks(v: Sequence[float]) -> np.ndarray[Any, np.dtype[np.float64]]:
    arr = np.asarray(v, dtype=float)
    order = arr.argsort()
    ranks = np.empty(len(arr), dtype=float)
    ranks[order] = np.arange(len(arr), dtype=float)
    # average ties
    unique, inverse, counts = np.unique(arr, return_inverse=True, return_counts=True)
    sums = np.zeros(len(unique))
    np.add.at(sums, inverse, ranks)
    return sums[inverse] / counts[inverse]


def event_stats(
    returns: Sequence[float], excess: Sequence[float], magnitudes: Sequence[float] | None = None
) -> EventStats:
    n = len(excess)
    if n == 0:
        return EventStats(0, None, None, None, None, None, None, None)
    mean_ex = statistics.fmean(excess)
    ci_low = ci_high = None
    if n >= 2:
        se = statistics.stdev(excess) / math.sqrt(n)
        ci_low, ci_high = mean_ex - 1.96 * se, mean_ex + 1.96 * se
    ic = spearman(magnitudes, excess) if magnitudes is not None else None
    return EventStats(
        n=n,
        hit_rate=sum(1 for e in excess if e > 0) / n,
        mean_return=statistics.fmean(returns),
        mean_excess=mean_ex,
        median_excess=statistics.median(excess),
        ci_low=ci_low,
        ci_high=ci_high,
        information_coefficient=ic,
    )


@dataclass
class PortfolioStats:
    trading_days: int
    annual_return: float | None
    volatility: float | None
    sharpe: float | None
    sortino: float | None
    max_drawdown: float | None
    turnover: float | None
    cost_drag: float | None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d.pop("extra")
        return {**d, **self.extra}


def max_drawdown(daily_returns: Sequence[float]) -> float:
    peak = 1.0
    value = 1.0
    worst = 0.0
    for r in daily_returns:
        value *= 1 + r
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def portfolio_stats(
    daily_returns: Sequence[float],
    daily_costs: Sequence[float],
    daily_turnover: Sequence[float],
    periods_per_year: int = 252,
) -> PortfolioStats:
    n = len(daily_returns)
    if n == 0:
        return PortfolioStats(0, None, None, None, None, None, None, None)
    net = [r - c for r, c in zip(daily_returns, daily_costs, strict=True)]
    mean = statistics.fmean(net)
    years = n / periods_per_year
    growth = 1.0
    for r in net:
        growth *= 1 + r
    annual = growth ** (1 / years) - 1 if years > 0 and growth > 0 else None
    vol = statistics.pstdev(net) * math.sqrt(periods_per_year) if n > 1 else None
    downside = [min(r, 0.0) for r in net]
    dd = (
        math.sqrt(statistics.fmean(d * d for d in downside)) * math.sqrt(periods_per_year)
        if n > 1
        else None
    )
    sharpe = mean * periods_per_year / vol if vol else None
    sortino = mean * periods_per_year / dd if dd else None
    return PortfolioStats(
        trading_days=n,
        annual_return=annual,
        volatility=vol,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown(net),
        turnover=sum(daily_turnover) / years if years > 0 else None,
        cost_drag=sum(daily_costs) / years if years > 0 else None,
    )
