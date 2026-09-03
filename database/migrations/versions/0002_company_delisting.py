"""companies: delisted_on and delisting_kind (PRD §4 survivorship)

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("delisted_on", sa.Date(), nullable=True))
    op.add_column(
        "companies",
        sa.Column(
            "delisting_kind",
            sa.Enum("compulsory", "voluntary", name="delistingkind", native_enum=False, length=16),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("companies", "delisting_kind")
    op.drop_column("companies", "delisted_on")
