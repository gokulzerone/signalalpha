"""Discovery endpoints (PRD §10)."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from apps.api import queries as q
from apps.api.deps import PitDep
from apps.api.envelope import wrap
from apps.api.schemas import CompanyRow, Envelope, Page

router = APIRouter(prefix="/discoveries", tags=["discovery"])
FORENSIC_OR_NEGATIVE_OWNERSHIP = {"forensic"}


def parse_since(since: str) -> int:
    m = re.fullmatch(r"(\d+)d", since)
    if m is None:
        raise HTTPException(status_code=422, detail="since must look like '7d'")
    days = int(m.group(1))
    if not 1 <= days <= 365:
        raise HTTPException(status_code=422, detail="since must be between 1d and 365d")
    return days


def _rows(pit: PitDep, since_days: int) -> list[CompanyRow]:
    snapshots = {s.company_id: s for s in pit.universe()}
    scores, scores_as_of = q.score_map(pit)
    recent = q.signal_window(pit, since_days)
    failures = q.failures_map(pit)
    return [
        q.company_row(
            pit,
            c,
            snapshots.get(c.id),
            scores.get(c.id, {}),
            scores_as_of,
            recent.get(c.id, []),
            failures.get(c.id, 0),
        )
        for c in pit.companies()
        if c.id in recent
    ]


def _page(rows: list[CompanyRow], page: int, page_size: int) -> Page[CompanyRow]:
    start = (page - 1) * page_size
    return Page(
        items=rows[start : start + page_size], page=page, page_size=page_size, total=len(rows)
    )


@router.get("/inflections", response_model=Envelope[Page[CompanyRow]])
def inflections(
    pit: PitDep,
    since: str = "7d",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Envelope[Page[CompanyRow]]:
    """Companies with new positive signals in the window, ranked by Opportunity."""
    days = parse_since(since)
    recent = q.signal_window(pit, days)
    positive = {
        cid
        for cid, sigs in recent.items()
        if any(s.direction > 0 and s.family in ("financial", "business", "ownership") for s in sigs)
    }
    rows = [r for r in _rows(pit, days) if r.id in positive and r.in_universe]
    rows.sort(key=lambda r: (r.scores.opportunity is None, -(r.scores.opportunity or 0.0)))
    return wrap(pit, _page(rows, page, page_size))


@router.get("/attention-gap", response_model=Envelope[Page[CompanyRow]])
def attention_gap(
    pit: PitDep,
    min_attention_gap: float = 60.0,
    min_inflection: float = 60.0,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Envelope[Page[CompanyRow]]:
    """High Attention gap x high Inflection."""
    snapshots = {s.company_id: s for s in pit.universe()}
    scores, scores_as_of = q.score_map(pit)
    recent = q.signal_window(pit, 180)
    failures = q.failures_map(pit)
    rows: list[CompanyRow] = []
    for c in pit.companies():
        s = scores.get(c.id, {})
        ag, inf = s.get("attention_gap"), s.get("inflection")
        if ag is None or inf is None or ag < min_attention_gap or inf < min_inflection:
            continue
        rows.append(
            q.company_row(
                pit,
                c,
                snapshots.get(c.id),
                s,
                scores_as_of,
                recent.get(c.id, []),
                failures.get(c.id, 0),
            )
        )
    rows.sort(key=lambda r: -((r.scores.attention_gap or 0) * (r.scores.inflection or 0)))
    return wrap(pit, _page(rows, page, page_size))


@router.get("/red-flags", response_model=Envelope[Page[CompanyRow]])
def red_flags(
    pit: PitDep,
    since: str = "7d",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Envelope[Page[CompanyRow]]:
    """New forensic or negative ownership signals, worst Risk first."""
    days = parse_since(since)
    recent = q.signal_window(pit, days)
    flagged = {
        cid
        for cid, sigs in recent.items()
        if any(
            s.family == "forensic" or (s.family == "ownership" and s.direction < 0) for s in sigs
        )
    }
    rows = [r for r in _rows(pit, days) if r.id in flagged]
    rows.sort(key=lambda r: (r.scores.risk is None, -(r.scores.risk or 0.0)))
    return wrap(pit, _page(rows, page, page_size))
