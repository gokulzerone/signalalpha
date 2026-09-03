"""backtest runs and performance tables (PRD §15 step 6)

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stats_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("low_sample", sa.Boolean(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("is_mock", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        sa.Column("signal_config_version", sa.String(length=32), nullable=False),
        sa.Column("score_config_version", sa.String(length=32), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_mock", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "signal_performance",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("backtest_run_id", sa.BigInteger(), nullable=False),
        sa.Column("signal_type", sa.String(length=48), nullable=False),
        sa.Column("decile", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        *_stats_columns(),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "signal_type",
            "decile",
            "horizon_days",
            "backtest_run_id",
            "config_version",
            name="uq_signal_performance_key",
        ),
    )
    op.create_index(
        "ix_signal_performance_backtest_run_id", "signal_performance", ["backtest_run_id"]
    )
    op.create_index("ix_signal_performance_signal_type", "signal_performance", ["signal_type"])
    op.create_table(
        "score_performance",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("backtest_run_id", sa.BigInteger(), nullable=False),
        sa.Column("score_type", sa.String(length=24), nullable=False),
        sa.Column("decile", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        *_stats_columns(),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "score_type",
            "decile",
            "horizon_days",
            "backtest_run_id",
            "config_version",
            name="uq_score_performance_key",
        ),
    )
    op.create_index(
        "ix_score_performance_backtest_run_id", "score_performance", ["backtest_run_id"]
    )
    op.create_index("ix_score_performance_score_type", "score_performance", ["score_type"])


def downgrade() -> None:
    op.drop_table("score_performance")
    op.drop_table("signal_performance")
    op.drop_table("backtest_runs")
