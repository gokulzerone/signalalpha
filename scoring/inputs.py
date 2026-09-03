"""Score inputs (PRD §9): every raw metric is computed here, in Python, from point-in-time
data. The score functions in :mod:`scoring.scores` only rank and weight these numbers."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from sqlalchemy.orm import Session

from database.models import Company, Financial, Source, UniverseSnapshot
from database.pit import PointInTimeSession, end_of_day
from scoring.config import ScoreConfig
from signals.context import DetectionContext, HistoryLoader, Period


@dataclass(frozen=True)
class SignalView:
    id: int
    signal_type: str
    family: str
    direction: int
    magnitude: float
    public_at: datetime


@dataclass
class CompanyInputs:
    company_id: int
    sector: str
    market_cap_cr: float | None
    in_universe: bool
    is_illiquid: bool
    signals: list[SignalView] = field(default_factory=list)
    # quality
    roce_3y: float | None = None
    cfo_to_ebitda_ttm: float | None = None
    receivable_days_trend: float | None = None  # days now minus days a year ago (lower better)
    promoter_pct: float | None = None
    # valuation
    ev_ebitda: float | None = None
    pe: float | None = None
    ev_ebitda_own_median: float | None = None
    pe_own_median: float | None = None
    peg_trailing: float | None = None
    # risk
    pledge_pct: float | None = None
    median_traded_value: float | None = None
    surveillance_stage: int = 0
    audit_qualification: float = 0.0
    volatility_90d: float | None = None
    # attention gap
    institutional_pct: float | None = None
    turnover: float | None = None  # avg daily traded value / market cap
    days_since_reaction: float | None = None
    annual_report_chars: int | None = None
    # derived at universe level
    sector_ev_ebitda_median: float | None = None
    sector_pe_median: float | None = None
    sector_report_chars_median: float | None = None


@dataclass
class UniverseInputs:
    as_of: date
    companies: dict[int, CompanyInputs]

    def scored_ids(self) -> list[int]:
        return sorted(cid for cid, c in self.companies.items() if c.in_universe)


@dataclass(frozen=True)
class ScoreInputs:
    """PRD §9 ``ScoreInputs``: one company plus the cross-section it is ranked within."""

    company_id: int
    universe: UniverseInputs

    @property
    def company(self) -> CompanyInputs:
        return self.universe.companies[self.company_id]


# ------------------------------------------------------------------- helpers
def _f(x: Decimal | None) -> float | None:
    return None if x is None else float(x)


def _ttm(periods: Sequence[Period], attr: str, upto: date | None = None) -> Decimal | None:
    qs = [q for q in periods if upto is None or q.period_end <= upto][-4:]
    if len(qs) < 4 or any(getattr(q, attr) is None for q in qs):
        return None
    return sum((getattr(q, attr) for q in qs), Decimal(0))


def _days(amount: Decimal | None, ttm_revenue: Decimal | None) -> float | None:
    if amount is None or not ttm_revenue or ttm_revenue <= 0:
        return None
    return float(amount / ttm_revenue * 365)


def compute_company_inputs(
    pit: PointInTimeSession,
    company: Company,
    ctx: DetectionContext,
    snapshot: UniverseSnapshot | None,
    config: ScoreConfig,
) -> CompanyInputs:
    as_of = pit.as_of
    w = config.windows
    ci = CompanyInputs(
        company_id=company.id,
        sector=company.sector,
        market_cap_cr=_f(snapshot.market_cap_cr) if snapshot else None,
        in_universe=bool(snapshot and snapshot.in_universe),
        is_illiquid=bool(snapshot is None or snapshot.is_illiquid),
        median_traded_value=_f(snapshot.median_traded_value_30d) if snapshot else None,
        surveillance_stage=max((snapshot.gsm_stage or 0), (snapshot.asm_stage or 0))
        if snapshot
        else 0,
    )
    ci.signals = [
        SignalView(s.id, s.signal_type, s.family, s.direction, float(s.magnitude), s.public_at)
        for s in pit.signals(company.id)
    ]

    # ---- quality
    annuals = ctx.annuals
    roces = [r for r in (_roce_from_row(pit, a) for a in annuals[-3:]) if r is not None]
    ci.roce_3y = statistics.fmean(roces) if roces else None
    bps = ctx.balance_periods
    if bps:
        now = bps[-1]
        cfo, ebitda = ctx.ttm_cfo(now.period_end), ctx.ttm_ebitda(upto=now.period_end)
        if cfo is not None and ebitda and ebitda > 0:
            ci.cfo_to_ebitda_ttm = float(cfo / ebitda)
        prior = next((p for p in bps if p.period_end == _year_before(now.period_end)), None)
        d_now = _days(now.receivables, ctx.ttm_revenue(now.period_end))
        d_prior = _days(prior.receivables, ctx.ttm_revenue(prior.period_end)) if prior else None
        if d_now is not None and d_prior is not None:
            ci.receivable_days_trend = d_now - d_prior
    if ctx.holdings:
        h = ctx.holdings[-1]
        ci.promoter_pct = float(h.promoter_pct)
        ci.pledge_pct = float(h.pledged_pct)
        ci.institutional_pct = float(h.fii_pct + h.dii_pct)

    # ---- valuation
    mcap = ci.market_cap_cr
    ttm_ebitda = _ttm(ctx.quarters, "ebitda")
    ttm_pat = _ttm(ctx.quarters, "pat")
    if mcap is not None and bps:
        now = bps[-1]
        if (
            ttm_ebitda
            and ttm_ebitda > 0
            and now.total_borrowings is not None
            and now.cash is not None
        ):
            ev = mcap + float(now.total_borrowings - now.cash)
            ci.ev_ebitda = ev / float(ttm_ebitda)
    if mcap is not None and ttm_pat and ttm_pat > 0:
        ci.pe = mcap / float(ttm_pat)
        prior_pat = _ttm(ctx.quarters[:-4], "pat") if len(ctx.quarters) >= 8 else None
        if prior_pat and prior_pat > 0:
            growth = float((ttm_pat - prior_pat) / prior_pat)
            if growth > 0:
                ci.peg_trailing = ci.pe / (growth * 100)
    ci.ev_ebitda_own_median, ci.pe_own_median = _own_history_medians(
        ctx, as_of, w.own_history_years
    )

    # ---- risk
    latest_opinion = next((a.audit_opinion for a in reversed(annuals) if a.audit_opinion), None)
    if latest_opinion and latest_opinion != "unqualified":
        ci.audit_qualification = 0.5 if latest_opinion == "emphasis_of_matter" else 1.0
    closes = [float(b.close) for b in ctx.prices[-(w.volatility_trading_days + 1) :]]
    if len(closes) > 20:
        rets = [math.log(b / a) for a, b in pairwise(closes) if a > 0 and b > 0]
        ci.volatility_90d = statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 2 else None

    # ---- attention gap
    recent = ctx.prices[-w.turnover_trading_days :]
    if recent and mcap:
        ci.turnover = statistics.fmean(float(b.traded_value) for b in recent) / (mcap * 1e7)
    ci.days_since_reaction = _days_since_reaction(ctx, ci.signals, as_of, config)
    ci.annual_report_chars = _annual_report_chars(pit, company.id)
    return ci


def _roce_from_row(pit: PointInTimeSession, annual: Period) -> float | None:
    row = pit.session.get(Financial, annual.id)
    if row is None or row.net_worth is None or row.total_borrowings is None:
        return None
    if row.ebitda is None or row.depreciation is None:
        return None
    capital = float(row.net_worth + row.total_borrowings)
    if capital <= 0:
        return None
    return float(row.ebitda - row.depreciation) / capital


def _year_before(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def _own_history_medians(
    ctx: DetectionContext, as_of: datetime, years: int
) -> tuple[float | None, float | None]:
    """Monthly EV/EBITDA and P/E over the trailing years, using only data public at each month."""
    if not ctx.prices or not ctx.quarters:
        return None, None
    ev_vals: list[float] = []
    pe_vals: list[float] = []
    start = as_of.date() - timedelta(days=365 * years)
    d = start
    while d < as_of.date():
        at = end_of_day(d)
        bars = [b for b in ctx.prices if b.public_at <= at]
        quarters = [q for q in ctx.quarters if q.public_at <= at]
        bps = [p for p in ctx.balance_periods if p.public_at <= at]
        if bars and len(quarters) >= 4:
            close = float(bars[-1].close)
            shares = quarters[-1].shares_outstanding
            ttm_e = _ttm(quarters, "ebitda")
            ttm_p = _ttm(quarters, "pat")
            if shares:
                mcap = close * float(shares)
                if (
                    ttm_e
                    and ttm_e > 0
                    and bps
                    and bps[-1].total_borrowings is not None
                    and bps[-1].cash is not None
                ):
                    ev_vals.append(
                        (mcap + float(bps[-1].total_borrowings - bps[-1].cash)) / float(ttm_e)
                    )
                if ttm_p and ttm_p > 0:
                    pe_vals.append(mcap / float(ttm_p))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (
        statistics.median(ev_vals) if ev_vals else None,
        statistics.median(pe_vals) if pe_vals else None,
    )


def _days_since_reaction(
    ctx: DetectionContext, signals: list[SignalView], as_of: datetime, config: ScoreConfig
) -> float | None:
    """Days since the last positive fundamental signal that moved the price by >= the threshold
    within the reaction window. No reaction ever -> capped maximum (most under-followed)."""
    w = config.windows
    fundamentals = [s for s in signals if s.family in ("financial", "business") and s.direction > 0]
    if not fundamentals or not ctx.prices:
        return None
    last_reaction: datetime | None = None
    for s in fundamentals:
        before = [b for b in ctx.prices if b.public_at <= s.public_at]
        after = [b for b in ctx.prices if b.public_at > s.public_at][
            : w.reaction_window_trading_days
        ]
        if not before or len(after) < w.reaction_window_trading_days:
            continue
        move = float(after[-1].close / before[-1].close) - 1
        if abs(move) >= w.reaction_min_move and (
            last_reaction is None or s.public_at > last_reaction
        ):
            last_reaction = s.public_at
    if last_reaction is None:
        return float(w.max_days_since_reaction)
    return min(float((as_of - last_reaction).days), float(w.max_days_since_reaction))


def _annual_report_chars(pit: PointInTimeSession, company_id: int) -> int | None:
    docs = pit.raw_documents(company_id, Source.ANNUAL_REPORT)
    if not docs:
        return None
    text = pit.document_text(docs[0].id)
    return text.char_count if text else None


def compute_universe_inputs(
    session: Session, *, as_of: datetime | date, is_mock: bool, config: ScoreConfig
) -> UniverseInputs:
    pit = PointInTimeSession(session, as_of, is_mock=is_mock)
    snapshots = {s.company_id: s for s in pit.universe()}
    companies: dict[int, CompanyInputs] = {}
    for company in pit.companies():
        snap = snapshots.get(company.id)
        if snap is None or snap.listing_status.value != "listed":
            continue
        loader = HistoryLoader(pit, company)
        ctx = loader.at(pit.as_of)
        companies[company.id] = compute_company_inputs(pit, company, ctx, snap, config)
    universe = UniverseInputs(as_of=pit.as_of_date, companies=companies)
    _attach_sector_medians(universe)
    return universe


def _attach_sector_medians(universe: UniverseInputs) -> None:
    by_sector: dict[str, list[CompanyInputs]] = {}
    for c in universe.companies.values():
        by_sector.setdefault(c.sector, []).append(c)
    for members in by_sector.values():
        ev = [c.ev_ebitda for c in members if c.ev_ebitda is not None and c.ev_ebitda > 0]
        pe = [c.pe for c in members if c.pe is not None and c.pe > 0]
        chars = [float(c.annual_report_chars) for c in members if c.annual_report_chars]
        for c in members:
            c.sector_ev_ebitda_median = statistics.median(ev) if ev else None
            c.sector_pe_median = statistics.median(pe) if pe else None
            c.sector_report_chars_median = statistics.median(chars) if chars else None
