from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from data.mock.synth import Story, load_blueprints
from database.models import Company

AS_OF = {"as_of": "2026-08-31"}


def _id(session: Session, story: Story, nth: int = 0) -> int:
    ticker = [b for b in load_blueprints() if b.story is story][nth].ticker
    return session.scalars(select(Company.id).where(Company.ticker == ticker)).one()


def test_list_companies_filters_sort_and_paginate(
    client: TestClient, mock_scores: int, mock_session: Session
) -> None:
    r = client.get("/api/v1/companies", params={**AS_OF, "page_size": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["dataset"] == "mock"
        and body["data"]["total"] == 40
        and len(body["data"]["items"]) == 10
    )
    first = body["data"]["items"][0]
    assert first["scores"]["opportunity"] is not None
    opps = [
        i["scores"]["opportunity"]
        for i in body["data"]["items"]
        if i["scores"]["opportunity"] is not None
    ]
    assert opps == sorted(opps, reverse=True)
    r = client.get("/api/v1/companies", params={**AS_OF, "sector": "Chemicals", "sort": "ticker"})
    items = r.json()["data"]["items"]
    assert items and all(i["sector"] == "Chemicals" for i in items)
    assert [i["ticker"] for i in items] == sorted(i["ticker"] for i in items)
    r = client.get(
        "/api/v1/companies",
        params={**AS_OF, "exclude_illiquid": "true", "in_universe_only": "true"},
    )
    assert all(i["in_universe"] and not i["is_illiquid"] for i in r.json()["data"]["items"])
    r = client.get("/api/v1/companies", params={**AS_OF, "risk_min": 70})
    assert all(i["scores"]["risk"] >= 70 for i in r.json()["data"]["items"])
    r = client.get(
        "/api/v1/companies", params={**AS_OF, "surveillance": "true", "as_of": "2025-03-31"}
    )
    assert r.status_code == 200
    assert client.get("/api/v1/companies", params={**AS_OF, "sort": "nonsense"}).status_code == 422
    delisted = _id(mock_session, Story.DELISTED)
    row = next(
        i
        for i in client.get("/api/v1/companies", params={**AS_OF, "page_size": 200}).json()["data"][
            "items"
        ]
        if i["id"] == delisted
    )
    assert row["listing_status"] == "delisted" and not row["in_universe"]


def test_company_profile_and_financials(client: TestClient, mock_session: Session) -> None:
    cid = _id(mock_session, Story.MARGIN_TURNAROUND, 1)
    r = client.get(f"/api/v1/companies/{cid}", params=AS_OF)
    assert r.status_code == 200, r.text
    p = r.json()["data"]
    assert p["ticker"].startswith("MOCK-") and p["price"] and p["market_cap_cr"]
    assert r.json()["data_quality"]["sources"]
    r = client.get(
        f"/api/v1/companies/{cid}/financials", params={**AS_OF, "periods": 12, "period_months": 3}
    )
    rows = r.json()["data"]
    assert len(rows) == 12 and all(row["filing_id"] and row["raw_document_id"] for row in rows)
    assert rows[0]["ratios"]["ebitda_margin"] > rows[8]["ratios"]["ebitda_margin"] + 0.05
    assert "revenue_yoy" in rows[0]["ratios"]
    r = client.get(f"/api/v1/companies/{cid}/financials", params={**AS_OF, "period_months": 12})
    annual = r.json()["data"]
    assert (
        annual
        and annual[0]["ratios"].get("cfo_to_ebitda") is not None
        and annual[0]["audit_opinion"] == "unqualified"
    )
    early = client.get(
        f"/api/v1/companies/{cid}/financials", params={"as_of": "2023-06-30", "period_months": 3}
    ).json()["data"]
    assert len(early) == 4
    assert client.get("/api/v1/companies/999999", params=AS_OF).status_code == 404


def test_ownership_prices_signals_scores(
    client: TestClient, mock_scores: int, mock_backtest: int, mock_session: Session
) -> None:
    cid = _id(mock_session, Story.PLEDGE_UNWIND)
    own = client.get(f"/api/v1/companies/{cid}/ownership", params=AS_OF).json()["data"]
    assert (
        own["shareholdings"][0]["promoter_pledged_pct"] == "0.0000"
        and len(own["pledge_events"]) == 3
    )
    assert own["insider_trades"] and own["insider_trades"][0]["fields"]["side"] == "buy"

    bonus = _id(mock_session, Story.CONTROL, 1)  # MOCK-TGBR has a 1:1 bonus
    prices = client.get(
        f"/api/v1/companies/{bonus}/prices",
        params={**AS_OF, "from": "2024-01-01", "to": "2024-12-31"},
    ).json()["data"]
    assert prices and any(abs(p["adjusted_close"] - p["close"]) > 1e-6 for p in prices[:5])
    assert abs(prices[-1]["adjusted_close"] - prices[-1]["close"]) < 1e-6
    assert (
        client.get(
            f"/api/v1/companies/{bonus}/prices", params={"as_of": "2024-06-30", "to": "2024-12-31"}
        ).status_code
        == 422
    )

    sigs = client.get(f"/api/v1/companies/{cid}/signals", params=AS_OF).json()["data"]
    types = {s["signal_type"] for s in sigs}
    assert {"pledge_reduction", "promoter_stake_increase"} <= types
    with_perf = next(s for s in sigs if s["signal_type"] == "pledge_reduction")
    assert with_perf["performance"] and "180" in with_perf["performance"]["horizons"]
    assert all(s["parameters"] for s in sigs)

    scores = client.get(f"/api/v1/companies/{cid}/scores", params=AS_OF).json()["data"]
    assert [s["score_type"] for s in scores] == [
        "opportunity",
        "inflection",
        "quality",
        "valuation",
        "risk",
        "attention_gap",
    ]
    assert all(s["components"]["components"] for s in scores)


def test_valuation_and_thesis_without_agents(client: TestClient, mock_session: Session) -> None:
    cid = _id(mock_session, Story.ORDER_BOOK_SURGE)
    r = client.get(f"/api/v1/companies/{cid}/valuation", params=AS_OF)
    assert r.status_code == 200, r.text
    v = r.json()["data"]
    assert v["source"] == "default" and [s["name"] for s in v["scenarios"]] == [
        "bear",
        "base",
        "bull",
    ]
    assert v["scenarios"][2]["value_per_share"] > v["scenarios"][0]["value_per_share"]
    assert v["spec"]["steps"] and v["inputs"]["price"] > 0
    body = r.text.lower()
    for banned in ("buy", "sell", "target price", "recommendation"):
        assert banned not in body, banned
    t = client.get(f"/api/v1/companies/{cid}/thesis", params=AS_OF).json()["data"]
    assert t["thesis"] is None and t["contradiction"] is None and "contradiction" in t["message"]
