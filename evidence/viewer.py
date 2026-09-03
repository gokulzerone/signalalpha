"""Point-in-time document viewer (PRD §8.2 rule 4, §10 documents endpoint)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from database.models import Evidence, Source
from database.pit import PointInTimeSession
from evidence.records import page_number_for


class DocumentNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Highlight:
    evidence_id: int
    char_start: int
    char_end: int
    page_number: int | None
    text: str


@dataclass(frozen=True)
class DocumentView:
    raw_document_id: int
    company_id: int | None
    source: Source
    title: str | None
    public_at: datetime
    content_type: str
    storage_key: str
    parser_version: str
    text: str
    page_offsets: list[int]
    highlight: Highlight | None


def document_view(
    pit: PointInTimeSession,
    raw_document_id: int,
    *,
    company_id: int | None = None,
    highlight_evidence_id: int | None = None,
    parser_version: str | None = None,
) -> DocumentView:
    """The document as it can be shown at ``pit.as_of``, optionally with one highlighted span."""
    raw = pit.raw_document(raw_document_id)
    if raw is None or (company_id is not None and raw.company_id not in (None, company_id)):
        raise DocumentNotFoundError(f"document {raw_document_id} is not available")
    text = pit.document_text(raw_document_id, parser_version)
    if text is None:
        raise DocumentNotFoundError(f"document {raw_document_id} has no extracted text")
    highlight: Highlight | None = None
    if highlight_evidence_id is not None:
        ev: Evidence | None = pit.evidence_record(highlight_evidence_id)
        if ev is None or ev.raw_document_id != raw.id:
            raise DocumentNotFoundError(
                f"evidence {highlight_evidence_id} does not belong to document {raw_document_id}"
            )
        if ev.document_text_id == text.id:
            start, end = ev.char_start, ev.char_end
        else:
            # A different parser version: re-locate the verbatim text in this version.
            idx = text.text.find(ev.extracted_text)
            if idx < 0:
                raise DocumentNotFoundError("evidence span not present in this text version")
            start, end = idx, idx + len(ev.extracted_text)
        highlight = Highlight(
            evidence_id=ev.id,
            char_start=start,
            char_end=end,
            page_number=page_number_for(list(text.page_offsets), start),
            text=ev.extracted_text,
        )
    return DocumentView(
        raw_document_id=raw.id,
        company_id=raw.company_id,
        source=raw.source,
        title=raw.title,
        public_at=raw.public_at,
        content_type=raw.content_type,
        storage_key=raw.storage_key,
        parser_version=text.parser_version,
        text=text.text,
        page_offsets=list(text.page_offsets),
        highlight=highlight,
    )
