from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

SOURCES_PATH = Path(__file__).resolve().parents[1] / "sources.yaml"
LIVE_UNIVERSE_PATH = Path(__file__).resolve().parents[1] / "live_universe.yaml"


class IngestionFlags(BaseSettings):
    """Feature flags (PRD §15 step 10): every live source is off unless explicitly enabled."""

    model_config = SettingsConfigDict(env_prefix="SIGNALALPHA_", extra="ignore")

    live_eod_prices: bool = False
    live_nse_announcements: bool = False
    contact: str = "unset"


class EodPricesSource(BaseModel):
    url_template: str
    publication_time_ist: str
    series: list[str]
    parser_version: str


class AnnouncementsSource(BaseModel):
    url_template: str
    warmup_url: str
    parser_version: str
    attachment_parser_version: str


class SourceRegistry(BaseModel):
    user_agent: str
    rate_limit_per_minute: int
    request_timeout_seconds: int
    respect_robots: bool
    eod_prices: EodPricesSource
    nse_announcements: AnnouncementsSource


class LiveCompany(BaseModel):
    ticker: str
    name: str
    isin: str | None = None
    sector: str = "Unclassified"
    industry: str | None = None


def load_sources(path: Path | None = None) -> SourceRegistry:
    with (path or SOURCES_PATH).open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return SourceRegistry.model_validate(raw)


def load_live_universe(path: Path | None = None) -> list[LiveCompany]:
    with (path or LIVE_UNIVERSE_PATH).open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return [LiveCompany.model_validate(c) for c in raw.get("companies", []) or []]
