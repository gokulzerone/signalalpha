"""Builders for detection contexts in unit tests (no database)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from signals.context import DetectionContext, Event, Holding, Period, PriceBar

IST = ZoneInfo("Asia/Kolkata")
_ids = iter(range(1, 1_000_000))


def D(x: float | int | str | None) -> Decimal | None:  # noqa: N802
    return None if x is None else Decimal(str(x))


def qend(i: int, start: date = date(2022, 6, 30)) -> date:
    """i-th quarter end from ``start`` (Jun/Sep/Dec/Mar)."""
    month = start.month + 3 * i
    year = start.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last = (date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)).day
    return date(year, month, last)


def public(period_end: date, lag_days: int = 40) -> datetime:
    return datetime.combine(
        period_end + timedelta(days=lag_days), datetime.min.time(), tzinfo=IST
    ).replace(hour=17)


def period(
    period_end: date,
    *,
    months: int = 3,
    revenue: float | None = 100,
    ebitda: float | None = 15,
    **kw: Any,
) -> Period:
    fields: dict[str, Any] = dict(
        id=next(_ids),
        filing_id=next(_ids),
        raw_document_id=next(_ids),
        period_end=period_end,
        months=months,
        consolidated=True,
        public_at=public(period_end),
        revenue=D(revenue),
        ebitda=D(ebitda),
        depreciation=D(3),
        pat=D(8),
        cfo=None,
        capex=None,
        receivables=None,
        inventory=None,
        payables=None,
        cash=None,
        total_borrowings=None,
        short_term_borrowings=None,
        related_party_revenue=None,
        contingent_liabilities=None,
        audit_opinion=None,
        shares_outstanding=D(10),
    )
    for k, v in kw.items():
        fields[k] = (
            D(v)
            if k
            not in {
                "audit_opinion",
                "consolidated",
                "public_at",
                "id",
                "filing_id",
                "raw_document_id",
            }
            and isinstance(v, int | float | str)
            and k != "audit_opinion"
            else v
        )
    return Period(**fields)


def quarters(revenues: Sequence[float], ebitdas: Sequence[float] | None = None) -> list[Period]:
    ebitdas = ebitdas or [r * 0.15 for r in revenues]
    return [
        period(qend(i), revenue=r, ebitda=e)
        for i, (r, e) in enumerate(zip(revenues, ebitdas, strict=True))
    ]


def holding(
    period_end: date,
    promoter: float = 55,
    pledged: float = 0,
    retail: int = 10000,
    holders: Sequence[tuple[str, str, float]] = (),
) -> Holding:
    return Holding(
        id=next(_ids),
        filing_id=next(_ids),
        raw_document_id=next(_ids),
        period_end=period_end,
        public_at=public(period_end, 14),
        promoter_pct=Decimal(str(promoter)),
        pledged_pct=Decimal(str(pledged)),
        fii_pct=Decimal(2),
        dii_pct=Decimal(3),
        total_shareholders=int(retail * 1.04),
        retail_shareholders=retail,
        holders=tuple((n, c, Decimal(str(p))) for n, c, p in holders),
    )


def event(table: str, at: datetime, raw_document_id: int | None = None, **payload: Any) -> Event:
    return Event(table, next(_ids), raw_document_id or next(_ids), at, payload)


def bars(
    n: int,
    *,
    start: date = date(2024, 1, 1),
    close: float = 100,
    value: float = 1e6,
    delivery: float = 40,
    tail: int = 0,
    tail_value_mult: float = 1.0,
    tail_delivery_add: float = 0.0,
) -> list[PriceBar]:
    out: list[PriceBar] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            i = len(out)
            is_tail = i >= n - tail
            out.append(
                PriceBar(
                    d,
                    datetime.combine(d, datetime.min.time(), tzinfo=IST).replace(hour=18),
                    Decimal(str(close)),
                    Decimal(str(value * (tail_value_mult if is_tail else 1.0))),
                    Decimal(str(delivery + (tail_delivery_add if is_tail else 0))),
                )
            )
        d += timedelta(days=1)
    return out


def make_ctx(
    *,
    quarters: Sequence[Period] = (),
    halves: Sequence[Period] = (),
    annuals: Sequence[Period] = (),
    holdings: Sequence[Holding] = (),
    announcements: Sequence[Event] = (),
    pledge_events: Sequence[Event] = (),
    insider_trades: Sequence[Event] = (),
    bulk_deals: Sequence[Event] = (),
    ratings: Sequence[Event] = (),
    surveillance: Sequence[Event] = (),
    prices: Sequence[PriceBar] = (),
    texts: dict[int, str] | None = None,
    sector_change: float | None = None,
    prior_signals: Sequence[tuple[str, datetime]] = (),
    as_of: datetime | None = None,
) -> DetectionContext:
    texts = texts or {}
    items: list[Any] = [
        *quarters,
        *halves,
        *annuals,
        *holdings,
        *announcements,
        *pledge_events,
        *insider_trades,
        *bulk_deals,
        *ratings,
        *surveillance,
        *prices,
    ]
    latest = max((x.public_at for x in items), default=datetime(2024, 1, 1, tzinfo=IST))
    return DetectionContext(
        company_id=1,
        sector="Capital Goods",
        as_of=as_of or latest,
        quarters=sorted(quarters, key=lambda p: p.period_end),
        halves=sorted(halves, key=lambda p: p.period_end),
        annuals=sorted(annuals, key=lambda p: p.period_end),
        holdings=sorted(holdings, key=lambda h: h.period_end),
        announcements=list(announcements),
        pledge_events=list(pledge_events),
        insider_trades=list(insider_trades),
        bulk_deals=list(bulk_deals),
        ratings=list(ratings),
        surveillance=list(surveillance),
        prices=sorted(prices, key=lambda b: b.trade_date),
        document_text=lambda rid: texts.get(rid),
        sector_price_change=lambda _w: sector_change,
        prior_signals=list(prior_signals),
    )
