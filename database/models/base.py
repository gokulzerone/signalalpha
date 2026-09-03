"""Declarative base, shared mixins and enumerations.

PRD §5.2: every derived table row carries ``raw_document_id``, ``parser_version``,
``public_at`` and ``ingested_at``. PRD §2.4: every row carries ``is_mock``.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, String, false, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        date: Date(),
        Decimal: Numeric(24, 6),
    }


class Source(enum.StrEnum):
    """PRD §5.1 source registry. Sources not listed here are not used in v1."""

    NSE_ANNOUNCEMENTS = "nse_announcements"
    BSE_ANNOUNCEMENTS = "bse_announcements"
    FINANCIAL_RESULTS = "financial_results"
    SHAREHOLDING_PATTERN = "shareholding_pattern"
    PLEDGE_DISCLOSURE = "pledge_disclosure"
    INSIDER_TRADING = "insider_trading"
    BULK_BLOCK_DEALS = "bulk_block_deals"
    ANNUAL_REPORT = "annual_report"
    CREDIT_RATING = "credit_rating"
    EOD_PRICES = "eod_prices"
    CORPORATE_ACTIONS = "corporate_actions"
    SURVEILLANCE_LISTS = "surveillance_lists"
    INDEX_CONSTITUENTS = "index_constituents"


class ExtractionMethod(enum.StrEnum):
    TEXT = "text"
    TABLE = "table"
    OCR = "ocr"
    STRUCTURED = "structured"


class MockFlagMixin:
    is_mock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


class PublicAtMixin(MockFlagMixin):
    """Rows that become public at an instant and are therefore point-in-time filtered."""

    public_at: Mapped[datetime] = mapped_column(nullable=False, index=True)


class CompanyScopedMixin:
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class ProvenanceMixin(CompanyScopedMixin, PublicAtMixin):
    """Columns that every derived row must carry (PRD §5.2)."""

    raw_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class SupersedableMixin:
    """Rows re-derived by a newer parser version are retained and marked superseded."""

    is_superseded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
