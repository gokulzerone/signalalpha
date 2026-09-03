"""The research pipeline for one company (PRD §10 ``POST /research/{company_id}``):
refresh data -> signals -> agents in dependency order -> scores -> thesis.

Agents are attached in build step 8 through :data:`AGENT_STAGE`; until then the pipeline
runs the deterministic stages and records that no agents are registered.
"""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from database.models import Company, ResearchRun, RunStatus
from scoring.pipeline import run_scores
from signals.runner import detect_company_signals

UTC = ZoneInfo("UTC")

#: Hook for build step 8: ``(session, company, as_of, is_mock, run, agents) -> steps``.
AgentStage = Callable[
    [Session, Company, date, bool, ResearchRun, list[str] | None], list[dict[str, Any]]
]
AGENT_STAGE: AgentStage | None = None


def create_run(
    session: Session, company: Company, as_of: date, *, is_mock: bool, kind: str = "research"
) -> ResearchRun:
    run = ResearchRun(
        id=str(uuid.uuid4()),
        company_id=company.id,
        as_of=as_of,
        kind=kind,
        status=RunStatus.QUEUED,
        steps=[],
        is_mock=is_mock,
    )
    session.add(run)
    session.flush()
    return run


def _step(run: ResearchRun, name: str, status: str, detail: str | None = None) -> None:
    run.steps = [
        *run.steps,
        {"name": name, "status": status, "at": datetime.now(tz=UTC).isoformat(), "detail": detail},
    ]


def execute_run(session: Session, run_id: str, *, agents: list[str] | None = None) -> ResearchRun:
    run = session.get(ResearchRun, run_id)
    if run is None:
        raise LookupError(f"research run {run_id} not found")
    company = session.get(Company, run.company_id)
    assert company is not None
    run.status = RunStatus.RUNNING
    session.flush()
    try:
        _step(
            run,
            "refresh",
            "skipped",
            "live ingestion is feature-flagged (build step 10); mock data is static",
        )
        if run.kind == "research":
            result = detect_company_signals(session, company, as_of=run.as_of, is_mock=run.is_mock)
            _step(
                run,
                "signals",
                "completed",
                f"{len(result.created)} new signals, {result.duplicates_skipped} already present",
            )
        if AGENT_STAGE is not None:
            for step in AGENT_STAGE(session, company, run.as_of, run.is_mock, run, agents):
                _step(run, step["name"], step["status"], step.get("detail"))
        else:
            _step(run, "agents", "skipped", "no agents registered")
        if run.kind == "research":
            scores = run_scores(session, as_of=run.as_of, is_mock=run.is_mock)
            _step(
                run,
                "scores",
                "completed",
                f"{scores.rows_written} score rows for {len(scores.results)} companies",
            )
        run.status = RunStatus.COMPLETED
    except Exception as exc:
        run.status = RunStatus.FAILED
        run.error = f"{exc}\n{traceback.format_exc()}"
        _step(run, "failed", "failed", str(exc))
    run.finished_at = datetime.now(tz=UTC)
    session.flush()
    return run
