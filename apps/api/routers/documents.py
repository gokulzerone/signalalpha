"""Evidence and document endpoints (PRD §10 Companies)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import PitDep
from apps.api.envelope import wrap
from apps.api.schemas import DocumentOut, Envelope, EvidenceOut, HighlightOut
from evidence import DocumentNotFoundError, document_view

router = APIRouter(prefix="/companies/{company_id}", tags=["evidence"])


def _document_url(company_id: int, raw_document_id: int, evidence_id: int) -> str:
    return f"/api/v1/companies/{company_id}/documents/{raw_document_id}?highlight={evidence_id}"


@router.get("/evidence", response_model=Envelope[list[EvidenceOut]])
def get_evidence(
    company_id: int,
    pit: PitDep,
    ids: Annotated[list[int] | None, Query(description="Evidence ids; omit for all")] = None,
) -> Envelope[list[EvidenceOut]]:
    if pit.company(company_id) is None:
        raise HTTPException(status_code=404, detail="company not found")
    rows = pit.evidence(company_id, ids)
    data = [
        EvidenceOut(
            id=r.id,
            raw_document_id=r.raw_document_id,
            document_text_id=r.document_text_id,
            company_id=r.company_id,
            filing_id=r.filing_id,
            source=r.source.value,
            url=r.url,
            public_at=r.public_at,
            extracted_text=r.extracted_text,
            char_start=r.char_start,
            char_end=r.char_end,
            page_number=r.page_number,
            extraction_method=r.extraction_method.value,
            confidence=r.confidence,
            created_by=r.created_by,
            document_url=_document_url(company_id, r.raw_document_id, r.id),
        )
        for r in rows
    ]
    return wrap(pit, data, company_id=company_id)


@router.get("/documents/{raw_document_id}", response_model=Envelope[DocumentOut])
def get_document(
    company_id: int,
    raw_document_id: int,
    pit: PitDep,
    highlight: Annotated[int | None, Query(description="Evidence id to highlight")] = None,
) -> Envelope[DocumentOut]:
    if pit.company(company_id) is None:
        raise HTTPException(status_code=404, detail="company not found")
    try:
        view = document_view(
            pit, raw_document_id, company_id=company_id, highlight_evidence_id=highlight
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    data = DocumentOut(
        raw_document_id=view.raw_document_id,
        company_id=view.company_id,
        source=view.source.value,
        title=view.title,
        public_at=view.public_at,
        content_type=view.content_type,
        parser_version=view.parser_version,
        text=view.text,
        page_offsets=view.page_offsets,
        highlight=HighlightOut(
            evidence_id=view.highlight.evidence_id,
            char_start=view.highlight.char_start,
            char_end=view.highlight.char_end,
            page_number=view.highlight.page_number,
            text=view.highlight.text,
        )
        if view.highlight
        else None,
    )
    return wrap(pit, data, company_id=company_id)
