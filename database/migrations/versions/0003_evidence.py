"""evidence records with span and immutability triggers (PRD §15 step 3)

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("raw_document_id", sa.BigInteger(), nullable=False),
        sa.Column("document_text_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "nse_announcements",
                "bse_announcements",
                "financial_results",
                "shareholding_pattern",
                "pledge_disclosure",
                "insider_trading",
                "bulk_block_deals",
                "annual_report",
                "credit_rating",
                "eod_prices",
                "corporate_actions",
                "surveillance_lists",
                "index_constituents",
                name="source",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column(
            "extraction_method",
            sa.Enum(
                "text",
                "table",
                "ocr",
                "structured",
                name="extractionmethod",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("public_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_mock", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("char_start >= 0 AND char_end > char_start", name="ck_evidence_span"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_evidence_confidence"),
        sa.CheckConstraint(
            "created_by = 'parser' OR created_by LIKE 'agent:%'", name="ck_evidence_created_by"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_text_id"], ["document_texts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_document_id"], ["raw_documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_company_id", "evidence", ["company_id"])
    op.create_index("ix_evidence_company_public", "evidence", ["company_id", "public_at"])
    op.create_index("ix_evidence_document_text_id", "evidence", ["document_text_id"])
    op.create_index("ix_evidence_public_at", "evidence", ["public_at"])
    op.create_index("ix_evidence_raw_document_id", "evidence", ["raw_document_id"])
    op.execute((SQL_DIR / "evidence_triggers_v1.sql").read_text())


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_evidence_immutable ON evidence")
    op.execute("DROP TRIGGER IF EXISTS trg_evidence_check_span ON evidence")
    op.execute("DROP FUNCTION IF EXISTS sa_evidence_immutable")
    op.execute("DROP FUNCTION IF EXISTS sa_evidence_check_span")
    op.drop_table("evidence")
