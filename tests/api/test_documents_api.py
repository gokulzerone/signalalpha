from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from data.mock.synth import Story, load_blueprints
from database.models import AnnouncementCategory, Company, Evidence
from database.pit import PointInTimeSession
from evidence import create_evidence_from_quote


def _order_company(session: Session) -> Company:
    ticker = next(b.ticker for b in load_blueprints() if b.story is Story.ORDER_BOOK_SURGE)
    return session.scalars(select(Company).where(Company.ticker == ticker)).one()


def test_health_and_api_key(client: TestClient, secured_client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert secured_client.get("/api/v1/health").status_code == 401
    assert secured_client.get("/api/v1/health", headers={"X-API-Key": "secret"}).status_code == 200


def test_document_with_highlight(client: TestClient, mock_engine: Engine) -> None:
    # Evidence must be committed on its own connection so the API's session can see it.
    with Session(mock_engine, expire_on_commit=False) as writer:
        company = _order_company(writer)
        pit = PointInTimeSession(writer, date(2026, 8, 31), is_mock=True)
        ann = pit.announcements(company.id, categories=[AnnouncementCategory.ORDER_WIN])[0]
        text = pit.document_text(ann.raw_document_id)
        assert text is not None
        ev = create_evidence_from_quote(
            writer,
            document_text=text,
            company_id=company.id,
            quote="received an order worth",
            created_by="agent:business",
        )
        writer.commit()
        company_id, doc_id, ev_id = company.id, ann.raw_document_id, ev.id
    try:
        r = client.get(
            f"/api/v1/companies/{company_id}/documents/{doc_id}",
            params={"highlight": ev_id, "as_of": "2026-08-31"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dataset"] == "mock" and body["as_of"].startswith("2026-08-31")
        assert body["data_quality"]["sources"]
        h = body["data"]["highlight"]
        assert body["data"]["text"][h["char_start"] : h["char_end"]] == "received an order worth"

        r = client.get(
            f"/api/v1/companies/{company_id}/evidence",
            params={"ids": [ev_id], "as_of": "2026-08-31"},
        )
        assert r.status_code == 200
        assert r.json()["data"][0]["document_url"].endswith(f"?highlight={ev_id}")

        # Before the announcement was public, the document does not exist for the viewer.
        r = client.get(
            f"/api/v1/companies/{company_id}/documents/{doc_id}", params={"as_of": "2023-01-01"}
        )
        assert r.status_code == 404
        # Another company cannot fetch it.
        r = client.get(f"/api/v1/companies/{company_id + 1}/documents/{doc_id}")
        assert r.status_code == 404
        # The live dataset does not contain mock companies.
        r = client.get(f"/api/v1/companies/{company_id}/evidence", params={"dataset": "live"})
        assert r.status_code == 404
        # A naive datetime is rejected.
        r = client.get(
            f"/api/v1/companies/{company_id}/evidence", params={"as_of": "2026-08-31T10:00:00"}
        )
        assert r.status_code == 422
    finally:
        with Session(mock_engine) as cleanup:
            cleanup.execute(delete(Evidence).where(Evidence.id == ev_id))
            cleanup.commit()
