from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from evidence import Claim, ClaimValidationError, create_evidence, validate_claims
from tests.factories import ist, make_company, make_raw_document


def test_claim_without_evidence_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        Claim(text="Revenue grew", evidence_ids=[])


def test_claims_validate_company_and_time(session: Session) -> None:
    company = make_company(session)
    other = make_company(session)
    raw = make_raw_document(session, company, ist(2024, 7, 1), text="Revenue grew 20% in Q1.")
    raw_other = make_raw_document(session, other, ist(2024, 7, 1), text="Other company text.")
    ev = create_evidence(
        session,
        document_text=raw.texts[0],
        company_id=company.id,
        char_start=0,
        char_end=7,
        created_by="agent:financial",
    )
    ev_other = create_evidence(
        session,
        document_text=raw_other.texts[0],
        company_id=other.id,
        char_start=0,
        char_end=5,
        created_by="agent:financial",
    )

    ok = validate_claims(
        session,
        [Claim(text="Revenue grew", evidence_ids=[ev.id])],
        company_id=company.id,
        as_of=ist(2024, 8, 1),
        is_mock=True,
    )
    assert set(ok) == {ev.id}

    with pytest.raises(ClaimValidationError, match="belongs to company"):
        validate_claims(
            session,
            [Claim(text="x", evidence_ids=[ev_other.id])],
            company_id=company.id,
            as_of=ist(2024, 8, 1),
            is_mock=True,
        )
    with pytest.raises(ClaimValidationError, match="after as_of"):
        validate_claims(
            session,
            [Claim(text="x", evidence_ids=[ev.id])],
            company_id=company.id,
            as_of=ist(2024, 6, 1),
            is_mock=True,
        )
    with pytest.raises(ClaimValidationError, match="does not exist"):
        validate_claims(
            session,
            [Claim(text="x", evidence_ids=[999_999_999])],
            company_id=company.id,
            as_of=ist(2024, 8, 1),
            is_mock=True,
        )
    with pytest.raises(ClaimValidationError, match="mock dataset"):
        validate_claims(
            session,
            [Claim(text="x", evidence_ids=[ev.id])],
            company_id=company.id,
            as_of=ist(2024, 8, 1),
            is_mock=False,
        )
