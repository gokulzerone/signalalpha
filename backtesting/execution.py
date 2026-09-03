"""Execution model (PRD §11): costs and slippage calibrated to traded value, position caps."""

from __future__ import annotations

import math
from dataclasses import dataclass

from backtesting.config import ExecutionConfig
from backtesting.prices import PriceSeries

CRORE = 1e7


@dataclass(frozen=True)
class ExecutionEstimate:
    adv_inr: float | None
    one_way_cost_bps: float
    round_trip_cost: float  # fraction
    position_cap_inr: float | None


def slippage_bps(adv_inr: float | None, cfg: ExecutionConfig) -> float:
    if adv_inr is None or adv_inr <= 0:
        return cfg.slippage_bps_max
    raw = cfg.slippage_k / math.sqrt(adv_inr / CRORE)
    return min(cfg.slippage_bps_max, max(cfg.slippage_bps_min, raw))


def estimate(series: PriceSeries, entry_date: object, cfg: ExecutionConfig) -> ExecutionEstimate:
    from datetime import date, timedelta

    assert isinstance(entry_date, date)
    adv = series.adv(entry_date - timedelta(days=1), cfg.adv_window_days)
    one_way = cfg.base_cost_bps + slippage_bps(adv, cfg)
    cap = None if adv is None else adv * cfg.position_cap_pct_of_adv / 100
    return ExecutionEstimate(adv, one_way, 2 * one_way / 10_000, cap)
