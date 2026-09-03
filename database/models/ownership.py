"""Shareholding patterns, pledges, insider trades and bulk/block deals (PRD §5.1)."""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, ExtractionMethod, ProvenanceMixin, SupersedableMixin


class Shareholding(ProvenanceMixin, SupersedableMixin, Base):
    """Reg. 31 shareholding pattern for one quarter end. Percentages are of total equity."""

    __tablename__ = "shareholdings"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "period_end",
            "filing_id",
            "parser_version",
            name="uq_shareholdings_period",
        ),
        Index("ix_shareholdings_company_period", "company_id", "period_end"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("filings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_end: Mapped[date] = mapped_column(nullable=False)
    promoter_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    promoter_pledged_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    """Percentage of the promoter holding that is pledged / encumbered."""
    fii_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    dii_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    public_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    total_shareholders: Mapped[int] = mapped_column(Integer, nullable=False)
    retail_shareholders: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        Enum(ExtractionMethod, native_enum=False, length=16), nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    institutional_holders: Mapped[list[InstitutionalHolding]] = relationship(
        back_populates="shareholding", cascade="all, delete-orphan"
    )


class HolderCategory(enum.StrEnum):
    FII = "fii"
    DII = "dii"
    MUTUAL_FUND = "mutual_fund"
    INSURANCE = "insurance"
    OTHER = "other"


class InstitutionalHolding(Base):
    """A named holder ≥ 1% disclosed in a shareholding pattern (point-in-time via its parent)."""

    __tablename__ = "institutional_holdings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shareholding_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shareholdings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    holder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[HolderCategory] = mapped_column(
        Enum(HolderCategory, native_enum=False, length=16), nullable=False
    )
    pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)

    shareholding: Mapped[Shareholding] = relationship(back_populates="institutional_holders")


class PledgeEventType(enum.StrEnum):
    CREATION = "creation"
    RELEASE = "release"
    INVOCATION = "invocation"


class PledgeEvent(ProvenanceMixin, Base):
    __tablename__ = "pledge_events"
    __table_args__ = (Index("ix_pledge_events_company_public", "company_id", "public_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[PledgeEventType] = mapped_column(
        Enum(PledgeEventType, native_enum=False, length=16), nullable=False
    )
    holder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pct_of_promoter_holding: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    pct_of_total_shares: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    event_date: Mapped[date] = mapped_column(nullable=False)


class PersonCategory(enum.StrEnum):
    PROMOTER = "promoter"
    PROMOTER_GROUP = "promoter_group"
    DIRECTOR = "director"
    KMP = "kmp"
    OTHER = "other"


class TradeSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class TradeMode(enum.StrEnum):
    MARKET = "market"
    OFF_MARKET = "off_market"
    PREFERENTIAL = "preferential"
    ESOP = "esop"
    GIFT = "gift"


class InsiderTrade(ProvenanceMixin, Base):
    """Reg. 7 PIT disclosure."""

    __tablename__ = "insider_trades"
    __table_args__ = (Index("ix_insider_trades_company_public", "company_id", "public_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    person_name: Mapped[str] = mapped_column(String(200), nullable=False)
    person_category: Mapped[PersonCategory] = mapped_column(
        Enum(PersonCategory, native_enum=False, length=16), nullable=False
    )
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide, native_enum=False, length=8))
    mode: Mapped[TradeMode] = mapped_column(Enum(TradeMode, native_enum=False, length=16))
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value_inr: Mapped[Decimal] = mapped_column(nullable=False)
    trade_date: Mapped[date] = mapped_column(nullable=False)


class DealType(enum.StrEnum):
    BULK = "bulk"
    BLOCK = "block"


class BulkDeal(ProvenanceMixin, Base):
    __tablename__ = "bulk_deals"
    __table_args__ = (Index("ix_bulk_deals_company_public", "company_id", "public_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deal_type: Mapped[DealType] = mapped_column(Enum(DealType, native_enum=False, length=8))
    trade_date: Mapped[date] = mapped_column(nullable=False)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide, native_enum=False, length=8))
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price: Mapped[Decimal] = mapped_column(nullable=False)
    value_inr: Mapped[Decimal] = mapped_column(nullable=False)
