"""A top-down investigation: world conditions down to one listed company."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, MockFlagMixin


class InvestigationStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Investigation(MockFlagMixin, Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[InvestigationStatus] = mapped_column(
        Enum(InvestigationStatus, native_enum=False, length=16), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(nullable=False)
    #: One entry per step, each carrying what it did, what it read and how long it took.
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    #: The company it settled on and the case for it, once the run finishes.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None]
