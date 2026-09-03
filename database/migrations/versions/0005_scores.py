"""scores table (PRD §15 step 5)

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scores",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("score_type", sa.String(length=24), nullable=False),
        sa.Column("value", sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        sa.Column("signal_ids", sa.JSON(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_mock", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "as_of",
            "score_type",
            "config_version",
            name="uq_scores_company_asof_type",
        ),
    )
    op.create_index("ix_scores_company_id", "scores", ["company_id"])
    op.create_index("ix_scores_asof_type", "scores", ["as_of", "score_type"])


def downgrade() -> None:
    op.drop_table("scores")
