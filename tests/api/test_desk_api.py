"""The decision layer end to end (PRD §16: research attention, never trade instructions)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from data.mock.synth import Story, load_blueprints
from database.models import Company, Decision

AS_OF = {"as_of": "2026-08-31"}
BANNED = ("buy", "sell", "target price", "recommendation")


def _id(session: Session, story: Story, nth: int = 0) -> int:
    ticker = [b for b in load_blueprints() if b.story is story][nth].ticker
    return session.scalars(select(Company.id).where(Company.ticker == ticker)).one()


def test_desk_is_a_short_queue_with_readiness(
    client: TestClient, mock_scores: int, mock_backtest: int
) -> None:
    r = client.get("/api/v1/desk", params={**AS_OF, "since_days": 180, "limit": 8})
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert 0 < len(rows) <= 8, "the desk is a queue, not the whole universe"
    for row in rows:
        assert row["change"] and row["change"][0].isupper() and row["change"].endswith(".")
        assert row["readiness"]["status"] in ("ready", "partial", "not_ready")
        assert row["readiness"]["headline"]
        assert {c["key"] for c in row["readiness"]["checks"]} >= {
            "fundamentals",
            "history",
            "contradiction",
        }
    # Decidable names sort ahead of blocked ones.
    order = ["ready", "partial", "not_ready"]
    positions = [order.index(x["readiness"]["status"]) for x in rows]
    assert positions == sorted(positions)


def test_desk_and_brief_never_use_trading_language(
    client: TestClient, mock_scores: int, mock_session: Session
) -> None:
    body = client.get("/api/v1/desk", params={**AS_OF, "since_days": 180}).text.lower()
    for word in BANNED:
        assert word not in body, word
    cid = _id(mock_session, Story.ORDER_BOOK_SURGE)
    brief = client.get(f"/api/v1/companies/{cid}/brief", params=AS_OF).text.lower()
    for word in BANNED:
        assert word not in brief, word


def test_brief_assembles_the_whole_decision(
    client: TestClient, mock_scores: int, mock_backtest: int, mock_session: Session
) -> None:
    cid = _id(mock_session, Story.ORDER_BOOK_SURGE)
    r = client.get(f"/api/v1/companies/{cid}/brief", params={**AS_OF, "since_days": 400})
    assert r.status_code == 200, r.text
    b = r.json()["data"]
    assert b["change"] and b["narrated_signals"]
    assert all(s["sentence"] for s in b["narrated_signals"])
    assert b["readiness"]["checks"] and b["scores"]
    assert b["liquidity"]["days_to_exit"] and b["liquidity"]["adv_inr"] > 0
    assert b["break_conditions"], "a decision needs something that would change it"
    assert b["suggested_review_by"]
    accel = [x for x in b["narrated_signals"] if x["signal_type"] == "revenue_acceleration"]
    assert accel and "%" in accel[0]["sentence"], "narration carries the detector's own numbers"
    assert {r["signal_type"] for r in b["base_rates"]} & {
        x["signal_type"] for x in b["narrated_signals"]
    }
    # The order wins themselves are older than this window; they show up when it is widened.
    older = client.get(
        f"/api/v1/companies/{cid}/brief", params={"as_of": "2024-12-31", "since_days": 365}
    ).json()["data"]
    wins = [x for x in older["narrated_signals"] if x["signal_type"] == "order_win"]
    assert wins and "crore" in wins[0]["sentence"]
    assert client.get("/api/v1/companies/999999/brief").status_code == 404


def test_readiness_blocks_on_missing_contradiction(
    client: TestClient, mock_scores: int, mock_session: Session
) -> None:
    # A company with no agent runs has no case against it, so it cannot be decided on.
    cid = _id(mock_session, Story.CONTROL, 7)
    b = client.get(f"/api/v1/companies/{cid}/brief", params=AS_OF).json()["data"]
    contradiction = next(c for c in b["readiness"]["checks"] if c["key"] == "contradiction")
    assert contradiction["passed"] is False
    assert "case against" in contradiction["to_resolve"]
    assert b["readiness"]["status"] == "not_ready"


def test_recording_a_decision_and_its_alerts(
    client: TestClient, mock_scores: int, mock_engine: object, mock_session: Session
) -> None:
    cid = _id(mock_session, Story.FORENSIC_RED_FLAG)
    payload = {
        "verdict": "track",
        "reason": "Receivables story needs one more year before I size anything.",
        "conviction": "low",
        "review_trigger": "Receivable days fall below 120.",
        "as_of": "2025-06-30",
    }
    r = client.post(
        f"/api/v1/companies/{cid}/decisions", params={"as_of": "2025-06-30"}, json=payload
    )
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    assert d["verdict"] == "track" and d["review_by"]
    assert d["snapshot"]["readiness"]["status"] in ("ready", "partial", "not_ready")
    assert d["snapshot"]["signal_types"], "the decision records the evidence it was made on"
    try:
        listed = client.get("/api/v1/decisions", params=AS_OF).json()["data"]
        assert any(x["id"] == d["id"] for x in listed)
        # Negative signals after the decision date surface as alerts.
        alerts = client.get("/api/v1/decisions/alerts", params=AS_OF).json()["data"]
        mine = [a for a in alerts if a["decision"]["id"] == d["id"]]
        assert mine, "a forensic name should raise something after the decision"
        assert {a["kind"] for a in mine} <= {"negative_signal", "review_due"}
        assert all(a["text"] for a in mine)
        bad = client.post(
            f"/api/v1/companies/{cid}/decisions", json={"verdict": "nonsense", "reason": "x"}
        )
        assert bad.status_code == 422
    finally:
        with Session(mock_engine) as cleanup:  # type: ignore[arg-type]
            cleanup.execute(delete(Decision).where(Decision.id == d["id"]))
            cleanup.commit()


def test_desk_reflects_the_as_of_date(client: TestClient, mock_scores: int) -> None:
    early = client.get("/api/v1/desk", params={"as_of": "2024-06-30", "since_days": 90}).json()
    late = client.get("/api/v1/desk", params={**AS_OF, "since_days": 90}).json()
    assert early["as_of"].startswith("2024-06-30")
    assert {r["ticker"] for r in early["data"]} != {r["ticker"] for r in late["data"]}
