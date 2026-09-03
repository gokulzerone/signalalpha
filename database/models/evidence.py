"""Evidence records (PRD §8.1).

An evidence record is a verbatim span of a stored document. The span is verified on write both
in Python (:mod:`evidence.records`) and by a database trigger
(``database/sql/evidence_triggers_v1.sql``), so no code path can store text that is not in the
document. Records are immutable at the database level (updates are rejected); corrections
create new records.

PRD field mapping: ``publication_date`` is ``public_at`` (the document's publication instant).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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

from database.models.base import Base, ExtractionMethod, PublicAtMixin, Source

PARSER_CREATOR = "parser"
AGENT_CREATOR_PREFIX = "agent:"


class Evidence(PublicAtMixin, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint("char_start >= 0 AND char_end > char_start", name="ck_evidence_span"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_evidence_confidence"),
        CheckConstraint(
            "created_by = 'parser' OR created_by LIKE 'agent:%'", name="ck_evidence_created_by"
        ),
        Index("ix_evidence_company_public", "company_id", "public_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_text_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document_texts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    filing_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("filings.id", ondelete="RESTRICT")
    )
    source: Mapped[Source] = mapped_column(Enum(Source, native_enum=False, length=32))
    url: Mapped[str | None] = mapped_column(String(1024))
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        Enum(ExtractionMethod, native_enum=False, length=16), nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
