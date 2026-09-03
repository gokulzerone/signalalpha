"""Response schemas. Every response is an :class:`Envelope` carrying ``as_of``, the dataset and
a data-quality summary (PRD §10)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SourceQuality(BaseModel):
    source: str
    last_success_at: datetime | None
    latest_public_at: datetime | None
    fetch_failure_count: int
    parse_failure_count: int


class DataQualitySummary(BaseModel):
    sources: list[SourceQuality]
    total_failures: int
    latest_public_at: datetime | None


class Envelope[T](BaseModel):
    as_of: datetime
    dataset: str
    data_quality: DataQualitySummary | None
    data: T


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_document_id: int
    document_text_id: int
    company_id: int
    filing_id: int | None
    source: str
    url: str | None
    public_at: datetime
    extracted_text: str
    char_start: int
    char_end: int
    page_number: int | None
    extraction_method: str
    confidence: Decimal
    created_by: str
    document_url: str


class HighlightOut(BaseModel):
    evidence_id: int
    char_start: int
    char_end: int
    page_number: int | None
    text: str


class DocumentOut(BaseModel):
    raw_document_id: int
    company_id: int | None
    source: str
    title: str | None
    public_at: datetime
    content_type: str
    parser_version: str
    text: str
    page_offsets: list[int]
    highlight: HighlightOut | None
