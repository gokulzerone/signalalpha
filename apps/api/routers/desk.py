"""The decision layer's endpoints (PRD §16: research attention, never trade instructions).

``/desk`` answers "what deserves my attention and is it decidable"; ``/brief`` assembles
everything needed to form a view in one call; ``/decisions`` records what the reader
concluded and surfaces alerts when their own break conditions fire.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from apps.api import queries as q
from apps.api.deps import DatasetDep, PitDep, SessionDep
from apps.api.envelope import wrap
from apps.api.routers.companies import _dt, get_thesis, get_valuation
from apps.api.schemas import (
    AlertOut,
    BaseRateOut,
    BreakCondition,
    BriefOut,
    DecisionIn,
    DecisionOut,
    DeskRow,
    Envelope,
    EvidenceOut,
    ReadinessOut,
    ScoreOut,
)
from database.models import (
    BacktestRun,
    Company,
    Conviction,
    Decision,
    Signal,
    SignalPerformance,
    Verdict,
)
from database.pit import PointInTimeSession
from decisions.narrate import narrate_signal
from decisions.readiness import ReadinessInputs, assess_readiness, next_review_default
from decisions.sizing import liquidity_profile

router = APIRouter(tags=["desk"])
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_HORIZON = 180


# ------------------------------------------------------------------- helpers
def _base_rates(pit: PointInTimeSession) -> dict[str, dict[int, SignalPerformance]]:
    run = pit.session.scalars(
        select(BacktestRun)
        .where(BacktestRun.is_mock == pit.is_mock, BacktestRun.as_of <= pit.as_of_date)
        .order_by(BacktestRun.as_of.desc(), BacktestRun.id.desc())
    ).first()
    if run is None:
        return {}
    out: dict[str, dict[int, SignalPerformance]] = {}
    rows = pit.session.scalars(
        select(SignalPerformance).where(
            SignalPerformance.backtest_run_id == run.id, SignalPerformance.decile == 0
        )
    ).all()
    for row in rows:
        out.setdefault(row.signal_type, {})[row.horizon_days] = row
    return out


def _decision_out(d: Decision, company: Company) -> DecisionOut:
    return DecisionOut(
        id=d.id,
        company_id=d.company_id,
        ticker=company.ticker,
        name=company.name,
        as_of=_dt(d.as_of) or datetime.now(tz=IST),
        verdict=d.verdict.value,
        conviction=d.conviction.value if d.conviction else None,
        reason=d.reason,
        review_trigger=d.review_trigger,
        review_by=_dt(d.review_by),
        created_at=d.created_at,
        snapshot=d.snapshot,
    )


def _latest_decisions(session: SessionDep, is_mock: bool) -> dict[int, Decision]:
    rows = session.scalars(
        select(Decision)
        .where(Decision.is_mock == is_mock)
        .order_by(Decision.company_id, Decision.created_at.desc())
    ).all()
    out: dict[int, Decision] = {}
    for d in rows:
        out.setdefault(d.company_id, d)
    return out


def _readiness_for(
    pit: PointInTimeSession,
    company: Company,
    signals: list[Signal],
    rates: dict[str, dict[int, SignalPerformance]],
    failures: int,
) -> tuple[ReadinessOut, list[str], date | None]:
    quarters = pit.financials_preferring_consolidated(company.id, period_months=3)
    latest_period = quarters[0].period_end if quarters else None
    driving = [(s.signal_type, len(s.evidence_ids)) for s in signals]
    flags = sorted({s.signal_type for s in signals if s.family == "forensic"})
    snap = next((s for s in pit.universe() if s.company_id == company.id), None)
    rate_summary = {
        stype: (perf[DEFAULT_HORIZON].n, perf[DEFAULT_HORIZON].low_sample)
        for stype, perf in rates.items()
        if DEFAULT_HORIZON in perf
    }
    readiness = assess_readiness(
        ReadinessInputs(
            as_of=pit.as_of_date,
            latest_period_end=latest_period,
            latest_results_public_at=quarters[0].public_at if quarters else None,
            quarter_count=len(quarters),
            driving_signals=driving,
            has_contradiction=q.latest_agent_output(pit, company.id, "contradiction") is not None,
            forensic_flag_types=flags,
            is_illiquid=bool(snap.is_illiquid) if snap else True,
            median_traded_value=float(snap.median_traded_value_30d)
            if snap and snap.median_traded_value_30d
            else None,
            base_rates=rate_summary,
            data_quality_failures=failures,
        )
    )
    return ReadinessOut.model_validate(readiness.to_json()), flags, latest_period


# ---------------------------------------------------------------------- desk
@router.get("/desk", response_model=Envelope[list[DeskRow]])
def desk(
    pit: PitDep,
    session: SessionDep,
    since_days: Annotated[
        int, Query(ge=1, le=365, description="how far back a change counts as new")
    ] = 30,
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
    include_decided: bool = False,
) -> Envelope[list[DeskRow]]:
    """A short queue of companies that changed, each with whether it can be decided on yet."""
    recent = q.signal_window(pit, since_days)
    scores, scores_as_of = q.score_map(pit)
    failures = q.failures_map(pit)
    rates = _base_rates(pit)
    decisions = _latest_decisions(session, pit.is_mock)
    snapshots = {s.company_id: s for s in pit.universe()}
    rows: list[DeskRow] = []
    for company in pit.companies():
        signals = recent.get(company.id, [])
        if not signals:
            continue
        decision = decisions.get(company.id)
        if decision is not None and not include_decided and decision.verdict is Verdict.PASS:
            continue
        strongest = max(signals, key=lambda s: (s.direction > 0, float(s.magnitude)))
        others = [s for s in signals if s.id != strongest.id]
        positives = sorted(
            (s for s in others if s.direction > 0), key=lambda s: -float(s.magnitude)
        )
        negatives = sorted(
            (s for s in signals if s.direction < 0), key=lambda s: -float(s.magnitude)
        )
        readiness, _flags, _period = _readiness_for(
            pit, company, signals, rates, failures.get(company.id, 0)
        )
        perf = rates.get(strongest.signal_type, {}).get(DEFAULT_HORIZON)
        snap = snapshots.get(company.id)
        rows.append(
            DeskRow(
                company_id=company.id,
                ticker=company.ticker,
                name=company.name,
                sector=company.sector,
                market_cap_cr=float(snap.market_cap_cr) if snap and snap.market_cap_cr else None,
                change=narrate_signal(strongest.signal_type, strongest.parameters),
                change_at=strongest.public_at,
                for_case=narrate_signal(positives[0].signal_type, positives[0].parameters)
                if positives
                else "No positive signal in this window.",
                against_case=narrate_signal(negatives[0].signal_type, negatives[0].parameters)
                if negatives
                else "No negative signal in this window.",
                readiness=readiness,
                scores=q.brief(scores.get(company.id, {}), scores_as_of),
                base_rate=(
                    {
                        "signal_type": strongest.signal_type,
                        "n": perf.n,
                        "low_sample": perf.low_sample,
                        **perf.stats,
                    }
                    if perf
                    else None
                ),
                signal_types=sorted({s.signal_type for s in signals}),
                decision=_decision_out(decision, company) if decision else None,
            )
        )
    order = {"ready": 0, "partial": 1, "not_ready": 2}
    rows.sort(key=lambda r: (order[r.readiness.status], -(r.scores.opportunity or 0)))
    return wrap(pit, rows[:limit])


# --------------------------------------------------------------------- brief
@router.get("/companies/{company_id}/brief", response_model=Envelope[BriefOut])
def brief(
    company_id: int,
    pit: PitDep,
    session: SessionDep,
    since_days: Annotated[int, Query(ge=1, le=730)] = 180,
) -> Envelope[BriefOut]:
    """Everything needed to form a view on one company, in the order a person decides."""
    company = pit.company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    from apps.api.routers.companies import get_company

    profile = get_company(company_id, pit).data
    signals = list(pit.signals(company_id, since=pit.as_of_date - timedelta(days=since_days)))
    rates = _base_rates(pit)
    failures = q.failures_map(pit).get(company_id, 0)
    readiness, flags, latest_period = _readiness_for(pit, company, signals, rates, failures)

    # A signal derived from a filing table carries no quoted span, so point at the filing it
    # was computed from: every sentence on the brief has to be checkable against a document.
    financial_docs = {f.id: f.raw_document_id for f in pit.financials(company_id)}
    narrated: list[dict[str, Any]] = []
    for s in signals:
        doc_ids: list[int] = []
        if not s.evidence_ids:
            for rec in s.source_records:
                if not isinstance(rec, dict) or rec.get("table") != "financials":
                    continue
                doc = financial_docs.get(int(rec.get("id") or 0))
                if doc is not None and doc not in doc_ids:
                    doc_ids.append(doc)
        narrated.append(
            {
                "signal_id": s.id,
                "signal_type": s.signal_type,
                "family": s.family,
                "direction": s.direction,
                "magnitude": float(s.magnitude),
                "public_at": s.public_at.isoformat(),
                "sentence": narrate_signal(s.signal_type, s.parameters),
                "evidence_ids": s.evidence_ids,
                "document_ids": doc_ids,
            }
        )
    strongest = max(signals, key=lambda s: (s.direction > 0, float(s.magnitude)), default=None)

    base_rows = [
        BaseRateOut(
            signal_type=stype,
            horizon_days=h,
            n=perf.n,
            low_sample=perf.low_sample,
            hit_rate=perf.stats.get("hit_rate"),
            mean_excess=perf.stats.get("mean_excess"),
            median_excess=perf.stats.get("median_excess"),
            ci_low=perf.stats.get("ci_low"),
            ci_high=perf.stats.get("ci_high"),
        )
        for stype in sorted({s.signal_type for s in signals})
        for h, perf in sorted(rates.get(stype, {}).items())
    ]

    prices = pit.prices(company_id, pit.as_of_date - timedelta(days=120))
    snap = next((s for s in pit.universe() if s.company_id == company_id), None)
    liq = liquidity_profile(
        [float(p.traded_value) for p in prices], illiquid=bool(snap.is_illiquid) if snap else True
    )

    try:
        valuation = get_valuation(company_id, pit).data
    except HTTPException:
        valuation = None
    thesis = get_thesis(company_id, pit).data

    forensic_run = q.latest_agent_output(pit, company_id, "forensic")
    raw_flags = (forensic_run.output or {}).get("flags", []) if forensic_run else []
    forensic_flags: list[dict[str, Any]] = (
        [f for f in raw_flags if isinstance(f, dict)] if isinstance(raw_flags, list) else []
    )

    breaks: list[BreakCondition] = []
    contradiction = thesis.contradiction.output if thesis.contradiction else None
    disputed = (contradiction or {}).get("disputed_claims", [])
    for item in disputed if isinstance(disputed, list) else []:
        if not isinstance(item, dict):
            continue
        breaks.append(
            BreakCondition(
                text=str(item.get("resolving_evidence") or item.get("dispute")),
                source="contradiction",
            )
        )
    thesis_out = thesis.thesis.output if thesis.thesis else None
    if thesis_out and thesis_out.get("what_would_break_this"):
        breaks.append(
            BreakCondition(text=str(thesis_out["what_would_break_this"]), source="thesis")
        )
    for s in signals:
        if s.direction > 0 and s.signal_type in (
            "margin_inflection",
            "revenue_acceleration",
            "operating_leverage",
        ):
            breaks.append(
                BreakCondition(
                    text=f"The next quarter reverses {s.signal_type.replace('_', ' ')}.",
                    source="signal",
                )
            )
            break
    for flag in flags:
        breaks.append(
            BreakCondition(
                text=f"The {flag.replace('_', ' ')} flag is not explained in the next annual report.",
                source="forensic",
            )
        )

    rows = session.scalars(
        select(Decision)
        .where(Decision.company_id == company_id, Decision.is_mock == pit.is_mock)
        .order_by(Decision.created_at.desc())
    ).all()

    data = BriefOut(
        company=profile,
        change=narrate_signal(strongest.signal_type, strongest.parameters)
        if strongest
        else "No signals in this window.",
        change_at=strongest.public_at if strongest else None,
        narrated_signals=narrated,
        readiness=readiness,
        scores=[
            ScoreOut(
                score_type=s.score_type,
                value=None if s.value is None else float(s.value),
                as_of=_dt(s.as_of) or pit.as_of,
                config_version=s.config_version,
                components=s.components,
                signal_ids=s.signal_ids,
            )
            for s in pit.scores(company_id)
        ],
        base_rates=base_rows,
        liquidity=liq.to_json(),
        valuation=valuation,
        thesis=thesis,
        forensic_flags=forensic_flags,
        break_conditions=breaks,
        evidence=[
            EvidenceOut(
                id=e.id,
                raw_document_id=e.raw_document_id,
                document_text_id=e.document_text_id,
                company_id=e.company_id,
                filing_id=e.filing_id,
                source=e.source.value,
                url=e.url,
                public_at=e.public_at,
                extracted_text=e.extracted_text,
                char_start=e.char_start,
                char_end=e.char_end,
                page_number=e.page_number,
                extraction_method=e.extraction_method.value,
                confidence=e.confidence,
                created_by=e.created_by,
                document_url=f"/api/v1/companies/{company_id}/documents/{e.raw_document_id}?highlight={e.id}",
            )
            for e in pit.evidence(company_id)
        ],
        decisions=[_decision_out(d, company) for d in rows],
        suggested_review_by=_dt(next_review_default(pit.as_of_date, latest_period)) or pit.as_of,
    )
    return wrap(pit, data, company_id=company_id)


# ----------------------------------------------------------------- decisions
@router.post(
    "/companies/{company_id}/decisions", response_model=Envelope[DecisionOut], status_code=201
)
def record_decision(
    company_id: int, payload: DecisionIn, pit: PitDep, session: SessionDep, dataset: DatasetDep
) -> Envelope[DecisionOut]:
    """Record what the reader concluded, with the evidence state at that moment."""
    company = pit.company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    signals = list(pit.signals(company_id, since=pit.as_of_date - timedelta(days=180)))
    rates = _base_rates(pit)
    readiness, flags, latest_period = _readiness_for(
        pit, company, signals, rates, q.failures_map(pit).get(company_id, 0)
    )
    scores = {
        s.score_type: (None if s.value is None else float(s.value)) for s in pit.scores(company_id)
    }
    snapshot: dict[str, Any] = {
        "scores": scores,
        "signal_ids": [s.id for s in signals],
        "signal_types": sorted({s.signal_type for s in signals}),
        "readiness": readiness.model_dump(),
        "forensic_flags": flags,
        "latest_period_end": latest_period.isoformat() if latest_period else None,
    }
    row = Decision(
        company_id=company_id,
        as_of=payload.as_of or pit.as_of_date,
        verdict=Verdict(payload.verdict),
        conviction=Conviction(payload.conviction) if payload.conviction else None,
        reason=payload.reason,
        review_trigger=payload.review_trigger,
        review_by=payload.review_by or next_review_default(pit.as_of_date, latest_period),
        snapshot=snapshot,
        is_mock=dataset.value == "mock",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return wrap(pit, _decision_out(row, company), company_id=company_id)


@router.get("/decisions", response_model=Envelope[list[DecisionOut]])
def list_decisions(
    pit: PitDep, session: SessionDep, verdict: str | None = None
) -> Envelope[list[DecisionOut]]:
    stmt = (
        select(Decision).where(Decision.is_mock == pit.is_mock).order_by(Decision.created_at.desc())
    )
    if verdict:
        stmt = stmt.where(Decision.verdict == Verdict(verdict))
    rows = session.scalars(stmt).all()
    companies = {c.id: c for c in pit.companies()}
    return wrap(
        pit, [_decision_out(d, companies[d.company_id]) for d in rows if d.company_id in companies]
    )


@router.get("/decisions/alerts", response_model=Envelope[list[AlertOut]])
def alerts(pit: PitDep, session: SessionDep) -> Envelope[list[AlertOut]]:
    """Break conditions that have fired: new negative signals on a name you kept, and reviews due."""
    rows = session.scalars(
        select(Decision)
        .where(Decision.is_mock == pit.is_mock, Decision.verdict != Verdict.PASS)
        .order_by(Decision.created_at.desc())
    ).all()
    companies = {c.id: c for c in pit.companies()}
    out: list[AlertOut] = []
    for d in rows:
        company = companies.get(d.company_id)
        if company is None:
            continue
        for s in pit.signals(d.company_id, since=d.as_of):
            if s.direction < 0:
                out.append(
                    AlertOut(
                        decision=_decision_out(d, company),
                        kind="negative_signal",
                        text=narrate_signal(s.signal_type, s.parameters),
                        at=s.public_at,
                    )
                )
        if d.review_by and d.review_by <= pit.as_of_date:
            out.append(
                AlertOut(
                    decision=_decision_out(d, company),
                    kind="review_due",
                    text=f"Review was set for {d.review_by.isoformat()}."
                    + (f" Trigger: {d.review_trigger}" if d.review_trigger else ""),
                    at=_dt(d.review_by) or pit.as_of,
                )
            )
    out.sort(key=lambda a: a.at, reverse=True)
    return wrap(pit, out)
