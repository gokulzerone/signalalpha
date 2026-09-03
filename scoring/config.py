from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CONFIG_PATH = Path(__file__).with_name("config.yaml")


class Windows(BaseModel):
    inflection_days: int
    inflection_half_life_days: float
    forensic_flag_days: int
    negative_ownership_days: int
    key_person_exit_days: int
    price_lag_days: int
    volatility_trading_days: int
    turnover_trading_days: int
    reaction_window_trading_days: int
    reaction_min_move: float
    max_days_since_reaction: int
    own_history_years: int


class InflectionConfig(BaseModel):
    consistency_bonus: float
    families: list[str]


class QualityConfig(BaseModel):
    weights: dict[str, float]
    forensic_penalties: dict[str, float]


class WeightedConfig(BaseModel):
    weights: dict[str, float]


class RiskPenalty(BaseModel):
    start: float
    full: float
    max_penalty: float = Field(ge=0, le=1)


class OpportunityConfig(BaseModel):
    weights: dict[str, float]
    risk_penalty: RiskPenalty


class ScoreConfig(BaseModel):
    version: str
    windows: Windows
    inflection: InflectionConfig
    quality: QualityConfig
    valuation: WeightedConfig
    risk: WeightedConfig
    attention_gap: WeightedConfig
    opportunity: OpportunityConfig


@lru_cache(maxsize=4)
def load_score_config(path: Path | None = None) -> ScoreConfig:
    with (path or CONFIG_PATH).open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return ScoreConfig.model_validate(raw)
