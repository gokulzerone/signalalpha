"""Liquidity arithmetic (PRD §11 execution model, reused for the reader's own sizing).

This is arithmetic, not advice: it answers "at this participation rate, how long would a
position of this size take to build or exit, and what does the spread cost", and leaves the
position size to the reader.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backtesting.config import ExecutionConfig, load_backtest_config
from backtesting.execution import slippage_bps

CRORE = 1e7


@dataclass(frozen=True)
class LiquidityProfile:
    adv_inr: float | None
    """Average daily traded value over the recent window."""
    participation_pct: float
    """Share of a day's traded value the reader is assumed to take."""
    comfortable_position_inr: float | None
    """One day's worth of participation: the size that needs no patience."""
    days_to_exit: dict[str, float]
    """Position size in rupees (as a label) -> trading days to exit at this participation."""
    round_trip_cost_pct: float | None
    illiquid: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "adv_inr": self.adv_inr,
            "participation_pct": self.participation_pct,
            "comfortable_position_inr": self.comfortable_position_inr,
            "days_to_exit": self.days_to_exit,
            "round_trip_cost_pct": self.round_trip_cost_pct,
            "illiquid": self.illiquid,
        }


DEFAULT_SIZES_INR = (100_000.0, 500_000.0, 1_000_000.0, 5_000_000.0)


def liquidity_profile(
    traded_values: Sequence[float],
    *,
    participation_pct: float | None = None,
    sizes_inr: Sequence[float] = DEFAULT_SIZES_INR,
    execution: ExecutionConfig | None = None,
    illiquid: bool = False,
) -> LiquidityProfile:
    execution = execution or load_backtest_config().execution
    participation = (
        participation_pct if participation_pct is not None else execution.position_cap_pct_of_adv
    )
    window = list(traded_values)[-execution.adv_window_days :]
    adv = statistics.fmean(window) if window else None
    per_day = adv * participation / 100 if adv else None
    cost = None
    if adv:
        cost = 2 * (execution.base_cost_bps + slippage_bps(adv, execution)) / 10_000
    days = {}
    for size in sizes_inr:
        label = f"{size / 100000:.0f}L" if size < CRORE else f"{size / CRORE:.1f}Cr"
        days[label] = max(0.1, round(size / per_day, 1)) if per_day else float("inf")
    return LiquidityProfile(
        adv_inr=adv,
        participation_pct=participation,
        comfortable_position_inr=per_day,
        days_to_exit=days,
        round_trip_cost_pct=cost,
        illiquid=illiquid,
    )
