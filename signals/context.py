"""Point-in-time detection context.

The loader fetches a company's whole visible history once (at the run's ``as_of``) and then
:meth:`HistoryLoader.at` materialises the state as it was at any earlier instant ``T`` by
filtering ``public_at <= T`` and re-resolving restatements with the same rule as
``sa_financials_as_of`` (latest ``public_at``, then ``filing_id``). A test asserts that the
two resolutions agree.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from database.models import (
    Announcement,
    BulkDeal,
    Company,
    CreditRating,
    Financial,
    InsiderTrade,
    PledgeEvent,
    Price,
    Shareholding,
    SurveillanceEvent,
)
from database.pit import PointInTimeSession


@dataclass(frozen=True)
class Period:
    id: int
    filing_id: int
    raw_document_id: int
    period_end: date
    months: int
    consolidated: bool
    public_at: datetime
    revenue: Decimal | None
    ebitda: Decimal | None
    depreciation: Decimal | None
    pat: Decimal | None
    cfo: Decimal | None
    capex: Decimal | None
    receivables: Decimal | None
    inventory: Decimal | None
    payables: Decimal | None
    cash: Decimal | None
    total_borrowings: Decimal | None
    short_term_borrowings: Decimal | None
    related_party_revenue: Decimal | None
    contingent_liabilities: Decimal | None
    audit_opinion: str | None
    shares_outstanding: Decimal | None

    @property
    def margin(self) -> Decimal | None:
        if self.revenue and self.ebitda is not None:
            return self.ebitda / self.revenue
        return None

    @property
    def source_record(self) -> dict[str, Any]:
        return {"table": "financials", "id": self.id, "filing_id": self.filing_id}


@dataclass(frozen=True)
class Holding:
    id: int
    filing_id: int
    raw_document_id: int
    period_end: date
    public_at: datetime
    promoter_pct: Decimal
    pledged_pct: Decimal
    fii_pct: Decimal
    dii_pct: Decimal
    total_shareholders: int
    retail_shareholders: int
    holders: tuple[tuple[str, str, Decimal], ...]

    @property
    def source_record(self) -> dict[str, Any]:
        return {"table": "shareholdings", "id": self.id, "filing_id": self.filing_id}


@dataclass(frozen=True)
class Event:
    table: str
    id: int
    raw_document_id: int
    public_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def source_record(self) -> dict[str, Any]:
        return {"table": self.table, "id": self.id}


@dataclass(frozen=True)
class PriceBar:
    trade_date: date
    public_at: datetime
    close: Decimal
    traded_value: Decimal
    delivery_pct: Decimal | None


@dataclass
class DetectionContext:
    """Everything a detector may look at, all public at ``as_of``."""

    company_id: int
    sector: str
    as_of: datetime
    quarters: list[Period]  # 3-month P&L, oldest -> newest, consolidated preferred
    halves: list[Period]  # 6-month rows (balance sheet + cash flow)
    annuals: list[Period]  # 12-month rows
    holdings: list[Holding]  # oldest -> newest
    announcements: list[Event]
    pledge_events: list[Event]
    insider_trades: list[Event]
    bulk_deals: list[Event]
    ratings: list[Event]
    surveillance: list[Event]
    prices: list[PriceBar]  # oldest -> newest
    document_text: Callable[[int], str | None]
    sector_price_change: Callable[[int], float | None]
    """90-day-style sector median price change for a window of N days (computed lazily)."""
    prior_signals: list[tuple[str, datetime]] = field(default_factory=list)
    """(signal_type, public_at) of this company's signals already emitted before ``as_of``."""

    @property
    def balance_periods(self) -> list[Period]:
        rows = [p for p in self.halves + self.annuals if p.receivables is not None]
        rows.sort(key=lambda p: (p.period_end, p.months))
        # one row per period_end: prefer the annual row (it carries the notes)
        out: dict[date, Period] = {}
        for p in rows:
            out[p.period_end] = p
        return [out[k] for k in sorted(out)]

    def ttm_revenue(self, upto: date | None = None) -> Decimal | None:
        qs = [q for q in self.quarters if upto is None or q.period_end <= upto][-4:]
        if len(qs) < 4 or any(q.revenue is None for q in qs):
            return None
        return sum((q.revenue for q in qs if q.revenue is not None), Decimal(0))

    def ttm_ebitda(self, upto: date | None = None) -> Decimal | None:
        qs = [q for q in self.quarters if upto is None or q.period_end <= upto][-4:]
        if len(qs) < 4 or any(q.ebitda is None for q in qs):
            return None
        return sum((q.ebitda for q in qs if q.ebitda is not None), Decimal(0))

    def ttm_cfo(self, upto: date) -> Decimal | None:
        """TTM CFO at a balance-sheet date from 6- and 12-month cash-flow rows."""
        annual = next((a for a in reversed(self.annuals) if a.period_end == upto), None)
        if annual is not None and annual.cfo is not None:
            return annual.cfo
        half = next((h for h in reversed(self.halves) if h.period_end == upto), None)
        if half is None or half.cfo is None:
            return None
        prev_annual = max(
            (a for a in self.annuals if a.period_end < upto and a.cfo is not None),
            key=lambda a: a.period_end,
            default=None,
        )
        if prev_annual is None:
            return None
        prev_half = next(
            (
                h
                for h in self.halves
                if h.cfo is not None and prev_annual.period_end > h.period_end >= _year_before(upto)
            ),
            None,
        )
        if prev_half is None or prev_half.cfo is None or prev_annual.cfo is None:
            return None
        return half.cfo + prev_annual.cfo - prev_half.cfo


def _year_before(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


# ------------------------------------------------------------------------ conversion
def period_from_row(row: Financial) -> Period:
    return Period(
        id=row.id,
        filing_id=row.filing_id,
        raw_document_id=row.raw_document_id,
        period_end=row.period_end,
        months=row.period_months,
        consolidated=row.consolidated,
        public_at=row.public_at,
        revenue=row.revenue,
        ebitda=row.ebitda,
        depreciation=row.depreciation,
        pat=row.pat,
        cfo=row.cfo,
        capex=row.capex,
        receivables=row.receivables,
        inventory=row.inventory,
        payables=row.payables,
        cash=row.cash_and_equivalents,
        total_borrowings=row.total_borrowings,
        short_term_borrowings=row.short_term_borrowings,
        related_party_revenue=row.related_party_revenue,
        contingent_liabilities=row.contingent_liabilities,
        audit_opinion=row.audit_opinion.value if row.audit_opinion else None,
        shares_outstanding=row.shares_outstanding,
    )


def holding_from_row(row: Shareholding) -> Holding:
    return Holding(
        id=row.id,
        filing_id=row.filing_id,
        raw_document_id=row.raw_document_id,
        period_end=row.period_end,
        public_at=row.public_at,
        promoter_pct=row.promoter_pct,
        pledged_pct=row.promoter_pledged_pct,
        fii_pct=row.fii_pct,
        dii_pct=row.dii_pct,
        total_shareholders=row.total_shareholders,
        retail_shareholders=row.retail_shareholders,
        holders=tuple((h.holder_name, h.category.value, h.pct) for h in row.institutional_holders),
    )


def _announcement_event(a: Announcement) -> Event:
    return Event(
        "announcements",
        a.id,
        a.raw_document_id,
        a.public_at,
        {"category": a.category.value, "subject": a.subject, "summary": a.summary or ""},
    )


def _pledge_event(p: PledgeEvent) -> Event:
    return Event(
        "pledge_events",
        p.id,
        p.raw_document_id,
        p.public_at,
        {
            "event_type": p.event_type.value,
            "pct_of_promoter_holding": p.pct_of_promoter_holding,
            "pct_of_total_shares": p.pct_of_total_shares,
        },
    )


def _insider_event(t: InsiderTrade) -> Event:
    return Event(
        "insider_trades",
        t.id,
        t.raw_document_id,
        t.public_at,
        {
            "side": t.side.value,
            "mode": t.mode.value,
            "category": t.person_category.value,
            "value_inr": t.value_inr,
        },
    )


def _bulk_event(b: BulkDeal) -> Event:
    return Event(
        "bulk_deals",
        b.id,
        b.raw_document_id,
        b.public_at,
        {"client_name": b.client_name, "side": b.side.value, "value_inr": b.value_inr},
    )


def _rating_event(r: CreditRating) -> Event:
    return Event(
        "credit_ratings",
        r.id,
        r.raw_document_id,
        r.public_at,
        {"action": r.action.value, "rating": r.rating, "agency": r.agency},
    )


def _surveillance_event(s: SurveillanceEvent) -> Event:
    return Event(
        "surveillance_events",
        s.id,
        s.raw_document_id,
        s.public_at,
        {"framework": s.framework.value, "event": s.event.value, "stage": s.stage},
    )


def _bar(p: Price) -> PriceBar:
    return PriceBar(p.trade_date, p.public_at, p.close, p.traded_value, p.delivery_pct)


def resolve_periods(rows: Sequence[Financial], at: datetime) -> list[Period]:
    """Latest non-superseded filing per (period_end, months, consolidated) public at ``at``."""
    best: dict[tuple[date, int, bool], Financial] = {}
    for row in rows:
        if row.public_at > at or row.is_superseded:
            continue
        key = (row.period_end, row.period_months, row.consolidated)
        cur = best.get(key)
        if cur is None or (row.public_at, row.filing_id, row.id) > (
            cur.public_at,
            cur.filing_id,
            cur.id,
        ):
            best[key] = row
    return [period_from_row(r) for r in best.values()]


def prefer_consolidated(periods: Sequence[Period], months: int) -> list[Period]:
    by_end: dict[date, Period] = {}
    for p in periods:
        if p.months != months:
            continue
        cur = by_end.get(p.period_end)
        if cur is None or (p.consolidated and not cur.consolidated):
            by_end[p.period_end] = p
    return [by_end[k] for k in sorted(by_end)]


class HistoryLoader:
    """Loads a company's history visible at ``pit.as_of`` and materialises earlier states."""

    def __init__(self, pit: PointInTimeSession, company: Company) -> None:
        self.pit = pit
        self.company = company
        cid = company.id
        self.financial_rows = list(pit.financial_history(cid))  # every filing; resolved per T
        self.holding_rows = list(pit.shareholding_history(cid))
        self.announcements = [_announcement_event(a) for a in pit.announcements(cid)]
        self.pledges = [_pledge_event(p) for p in pit.pledge_events(cid)]
        self.insiders = [_insider_event(t) for t in pit.insider_trades(cid)]
        self.bulks = [_bulk_event(b) for b in pit.bulk_deals(cid)]
        self.ratings = [_rating_event(r) for r in pit.credit_ratings(cid)]
        self.surveillance = [_surveillance_event(s) for s in pit.surveillance_events(cid)]
        first_price = date(1990, 1, 1)
        self.prices = [_bar(p) for p in pit.prices(cid, first_price)]
        self._texts: dict[int, str | None] = {}
        self._sector_cache: dict[tuple[datetime, int], float | None] = {}

    def event_times(self) -> list[datetime]:
        times = {r.public_at for r in self.financial_rows}
        times |= {r.public_at for r in self.holding_rows}
        for events in (
            self.announcements,
            self.pledges,
            self.insiders,
            self.bulks,
            self.ratings,
            self.surveillance,
        ):
            times |= {e.public_at for e in events}
        return sorted(t for t in times if t <= self.pit.as_of)

    def document_text(self, raw_document_id: int) -> str | None:
        if raw_document_id not in self._texts:
            text = self.pit.document_text(raw_document_id)
            self._texts[raw_document_id] = text.text if text else None
        return self._texts[raw_document_id]

    def at(
        self, at: datetime, prior_signals: list[tuple[str, datetime]] | None = None
    ) -> DetectionContext:
        periods = resolve_periods(self.financial_rows, at)
        holdings_best: dict[date, Shareholding] = {}
        for row in self.holding_rows:
            if row.public_at > at or row.is_superseded:
                continue
            cur = holdings_best.get(row.period_end)
            if cur is None or (row.public_at, row.filing_id, row.id) > (
                cur.public_at,
                cur.filing_id,
                cur.id,
            ):
                holdings_best[row.period_end] = row
        holdings = [holding_from_row(holdings_best[k]) for k in sorted(holdings_best)]

        def visible(events: list[Event]) -> list[Event]:
            return sorted(
                (e for e in events if e.public_at <= at), key=lambda e: (e.public_at, e.id)
            )

        def sector_change(window_days: int) -> float | None:
            key = (at, window_days)
            if key not in self._sector_cache:
                self._sector_cache[key] = _sector_median_change(
                    self.pit, self.company, at, window_days
                )
            return self._sector_cache[key]

        return DetectionContext(
            company_id=self.company.id,
            sector=self.company.sector,
            as_of=at,
            quarters=prefer_consolidated(periods, 3),
            halves=prefer_consolidated(periods, 6),
            annuals=prefer_consolidated(periods, 12),
            holdings=holdings,
            announcements=visible(self.announcements),
            pledge_events=visible(self.pledges),
            insider_trades=visible(self.insiders),
            bulk_deals=visible(self.bulks),
            ratings=visible(self.ratings),
            surveillance=visible(self.surveillance),
            prices=[b for b in self.prices if b.public_at <= at],
            document_text=self.document_text,
            sector_price_change=sector_change,
            prior_signals=list(prior_signals or []),
        )


def price_change(bars: Sequence[PriceBar], at: datetime, window_days: int) -> float | None:
    visible = [b for b in bars if b.public_at <= at]
    if not visible:
        return None
    last = visible[-1]
    start_date = last.trade_date.fromordinal(last.trade_date.toordinal() - window_days)
    earlier = [b for b in visible if b.trade_date <= start_date]
    if not earlier:
        return None
    return float(last.close / earlier[-1].close) - 1


def _sector_median_change(
    pit: PointInTimeSession, company: Company, at: datetime, window_days: int
) -> float | None:
    from statistics import median

    peers = [c for c in pit.companies() if c.sector == company.sector and c.id != company.id]
    changes: list[float] = []
    since = at.date().fromordinal(at.date().toordinal() - window_days - 10)
    for peer in peers:
        bars = [_bar(p) for p in pit.prices(peer.id, since, at.date())]
        ch = price_change(bars, at, window_days)
        if ch is not None:
            changes.append(ch)
    return median(changes) if changes else None
