"""Running an investigation, one stage at a time, writing progress as it goes.

The row is updated after every stage so the page can watch it happen. Each stage records what
it did and what it read: a web stage carries its pages, a company stage carries the filings
and the figures Python computed from them.
"""

from __future__ import annotations

import statistics
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api import queries as q
from database.models import Company, Investigation, InvestigationStatus, Signal
from database.pit import PointInTimeSession
from decisions.narrate import narrate_signal
from decisions.readiness import ReadinessInputs, assess_readiness
from decisions.sizing import liquidity_profile
from decisions.verdict import build_verdict
from investigations.macro import MacroResult, WebResearchUnavailableError
from investigations.stages import STAGES
from scoring.ratios import ratios_for
from signals.context import HistoryLoader

#: How far back a disclosure still counts as part of the current picture.
SIGNAL_WINDOW_DAYS = 200


def start_investigation(session: Session, *, as_of: datetime, is_mock: bool) -> Investigation:
    row = Investigation(
        id=str(uuid.uuid4()),
        status=InvestigationStatus.QUEUED,
        as_of=as_of,
        stages=[{"key": s.key, "label": s.running, "status": "pending"} for s in STAGES],
        is_mock=is_mock,
    )
    session.add(row)
    session.flush()
    return row


class _Progress:
    """Writes each stage's state to the row as it happens, so the page can follow along."""

    def __init__(self, session: Session, row: Investigation) -> None:
        self.session = session
        self.row = row

    def _write(self, key: str, **fields: Any) -> None:
        stages = [dict(s) for s in self.row.stages]
        for stage in stages:
            if stage["key"] == key:
                stage.update(fields)
        self.row.stages = stages
        self.session.flush()
        self.session.commit()

    def running(self, key: str, label: str) -> None:
        self._write(key, status="running", label=label, started_at=datetime.now(tz=UTC).isoformat())

    def done(self, key: str, label: str, detail: str, **extra: Any) -> None:
        self._write(
            key,
            status="done",
            label=label,
            detail=detail,
            finished_at=datetime.now(tz=UTC).isoformat(),
            **extra,
        )

    def skipped(self, key: str, label: str, reason: str) -> None:
        self._write(
            key,
            status="skipped",
            label=label,
            detail=reason,
            finished_at=datetime.now(tz=UTC).isoformat(),
        )


def _sector_matches(sector: str, wanted: list[str]) -> bool:
    """Loose match: the web names industries in its own words, our universe in its own."""
    s = sector.lower()
    return any(w.lower().rstrip("s") in s or s.rstrip("s") in w.lower() for w in wanted if w)


def run_investigation(session: Session, investigation_id: str) -> Investigation:
    row = session.get(Investigation, investigation_id)
    if row is None:
        raise LookupError(f"investigation {investigation_id} not found")
    row.status = InvestigationStatus.RUNNING
    session.flush()
    session.commit()
    progress = _Progress(session, row)
    pit = PointInTimeSession(session, row.as_of, is_mock=row.is_mock)

    try:
        macro = _macro_stages(progress)
        candidates = _india_stage(progress, pit, macro)
        if not candidates:
            row.status = InvestigationStatus.FAILED
            row.error = (
                "No covered company matched. Ingest more companies with scripts/sync_live.py."
            )
            row.finished_at = datetime.now(tz=UTC)
            session.flush()
            session.commit()
            return row
        company, why_this_one = _company_stage(progress, pit, candidates, macro)
        value = _value_stage(progress, pit, company)
        fundamentals = _fundamentals_stage(progress, pit, company)
        threats = _threats_stage(progress, pit, company)
        result = _case_stage(
            progress, pit, company, macro, why_this_one, value, fundamentals, threats
        )
        row.company_id = company.id
        row.result = result
        row.status = InvestigationStatus.COMPLETED
    except Exception as exc:  # the run records its own failure rather than vanishing
        row.status = InvestigationStatus.FAILED
        row.error = f"{exc}\n{traceback.format_exc()}"
    row.finished_at = datetime.now(tz=UTC)
    session.flush()
    session.commit()
    return row


# ------------------------------------------------------------------ the world
def _macro_stages(progress: _Progress) -> dict[str, MacroResult | None]:
    from investigations.llm import read_the_web

    out: dict[str, MacroResult | None] = {}
    context = ""
    for stage in STAGES[:3]:
        progress.running(stage.key, stage.running)
        try:
            result = read_the_web(stage.key, context)
        except WebResearchUnavailableError as exc:
            progress.skipped(stage.key, stage.done, str(exc))
            out[stage.key] = None
            continue
        except Exception as exc:  # a failed search must not sink the run
            progress.skipped(stage.key, stage.done, f"The web search did not complete: {exc}")
            out[stage.key] = None
            continue
        out[stage.key] = result
        context = f"{context}\n\n{result.text}".strip()[:6000]
        progress.done(
            stage.key,
            stage.done,
            result.reading.summary if result.reading else result.text[:600],
            sources=[s.to_json() for s in result.sources],
            findings=[f.model_dump() for f in (result.reading.findings if result.reading else [])],
        )
    return out


# ------------------------------------------------------------------ to India
def _india_stage(
    progress: _Progress, pit: PointInTimeSession, macro: dict[str, MacroResult | None]
) -> list[Company]:
    stage = STAGES[3]
    progress.running(stage.key, stage.running)
    wanted: list[str] = []
    for result in macro.values():
        if result:
            wanted.extend(result.sectors())

    covered = {
        cid
        for (cid,) in pit.session.execute(
            select(Signal.company_id)
            .where(Signal.is_mock == pit.is_mock, Signal.public_at <= pit.as_of)
            .group_by(Signal.company_id)
        ).all()
    }
    scores, _ = q.score_map(pit)
    universe = [c for c in pit.companies() if c.id in covered and c.id in scores]
    matched = [c for c in universe if wanted and _sector_matches(c.sector, wanted)]
    used_sectors = bool(matched)
    candidates = matched or universe
    candidates.sort(key=lambda c: -(scores.get(c.id, {}).get("opportunity") or 0))
    top = candidates[:8]

    if used_sectors:
        detail = f"{len(matched)} of {len(universe)} covered companies sit in {', '.join(sorted({c.sector for c in matched}))}."
    elif wanted:
        detail = f"No covered company sits in {', '.join(wanted[:4])}, so every covered company was considered instead."
    else:
        detail = f"Without a web reading to narrow by sector, all {len(universe)} covered companies were considered."
    progress.done(
        stage.key,
        stage.done,
        detail,
        sectors_wanted=wanted[:8],
        shortlist=[
            {
                "company_id": c.id,
                "ticker": c.ticker,
                "name": c.name,
                "sector": c.sector,
                "opportunity": scores.get(c.id, {}).get("opportunity"),
            }
            for c in top
        ],
    )
    return top


def _company_stage(
    progress: _Progress,
    pit: PointInTimeSession,
    candidates: list[Company],
    macro: dict[str, MacroResult | None],
) -> tuple[Company, str]:
    stage = STAGES[4]
    progress.running(stage.key, stage.running)
    company = candidates[0]
    scores, _ = q.score_map(pit)
    opportunity = scores.get(company.id, {}).get("opportunity")
    linked = any(m and _sector_matches(company.sector, m.sectors()) for m in macro.values() if m)
    why = (
        f"{company.name} ranks highest on opportunity among the covered companies that sit in the sectors the "
        f"macro reading pointed to."
        if linked
        else f"{company.name} ranks highest on opportunity among the companies covered here."
    )
    progress.done(
        stage.key,
        stage.done,
        why,
        company={
            "company_id": company.id,
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "opportunity": opportunity,
        },
    )
    return company, why


# --------------------------------------------------------------- the company
def _value_stage(progress: _Progress, pit: PointInTimeSession, company: Company) -> dict[str, Any]:
    stage = STAGES[5]
    progress.running(stage.key, stage.running)
    snap = next((s for s in pit.universe() if s.company_id == company.id), None)
    prices = pit.prices(company.id, pit.as_of_date - timedelta(days=30))
    ctx = HistoryLoader(pit, company).at(pit.as_of)
    ttm_pat = None
    quarters = ctx.quarters[-4:]
    if len(quarters) == 4 and all(x.pat is not None for x in quarters):
        ttm_pat = float(sum(x.pat for x in quarters if x.pat is not None))
    mcap = float(snap.market_cap_cr) if snap and snap.market_cap_cr else None
    pe = mcap / ttm_pat if mcap and ttm_pat and ttm_pat > 0 else None
    scores = {
        s.score_type: (None if s.value is None else float(s.value)) for s in pit.scores(company.id)
    }
    numbers = {
        "price": float(prices[-1].close) if prices else None,
        "price_date": prices[-1].trade_date.isoformat() if prices else None,
        "market_cap_cr": mcap,
        "trailing_pe": round(pe, 1) if pe else None,
        "ttm_profit_cr": round(ttm_pat, 2) if ttm_pat else None,
        "valuation_score": scores.get("valuation"),
    }
    parts = []
    if mcap:
        parts.append(f"The market values it at Rs {mcap:,.0f} crore")
    if pe:
        parts.append(f"about {pe:.1f} times its trailing twelve-month profit")
    if scores.get("valuation") is not None:
        parts.append(
            f"which ranks it {scores['valuation']:.0f} out of 100 against its peers and its own history"
        )
    detail = ", ".join(parts) + "." if parts else "Not enough on file to value it."
    progress.done(stage.key, stage.done, detail, numbers=numbers)
    return numbers


def _fundamentals_stage(
    progress: _Progress, pit: PointInTimeSession, company: Company
) -> dict[str, Any]:
    stage = STAGES[6]
    progress.running(stage.key, stage.running)
    ctx = HistoryLoader(pit, company).at(pit.as_of)
    all_periods = ctx.quarters + ctx.halves + ctx.annuals
    rows = []
    for period in ctx.quarters[-6:]:
        r = ratios_for(period, all_periods)
        rows.append(
            {
                "period_end": period.period_end.isoformat(),
                "revenue_cr": float(period.revenue) if period.revenue is not None else None,
                "ebitda_cr": float(period.ebitda) if period.ebitda is not None else None,
                "ebitda_margin": r.get("ebitda_margin"),
                "revenue_yoy": r.get("revenue_yoy"),
                "document_id": period.raw_document_id,
            }
        )
    signals = [
        s
        for s in pit.signals(company.id, since=pit.as_of_date - timedelta(days=SIGNAL_WINDOW_DAYS))
    ]
    positives = [narrate_signal(s.signal_type, s.parameters) for s in signals if s.direction > 0][
        :4
    ]
    margins = [r["ebitda_margin"] for r in rows if r["ebitda_margin"] is not None]
    trend = None
    if len(margins) >= 4:
        trend = "widening" if margins[-1] > statistics.fmean(margins[:-1]) else "narrowing"
    detail = positives[0] if positives else "No fundamental change was detected in this window."
    progress.done(
        stage.key,
        stage.done,
        detail,
        quarters=rows,
        positives=positives,
        margin_trend=trend,
        quarters_on_file=len(ctx.quarters),
    )
    return {"quarters": rows, "positives": positives, "margin_trend": trend}


def _threats_stage(
    progress: _Progress, pit: PointInTimeSession, company: Company
) -> dict[str, Any]:
    stage = STAGES[7]
    progress.running(stage.key, stage.running)
    signals = list(
        pit.signals(company.id, since=pit.as_of_date - timedelta(days=SIGNAL_WINDOW_DAYS))
    )
    negatives = [narrate_signal(s.signal_type, s.parameters) for s in signals if s.direction < 0]
    flags = sorted({s.signal_type for s in signals if s.family == "forensic"})
    snap = next((s for s in pit.universe() if s.company_id == company.id), None)
    prices = pit.prices(company.id, pit.as_of_date - timedelta(days=120))
    liq = liquidity_profile(
        [float(p.traded_value) for p in prices], illiquid=bool(snap.is_illiquid) if snap else True
    )
    quarters = pit.financials_preferring_consolidated(company.id, period_months=3)
    readiness = assess_readiness(
        ReadinessInputs(
            as_of=pit.as_of_date,
            latest_period_end=quarters[0].period_end if quarters else None,
            latest_results_public_at=quarters[0].public_at if quarters else None,
            quarter_count=len(quarters),
            driving_signals=[(s.signal_type, len(s.evidence_ids)) for s in signals],
            has_contradiction=q.latest_agent_output(pit, company.id, "contradiction") is not None,
            forensic_flag_types=flags,
            is_illiquid=bool(snap.is_illiquid) if snap else True,
            median_traded_value=float(snap.median_traded_value_30d)
            if snap and snap.median_traded_value_30d
            else None,
            base_rates={},
            data_quality_failures=q.failures_map(pit).get(company.id, 0),
        )
    )
    gaps = [c.to_resolve for c in readiness.checks if not c.passed and c.to_resolve]
    days = liq.days_to_exit.get("10L")
    detail = (
        negatives[0]
        if negatives
        else (
            f"No signal points the other way. The practical constraint is liquidity: leaving a ten lakh position takes about {days:.0f} trading days."
            if days and days >= 2
            else "No signal points the other way, and it trades freely enough to leave."
        )
    )
    payload = {
        "negatives": negatives,
        "forensic_flags": flags,
        "gaps": gaps,
        "days_to_exit_10L": days,
        "illiquid": liq.illiquid,
        "round_trip_cost_pct": liq.round_trip_cost_pct,
        "readiness": readiness.to_json(),
    }
    progress.done(stage.key, stage.done, detail, **payload)
    return payload


def _case_stage(
    progress: _Progress,
    pit: PointInTimeSession,
    company: Company,
    macro: dict[str, MacroResult | None],
    why_this_one: str,
    value: dict[str, Any],
    fundamentals: dict[str, Any],
    threats: dict[str, Any],
) -> dict[str, Any]:
    stage = STAGES[8]
    progress.running(stage.key, stage.running)
    scores = {
        s.score_type: (None if s.value is None else float(s.value)) for s in pit.scores(company.id)
    }
    verdict = build_verdict(
        {k: scores.get(k) for k in ("inflection", "quality", "valuation", "attention_gap", "risk")},
        change_sentence=(fundamentals["positives"] or [None])[0],
        readiness_gaps=threats["gaps"],
        liquidity_days_to_exit=threats["days_to_exit_10L"],
        base_rate_known=False,
        negative_count=len(threats["negatives"]),
        forensic_flags=threats["forensic_flags"],
    )
    macro_line = None
    for key in ("supply_demand", "impact", "world"):
        result = macro.get(key)
        if result and result.reading:
            macro_line = result.reading.summary
            break
    result_payload = {
        "company": {
            "company_id": company.id,
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
        },
        "why_this_one": why_this_one,
        "macro_line": macro_line,
        "verdict": verdict.to_json(),
        "value": value,
        "fundamentals": fundamentals,
        "threats": threats,
        "scores": scores,
        "web_grounded": any(m is not None for m in macro.values()),
    }
    progress.done(stage.key, stage.done, verdict.headline, verdict=verdict.to_json())
    return result_payload
