"""An investigation must run its grounded stages even when the web is unavailable, and must
never present a skipped step as a completed one."""

from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from database.models import InvestigationStatus
from database.pit import coerce_as_of
from investigations.macro import MacroReading, MacroResult, WebSource
from investigations.runner import run_investigation, start_investigation
from investigations.stages import STAGES

AS_OF = date(2026, 8, 31)
BANNED = ("buy", "sell", "target price", "recommendation")


def test_stage_wording_is_present_tense_and_distinct() -> None:
    assert len(STAGES) == 9
    assert STAGES[0].running == "Scanning the world for economic conditions"
    assert STAGES[3].running == "Scanning India for companies in the path of it"
    assert STAGES[4].running == "Finalising the company"
    assert len({s.key for s in STAGES}) == len(STAGES)
    assert [s.key for s in STAGES if s.needs_web] == ["world", "impact", "supply_demand"]


def test_runs_end_to_end_without_the_web(mock_session: Session, mock_scores: int) -> None:
    row = start_investigation(mock_session, as_of=coerce_as_of(AS_OF), is_mock=True)
    done = run_investigation(mock_session, row.id)

    assert done.status is InvestigationStatus.COMPLETED, done.error
    by_key = {s["key"]: s for s in done.stages}
    # The three web stages say they were skipped and why; nothing pretends they ran.
    for key in ("world", "impact", "supply_demand"):
        assert by_key[key]["status"] == "skipped"
        assert "ANTHROPIC_API_KEY" in by_key[key]["detail"]
    # Everything grounded in filings actually ran.
    for key in ("india", "company", "value", "fundamentals", "threats", "case"):
        assert by_key[key]["status"] == "done", key
        assert by_key[key]["detail"]

    assert done.company_id is not None
    result = done.result
    assert result is not None
    assert result["company"]["company_id"] == done.company_id
    assert result["web_grounded"] is False
    assert result["verdict"]["headline"]
    assert result["macro_line"] is None
    # The company came from the covered universe, not from thin air.
    shortlist = by_key["india"]["shortlist"]
    assert shortlist and any(c["company_id"] == done.company_id for c in shortlist)


def test_nothing_in_the_output_reads_as_advice(mock_session: Session, mock_scores: int) -> None:
    row = start_investigation(mock_session, as_of=coerce_as_of(AS_OF), is_mock=True)
    done = run_investigation(mock_session, row.id)
    text = str(done.stages).lower() + str(done.result).lower()
    for word in BANNED:
        assert word not in text, word


def test_sector_matching_is_forgiving_about_wording() -> None:
    from investigations.runner import _sector_matches

    assert _sector_matches("Chemicals", ["chemical"])
    assert _sector_matches("Auto Ancillaries", ["auto ancillaries"])
    assert _sector_matches("Textiles", ["textile"])
    assert not _sector_matches("Pharma", ["shipping"])
    assert not _sector_matches("Pharma", [])


def test_macro_result_collects_sectors_without_duplicates() -> None:
    reading = MacroReading(
        summary="Rates are falling and energy is cheap.",
        findings=[
            {
                "condition": "Energy prices fell",
                "so_what": "Input costs ease",
                "sectors": ["Chemicals", "Textiles"],
            },
            {
                "condition": "Rates fell",
                "so_what": "Financing is cheaper",
                "sectors": ["chemicals", "Capital goods"],
            },
        ],
    )
    result = MacroResult(
        text="...", reading=reading, sources=[WebSource("A report", "https://example.invalid/a")]
    )
    assert result.sectors() == ["Chemicals", "Textiles", "Capital goods"]
    assert result.to_json()["sources"] == [
        {"title": "A report", "url": "https://example.invalid/a"}
    ]


def test_api_reports_what_it_can_do_and_runs_one(client: TestClient, mock_scores: int) -> None:
    caps = client.get("/api/v1/investigations/capabilities").json()["data"]
    assert caps["web_research"] is False
    assert "ANTHROPIC_API_KEY" in caps["how_to_enable"]
    assert [s["key"] for s in caps["stages"]] == [s.key for s in STAGES]

    created = client.post("/api/v1/investigations", params={"as_of": "2026-08-31"})
    assert created.status_code == 202, created.text
    run_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "queued"

    import time

    deadline = time.time() + 120
    body: dict[str, object] = {}
    while time.time() < deadline:
        body = client.get(
            f"/api/v1/investigations/{run_id}", params={"as_of": "2026-08-31"}
        ).json()["data"]
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert body["status"] == "completed", body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    assert str(result["company"]["ticker"]).startswith("MOCK-")
    assert client.get("/api/v1/investigations/does-not-exist").status_code == 404
    assert any(x["id"] == run_id for x in client.get("/api/v1/investigations").json()["data"])


def test_started_investigation_starts_pending(mock_session: Session) -> None:
    row = start_investigation(
        mock_session, as_of=datetime.now(tz=coerce_as_of(AS_OF).tzinfo), is_mock=True
    )
    assert row.status is InvestigationStatus.QUEUED
    assert [s["status"] for s in row.stages] == ["pending"] * len(STAGES)
    assert row.stages[0]["label"] == STAGES[0].running
