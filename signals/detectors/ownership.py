"""Ownership signals (PRD §6.2)."""

from __future__ import annotations

from decimal import Decimal

from signals.config import SignalCatalogue
from signals.context import DetectionContext
from signals.detectors.base import Candidate, clamp01, detector, jsonable

CRORE = Decimal(10_000_000)
PROMOTER_CATEGORIES = {"promoter", "promoter_group"}


def _stake_change(
    ctx: DetectionContext, cfg: SignalCatalogue, signal_type: str, sign: int
) -> list[Candidate]:
    out: list[Candidate] = []
    h = ctx.holdings
    min_pp = cfg.param(signal_type, "min_pp")
    if len(h) >= 2:
        delta = float(h[-1].promoter_pct - h[-2].promoter_pct)
        if sign * delta >= min_pp:
            out.append(
                Candidate(
                    signal_type,
                    sign,
                    clamp01(abs(delta) / cfg.param(signal_type, "magnitude_full_pp")),
                    h[-1].public_at,
                    h[-1].period_end.isoformat(),
                    [h[-1].source_record, h[-2].source_record],
                    jsonable(
                        {
                            "promoter_pct": h[-1].promoter_pct,
                            "promoter_pct_previous": h[-2].promoter_pct,
                            "change_pp": delta,
                            "threshold_pp": min_pp,
                            "trigger": "shareholding_pattern",
                        }
                    ),
                )
            )
    side = "buy" if sign > 0 else "sell"
    min_value = Decimal(str(cfg.param(signal_type, "min_value_cr"))) * CRORE
    for t in ctx.insider_trades:
        p = t.payload
        if p["side"] != side or p["mode"] != "market" or p["category"] not in PROMOTER_CATEGORIES:
            continue
        value: Decimal = p["value_inr"]
        if value < min_value:
            continue
        out.append(
            Candidate(
                signal_type,
                sign,
                clamp01(float(value / CRORE) / cfg.param(signal_type, "magnitude_full_value_cr")),
                t.public_at,
                f"insider:{t.id}",
                [t.source_record],
                jsonable(
                    {
                        "value_cr": value / CRORE,
                        "threshold_cr": min_value / CRORE,
                        "trigger": "insider_trade",
                        "side": side,
                    }
                ),
                evidence=[],
            )
        )
    return out


@detector("promoter_stake_increase")
def promoter_stake_increase(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    return _stake_change(ctx, cfg, "promoter_stake_increase", 1)


@detector("promoter_stake_decrease")
def promoter_stake_decrease(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    return _stake_change(ctx, cfg, "promoter_stake_decrease", -1)


def _pledge_change(
    ctx: DetectionContext, cfg: SignalCatalogue, signal_type: str, sign: int, event_type: str
) -> list[Candidate]:
    out: list[Candidate] = []
    h = ctx.holdings
    min_pp = cfg.param(signal_type, "min_pp")
    full = cfg.param(signal_type, "magnitude_full_pp")
    if len(h) >= 2:
        delta = float(h[-1].pledged_pct - h[-2].pledged_pct)  # negative = reduction
        if -sign * delta >= min_pp:
            out.append(
                Candidate(
                    signal_type,
                    sign,
                    clamp01(abs(delta) / full),
                    h[-1].public_at,
                    h[-1].period_end.isoformat(),
                    [h[-1].source_record, h[-2].source_record],
                    jsonable(
                        {
                            "pledged_pct": h[-1].pledged_pct,
                            "pledged_pct_previous": h[-2].pledged_pct,
                            "change_pp": delta,
                            "threshold_pp": min_pp,
                            "trigger": "shareholding_pattern",
                        }
                    ),
                )
            )
    for e in ctx.pledge_events:
        if e.payload["event_type"] != event_type:
            continue
        pct = float(e.payload["pct_of_promoter_holding"])
        if pct < min_pp:
            continue
        out.append(
            Candidate(
                signal_type,
                sign,
                clamp01(pct / full),
                e.public_at,
                f"pledge:{e.id}",
                [e.source_record],
                jsonable(
                    {
                        "pct_of_promoter_holding": pct,
                        "pct_of_total_shares": e.payload["pct_of_total_shares"],
                        "threshold_pp": min_pp,
                        "trigger": "pledge_disclosure",
                    }
                ),
            )
        )
    return out


@detector("pledge_reduction")
def pledge_reduction(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    return _pledge_change(ctx, cfg, "pledge_reduction", 1, "release")


@detector("pledge_increase")
def pledge_increase(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    return _pledge_change(ctx, cfg, "pledge_increase", -1, "creation")


@detector("pledge_invocation")
def pledge_invocation(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    full = cfg.param("pledge_invocation", "magnitude_full_pp")
    return [
        Candidate(
            "pledge_invocation",
            -1,
            clamp01(float(e.payload["pct_of_promoter_holding"]) / full),
            e.public_at,
            f"pledge:{e.id}",
            [e.source_record],
            jsonable(
                {
                    "pct_of_promoter_holding": e.payload["pct_of_promoter_holding"],
                    "trigger": "pledge_disclosure",
                }
            ),
        )
        for e in ctx.pledge_events
        if e.payload["event_type"] == "invocation"
    ]


@detector("institutional_entry")
def institutional_entry(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    out: list[Candidate] = []
    min_pct = cfg.param("institutional_entry", "min_pct")
    full = cfg.param("institutional_entry", "magnitude_full_pct")
    h = ctx.holdings
    if h:
        previous_names = {name for name, _, _ in h[-2].holders} if len(h) >= 2 else set()
        for name, category, pct in h[-1].holders:
            if name in previous_names or float(pct) < min_pct:
                continue
            out.append(
                Candidate(
                    "institutional_entry",
                    1,
                    clamp01(float(pct) / full),
                    h[-1].public_at,
                    f"{h[-1].period_end.isoformat()}:{name[:30]}",
                    [h[-1].source_record],
                    jsonable(
                        {
                            "holder": name,
                            "category": category,
                            "pct": pct,
                            "threshold_pct": min_pct,
                            "trigger": "shareholding_pattern",
                        }
                    ),
                )
            )
    keywords = [k.lower() for k in cfg.institution_keywords]
    for b in ctx.bulk_deals:
        client = str(b.payload["client_name"]).lower()
        if b.payload["side"] != "buy" or not any(k in client for k in keywords):
            continue
        out.append(
            Candidate(
                "institutional_entry",
                1,
                0.5,
                b.public_at,
                f"bulk:{b.id}",
                [b.source_record],
                jsonable(
                    {
                        "holder": b.payload["client_name"],
                        "value_inr": b.payload["value_inr"],
                        "trigger": "bulk_deal",
                    }
                ),
            )
        )
    return out


@detector("shareholder_count_spike")
def shareholder_count_spike(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    h = ctx.holdings
    if len(h) < 2 or h[-2].retail_shareholders <= 0:
        return []
    growth = h[-1].retail_shareholders / h[-2].retail_shareholders - 1
    min_growth = cfg.param("shareholder_count_spike", "min_growth")
    if growth < min_growth:
        return []
    return [
        Candidate(
            "shareholder_count_spike",
            -1,
            clamp01(growth / cfg.param("shareholder_count_spike", "magnitude_full_growth")),
            h[-1].public_at,
            h[-1].period_end.isoformat(),
            [h[-1].source_record, h[-2].source_record],
            jsonable(
                {
                    "retail_shareholders": h[-1].retail_shareholders,
                    "retail_shareholders_previous": h[-2].retail_shareholders,
                    "growth": growth,
                    "threshold": min_growth,
                }
            ),
        )
    ]
