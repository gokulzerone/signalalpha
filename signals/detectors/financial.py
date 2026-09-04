"""Financial signals (PRD §6.2). Quarterly rows are oldest -> newest, consolidated preferred."""

from __future__ import annotations

from decimal import Decimal

from signals.config import SignalCatalogue
from signals.context import DetectionContext, Period
from signals.detectors.base import (
    Candidate,
    clamp01,
    detector,
    f,
    jsonable,
    mean,
    pct_change,
    year_before,
)


def too_small(ctx: DetectionContext, cfg: SignalCatalogue) -> bool:
    """Ratio signals need a real revenue base to mean anything."""
    ttm = ctx.ttm_revenue()
    return ttm is None or float(ttm) < cfg.min_ttm_revenue_cr


def _yoy(rows: list[Period], attr: str) -> list[float | None]:
    """YoY growth aligned to rows[4:]."""
    return [
        pct_change(getattr(rows[i], attr), getattr(rows[i - 4], attr)) for i in range(4, len(rows))
    ]


@detector("revenue_acceleration")
def revenue_acceleration(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    if too_small(ctx, cfg):
        return []
    q = ctx.quarters
    if len(q) < 9:
        return []
    yoy = _yoy(q, "revenue")
    latest, trailing = yoy[-1], yoy[-5:-1]
    if latest is None or any(v is None for v in trailing):
        return []
    trailing_avg = mean([v for v in trailing if v is not None])
    excess_pp = (latest - trailing_avg) * 100
    min_pp = cfg.param("revenue_acceleration", "min_excess_pp")
    if excess_pp < min_pp:
        return []
    return [
        Candidate(
            "revenue_acceleration",
            1,
            clamp01(excess_pp / cfg.param("revenue_acceleration", "magnitude_full_pp")),
            q[-1].public_at,
            q[-1].period_end.isoformat(),
            [q[-1].source_record, q[-5].source_record],
            jsonable(
                {
                    "yoy_growth_latest": latest,
                    "trailing_4q_avg_yoy": trailing_avg,
                    "excess_pp": excess_pp,
                    "threshold_pp": min_pp,
                    "period_end": q[-1].period_end,
                }
            ),
        )
    ]


@detector("margin_inflection")
def margin_inflection(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    if too_small(ctx, cfg):
        return []
    q = ctx.quarters
    if len(q) < 6:
        return []
    margins = [p.margin for p in q]
    if any(m is None for m in margins[-6:]):
        return []
    deltas_bp: list[float] = []
    for i in (-2, -1):
        window = [float(m) for m in margins[i - 4 : i] if m is not None]
        cur = margins[i]
        assert cur is not None
        deltas_bp.append((float(cur) - mean(window)) * 10_000)
    min_bp = cfg.param("margin_inflection", "min_change_bp")
    if all(d >= min_bp for d in deltas_bp):
        direction = 1
    elif all(d <= -min_bp for d in deltas_bp):
        direction = -1
    else:
        return []
    size = min(abs(d) for d in deltas_bp)
    return [
        Candidate(
            "margin_inflection",
            direction,
            clamp01(size / cfg.param("margin_inflection", "magnitude_full_bp")),
            q[-1].public_at,
            q[-1].period_end.isoformat(),
            [q[-1].source_record, q[-2].source_record],
            jsonable(
                {
                    "delta_bp_latest": deltas_bp[1],
                    "delta_bp_previous": deltas_bp[0],
                    "margin_latest": margins[-1],
                    "threshold_bp": min_bp,
                    "period_end": q[-1].period_end,
                }
            ),
        )
    ]


@detector("operating_leverage")
def operating_leverage(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    if too_small(ctx, cfg):
        return []
    q = ctx.quarters
    if len(q) < 6:
        return []
    rev = _yoy(q, "revenue")
    ebt = _yoy(q, "ebitda")
    ratios: list[float] = []
    for i in (-2, -1):
        r, e = rev[i], ebt[i]
        if r is None or e is None or r <= 0 or e <= 0:
            return []
        ratios.append(e / r)
    min_ratio = cfg.param("operating_leverage", "min_ratio")
    if any(x < min_ratio for x in ratios):
        return []
    return [
        Candidate(
            "operating_leverage",
            1,
            clamp01(min(ratios) / cfg.param("operating_leverage", "magnitude_full_ratio")),
            q[-1].public_at,
            q[-1].period_end.isoformat(),
            [q[-1].source_record, q[-2].source_record],
            jsonable(
                {
                    "ebitda_to_revenue_growth_ratio_latest": ratios[1],
                    "ratio_previous": ratios[0],
                    "revenue_yoy_latest": rev[-1],
                    "ebitda_yoy_latest": ebt[-1],
                    "threshold_ratio": min_ratio,
                    "period_end": q[-1].period_end,
                }
            ),
        )
    ]


def _cash_conversion(ctx: DetectionContext, p: Period) -> float | None:
    cfo = ctx.ttm_cfo(p.period_end)
    ebitda = ctx.ttm_ebitda(upto=p.period_end)
    if cfo is None or ebitda is None or ebitda <= 0:
        return None
    return float(cfo / ebitda)


@detector("cash_conversion_improvement")
def cash_conversion_improvement(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    bps = ctx.balance_periods
    if len(bps) < 2:
        return []
    now, prev = bps[-1], bps[-2]
    cur, before = _cash_conversion(ctx, now), _cash_conversion(ctx, prev)
    threshold = cfg.param("cash_conversion_improvement", "threshold")
    if cur is None or before is None or not (cur >= threshold > before):
        return []
    return [
        Candidate(
            "cash_conversion_improvement",
            1,
            clamp01(cur / cfg.param("cash_conversion_improvement", "magnitude_full")),
            now.public_at,
            now.period_end.isoformat(),
            [now.source_record, prev.source_record],
            jsonable(
                {
                    "cfo_to_ebitda_ttm": cur,
                    "cfo_to_ebitda_previous": before,
                    "threshold": threshold,
                    "period_end": now.period_end,
                }
            ),
        )
    ]


def _days(amount: Decimal | None, ttm_revenue: Decimal | None) -> float | None:
    if amount is None or ttm_revenue is None or ttm_revenue <= 0:
        return None
    return float(amount / ttm_revenue * 365)


@detector("working_capital_release")
def working_capital_release(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    bps = ctx.balance_periods
    if not bps:
        return []
    now = bps[-1]
    prior = next((p for p in bps if p.period_end == year_before(now.period_end)), None)
    if prior is None:
        return []
    rev_now, rev_prior = ctx.ttm_revenue(now.period_end), ctx.ttm_revenue(prior.period_end)
    falls: dict[str, float] = {}
    for name in ("receivables", "inventory"):
        d_now = _days(getattr(now, name), rev_now)
        d_prior = _days(getattr(prior, name), rev_prior)
        if d_now is not None and d_prior is not None:
            falls[name] = d_prior - d_now
    min_days = cfg.param("working_capital_release", "min_days")
    if not falls or max(falls.values()) < min_days:
        return []
    best = max(falls, key=lambda k: falls[k])
    return [
        Candidate(
            "working_capital_release",
            1,
            clamp01(falls[best] / cfg.param("working_capital_release", "magnitude_full_days")),
            now.public_at,
            now.period_end.isoformat(),
            [now.source_record, prior.source_record],
            jsonable(
                {
                    "component": best,
                    "days_fall": falls[best],
                    **{f"{k}_days_fall": v for k, v in falls.items()},
                    "threshold_days": min_days,
                    "period_end": now.period_end,
                }
            ),
        )
    ]


def _net_debt_ratio(ctx: DetectionContext, p: Period) -> tuple[Decimal | None, float | None]:
    if p.total_borrowings is None or p.cash is None:
        return None, None
    net_debt = p.total_borrowings - p.cash
    ebitda = ctx.ttm_ebitda(upto=p.period_end)
    if ebitda is None or ebitda <= 0:
        return net_debt, None
    return net_debt, float(net_debt / ebitda)


@detector("deleveraging")
def deleveraging(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    bps = ctx.balance_periods
    if len(bps) < 2:
        return []
    now, prev = bps[-1], bps[-2]
    nd_now, r_now = _net_debt_ratio(ctx, now)
    nd_prev, r_prev = _net_debt_ratio(ctx, prev)
    if nd_now is None or nd_prev is None:
        return []
    threshold = cfg.param("deleveraging", "threshold")
    turned_net_cash = nd_now <= 0 < nd_prev
    crossed = r_now is not None and r_prev is not None and r_now < threshold <= r_prev
    if not (turned_net_cash or crossed):
        return []
    magnitude = 1.0 if turned_net_cash else clamp01((r_prev - r_now) / r_prev) if r_prev else 0.0  # type: ignore[operator]
    return [
        Candidate(
            "deleveraging",
            1,
            magnitude,
            now.public_at,
            now.period_end.isoformat(),
            [now.source_record, prev.source_record],
            jsonable(
                {
                    "net_debt": nd_now,
                    "net_debt_previous": nd_prev,
                    "net_debt_to_ebitda": r_now,
                    "net_debt_to_ebitda_previous": r_prev,
                    "threshold": threshold,
                    "turned_net_cash": turned_net_cash,
                    "period_end": now.period_end,
                }
            ),
        )
    ]


@detector("capex_cycle_start")
def capex_cycle_start(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    rows = [p for p in ctx.balance_periods if p.capex is not None and p.depreciation]
    if len(rows) < 3:
        return []
    now = rows[-1]
    assert now.capex is not None and now.depreciation is not None
    ratio = float(now.capex / now.depreciation)
    threshold = cfg.param("capex_cycle_start", "threshold")
    if ratio < threshold:
        return []
    lookback_q = int(cfg.param("capex_cycle_start", "lookback_quarters"))
    cutoff = now.period_end.fromordinal(now.period_end.toordinal() - 91 * lookback_q)
    prior = [p for p in rows[:-1] if p.period_end > cutoff]
    if len(prior) < 2:
        return []
    for p in prior:
        assert p.capex is not None and p.depreciation is not None
        if float(p.capex / p.depreciation) >= threshold:
            return []
    return [
        Candidate(
            "capex_cycle_start",
            1,
            clamp01(ratio / cfg.param("capex_cycle_start", "magnitude_full")),
            now.public_at,
            now.period_end.isoformat(),
            [now.source_record],
            jsonable(
                {
                    "capex_to_depreciation": ratio,
                    "threshold": threshold,
                    "lookback_quarters": lookback_q,
                    "period_end": now.period_end,
                    "capex": f(now.capex),
                    "depreciation": f(now.depreciation),
                }
            ),
        )
    ]
