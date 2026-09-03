"""End-of-day prices and index constituents (PRD §5.1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, ProvenanceMixin


class Price(ProvenanceMixin, Base):
    """Unadjusted OHLCV as published in the bhavcopy.

    Corporate-action adjustment is applied at query time from ``corporate_actions`` rows whose
    ``public_at`` is within the as-of window, so that adjusted series are themselves
    point-in-time correct (a split announced after ``as_of`` must not be applied).
    """

    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "trade_date", "parser_version", name="uq_prices_company_date"
        ),
        Index("ix_prices_company_date", "company_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(nullable=False)
    open: Mapped[Decimal] = mapped_column(nullable=False)
    high: Mapped[Decimal] = mapped_column(nullable=False)
    low: Mapped[Decimal] = mapped_column(nullable=False)
    close: Mapped[Decimal] = mapped_column(nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    traded_value: Mapped[Decimal] = mapped_column(nullable=False)
    delivery_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))


class IndexConstituent(ProvenanceMixin, Base):
    """Historical index membership. ``public_at`` is the effective date of the change."""

    __tablename__ = "index_constituents"
    __table_args__ = (
        Index("ix_index_constituents_index_dates", "index_name", "effective_from", "effective_to"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    index_name: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date] = mapped_column(nullable=False)
    effective_to: Mapped[date | None]
