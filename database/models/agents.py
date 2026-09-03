"""Research runs and agent runs (PRD §7.1, §10 research jobs)."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, MockFlagMixin


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchRun(MockFlagMixin, Base):
    """One asynchronous research job: refresh -> signals -> agents -> scores -> thesis."""

    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    as_of: Mapped[date] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # "research" | "agent:<name>"
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False, length=16), nullable=False
    )
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None]


class AgentRun(MockFlagMixin, Base):
    """A stored agent output (PRD §7.1): model, prompt version, input hash, validation."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_company_agent_asof", "company_id", "agent_name", "as_of"),
        Index(
            "ix_agent_runs_cache_key",
            "company_id",
            "agent_name",
            "as_of",
            "prompt_version",
            "input_snapshot_hash",
            "model_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("research_runs.id", ondelete="SET NULL")
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of: Mapped[date] = mapped_column(nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False, length=16), nullable=False
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
