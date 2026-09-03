from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from database.models import Evidence, ExtractionMethod
from evidence import SpanError, create_evidence, create_evidence_from_quote, locate_span
from evidence.records import page_number_for
from tests.factories import ist, make_company, make_raw_document

DOC = (
    "Page one.\nThe Company has received an order worth Rs. 120.50 crore from a customer."
    "\fPage two.\nMore text."
)


def _doc(session: Session):  # type: ignore[no-untyped-def]
    company = make_company(session)
    raw = make_raw_document(session, company, ist(2024, 7, 1), text=DOC)
    return company, raw, raw.texts[0]


def test_create_evidence_selects_verbatim_span(session: Session) -> None:
    company, raw, text = _doc(session)
    start = DOC.index("Rs. 120.50 crore")
    ev = create_evidence(
        session,
        document_text=text,
        company_id=company.id,
        char_start=start,
        char_end=start + len("Rs. 120.50 crore"),
        created_by="agent:business",
    )
    assert ev.extracted_text == "Rs. 120.50 crore"
    assert ev.public_at == raw.public_at
    assert ev.confidence == Decimal("0.900")  # text extraction default, not chosen by the agent
    assert ev.page_number == 1 and ev.extraction_method is ExtractionMethod.TEXT
    assert ev.is_mock is True


def test_page_number_follows_form_feeds(session: Session) -> None:
    company, _, text = _doc(session)
    start = DOC.index("More text")
    ev = create_evidence(
        session,
        document_text=text,
        company_id=company.id,
        char_start=start,
        char_end=start + 4,
        created_by="parser",
        confidence=Decimal("1"),
    )
    assert ev.page_number == 2
    assert page_number_for([], 0) is None


def test_mismatched_extracted_text_is_rejected(session: Session) -> None:
    company, _, text = _doc(session)
    with pytest.raises(SpanError):
        create_evidence(
            session,
            document_text=text,
            company_id=company.id,
            char_start=0,
            char_end=8,
            created_by="parser",
            extracted_text="Page two",
        )


def test_out_of_range_span_is_rejected(session: Session) -> None:
    company, _, text = _doc(session)
    with pytest.raises(SpanError):
        create_evidence(
            session,
            document_text=text,
            company_id=company.id,
            char_start=5,
            char_end=5,
            created_by="parser",
        )
    with pytest.raises(SpanError):
        create_evidence(
            session,
            document_text=text,
            company_id=company.id,
            char_start=0,
            char_end=10_000,
            created_by="parser",
        )


def test_agent_cannot_set_confidence(session: Session) -> None:
    company, _, text = _doc(session)
    with pytest.raises(ValueError, match="never by agents"):
        create_evidence(
            session,
            document_text=text,
            company_id=company.id,
            char_start=0,
            char_end=4,
            created_by="agent:financial",
            confidence=Decimal("1"),
        )


def test_other_company_cannot_cite_document(session: Session) -> None:
    _, _, text = _doc(session)
    other = make_company(session)
    with pytest.raises(SpanError):
        create_evidence(
            session,
            document_text=text,
            company_id=other.id,
            char_start=0,
            char_end=4,
            created_by="parser",
        )


def test_database_trigger_rejects_fabricated_text(session: Session) -> None:
    """Bypassing the Python layer still cannot store text that is not in the document."""
    company, raw, text = _doc(session)
    session.add(
        Evidence(
            raw_document_id=raw.id,
            document_text_id=text.id,
            company_id=company.id,
            source=raw.source,
            extracted_text="Rs. 999 crore",
            char_start=0,
            char_end=13,
            extraction_method=ExtractionMethod.TEXT,
            confidence=Decimal("0.9"),
            created_by="agent:financial",
            public_at=raw.public_at,
            is_mock=True,
        )
    )
    with pytest.raises(DBAPIError, match="not the verbatim span"):
        session.flush()


def test_database_trigger_rejects_company_mismatch(session: Session) -> None:
    _, raw, text = _doc(session)
    other = make_company(session)
    session.add(
        Evidence(
            raw_document_id=raw.id,
            document_text_id=text.id,
            company_id=other.id,
            source=raw.source,
            extracted_text=DOC[:4],
            char_start=0,
            char_end=4,
            extraction_method=ExtractionMethod.TEXT,
            confidence=Decimal("0.9"),
            created_by="parser",
            public_at=raw.public_at,
            is_mock=True,
        )
    )
    with pytest.raises(DBAPIError, match="does not own document"):
        session.flush()


def test_evidence_is_immutable(session: Session) -> None:
    company, _, text = _doc(session)
    ev = create_evidence(
        session,
        document_text=text,
        company_id=company.id,
        char_start=0,
        char_end=4,
        created_by="parser",
    )
    ev.extracted_text = "Fake"
    with pytest.raises(DBAPIError, match="immutable"):
        session.flush()


def test_create_from_quote_tolerates_whitespace_only(session: Session) -> None:
    company, _, text = _doc(session)
    ev = create_evidence_from_quote(
        session,
        document_text=text,
        company_id=company.id,
        quote="Page one. The Company has received",
        created_by="agent:business",
    )
    assert ev.extracted_text == "Page one.\nThe Company has received"
    with pytest.raises(SpanError):
        create_evidence_from_quote(
            session,
            document_text=text,
            company_id=company.id,
            quote="order worth Rs. 999 crore",
            created_by="agent:business",
        )


def test_locate_span() -> None:
    assert locate_span("a b  c", "b c") == (2, 6)
    assert locate_span("abc", "abc") == (0, 3)
    assert locate_span("abc", "") is None
    assert locate_span("abc", "xyz") is None
