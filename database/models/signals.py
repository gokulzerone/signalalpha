"""Signals (PRD §6.1): deterministic, timestamped, typed events derived from structured data."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, PublicAtMixin


class Signal(PublicAtMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "signal_type",
            "public_at",
            "dedupe_key",
            "detector_version",
            name="uq_signals_event",
        ),
        CheckConstraint("direction IN (-1, 0, 1)", name="ck_signals_direction"),
        CheckConstraint("magnitude >= 0 AND magnitude <= 1", name="ck_signals_magnitude"),
        Index("ix_signals_company_public", "company_id", "public_at"),
        Index("ix_signals_type_public", "signal_type", "public_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    signal_type: Mapped[str] = mapped_column(String(48), nullable=False)
    family: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    magnitude: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_records: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    evidence_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
