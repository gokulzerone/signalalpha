"""Versioned universe snapshots (PRD §4), computed from point-in-time data."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    Company,
    ListingStatus,
    SurveillanceEventType,
    SurveillanceFramework,
    UniverseSnapshot,
)
from database.pit import PointInTimeSession

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "universe_config.yaml"


class UniverseConfig(BaseModel):
    version: str
    market_cap_min_cr: Decimal
    market_cap_max_cr: Decimal
    liquidity_floor_inr: Decimal
    liquidity_window_days: int = 30


def load_universe_config(path: Path | None = None) -> UniverseConfig:
    with (path or DEFAULT_CONFIG_PATH).open() as fh:
        return UniverseConfig.model_validate(yaml.safe_load(fh))


def _surveillance_stage(
    pit: PointInTimeSession, company_id: int, framework: SurveillanceFramework
) -> int | None:
    events = [e for e in pit.surveillance_events(company_id) if e.framework is framework]
    if not events:
        return None
    latest = max(events, key=lambda e: (e.effective_date, e.public_at))
    if latest.event is SurveillanceEventType.EXIT:
        return None
    return latest.stage


def snapshot_for(
    pit: PointInTimeSession, company: Company, on: date, config: UniverseConfig
) -> UniverseSnapshot:
    """Compute one company's snapshot on ``on`` using only data public at ``pit.as_of``."""
    window_start = on - timedelta(days=config.liquidity_window_days)
    prices = pit.prices(company.id, window_start, on)
    last_close = prices[-1].close if prices else None
    shares = next(
        (f.shares_outstanding for f in pit.financials(company.id) if f.shares_outstanding),
        None,
    )
    market_cap = last_close * shares if last_close is not None and shares is not None else None
    median_tv = Decimal(statistics.median(p.traded_value for p in prices)) if prices else None

    if company.delisted_on is not None and company.delisted_on <= on:
        status = ListingStatus.DELISTED
    else:
        status = ListingStatus.LISTED

    in_cap_band = (
        market_cap is not None
        and config.market_cap_min_cr <= market_cap <= config.market_cap_max_cr
    )
    is_illiquid = median_tv is None or median_tv < config.liquidity_floor_inr
    return UniverseSnapshot(
        company_id=company.id,
        snapshot_date=on,
        market_cap_cr=market_cap,
        median_traded_value_30d=median_tv,
        is_illiquid=is_illiquid,
        listing_status=status,
        delisting_kind=company.delisting_kind if status is ListingStatus.DELISTED else None,
        gsm_stage=_surveillance_stage(pit, company.id, SurveillanceFramework.GSM),
        asm_stage=_surveillance_stage(pit, company.id, SurveillanceFramework.ASM),
        in_cap_band=in_cap_band,
        in_universe=status is ListingStatus.LISTED and in_cap_band,
        config_version=config.version,
        is_mock=company.is_mock,
    )


def build_universe_snapshots(
    session: Session,
    *,
    is_mock: bool,
    snapshot_dates: Sequence[date],
    config: UniverseConfig | None = None,
) -> int:
    """Create snapshots for every company on each date. Existing rows for a date are replaced."""
    config = config or load_universe_config()
    companies = session.scalars(select(Company).where(Company.is_mock == is_mock)).all()
    count = 0
    for on in snapshot_dates:
        pit = PointInTimeSession(session, on, is_mock=is_mock)
        for company in companies:
            if company.listed_on is not None and company.listed_on > on:
                continue
            existing = session.scalars(
                select(UniverseSnapshot).where(
                    UniverseSnapshot.company_id == company.id,
                    UniverseSnapshot.snapshot_date == on,
                )
            ).first()
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(snapshot_for(pit, company, on, config))
            count += 1
        session.flush()
    return count
