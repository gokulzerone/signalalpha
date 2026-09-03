"""Latest validated agent outputs for a company (used by the company page sections)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api import queries as q
from apps.api.deps import PitDep
from apps.api.envelope import wrap
from apps.api.schemas import AgentOutputOut, Envelope

router = APIRouter(tags=["companies"])
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


ResearchOut = dict[str, AgentOutputOut | None]


@router.get("/companies/{company_id}/research", response_model=Envelope[ResearchOut])
def get_research(company_id: int, pit: PitDep) -> Envelope[ResearchOut]:
    if pit.company(company_id) is None:
        raise HTTPException(status_code=404, detail="company not found")
    out: dict[str, AgentOutputOut | None] = {}
    for name in AGENT_NAMES:
        run = q.latest_agent_output(pit, company_id, name)
        out[name] = q.agent_output_out(run) if run else None
    if out["thesis"] is not None and out["contradiction"] is None:
        out["thesis"] = None  # never a thesis without its contradiction (PRD §2.6)
    return wrap(pit, out, company_id=company_id)
