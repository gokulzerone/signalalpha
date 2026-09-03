"""Raw documents, their extracted text, and filings (PRD §5.2)."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import (
    Base,
    ExtractionMethod,
    ProvenanceMixin,
    PublicAtMixin,
    Source,
)


class RawDocument(PublicAtMixin, Base):
    """A verbatim fetched document. ``sha256`` is its identity; re-fetches deduplicate."""

    __tablename__ = "raw_documents"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_raw_documents_sha256"),
        Index("ix_raw_documents_company_public", "company_id", "public_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[Source] = mapped_column(Enum(Source, native_enum=False, length=32))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1024))
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now())

    texts: Mapped[list[DocumentText]] = relationship(back_populates="raw_document")


class DocumentText(Base):
    """Extracted text of a raw document for one parser version.

    Evidence spans (PRD §8) are validated as verbatim substrings of ``text``.
    ``page_offsets`` holds the character offset at which each page starts, so a span's page
    number can be derived deterministically.
    """

    __tablename__ = "document_texts"
    __table_args__ = (
        UniqueConstraint("raw_document_id", "parser_version", name="uq_document_texts_doc_parser"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        Enum(ExtractionMethod, native_enum=False, length=16), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_offsets: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    raw_document: Mapped[RawDocument] = relationship(back_populates="texts")


class FilingType(enum.StrEnum):
    QUARTERLY_RESULTS = "quarterly_results"
    ANNUAL_RESULTS = "annual_results"
    SHAREHOLDING_PATTERN = "shareholding_pattern"
    ANNUAL_REPORT = "annual_report"
    PLEDGE_DISCLOSURE = "pledge_disclosure"
    INSIDER_DISCLOSURE = "insider_disclosure"
    ANNOUNCEMENT = "announcement"


class Filing(ProvenanceMixin, Base):
    """A structured filing parsed from a raw document. Financials/shareholdings link here."""

    __tablename__ = "filings"
    __table_args__ = (Index("ix_filings_company_public", "company_id", "public_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filing_type: Mapped[FilingType] = mapped_column(
        Enum(FilingType, native_enum=False, length=32), nullable=False
    )
    period_end: Mapped[date | None]
