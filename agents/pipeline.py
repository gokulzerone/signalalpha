"""Runs agents in dependency order (PRD §15 step 8) and plugs into the research pipeline."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.base import Agent, AgentContext, AgentError
from agents.business import BusinessAgent
from agents.contradiction import ContradictionAgent
from agents.financial import FinancialAgent
from agents.forensic import ForensicAgent
from agents.industry import IndustryAgent
from agents.llm import LLMClient
from agents.promoter import PromoterAgent
from agents.thesis import ThesisAgent
from agents.valuation import ValuationAgent
from database.models import AgentRun, Company, ResearchRun, RunStatus
from pipelines import research

AGENTS: dict[str, Agent] = {
    a.name: a
    for a in (
        FinancialAgent(),
        PromoterAgent(),
        BusinessAgent(),
        IndustryAgent(),
        ForensicAgent(),
        ValuationAgent(),
        ContradictionAgent(),
        ThesisAgent(),
    )
}
ORDER = tuple(AGENTS)


def existing_outputs(
    session: Session, company: Company, as_of: date, *, is_mock: bool
) -> dict[str, AgentRun]:
    out: dict[str, AgentRun] = {}
    for name in ORDER:
        row = session.scalars(
            select(AgentRun)
            .where(
                AgentRun.company_id == company.id,
                AgentRun.agent_name == name,
                AgentRun.as_of == as_of,
                AgentRun.is_mock == is_mock,
                AgentRun.status == RunStatus.COMPLETED,
                AgentRun.validated.is_(True),
            )
            .order_by(AgentRun.id.desc())
        ).first()
        if row is not None:
            out[name] = row
    return out


def run_agents(
    session: Session,
    company: Company,
    as_of: date,
    *,
    is_mock: bool,
    run: ResearchRun | None = None,
    agents: list[str] | None = None,
    client: LLMClient | None = None,
) -> list[dict[str, Any]]:
    actx = AgentContext.build(session, company, as_of, is_mock=is_mock, client=client, run=run)
    actx.outputs = existing_outputs(session, company, as_of, is_mock=is_mock)
    steps: list[dict[str, Any]] = []
    for name in ORDER:
        if agents is not None and name not in agents:
            continue
        agent = AGENTS[name]
        try:
            record = agent.run(actx)
        except AgentError as exc:
            steps.append({"name": f"agent:{name}", "status": "failed", "detail": str(exc)})
            continue
        if record.validated:
            steps.append(
                {
                    "name": f"agent:{name}",
                    "status": "completed",
                    "detail": f"run {record.id}, {record.model_id}, cost ${record.cost_usd}",
                }
            )
        else:
            steps.append(
                {
                    "name": f"agent:{name}",
                    "status": "failed",
                    "detail": "; ".join(record.validation_errors)[:500],
                }
            )
    return steps


def agent_stage(
    session: Session,
    company: Company,
    as_of: date,
    is_mock: bool,
    run: ResearchRun,
    agents: list[str] | None,
) -> list[dict[str, Any]]:
    return run_agents(session, company, as_of, is_mock=is_mock, run=run, agents=agents)


research.AGENT_STAGE = agent_stage
