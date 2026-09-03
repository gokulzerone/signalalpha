"""Company endpoints (PRD §10)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from apps.api import queries as q
from apps.api.deps import PitDep
from apps.api.envelope import wrap
from apps.api.routers.documents import router as documents_router
from apps.api.schemas import (
    CompanyProfile,
    CompanyRow,
    Envelope,
    EventOut,
    EvidenceOut,
    FinancialRow,
    OwnershipOut,
    Page,
    PriceRow,
    ScoreOut,
    ShareholdingOut,
    SignalOut,
    ThesisOut,
    ValuationOut,
)
from backtesting.prices import load_series
from database.models import Company, SignalPerformance
from database.pit import PointInTimeSession
from scoring.config import load_score_config
from scoring.valuation import (
    SPEC,
    ScenarioAssumptions,
    ScenarioInputs,
    compute_scenario,
    default_assumptions,
    scenario_json,
)
from signals.context import HistoryLoader, Period

router = APIRouter(tags=["companies"])
router.include_router(documents_router)

SORTABLE = {
    "opportunity",
    "inflection",
    "quality",
    "valuation",
    "risk",
    "attention_gap",
    "market_cap_cr",
    "name",
    "ticker",
}


def _company_or_404(pit: PointInTimeSession, company_id: int) -> Company:
    company = pit.company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    return company


@router.get("/companies", response_model=Envelope[Page[CompanyRow]])
def list_companies(
    pit: PitDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sector: str | None = None,
    market_cap_min: float | None = None,
    market_cap_max: float | None = None,
    exclude_illiquid: bool = False,
    in_universe_only: bool = False,
    surveillance: Annotated[
        bool | None,
        Query(
            description="true = only names under GSM/ASM; false = only names not under surveillance"
        ),
    ] = None,
    opportunity_min: float | None = None,
    opportunity_max: float | None = None,
    risk_min: float | None = None,
    risk_max: float | None = None,
    attention_gap_min: float | None = None,
    attention_gap_max: float | None = None,
    inflection_min: float | None = None,
    signal_type: str | None = None,
    since_days: Annotated[int, Query(ge=1, le=365)] = 7,
    sort: str = "-opportunity",
) -> Envelope[Page[CompanyRow]]:
    snapshots = {s.company_id: s for s in pit.universe()}
    scores, scores_as_of = q.score_map(pit)
    recent = q.signal_window(pit, since_days)
    failures = q.failures_map(pit)
    rows: list[CompanyRow] = []
    for company in pit.companies():
        snap = snapshots.get(company.id)
        row = q.company_row(
            pit,
            company,
            snap,
            scores.get(company.id, {}),
            scores_as_of,
            recent.get(company.id, []),
            failures.get(company.id, 0),
        )
        if sector and row.sector != sector:
            continue
        if market_cap_min is not None and (
            row.market_cap_cr is None or row.market_cap_cr < market_cap_min
        ):
            continue
        if market_cap_max is not None and (
            row.market_cap_cr is None or row.market_cap_cr > market_cap_max
        ):
            continue
        if exclude_illiquid and row.is_illiquid:
            continue
        if in_universe_only and not row.in_universe:
            continue
        under = bool(row.gsm_stage or row.asm_stage)
        if surveillance is not None and under != surveillance:
            continue
        if signal_type and signal_type not in row.new_signal_types:
            continue
        s = row.scores
        if not _in_range(s.opportunity, opportunity_min, opportunity_max):
            continue
        if not _in_range(s.risk, risk_min, risk_max):
            continue
        if not _in_range(s.attention_gap, attention_gap_min, attention_gap_max):
            continue
        if not _in_range(s.inflection, inflection_min, None):
            continue
        rows.append(row)
    rows = _sort(rows, sort)
    total = len(rows)
    start = (page - 1) * page_size
    return wrap(
        pit,
        Page(items=rows[start : start + page_size], page=page, page_size=page_size, total=total),
    )


def _in_range(value: float | None, lo: float | None, hi: float | None) -> bool:
    if lo is None and hi is None:
        return True
    if value is None:
        return False
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def _sort(rows: list[CompanyRow], sort: str) -> list[CompanyRow]:
    desc = sort.startswith("-")
    key = sort.lstrip("-+")
    if key not in SORTABLE:
        raise HTTPException(status_code=422, detail=f"cannot sort by {key!r}")

    def keyfn(r: CompanyRow) -> tuple[int, float | str]:
        v: float | str | None = (
            getattr(r.scores, key, None)
            if key in {"opportunity", "inflection", "quality", "valuation", "risk", "attention_gap"}
            else getattr(r, key)
        )
        if v is None:
            return (1, 0.0)  # missing values last
        return (0, -v if desc and isinstance(v, float) else v)

    return sorted(rows, key=keyfn, reverse=desc and key in {"name", "ticker"})


@router.get("/companies/{company_id}", response_model=Envelope[CompanyProfile])
def get_company(company_id: int, pit: PitDep) -> Envelope[CompanyProfile]:
    company = _company_or_404(pit, company_id)
    snap = next((s for s in pit.universe() if s.company_id == company_id), None)
    scores, scores_as_of = q.score_map(pit)
    recent = q.signal_window(pit, 7).get(company_id, [])
    row = q.company_row(
        pit,
        company,
        snap,
        scores.get(company_id, {}),
        scores_as_of,
        recent,
        q.failures_map(pit).get(company_id, 0),
    )
    prices = pit.prices(company_id, pit.as_of_date - timedelta(days=30))
    last = prices[-1] if prices else None
    profile = CompanyProfile(
        **row.model_dump(),
        isin=company.isin,
        exchange=company.exchange.value,
        bse_code=company.bse_code,
        listed_on=_dt(company.listed_on),
        delisted_on=_dt(company.delisted_on),
        price=None if last is None else float(last.close),
        price_date=_dt(last.trade_date) if last else None,
        median_traded_value_30d=None
        if snap is None or snap.median_traded_value_30d is None
        else float(snap.median_traded_value_30d),
    )
    return wrap(pit, profile, company_id=company_id)


def _dt(d: date | None) -> datetime | None:
    return (
        None
        if d is None
        else datetime.combine(
            d, datetime.min.time(), tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Kolkata")
        )
    )


VALUE_FIELDS = (
    "revenue",
    "other_income",
    "total_expenses",
    "ebitda",
    "depreciation",
    "finance_cost",
    "pbt",
    "tax",
    "pat",
    "eps",
    "total_borrowings",
    "short_term_borrowings",
    "long_term_borrowings",
    "cash_and_equivalents",
    "receivables",
    "inventory",
    "payables",
    "net_worth",
    "total_assets",
    "shares_outstanding",
    "cfo",
    "cfi",
    "cff",
    "capex",
    "related_party_revenue",
    "contingent_liabilities",
)


@router.get("/companies/{company_id}/financials", response_model=Envelope[list[FinancialRow]])
def get_financials(
    company_id: int,
    pit: PitDep,
    consolidated: Annotated[
        bool | None,
        Query(description="true/false to force a basis; omit for consolidated-where-available"),
    ] = None,
    periods: Annotated[int, Query(ge=1, le=64)] = 12,
    period_months: Annotated[int | None, Query(description="3, 6 or 12; omit for all")] = None,
) -> Envelope[list[FinancialRow]]:
    company = _company_or_404(pit, company_id)
    loader = HistoryLoader(pit, company)
    ctx = loader.at(pit.as_of)
    from signals.context import period_from_row

    if consolidated is None:
        rows: list[Period] = [*ctx.quarters, *ctx.halves, *ctx.annuals]
    else:
        rows = [period_from_row(r) for r in pit.financials(company_id, consolidated=consolidated)]
    if period_months is not None:
        rows = [r for r in rows if r.months == period_months]
    rows.sort(key=lambda r: (r.period_end, r.months), reverse=True)
    rows = rows[:periods]
    by_id = {r.id: r for r in pit.financials(company_id)}
    out: list[FinancialRow] = []
    for p in rows:
        orm = by_id.get(p.id)
        if orm is None:
            continue
        out.append(
            FinancialRow(
                id=orm.id,
                filing_id=orm.filing_id,
                raw_document_id=orm.raw_document_id,
                period_end=_dt(orm.period_end) or pit.as_of,
                period_months=orm.period_months,
                consolidated=orm.consolidated,
                public_at=orm.public_at,
                extraction_method=orm.extraction_method.value,
                confidence=orm.confidence,
                values={name: getattr(orm, name) for name in VALUE_FIELDS},
                ratios=q.ratios_for(p, ctx.quarters + ctx.halves + ctx.annuals),
                audit_opinion=orm.audit_opinion.value if orm.audit_opinion else None,
            )
        )
    return wrap(pit, out, company_id=company_id)


@router.get("/companies/{company_id}/ownership", response_model=Envelope[OwnershipOut])
def get_ownership(company_id: int, pit: PitDep) -> Envelope[OwnershipOut]:
    _company_or_404(pit, company_id)
    holdings = [
        ShareholdingOut(
            id=h.id,
            filing_id=h.filing_id,
            period_end=_dt(h.period_end) or pit.as_of,
            public_at=h.public_at,
            promoter_pct=h.promoter_pct,
            promoter_pledged_pct=h.promoter_pledged_pct,
            fii_pct=h.fii_pct,
            dii_pct=h.dii_pct,
            public_pct=h.public_pct,
            total_shareholders=h.total_shareholders,
            retail_shareholders=h.retail_shareholders,
            holders=[
                {"name": i.holder_name, "category": i.category.value, "pct": i.pct}
                for i in h.institutional_holders
            ],
        )
        for h in pit.shareholdings(company_id)
    ]
    pledges = [
        EventOut(
            id=e.id,
            table="pledge_events",
            public_at=e.public_at,
            raw_document_id=e.raw_document_id,
            fields={
                "event_type": e.event_type.value,
                "holder": e.holder_name,
                "shares": e.shares,
                "pct_of_promoter_holding": float(e.pct_of_promoter_holding),
                "pct_of_total_shares": float(e.pct_of_total_shares),
                "event_date": e.event_date.isoformat(),
            },
        )
        for e in pit.pledge_events(company_id)
    ]
    insiders = [
        EventOut(
            id=t.id,
            table="insider_trades",
            public_at=t.public_at,
            raw_document_id=t.raw_document_id,
            fields={
                "person": t.person_name,
                "category": t.person_category.value,
                "side": t.side.value,
                "mode": t.mode.value,
                "quantity": t.quantity,
                "value_inr": float(t.value_inr),
                "trade_date": t.trade_date.isoformat(),
            },
        )
        for t in pit.insider_trades(company_id)
    ]
    bulk = [
        EventOut(
            id=b.id,
            table="bulk_deals",
            public_at=b.public_at,
            raw_document_id=b.raw_document_id,
            fields={
                "client": b.client_name,
                "side": b.side.value,
                "deal_type": b.deal_type.value,
                "quantity": b.quantity,
                "price": float(b.price),
                "value_inr": float(b.value_inr),
                "trade_date": b.trade_date.isoformat(),
            },
        )
        for b in pit.bulk_deals(company_id)
    ]
    return wrap(
        pit,
        OwnershipOut(
            shareholdings=holdings, pledge_events=pledges, insider_trades=insiders, bulk_deals=bulk
        ),
        company_id=company_id,
    )


@router.get("/companies/{company_id}/prices", response_model=Envelope[list[PriceRow]])
def get_prices(
    company_id: int,
    pit: PitDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> Envelope[list[PriceRow]]:
    company = _company_or_404(pit, company_id)
    start = from_ or (pit.as_of_date - timedelta(days=365))
    end = to or pit.as_of_date
    if end > pit.as_of_date:
        raise HTTPException(status_code=422, detail="'to' is after as_of")
    series = load_series(pit, company, start)
    adjusted = series.adjusted_closes()
    raw = pit.prices(company_id, start, end)
    by_date = {d: adj for d, adj in zip(series.dates, adjusted, strict=True)}
    rows = [
        PriceRow(
            trade_date=_dt(p.trade_date) or pit.as_of,
            open=float(p.open),
            high=float(p.high),
            low=float(p.low),
            close=float(p.close),
            adjusted_close=by_date.get(p.trade_date, float(p.close)),
            volume=p.volume,
            traded_value=float(p.traded_value),
            delivery_pct=None if p.delivery_pct is None else float(p.delivery_pct),
        )
        for p in raw
    ]
    return wrap(pit, rows, company_id=company_id)


def _performance_by_type(pit: PointInTimeSession) -> dict[str, dict[str, object]]:
    from sqlalchemy import select

    from database.models import BacktestRun

    run = pit.session.scalars(
        select(BacktestRun)
        .where(BacktestRun.is_mock == pit.is_mock, BacktestRun.as_of <= pit.as_of_date)
        .order_by(BacktestRun.as_of.desc(), BacktestRun.id.desc())
    ).first()
    if run is None:
        return {}
    out: dict[str, dict[str, object]] = {}
    for row in pit.session.scalars(
        select(SignalPerformance).where(
            SignalPerformance.backtest_run_id == run.id, SignalPerformance.decile == 0
        )
    ).all():
        out.setdefault(row.signal_type, {"backtest_run_id": run.id, "horizons": {}})
        horizons = out[row.signal_type]["horizons"]
        assert isinstance(horizons, dict)
        horizons[str(row.horizon_days)] = {"n": row.n, "low_sample": row.low_sample, **row.stats}
    return out


@router.get("/companies/{company_id}/signals", response_model=Envelope[list[SignalOut]])
def get_signals(
    company_id: int,
    pit: PitDep,
    active_days: Annotated[
        int, Query(ge=1, le=730, description="signals newer than this are 'active'")
    ] = 180,
    include_performance: bool = True,
) -> Envelope[list[SignalOut]]:
    _company_or_404(pit, company_id)
    perf = _performance_by_type(pit) if include_performance else {}
    cutoff = pit.as_of - timedelta(days=active_days)
    rows = [
        SignalOut(
            id=s.id,
            signal_type=s.signal_type,
            family=s.family,
            direction=s.direction,
            magnitude=float(s.magnitude),
            public_at=s.public_at,
            dedupe_key=s.dedupe_key,
            source_records=s.source_records,
            evidence_ids=s.evidence_ids,
            parameters=s.parameters,
            detector_version=s.detector_version,
            config_version=s.config_version,
            active=s.public_at > cutoff,
            performance=perf.get(s.signal_type),
        )
        for s in pit.signals(company_id)
    ]
    return wrap(pit, rows, company_id=company_id)


@router.get("/companies/{company_id}/scores", response_model=Envelope[list[ScoreOut]])
def get_scores(company_id: int, pit: PitDep) -> Envelope[list[ScoreOut]]:
    _company_or_404(pit, company_id)
    rows = [
        ScoreOut(
            score_type=s.score_type,
            value=None if s.value is None else float(s.value),
            as_of=_dt(s.as_of) or pit.as_of,
            config_version=s.config_version,
            components=s.components,
            signal_ids=s.signal_ids,
        )
        for s in pit.scores(company_id)
    ]
    order = {
        t: i
        for i, t in enumerate(
            ("opportunity", "inflection", "quality", "valuation", "risk", "attention_gap")
        )
    }
    rows.sort(key=lambda r: order.get(r.score_type, 99))
    return wrap(pit, rows, company_id=company_id)


@router.get("/companies/{company_id}/valuation", response_model=Envelope[ValuationOut])
def get_valuation(company_id: int, pit: PitDep) -> Envelope[ValuationOut]:
    company = _company_or_404(pit, company_id)
    config = load_score_config()
    ctx = HistoryLoader(pit, company).at(pit.as_of)
    quarters = ctx.quarters
    ttm_rev = ctx.ttm_revenue()
    ttm_ebitda = ctx.ttm_ebitda()
    bps = ctx.balance_periods
    prices = pit.prices(company_id, pit.as_of_date - timedelta(days=30))
    if (
        ttm_rev is None
        or ttm_ebitda is None
        or not bps
        or not prices
        or bps[-1].total_borrowings is None
        or bps[-1].cash is None
        or not quarters[-1].shares_outstanding
    ):
        raise HTTPException(status_code=404, detail="insufficient data for valuation scenarios")
    net_debt = float(bps[-1].total_borrowings - bps[-1].cash)
    price = float(prices[-1].close)
    shares = float(quarters[-1].shares_outstanding or 0)
    trailing_growth = None
    if len(quarters) >= 8:
        prev = sum((x.revenue for x in quarters[-8:-4] if x.revenue is not None), Decimal(0))
        if prev > 0:
            trailing_growth = float((ttm_rev - prev) / prev)
    mcap = price * shares
    current_multiple = (mcap + net_debt) / float(ttm_ebitda) if ttm_ebitda > 0 else None
    inputs = ScenarioInputs(
        float(ttm_rev),
        float(ttm_ebitda),
        net_debt,
        shares,
        price,
        trailing_growth,
        current_multiple,
    )
    agent = q.latest_agent_output(pit, company_id, "valuation")
    source, agent_run_id = "default", None
    assumptions = default_assumptions(inputs, config)
    if agent and agent.output and isinstance(agent.output.get("scenarios"), list):
        try:
            assumptions = [ScenarioAssumptions.model_validate(a) for a in agent.output["scenarios"]]
            source, agent_run_id = "agent", agent.id
        except ValueError:
            pass
    scenarios = [scenario_json(compute_scenario(inputs, a)) for a in assumptions]
    return wrap(
        pit,
        ValuationOut(
            inputs={
                "ttm_revenue": inputs.ttm_revenue,
                "ttm_ebitda": inputs.ttm_ebitda,
                "net_debt": net_debt,
                "shares_outstanding_cr": shares,
                "price": price,
                "trailing_revenue_growth": trailing_growth,
                "current_ev_ebitda": current_multiple,
            },
            scenarios=scenarios,
            source=source,
            agent_run_id=agent_run_id,
            spec=SPEC,
        ),
        company_id=company_id,
    )


@router.get("/companies/{company_id}/thesis", response_model=Envelope[ThesisOut])
def get_thesis(company_id: int, pit: PitDep) -> Envelope[ThesisOut]:
    _company_or_404(pit, company_id)
    thesis = q.latest_agent_output(pit, company_id, "thesis")
    contradiction = q.latest_agent_output(pit, company_id, "contradiction")
    ids: set[int] = set()
    for run in (thesis, contradiction):
        if run and run.output:
            for claim in run.output.get("claims", []):
                ids.update(int(e) for e in claim.get("evidence_ids", []))
    evidence = [
        EvidenceOut(
            id=r.id,
            raw_document_id=r.raw_document_id,
            document_text_id=r.document_text_id,
            company_id=r.company_id,
            filing_id=r.filing_id,
            source=r.source.value,
            url=r.url,
            public_at=r.public_at,
            extracted_text=r.extracted_text,
            char_start=r.char_start,
            char_end=r.char_end,
            page_number=r.page_number,
            extraction_method=r.extraction_method.value,
            confidence=r.confidence,
            created_by=r.created_by,
            document_url=f"/api/v1/companies/{company_id}/documents/{r.raw_document_id}?highlight={r.id}",
        )
        for r in (pit.evidence(company_id, ids) if ids else [])
    ]
    message = None
    if thesis is None or contradiction is None:
        message = (
            "No published thesis: a thesis is only served together with its contradiction "
            "analysis (PRD §2.6)."
        )
        thesis = None
    return wrap(
        pit,
        ThesisOut(
            thesis=q.agent_output_out(thesis) if thesis else None,
            contradiction=q.agent_output_out(contradiction) if contradiction else None,
            evidence=evidence,
            message=message,
        ),
        company_id=company_id,
    )
