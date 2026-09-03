from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import POINT_IN_TIME_MODELS, Base, Company, Exchange, RawDocument
from tests.factories import ist, make_company, make_raw_document


def test_every_point_in_time_model_carries_provenance() -> None:
    """PRD §5.2: derived rows carry raw_document_id, parser_version, public_at, ingested_at."""
    for model in POINT_IN_TIME_MODELS:
        mapper = inspect(model)
        assert mapper is not None
        cols = {c.key for c in mapper.columns}
        assert {"public_at", "is_mock"} <= cols, model.__name__
        if mapper.local_table.name == "evidence":
            # Evidence pins its text version via document_text_id and records created_by.
            assert {"document_text_id", "created_by", "created_at"} <= cols
        elif mapper.local_table.name != "raw_documents":
            assert {"raw_document_id", "parser_version", "ingested_at"} <= cols, model.__name__


def test_every_table_has_is_mock_flag() -> None:
    for name, table in Base.metadata.tables.items():
        if name in {"document_texts", "institutional_holdings"}:
            continue  # point-in-time and mock status come from their parent row
        assert "is_mock" in table.c, name


def test_mock_company_requires_mock_ticker(session: Session) -> None:
    session.add(Company(name="x", ticker="REALCO", exchange=Exchange.NSE, sector="s", is_mock=True))
    with pytest.raises(IntegrityError):
        session.flush()


def test_live_company_cannot_use_mock_ticker(session: Session) -> None:
    session.add(
        Company(name="x", ticker="MOCK-XYZ", exchange=Exchange.NSE, sector="s", is_mock=False)
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_raw_document_sha256_is_identity(session: Session) -> None:
    company = make_company(session)
    doc = make_raw_document(session, company, ist(2024, 1, 1))
    session.add(
        RawDocument(
            company_id=company.id,
            source=doc.source,
            sha256=doc.sha256,
            storage_key="raw/other",
            content_type="text/plain",
            byte_size=1,
            public_at=doc.public_at,
            is_mock=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
