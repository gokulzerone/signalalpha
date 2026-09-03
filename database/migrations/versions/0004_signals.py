"""signals table (PRD §15 step 4)

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("signal_type", sa.String(length=48), nullable=False),
        sa.Column("family", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.SmallInteger(), nullable=False),
        sa.Column("magnitude", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("source_records", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("detector_version", sa.String(length=32), nullable=False),
        sa.Column("validator_version", sa.String(length=32), nullable=False),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        sa.Column("public_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_mock", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("direction IN (-1, 0, 1)", name="ck_signals_direction"),
        sa.CheckConstraint("magnitude >= 0 AND magnitude <= 1", name="ck_signals_magnitude"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "signal_type",
            "public_at",
            "dedupe_key",
            "detector_version",
            name="uq_signals_event",
        ),
    )
    op.create_index("ix_signals_company_id", "signals", ["company_id"])
    op.create_index("ix_signals_company_public", "signals", ["company_id", "public_at"])
    op.create_index("ix_signals_public_at", "signals", ["public_at"])
    op.create_index("ix_signals_type_public", "signals", ["signal_type", "public_at"])


def downgrade() -> None:
    op.drop_table("signals")
