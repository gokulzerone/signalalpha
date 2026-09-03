"""Python-computed ratios for one financial period (PRD §2.3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from signals.context import Period


def _year_before(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def ratios_for(row: Period, periods: Sequence[Period]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    if row.revenue and row.ebitda is not None:
        out["ebitda_margin"] = float(row.ebitda / row.revenue)
    if row.revenue and row.pat is not None:
        out["pat_margin"] = float(row.pat / row.revenue)
    prior = next(
        (
            q
            for q in periods
            if q.months == row.months and q.period_end == _year_before(row.period_end)
        ),
        None,
    )
    if prior and prior.revenue and row.revenue is not None:
        out["revenue_yoy"] = float((row.revenue - prior.revenue) / prior.revenue)
    if prior and prior.ebitda and row.ebitda is not None and prior.ebitda > 0:
        out["ebitda_yoy"] = float((row.ebitda - prior.ebitda) / prior.ebitda)
    ttm = [q for q in periods if q.months == 3 and q.period_end <= row.period_end][-4:]
    ttm_rev = (
        sum((q.revenue for q in ttm if q.revenue is not None), Decimal(0))
        if len(ttm) == 4
        else None
    )
    if ttm_rev and row.receivables is not None:
        out["receivable_days"] = float(row.receivables / ttm_rev * 365)
    if ttm_rev and row.inventory is not None:
        out["inventory_days"] = float(row.inventory / ttm_rev * 365)
    if row.total_borrowings is not None and row.cash is not None:
        out["net_debt"] = float(row.total_borrowings - row.cash)
    if row.cfo is not None and row.ebitda and row.ebitda > 0:
        out["cfo_to_ebitda"] = float(row.cfo / row.ebitda)
    if row.capex is not None and row.depreciation and row.depreciation > 0:
        out["capex_to_depreciation"] = float(row.capex / row.depreciation)
    return out
