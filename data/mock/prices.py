"""Daily price synthesis with planted forward-return effects (PRD §5.3, §17)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt

from data.mock.synth import PriceEffect, q2

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    traded_value: Decimal
    delivery_pct: Decimal


def trading_days(start: date, end: date) -> list[date]:
    """Weekdays only. The mock calendar has no exchange holidays."""
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def synth_market_returns(rng: np.random.Generator, n: int) -> FloatArray:
    return rng.normal(0.00025, 0.008, n)


def synth_bars(
    rng: np.random.Generator,
    days: list[date],
    *,
    price0: float,
    shares_cr_by_day: FloatArray,
    beta: float,
    vol: float,
    turnover: float,
    market: FloatArray,
    effects: list[PriceEffect],
    stop_on: date | None = None,
    bonus: tuple[date, int] | None = None,
) -> list[DailyBar]:
    n = len(days)
    drift = np.zeros(n)
    for eff in effects:
        idx = [i for i, d in enumerate(days) if d >= eff.start][: eff.trading_days]
        drift[idx] += eff.daily_drift
    log_ret = beta * market + rng.normal(0.0, vol, n) + drift
    closes = price0 * np.exp(np.cumsum(log_ret))
    if bonus is not None:
        ex_date, ratio = bonus
        mask = np.array([d >= ex_date for d in days])
        closes = np.where(mask, closes / (1 + ratio), closes)
    delivery = 40.0
    bars: list[DailyBar] = []
    prev_close = price0
    for i, d in enumerate(days):
        if stop_on is not None and d > stop_on:
            break
        close = float(closes[i])
        gap = rng.normal(0, 0.004)
        open_ = prev_close * (1 + gap) if not (bonus and d == bonus[0]) else close * (1 + gap)
        hi = max(open_, close) * (1 + abs(rng.normal(0, 0.008)))
        lo = min(open_, close) * (1 - abs(rng.normal(0, 0.008)))
        mcap_inr = close * float(shares_cr_by_day[i]) * 1e7
        value = mcap_inr * turnover * float(np.exp(rng.normal(0, 0.45)))
        volume = max(int(value / close), 1)
        delivery = float(np.clip(0.85 * delivery + 0.15 * 42 + rng.normal(0, 4), 12, 90))
        bars.append(
            DailyBar(
                trade_date=d,
                open=q2(open_),
                high=q2(hi),
                low=q2(lo),
                close=q2(close),
                volume=volume,
                traded_value=q2(volume * close),
                delivery_pct=q2(delivery),
            )
        )
        prev_close = close
    return bars
