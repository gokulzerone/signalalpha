"""Agent contract tests (PRD §7, §14): schema + validator on the mock universe, offline."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.base import (
    AgentContext,
    BudgetExceededError,
    PrerequisiteMissingError,
    check_numbers,
    numbers_in,
)
from agents.config import load_agent_config
from agents.llm import LLMResponse, RecordedClient, TemplateClient
from agents.pipeline import AGENTS, ORDER, run_agents
from data.mock.synth import Story, load_blueprints
from database.models import AgentRun, Company, Evidence, RunStatus

AS_OF = date(2026, 8, 31)
FIXTURES = Path(__file__).parent / "fixtures"


def _company(session: Session, story: Story, nth: int = 0) -> Company:
    ticker = [b for b in load_blueprints() if b.story is story][nth].ticker
    return session.scalars(select(Company).where(Company.ticker == ticker)).one()


def test_numeric_checks() -> None:
    assert numbers_in("Revenue was Rs. 1,234.50 crore, up 12.5% in FY2024 over 4 quarters") == [
        (1234.5, "crore"),
        (12.5, "%"),
    ]
    assert check_numbers("Revenue was Rs. 120.00 crore", [120.0], 0.005) == []
    assert check_numbers("margin was 15.00%", [0.15], 0.005) == []
    assert check_numbers("Revenue was Rs. 999 crore", [120.0], 0.005)


def test_full_agent_pipeline_on_order_book_story(mock_session: Session, mock_signals: int) -> None:
    company = _company(mock_session, Story.ORDER_BOOK_SURGE)
    steps = run_agents(mock_session, company, AS_OF, is_mock=True, client=TemplateClient())
    assert [s["status"] for s in steps] == ["completed"] * 8, steps
    runs = {
        r.agent_name: r
        for r in mock_session.scalars(
            select(AgentRun).where(AgentRun.company_id == company.id, AgentRun.as_of == AS_OF)
        ).all()
    }
    assert set(runs) == set(ORDER)
    business = runs["business"].output
    assert (
        business
        and business["orders"]
        and business["order_book_estimate_cr"]
        == round(sum(o["value_cr"] for o in business["orders"]), 2)
    )
    for o in business["orders"]:
        ev = mock_session.get(Evidence, o["evidence_id"])
        assert (
            ev is not None and ev.created_by == "agent:business" and ev.extracted_text == o["quote"]
        )
    thesis = runs["thesis"].output
    assert thesis and thesis["contradiction_run_id"] == runs["contradiction"].id
    assert all(c["evidence_ids"] for c in thesis["claims"])
    valuation = runs["valuation"].output
    assert valuation and [c["name"] for c in valuation["computed"]] == ["bear", "base", "bull"]
    assert all(r.model_id == "template-v1" and r.input_snapshot_hash for r in runs.values())
    # Re-running hits the cache: no new rows.
    before = mock_session.scalar(
        select(AgentRun.id).where(AgentRun.company_id == company.id).order_by(AgentRun.id.desc())
    )
    run_agents(mock_session, company, AS_OF, is_mock=True, client=TemplateClient())
    after = mock_session.scalar(
        select(AgentRun.id).where(AgentRun.company_id == company.id).order_by(AgentRun.id.desc())
    )
    assert before == after


def test_forensic_and_promoter_on_negative_stories(
    mock_session: Session, mock_signals: int
) -> None:
    forensic_co = _company(mock_session, Story.FORENSIC_RED_FLAG)
    steps = run_agents(
        mock_session,
        forensic_co,
        AS_OF,
        is_mock=True,
        client=TemplateClient(),
        agents=["financial", "promoter", "business", "industry", "forensic"],
    )
    assert all(s["status"] == "completed" for s in steps), steps
    forensic = next(
        r
        for r in mock_session.scalars(
            select(AgentRun).where(AgentRun.company_id == forensic_co.id)
        ).all()
        if r.agent_name == "forensic"
    )
    assert forensic.output and len(forensic.output["flags"]) >= 3
    assert all(f["classified"] for f in forensic.output["flags"])
    deceptive = _company(mock_session, Story.DECEPTIVE_GROWTH)
    sells_window = date(2025, 9, 30)  # promoter sales happened Dec 2024 to Jun 2025
    run_agents(
        mock_session,
        deceptive,
        sells_window,
        is_mock=True,
        client=TemplateClient(),
        agents=["promoter"],
    )
    promoter = next(
        r
        for r in mock_session.scalars(
            select(AgentRun).where(AgentRun.company_id == deceptive.id)
        ).all()
        if r.agent_name == "promoter"
    )
    assert (
        promoter.validated
        and promoter.output
        and promoter.output["promoter_behaviour"] == "distributing"
    )


class _Canned:
    """A client that returns a fixed output, for validator negative tests."""

    model_id = "canned-test"

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output

    def complete(
        self, *, system: str, user: str, output_model: type[BaseModel], max_tokens: int
    ) -> LLMResponse:
        return LLMResponse(self.output, self.model_id, 10, 10, Decimal("0"))


def _run_one(session: Session, company: Company, name: str, output: dict[str, Any]) -> AgentRun:
    actx = AgentContext.build(session, company, AS_OF, is_mock=True, client=_Canned(output))
    from agents.pipeline import existing_outputs

    actx.outputs = existing_outputs(session, company, AS_OF, is_mock=True)
    return AGENTS[name].run(actx)


def test_validators_reject_fabrication(mock_session: Session, mock_signals: int) -> None:
    company = _company(mock_session, Story.ORDER_BOOK_SURGE, 1)
    inputs = AGENTS["financial"].build_inputs(
        AgentContext.build(mock_session, company, AS_OF, is_mock=True, client=TemplateClient())
    )
    doc_id = next(iter(inputs.documents))
    good_quote = inputs.documents[doc_id].text.text.splitlines()[0]
    # 1. A quote that is not in the document -> rejected.
    r = _run_one(
        mock_session,
        company,
        "financial",
        {
            "narrative": "Revenue grew strongly this quarter.",
            "trajectory": "improving",
            "proposed_signals": [],
            "claims": [
                {
                    "text": "Revenue doubled.",
                    "quotes": [
                        {"document_id": doc_id, "quote": "Revenue doubled to Rs. 999999 crore."}
                    ],
                }
            ],
        },
    )
    assert r.status is RunStatus.FAILED and any(
        "not found verbatim" in e for e in r.validation_errors
    )
    # 2. A fabricated number in the narrative -> rejected.
    r = _run_one(
        mock_session,
        company,
        "financial",
        {
            "narrative": "Revenue for the quarter was Rs. 123456.78 crore.",
            "trajectory": "stable",
            "proposed_signals": [],
            "claims": [
                {
                    "text": "Board approved.",
                    "quotes": [{"document_id": doc_id, "quote": good_quote}],
                }
            ],
        },
    )
    assert r.status is RunStatus.FAILED and any("does not match" in e for e in r.validation_errors)
    # 3. A proposed signal that no detector computed -> rejected.
    r = _run_one(
        mock_session,
        company,
        "financial",
        {
            "narrative": "Results were filed for the quarter.",
            "trajectory": "stable",
            "proposed_signals": [{"signal_type": "margin_inflection", "dedupe_key": "1999-01-01"}],
            "claims": [
                {
                    "text": "Board approved.",
                    "quotes": [{"document_id": doc_id, "quote": good_quote}],
                }
            ],
        },
    )
    assert r.status is RunStatus.FAILED and any("proposed signal" in e for e in r.validation_errors)
    # 4. Schema-level rejection: a claim without quotes.
    r = _run_one(
        mock_session,
        company,
        "financial",
        {
            "narrative": "Results were filed for the quarter.",
            "trajectory": "stable",
            "proposed_signals": [],
            "claims": [{"text": "Board approved.", "quotes": []}],
        },
    )
    assert r.status is RunStatus.FAILED and any(
        e.startswith("schema:") for e in r.validation_errors
    )
    # 5. Business: stated sum must equal the Python sum.
    binputs = AGENTS["business"].build_inputs(
        AgentContext.build(mock_session, company, AS_OF, is_mock=True, client=TemplateClient())
    )
    order_doc = next(
        (a for a in binputs.snapshot["announcements"] if a["category"] == "order_win"), None
    )
    assert order_doc is not None
    from agents.common import doc_text
    from signals.detectors.business import parse_order_value

    parsed = parse_order_value(doc_text(binputs.snapshot, order_doc["document_id"]))
    assert parsed is not None
    value, quote = float(parsed[0]), parsed[1]
    bad: dict[str, Any] = {
        "orders": [
            {
                "document_id": order_doc["document_id"],
                "quote": quote,
                "value_cr": value,
                "execution_months": None,
                "customer": "",
            }
        ],
        "order_book_estimate_cr": value * 3,
        "capacity_story": "None.",
        "concentration": "Not disclosed.",
        "claims": [
            {
                "text": "Order received.",
                "quotes": [{"document_id": order_doc["document_id"], "quote": quote}],
            }
        ],
    }
    r = _run_one(mock_session, company, "business", bad)
    assert r.status is RunStatus.FAILED and any("Python sum" in e for e in r.validation_errors)
    bad["orders"][0]["value_cr"] = value + 10
    bad["order_book_estimate_cr"] = value + 10
    r = _run_one(mock_session, company, "business", bad)
    assert r.status is RunStatus.FAILED and any(
        "differs from quoted" in e for e in r.validation_errors
    )


def test_thesis_requires_contradiction_and_budget_is_enforced(
    mock_session: Session, mock_signals: int
) -> None:
    company = _company(mock_session, Story.CONTROL, 4)
    actx = AgentContext.build(mock_session, company, AS_OF, is_mock=True, client=TemplateClient())
    with pytest.raises(PrerequisiteMissingError):
        AGENTS["thesis"].run(actx)
    with pytest.raises(PrerequisiteMissingError):
        AGENTS["contradiction"].run(actx)
    # Exhaust the budget with a fake expensive run, then any agent refuses.
    mock_session.add(
        AgentRun(
            company_id=company.id,
            agent_name="financial",
            as_of=AS_OF,
            model_id="x",
            prompt_version="v1",
            input_snapshot_hash="0" * 64,
            status=RunStatus.COMPLETED,
            validated=False,
            validation_errors=[],
            cost_usd=Decimal(str(load_agent_config().daily_budget_usd_per_company)),
            is_mock=True,
        )
    )
    mock_session.flush()
    with pytest.raises(BudgetExceededError):
        AGENTS["financial"].run(actx)


def test_recorded_fixtures_replay(mock_session: Session, mock_signals: int) -> None:
    """Recorded outputs (produced offline) validate against schema and post-validator."""
    company = _company(mock_session, Story.MARGIN_TURNAROUND, 1)
    recorder = RecordedClient(FIXTURES, inner=TemplateClient())
    steps = run_agents(mock_session, company, AS_OF, is_mock=True, client=recorder)
    assert all(s["status"] == "completed" for s in steps), steps
    assert any(FIXTURES.glob("*/*.json"))
    replay = RecordedClient(FIXTURES)  # strict: no inner client
    for path in FIXTURES.glob("*/*.json"):
        data = json.loads(path.read_text())
        assert "output" in data
    assert replay.fixture_dir == FIXTURES
