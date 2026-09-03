"""Per-company, per-source data quality (PRD §5.2 "failure modes are visible")."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, MockFlagMixin, Source


class DataQuality(MockFlagMixin, Base):
    __tablename__ = "data_quality"
    __table_args__ = (
        UniqueConstraint("company_id", "source", "is_mock", name="uq_data_quality_company_source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[Source] = mapped_column(Enum(Source, native_enum=False, length=32))
    last_fetch_at: Mapped[datetime | None]
    last_success_at: Mapped[datetime | None]
    latest_public_at: Mapped[datetime | None]
    fetch_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
