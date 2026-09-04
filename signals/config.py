"""Signal catalogue loader. Thresholds live in ``signals/catalogue.yaml`` (PRD §6.2)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CATALOGUE_PATH = Path(__file__).with_name("catalogue.yaml")


class SignalSpec(BaseModel):
    family: str
    direction: int = Field(ge=-1, le=1)
    description: str
    params: dict[str, float] = Field(default_factory=dict)


class SignalCatalogue(BaseModel):
    version: str
    market_signal_cadence_days: int = 7
    min_ttm_revenue_cr: float = 5.0
    institution_keywords: list[str] = Field(default_factory=list)
    signals: dict[str, SignalSpec]

    def spec(self, signal_type: str) -> SignalSpec:
        return self.signals[signal_type]

    def param(self, signal_type: str, name: str) -> float:
        return self.signals[signal_type].params[name]


@lru_cache(maxsize=4)
def load_catalogue(path: Path | None = None) -> SignalCatalogue:
    with (path or CATALOGUE_PATH).open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return SignalCatalogue.model_validate(raw)
