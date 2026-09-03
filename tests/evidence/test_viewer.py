from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from database.pit import PointInTimeSession
from evidence import DocumentNotFoundError, create_evidence, document_view
from tests.factories import ist, make_company, make_raw_document


def test_viewer_returns_highlight_and_respects_point_in_time(session: Session) -> None:
    company = make_company(session)
    raw = make_raw_document(session, company, ist(2024, 7, 15), text="Alpha\fBeta gamma")
    ev = create_evidence(
        session,
        document_text=raw.texts[0],
        company_id=company.id,
        char_start=6,
        char_end=10,
        created_by="parser",
    )

    pit = PointInTimeSession(session, date(2024, 7, 15), is_mock=True)
    view = document_view(pit, raw.id, company_id=company.id, highlight_evidence_id=ev.id)
    assert view.text == "Alpha\fBeta gamma"
    assert view.highlight is not None
    assert (view.highlight.char_start, view.highlight.char_end, view.highlight.page_number) == (
        6,
        10,
        2,
    )
    assert view.highlight.text == "Beta"

    earlier = PointInTimeSession(session, date(2024, 7, 14), is_mock=True)
    with pytest.raises(DocumentNotFoundError):
        document_view(earlier, raw.id)

    other = make_company(session)
    with pytest.raises(DocumentNotFoundError):
        document_view(pit, raw.id, company_id=other.id)
    with pytest.raises(DocumentNotFoundError):
        document_view(pit, raw.id, highlight_evidence_id=ev.id + 1000)
