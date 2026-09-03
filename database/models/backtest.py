"""Backtest runs and performance tables (PRD §11)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, MockFlagMixin


class BacktestRun(MockFlagMixin, Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    as_of: Mapped[date] = mapped_column(nullable=False)
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    score_config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None]


class PerformanceStatsMixin:
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    low_sample: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    """hit_rate, mean_return, mean_excess, median_excess, ci_low, ci_high, information_coefficient,
    volatility, sharpe, sortino, max_drawdown, turnover, cost_drag, decay (per-horizon means)."""


class SignalPerformance(PerformanceStatsMixin, MockFlagMixin, Base):
    __tablename__ = "signal_performance"
    __table_args__ = (
        UniqueConstraint(
            "signal_type",
            "decile",
            "horizon_days",
            "backtest_run_id",
            "config_version",
            name="uq_signal_performance_key",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    decile: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """0 = all events of the type; 1..10 = by magnitude decile (reserved)."""
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)


class ScorePerformance(PerformanceStatsMixin, MockFlagMixin, Base):
    __tablename__ = "score_performance"
    __table_args__ = (
        UniqueConstraint(
            "score_type",
            "decile",
            "horizon_days",
            "backtest_run_id",
            "config_version",
            name="uq_score_performance_key",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    decile: Mapped[int] = mapped_column(Integer, nullable=False)
    """1 = lowest scores ... 10 = highest."""
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
