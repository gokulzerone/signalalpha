"""Score rows (PRD §9): every score stores its value, components, weights and config version."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, MockFlagMixin


class Score(MockFlagMixin, Base):
    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "as_of",
            "score_type",
            "config_version",
            name="uq_scores_company_asof_type",
        ),
        Index("ix_scores_asof_type", "as_of", "score_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    as_of: Mapped[date] = mapped_column(nullable=False)
    score_type: Mapped[str] = mapped_column(String(24), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    components: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    computed_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
