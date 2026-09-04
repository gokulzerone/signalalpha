"""The reader's own decisions (PRD §16: research attention, never trade instructions)."""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, MockFlagMixin


class Verdict(enum.StrEnum):
    """Deliberately about research, not trading."""

    SHORTLIST = "shortlist"  # worth committing real work to
    TRACK = "track"  # interesting, not yet
    NEEDS_EVIDENCE = "needs_evidence"  # blocked on a specific missing fact
    PASS = "pass"  # not pursuing


class Conviction(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Decision(MockFlagMixin, Base):
    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_company_created", "company_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    as_of: Mapped[date] = mapped_column(nullable=False)
    verdict: Mapped[Verdict] = mapped_column(
        Enum(Verdict, native_enum=False, length=20), nullable=False
    )
    conviction: Mapped[Conviction | None] = mapped_column(
        Enum(Conviction, native_enum=False, length=8)
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    #: A condition the reader wants to be told about, in their own words.
    review_trigger: Mapped[str | None] = mapped_column(Text)
    review_by: Mapped[date | None]
    #: Scores, signal ids and readiness at the moment of deciding, so the record can be audited.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    author: Mapped[str] = mapped_column(String(64), nullable=False, default="me")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
