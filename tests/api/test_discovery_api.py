from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from data.mock.synth import Story, load_blueprints
from database.models import Company


def _ticker(story: Story, nth: int = 0) -> str:
    return [b for b in load_blueprints() if b.story is story][nth].ticker


def test_inflections_and_red_flags(
    client: TestClient, mock_scores: int, mock_session: Session
) -> None:
    r = client.get(
        "/api/v1/discoveries/inflections", params={"as_of": "2024-09-30", "since": "180d"}
    )
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert items
    tickers = [i["ticker"] for i in items]
    assert (
        _ticker(Story.ORDER_BOOK_SURGE) in tickers or _ticker(Story.ORDER_BOOK_SURGE, 1) in tickers
    )
    opps = [i["scores"]["opportunity"] for i in items if i["scores"]["opportunity"] is not None]
    assert opps == sorted(opps, reverse=True)
    assert all(i["new_signal_types"] for i in items)

    r = client.get("/api/v1/discoveries/red-flags", params={"as_of": "2025-12-31", "since": "180d"})
    items = r.json()["data"]["items"]
    tickers = [i["ticker"] for i in items]
    assert (
        _ticker(Story.FORENSIC_RED_FLAG) in tickers
        or _ticker(Story.FORENSIC_RED_FLAG, 1) in tickers
    )
    assert all(i["strongest_negative"] for i in items)
    assert client.get("/api/v1/discoveries/red-flags", params={"since": "bogus"}).status_code == 422


def test_attention_gap(client: TestClient, mock_scores: int) -> None:
    r = client.get(
        "/api/v1/discoveries/attention-gap",
        params={"as_of": "2026-08-31", "min_attention_gap": 40, "min_inflection": 40},
    )
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert all(
        i["scores"]["attention_gap"] >= 40 and i["scores"]["inflection"] >= 40 for i in items
    )
    products = [i["scores"]["attention_gap"] * i["scores"]["inflection"] for i in items]
    assert products == sorted(products, reverse=True)
    assert mock_session_unused(mock_scores)


def mock_session_unused(x: int) -> bool:
    return x > 0


def test_mock_and_live_never_mix(client: TestClient, mock_session: Session) -> None:
    live = client.get("/api/v1/companies", params={"dataset": "live"}).json()
    assert live["dataset"] == "live" and live["data"]["total"] == 0
    assert mock_session.scalar(select(Company.id).limit(1)) is not None
