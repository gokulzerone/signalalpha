"""Research jobs (PRD §10): async, return a run id, poll ``GET /runs/{run_id}``."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from apps.api.deps import DatasetDep, PitDep, SessionDep, parse_as_of
from apps.api.envelope import wrap
from apps.api.schemas import Envelope, RunOut
from database.models import ResearchRun
from database.pit import IST, coerce_as_of
from pipelines.research import create_run

router = APIRouter(tags=["research"])
AGENT_NAMES = (
    "financial",
    "promoter",
    "business",
    "industry",
    "forensic",
    "valuation",
    "contradiction",
    "thesis",
)


def _run_out(run: ResearchRun) -> RunOut:
    from datetime import datetime

    return RunOut(
        id=run.id,
        company_id=run.company_id,
        as_of=datetime.combine(run.as_of, datetime.min.time(), tzinfo=IST),
        kind=run.kind,
        status=run.status.value,
        steps=run.steps,
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


def _as_of_date(as_of: str | None) -> date:
    if as_of is None:
        return date.today()
    value = parse_as_of(as_of)
    return coerce_as_of(value).astimezone(IST).date()


@router.post("/research/{company_id}", response_model=Envelope[RunOut], status_code=202)
def start_research(
    company_id: int,
    request: Request,
    pit: PitDep,
    session: SessionDep,
    dataset: DatasetDep,
    as_of: Annotated[str | None, Query()] = None,
) -> Envelope[RunOut]:
    company = pit.company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    run = create_run(session, company, _as_of_date(as_of), is_mock=dataset.value == "mock")
    session.commit()
    request.app.state.dispatcher.enqueue_research(run.id)
    return wrap(pit, _run_out(run), company_id=company_id)


@router.post("/agents/{agent_name}/{company_id}", response_model=Envelope[RunOut], status_code=202)
def start_agent(
    agent_name: str,
    company_id: int,
    request: Request,
    pit: PitDep,
    session: SessionDep,
    dataset: DatasetDep,
    as_of: Annotated[str | None, Query()] = None,
) -> Envelope[RunOut]:
    if agent_name not in AGENT_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown agent {agent_name!r}")
    company = pit.company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    run = create_run(
        session,
        company,
        _as_of_date(as_of),
        is_mock=dataset.value == "mock",
        kind=f"agent:{agent_name}",
    )
    session.commit()
    request.app.state.dispatcher.enqueue_research(run.id, agents=[agent_name])
    return wrap(pit, _run_out(run), company_id=company_id)


@router.get("/runs/{run_id}", response_model=Envelope[RunOut])
def get_run(run_id: str, pit: PitDep, session: SessionDep) -> Envelope[RunOut]:
    run = session.get(ResearchRun, run_id)
    if run is None or run.is_mock != pit.is_mock:
        raise HTTPException(status_code=404, detail="run not found")
    session.refresh(run)
    return wrap(pit, _run_out(run), company_id=run.company_id)
