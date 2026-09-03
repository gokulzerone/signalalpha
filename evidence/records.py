"""Evidence record creation with verbatim-span validation (PRD §8.2 rules 1, 3, 5)."""

from __future__ import annotations

import bisect
import re
from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import (
    AGENT_CREATOR_PREFIX,
    PARSER_CREATOR,
    DocumentText,
    Evidence,
    ExtractionMethod,
    RawDocument,
)

#: Default confidence by extraction method (PRD §8.2 rule 5). Never set by an LLM.
DEFAULT_CONFIDENCE: dict[ExtractionMethod, Decimal] = {
    ExtractionMethod.STRUCTURED: Decimal("1.000"),
    ExtractionMethod.TABLE: Decimal("0.950"),
    ExtractionMethod.TEXT: Decimal("0.900"),
    ExtractionMethod.OCR: Decimal("0.600"),
}


class SpanError(ValueError):
    """The requested span is not a verbatim substring of the document."""


def page_number_for(page_offsets: list[int], char_start: int) -> int | None:
    if not page_offsets:
        return None
    return bisect.bisect_right(page_offsets, char_start)


_WS = re.compile(r"\s+")


def locate_span(text: str, quote: str) -> tuple[int, int] | None:
    """Find ``quote`` in ``text`` and return ``(char_start, char_end)`` in the original text.

    Exact matches win. Otherwise the search tolerates differences in whitespace only (an LLM
    often re-flows line breaks when quoting); the returned offsets always delimit the original,
    verbatim text. Returns ``None`` if the quote is not in the document.
    """
    quote = quote.strip()
    if not quote:
        return None
    idx = text.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)
    pattern = r"\s+".join(re.escape(part) for part in _WS.split(quote) if part)
    match = re.search(pattern, text)
    if match is None:
        return None
    return match.start(), match.end()


def _validate_creator(created_by: str) -> None:
    if created_by != PARSER_CREATOR and not created_by.startswith(AGENT_CREATOR_PREFIX):
        raise ValueError(f"created_by must be 'parser' or 'agent:<name>', got {created_by!r}")


def create_evidence(
    session: Session,
    *,
    document_text: DocumentText,
    company_id: int,
    char_start: int,
    char_end: int,
    created_by: str,
    extracted_text: str | None = None,
    filing_id: int | None = None,
    confidence: Decimal | None = None,
) -> Evidence:
    """Create an evidence record for ``[char_start, char_end)`` of ``document_text``.

    * If ``extracted_text`` is given it must equal the document span exactly.
    * Agents may not set ``confidence``; it comes from the document's extraction method.
    """
    _validate_creator(created_by)
    text = document_text.text
    if char_start < 0 or char_end <= char_start or char_end > len(text):
        raise SpanError(f"span [{char_start}, {char_end}) is outside the document")
    span = text[char_start:char_end]
    if extracted_text is not None and extracted_text != span:
        raise SpanError("extracted_text is not the verbatim span of the document")
    if created_by != PARSER_CREATOR and confidence is not None:
        raise ValueError("confidence is set by parsers, never by agents")
    raw: RawDocument = document_text.raw_document
    if raw.company_id is not None and raw.company_id != company_id:
        raise SpanError(f"company {company_id} does not own document {raw.id}")
    record = Evidence(
        raw_document_id=raw.id,
        document_text_id=document_text.id,
        company_id=company_id,
        filing_id=filing_id,
        source=raw.source,
        url=raw.url,
        extracted_text=span,
        char_start=char_start,
        char_end=char_end,
        page_number=page_number_for(list(document_text.page_offsets), char_start),
        extraction_method=document_text.extraction_method,
        confidence=confidence
        if confidence is not None
        else DEFAULT_CONFIDENCE[document_text.extraction_method],
        created_by=created_by,
        public_at=raw.public_at,
        is_mock=raw.is_mock,
    )
    session.add(record)
    session.flush()
    return record


def create_evidence_from_quote(
    session: Session,
    *,
    document_text: DocumentText,
    company_id: int,
    quote: str,
    created_by: str,
    filing_id: int | None = None,
) -> Evidence:
    """Create evidence by *selecting* a quoted passage; the quote must exist in the document."""
    span = locate_span(document_text.text, quote)
    if span is None:
        raise SpanError("quoted text was not found in the document")
    return create_evidence(
        session,
        document_text=document_text,
        company_id=company_id,
        char_start=span[0],
        char_end=span[1],
        created_by=created_by,
        filing_id=filing_id,
    )
