"""Structured financial statements (PRD §5.1, §5.2 restatements).

One wide row per (company, period, consolidated flag, filing). A restating filing creates a
new row; nothing is overwritten. Figures are in ₹ crore. All arithmetic on these rows happens
in Python (PRD §2.3).
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, ExtractionMethod, ProvenanceMixin, SupersedableMixin


class AuditOpinion(enum.StrEnum):
    UNQUALIFIED = "unqualified"
    EMPHASIS_OF_MATTER = "emphasis_of_matter"
    QUALIFIED = "qualified"
    GOING_CONCERN = "going_concern"
    ADVERSE = "adverse"
    DISCLAIMER = "disclaimer"


class Financial(ProvenanceMixin, SupersedableMixin, Base):
    __tablename__ = "financials"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "period_end",
            "period_months",
            "consolidated",
            "filing_id",
            "parser_version",
            name="uq_financials_period_filing",
        ),
        Index("ix_financials_company_period", "company_id", "period_end", "consolidated"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("filings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_end: Mapped[date] = mapped_column(nullable=False)
    period_months: Mapped[int] = mapped_column(Integer, nullable=False)  # 3 or 12
    consolidated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        Enum(ExtractionMethod, native_enum=False, length=16), nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    # Profit and loss
    revenue: Mapped[Decimal | None]
    other_income: Mapped[Decimal | None]
    total_expenses: Mapped[Decimal | None]
    ebitda: Mapped[Decimal | None]
    depreciation: Mapped[Decimal | None]
    finance_cost: Mapped[Decimal | None]
    pbt: Mapped[Decimal | None]
    tax: Mapped[Decimal | None]
    pat: Mapped[Decimal | None]
    eps: Mapped[Decimal | None]

    # Balance sheet (half-yearly / annual)
    total_borrowings: Mapped[Decimal | None]
    short_term_borrowings: Mapped[Decimal | None]
    long_term_borrowings: Mapped[Decimal | None]
    cash_and_equivalents: Mapped[Decimal | None]
    receivables: Mapped[Decimal | None]
    inventory: Mapped[Decimal | None]
    payables: Mapped[Decimal | None]
    net_worth: Mapped[Decimal | None]
    total_assets: Mapped[Decimal | None]
    shares_outstanding: Mapped[Decimal | None]  # in crore

    # Cash flow (half-yearly / annual)
    cfo: Mapped[Decimal | None]
    cfi: Mapped[Decimal | None]
    cff: Mapped[Decimal | None]
    capex: Mapped[Decimal | None]

    # Notes (annual report)
    related_party_revenue: Mapped[Decimal | None]
    contingent_liabilities: Mapped[Decimal | None]
    audit_opinion: Mapped[AuditOpinion | None] = mapped_column(
        Enum(AuditOpinion, native_enum=False, length=24)
    )
