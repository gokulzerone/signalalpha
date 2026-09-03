"""Companies and the date-versioned universe (PRD §4)."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, MockFlagMixin


class Exchange(enum.StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    BOTH = "NSE+BSE"


class ListingStatus(enum.StrEnum):
    LISTED = "listed"
    SUSPENDED = "suspended"
    DELISTED = "delisted"
    MERGED = "merged"


class DelistingKind(enum.StrEnum):
    COMPULSORY = "compulsory"
    VOLUNTARY = "voluntary"


class Company(MockFlagMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        # Mock companies must be unmistakable (PRD §5.3); live companies must never look mock.
        CheckConstraint(
            "(is_mock AND ticker LIKE 'MOCK-%') OR (NOT is_mock AND ticker NOT LIKE 'MOCK-%')",
            name="ck_companies_mock_ticker",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)
    exchange: Mapped[Exchange] = mapped_column(Enum(Exchange, native_enum=False, length=16))
    bse_code: Mapped[str | None] = mapped_column(String(16))
    sector: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    industry: Mapped[str | None] = mapped_column(String(64))
    listed_on: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    universe_snapshots: Mapped[list[UniverseSnapshot]] = relationship(back_populates="company")


class UniverseSnapshot(MockFlagMixin, Base):
    """One row per company per snapshot date.

    The universe on date D is, for every company, its latest snapshot with
    ``snapshot_date <= D``. Delisted / suspended / merged companies keep their rows, so the
    historical universe has no survivorship bias (PRD §4, §11).
    """

    __tablename__ = "universe_snapshots"
    __table_args__ = (
        UniqueConstraint("company_id", "snapshot_date", name="uq_universe_company_date"),
        Index("ix_universe_snapshot_date", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(nullable=False)
    market_cap_cr: Mapped[Decimal | None]
    median_traded_value_30d: Mapped[Decimal | None]
    is_illiquid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    listing_status: Mapped[ListingStatus] = mapped_column(
        Enum(ListingStatus, native_enum=False, length=16), nullable=False
    )
    delisting_kind: Mapped[DelistingKind | None] = mapped_column(
        Enum(DelistingKind, native_enum=False, length=16)
    )
    gsm_stage: Mapped[int | None] = mapped_column(Integer)
    asm_stage: Mapped[int | None] = mapped_column(Integer)
    in_cap_band: Mapped[bool] = mapped_column(Boolean, nullable=False)
    in_universe: Mapped[bool] = mapped_column(Boolean, nullable=False)
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="universe_snapshots")
