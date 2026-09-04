"""Investigation endpoints: start one, then watch it work."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from apps.api.deps import DatasetDep, PitDep, SessionDep
from apps.api.envelope import wrap
from apps.api.routers.desk import REPORTING_LAG_DAYS
from apps.api.schemas import Envelope
from database.models import Financial, Investigation
from decisions.readiness import STALE_AFTER_DAYS
from investigations.llm import web_research_available
from investigations.runner import start_investigation
from investigations.stages import STAGES

router = APIRouter(prefix="/investigations", tags=["investigate"])


class StageOut(BaseModel):
    key: str
    label: str
    status: str
    detail: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    sources: list[dict[str, str]] | None = None
    findings: list[dict[str, Any]] | None = None
    shortlist: list[dict[str, Any]] | None = None
    company: dict[str, Any] | None = None
    numbers: dict[str, Any] | None = None
    quarters: list[dict[str, Any]] | None = None
    positives: list[str] | None = None
    negatives: list[str] | None = None
    forensic_flags: list[str] | None = None
    gaps: list[str] | None = None
    sectors_wanted: list[str] | None = None


class InvestigationOut(BaseModel):
    id: str
    status: str
    as_of: datetime
    stages: list[StageOut]
    result: dict[str, Any] | None
    company_id: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class CapabilityOut(BaseModel):
    web_research: bool
    """Whether the macro stages can read the open web."""
    how_to_enable: str
    stages: list[dict[str, Any]]
    suggested_as_of: date | None
    """The most recent date whose filings are still current, when today's are not.

    An investigation dated after the newest filings would settle on a company it cannot say
    anything current about, so the page offers this date instead.
    """
    covered_companies: int


def _out(row: Investigation) -> InvestigationOut:
    return InvestigationOut(
        id=row.id,
        status=row.status.value,
        as_of=row.as_of,
        stages=[StageOut.model_validate(s) for s in row.stages],
        result=row.result,
        company_id=row.company_id,
        error=row.error,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


@router.get("/capabilities", response_model=Envelope[CapabilityOut])
def capabilities(pit: PitDep, session: SessionDep) -> Envelope[CapabilityOut]:
    """What an investigation will and will not be able to do as configured right now."""
    latest_period = session.scalar(
        select(func.max(Financial.period_end)).where(
            Financial.is_mock == pit.is_mock, Financial.public_at <= pit.as_of
        )
    )
    suggested = None
    if latest_period is not None and (pit.as_of_date - latest_period).days > STALE_AFTER_DAYS:
        suggested = min(latest_period + timedelta(days=REPORTING_LAG_DAYS), pit.as_of_date)
    covered = session.scalar(
        select(func.count(func.distinct(Financial.company_id))).where(
            Financial.is_mock == pit.is_mock, Financial.public_at <= pit.as_of
        )
    )
    return wrap(
        pit,
        CapabilityOut(
            suggested_as_of=suggested,
            covered_companies=int(covered or 0),
            web_research=web_research_available(),
            how_to_enable=(
                "Set ANTHROPIC_API_KEY and SIGNALALPHA_LLM_PROVIDER=anthropic on the API "
                "and worker to let the first three steps read the open web."
            ),
            stages=[
                {"key": s.key, "running": s.running, "done": s.done, "needs_web": s.needs_web}
                for s in STAGES
            ],
        ),
    )


@router.post("", response_model=Envelope[InvestigationOut], status_code=202)
def create(
    request: Request, pit: PitDep, session: SessionDep, dataset: DatasetDep
) -> Envelope[InvestigationOut]:
    row = start_investigation(session, as_of=pit.as_of, is_mock=dataset.value == "mock")
    session.commit()
    request.app.state.dispatcher.enqueue_investigation(row.id)
    return wrap(pit, _out(row))


@router.get("", response_model=Envelope[list[InvestigationOut]])
def recent(pit: PitDep, session: SessionDep) -> Envelope[list[InvestigationOut]]:
    rows = session.scalars(
        select(Investigation)
        .where(Investigation.is_mock == pit.is_mock)
        .order_by(Investigation.created_at.desc())
        .limit(10)
    ).all()
    return wrap(pit, [_out(r) for r in rows])


@router.get("/{investigation_id}", response_model=Envelope[InvestigationOut])
def get_one(investigation_id: str, pit: PitDep, session: SessionDep) -> Envelope[InvestigationOut]:
    row = session.get(Investigation, investigation_id)
    if row is None or row.is_mock != pit.is_mock:
        raise HTTPException(status_code=404, detail="investigation not found")
    session.refresh(row)
    return wrap(pit, _out(row))
