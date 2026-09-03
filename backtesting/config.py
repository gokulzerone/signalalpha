from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).with_name("config.yaml")


class ExecutionConfig(BaseModel):
    entry: str = "next_day_open"
    base_cost_bps: float
    slippage_bps_min: float
    slippage_bps_max: float
    slippage_k: float
    adv_window_days: int
    position_cap_pct_of_adv: float
    portfolio_capital_cr: float


class TerminalReturns(BaseModel):
    compulsory: float
    voluntary: str | float


class BacktestConfig(BaseModel):
    version: str
    horizons_days: list[int]
    benchmarks: dict[str, list[str]]
    min_sample: int
    include_illiquid: bool
    score_deciles: int
    score_rebalance_months: int
    execution: ExecutionConfig
    terminal_returns: TerminalReturns


@lru_cache(maxsize=4)
def load_backtest_config(path: Path | None = None) -> BacktestConfig:
    with (path or CONFIG_PATH).open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return BacktestConfig.model_validate(raw)
