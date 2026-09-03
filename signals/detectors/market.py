"""Market signals (PRD §6.2)."""

from __future__ import annotations

from datetime import datetime, timedelta

from signals.config import SignalCatalogue
from signals.context import DetectionContext, PriceBar, price_change
from signals.detectors.base import Candidate, clamp01, detector, jsonable


def _shift_condition(
    bars: list[PriceBar], short_n: int, long_n: int, min_uplift: float
) -> tuple[bool, dict[str, float]]:
    if len(bars) < long_n:
        return False, {}
    long = bars[-long_n:]
    short = bars[-short_n:]
    with_delivery_long = [float(b.delivery_pct) for b in long if b.delivery_pct is not None]
    with_delivery_short = [float(b.delivery_pct) for b in short if b.delivery_pct is not None]
    if len(with_delivery_long) < long_n // 2 or len(with_delivery_short) < short_n // 2:
        return False, {}
    d_long = sum(with_delivery_long) / len(with_delivery_long)
    d_short = sum(with_delivery_short) / len(with_delivery_short)
    v_long = sum(float(b.traded_value) for b in long) / len(long)
    v_short = sum(float(b.traded_value) for b in short) / len(short)
    stats = {
        "delivery_pct_20d": d_short,
        "delivery_pct_90d": d_long,
        "traded_value_20d": v_short,
        "traded_value_90d": v_long,
    }
    if v_long <= 0 or d_long <= 0:
        return False, stats
    ok = d_short > d_long * (1 + min_uplift) and v_short > v_long * (1 + min_uplift)
    stats["delivery_uplift"] = d_short / d_long - 1
    stats["value_uplift"] = v_short / v_long - 1
    return ok, stats


@detector("delivery_volume_shift")
def delivery_volume_shift(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    bars = ctx.prices
    if not bars:
        return []
    short_n = int(cfg.param("delivery_volume_shift", "short_days"))
    long_n = int(cfg.param("delivery_volume_shift", "long_days"))
    min_uplift = cfg.param("delivery_volume_shift", "min_uplift")
    now_ok, stats = _shift_condition(bars, short_n, long_n, min_uplift)
    if not now_ok:
        return []
    # Emit only when the condition has just become true (evaluated one cadence earlier).
    cadence = cfg.market_signal_cadence_days
    earlier_cut = bars[-1].public_at - timedelta(days=cadence)
    earlier = [b for b in bars if b.public_at <= earlier_cut]
    before_ok, _ = _shift_condition(earlier, short_n, long_n, min_uplift)
    if before_ok:
        return []
    uplift = min(stats["delivery_uplift"], stats["value_uplift"])
    return [
        Candidate(
            "delivery_volume_shift",
            1,
            clamp01(uplift / cfg.param("delivery_volume_shift", "magnitude_full_uplift")),
            bars[-1].public_at,
            bars[-1].trade_date.isoformat(),
            [{"table": "prices", "trade_date": bars[-1].trade_date.isoformat()}],
            jsonable({**stats, "threshold_uplift": min_uplift}),
        )
    ]


@detector("surveillance_entry")
def surveillance_entry(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    return [
        Candidate(
            "surveillance_entry",
            -1,
            cfg.param("surveillance_entry", "magnitude"),
            e.public_at,
            f"surveillance:{e.id}",
            [e.source_record],
            jsonable(
                {
                    "framework": e.payload["framework"],
                    "event": e.payload["event"],
                    "stage": e.payload["stage"],
                }
            ),
        )
        for e in ctx.surveillance
        if e.payload["event"] in ("entry", "stage_change")
    ]


@detector("surveillance_exit")
def surveillance_exit(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    return [
        Candidate(
            "surveillance_exit",
            1,
            cfg.param("surveillance_exit", "magnitude"),
            e.public_at,
            f"surveillance:{e.id}",
            [e.source_record],
            jsonable({"framework": e.payload["framework"], "event": e.payload["event"]}),
        )
        for e in ctx.surveillance
        if e.payload["event"] == "exit"
    ]


FUNDAMENTAL_TRIGGERS = ("revenue_acceleration", "margin_inflection")


@detector("price_lagging_fundamentals")
def price_lagging_fundamentals(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    window = int(cfg.param("price_lagging_fundamentals", "window_days"))
    active_days = cfg.param("price_lagging_fundamentals", "active_signal_days")
    cutoff = ctx.as_of - timedelta(days=active_days)
    triggers = [
        (t, at)
        for t, at in ctx.prior_signals
        if t in FUNDAMENTAL_TRIGGERS and cutoff < at <= ctx.as_of
    ]
    if not triggers:
        return []
    company_change = price_change(ctx.prices, ctx.as_of, window)
    sector_change = ctx.sector_price_change(window)
    if company_change is None or sector_change is None or company_change >= sector_change:
        return []
    gap = sector_change - company_change
    trigger_type, trigger_at = max(triggers, key=lambda x: x[1])
    return [
        Candidate(
            "price_lagging_fundamentals",
            1,
            clamp01(gap / cfg.param("price_lagging_fundamentals", "magnitude_full_gap")),
            ctx.as_of,
            f"trigger:{trigger_at.date().isoformat()}",
            [{"table": "prices", "window_days": window}],
            jsonable(
                {
                    "price_change_90d": company_change,
                    "sector_median_change_90d": sector_change,
                    "gap": gap,
                    "trigger_signal": trigger_type,
                    "trigger_public_at": trigger_at,
                }
            ),
        )
    ]


def _unused(_: datetime) -> None:  # keeps datetime import meaningful for type checkers
    return None
