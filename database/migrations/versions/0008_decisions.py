"""decisions table: the reader's own verdicts and review triggers

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(
                "shortlist",
                "track",
                "needs_evidence",
                "pass",
                name="verdict",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "conviction",
            sa.Enum("low", "medium", "high", name="conviction", native_enum=False, length=8),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("review_trigger", sa.Text(), nullable=True),
        sa.Column("review_by", sa.Date(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("author", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_mock", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_company_id", "decisions", ["company_id"])
    op.create_index("ix_decisions_company_created", "decisions", ["company_id", "created_at"])


def downgrade() -> None:
    op.drop_table("decisions")
