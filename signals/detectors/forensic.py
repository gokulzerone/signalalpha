"""Forensic signals (PRD §6.2), all negative."""

from __future__ import annotations

import re
from datetime import timedelta

from signals.config import SignalCatalogue
from signals.context import DetectionContext
from signals.detectors.base import Candidate, clamp01, detector, jsonable, pct_change, year_before

SEVERE_OPINIONS = {"qualified", "going_concern", "adverse", "disclaimer"}
PROMOTER_DISCOUNT_RE = re.compile(r"promoter", re.IGNORECASE)
DISCOUNT_RE = re.compile(r"discount", re.IGNORECASE)


@detector("related_party_revenue")
def related_party_revenue(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    rows = [a for a in ctx.annuals if a.related_party_revenue is not None and a.revenue]
    if not rows:
        return []
    a = rows[-1]
    assert a.related_party_revenue is not None and a.revenue is not None
    share = float(a.related_party_revenue / a.revenue)
    min_share = cfg.param("related_party_revenue", "min_share")
    if share < min_share:
        return []
    return [
        Candidate(
            "related_party_revenue",
            -1,
            clamp01(share / cfg.param("related_party_revenue", "magnitude_full_share")),
            a.public_at,
            a.period_end.isoformat(),
            [a.source_record],
            jsonable(
                {
                    "related_party_revenue": a.related_party_revenue,
                    "revenue": a.revenue,
                    "share": share,
                    "threshold_share": min_share,
                    "period_end": a.period_end,
                }
            ),
        )
    ]


@detector("receivables_outrunning_revenue")
def receivables_outrunning_revenue(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    rows = [a for a in ctx.annuals if a.receivables is not None and a.revenue]
    if len(rows) < 3:
        return []
    gaps: list[float] = []
    for prev, cur in ((rows[-3], rows[-2]), (rows[-2], rows[-1])):
        rec_g = pct_change(cur.receivables, prev.receivables)
        rev_g = pct_change(cur.revenue, prev.revenue)
        if rec_g is None or rev_g is None:
            return []
        gaps.append(rec_g - rev_g)
    min_gap = cfg.param("receivables_outrunning_revenue", "min_gap")
    if any(g < min_gap for g in gaps):
        return []
    a = rows[-1]
    return [
        Candidate(
            "receivables_outrunning_revenue",
            -1,
            clamp01(min(gaps) / cfg.param("receivables_outrunning_revenue", "magnitude_full_gap")),
            a.public_at,
            a.period_end.isoformat(),
            [r.source_record for r in rows[-3:]],
            jsonable(
                {
                    "gap_latest": gaps[1],
                    "gap_previous": gaps[0],
                    "threshold_gap": min_gap,
                    "period_end": a.period_end,
                }
            ),
        )
    ]


@detector("cash_vs_debt_anomaly")
def cash_vs_debt_anomaly(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    bps = [
        p for p in ctx.balance_periods if p.cash is not None and p.short_term_borrowings is not None
    ]
    if not bps:
        return []
    now = bps[-1]
    prior = next((p for p in bps if p.period_end == year_before(now.period_end)), None)
    ttm = ctx.ttm_revenue(now.period_end)
    if prior is None or ttm is None or ttm <= 0:
        return []
    assert now.cash is not None
    cash_ratio = float(now.cash / ttm)
    st_growth = pct_change(now.short_term_borrowings, prior.short_term_borrowings)
    min_cash = cfg.param("cash_vs_debt_anomaly", "min_cash_to_revenue")
    min_growth = cfg.param("cash_vs_debt_anomaly", "min_st_debt_growth")
    if st_growth is None or cash_ratio < min_cash or st_growth < min_growth:
        return []
    return [
        Candidate(
            "cash_vs_debt_anomaly",
            -1,
            clamp01(st_growth / cfg.param("cash_vs_debt_anomaly", "magnitude_full_growth")),
            now.public_at,
            now.period_end.isoformat(),
            [now.source_record, prior.source_record],
            jsonable(
                {
                    "cash": now.cash,
                    "cash_to_ttm_revenue": cash_ratio,
                    "short_term_borrowings": now.short_term_borrowings,
                    "short_term_borrowings_previous": prior.short_term_borrowings,
                    "st_debt_growth": st_growth,
                    "threshold_cash_ratio": min_cash,
                    "threshold_growth": min_growth,
                    "period_end": now.period_end,
                }
            ),
        )
    ]


@detector("audit_qualification")
def audit_qualification(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    rows = [a for a in ctx.annuals if a.audit_opinion is not None]
    if not rows:
        return []
    a = rows[-1]
    opinion = a.audit_opinion
    if opinion == "unqualified":
        return []
    magnitude = (
        1.0
        if opinion in SEVERE_OPINIONS
        else cfg.param("audit_qualification", "emphasis_magnitude")
    )
    return [
        Candidate(
            "audit_qualification",
            -1,
            magnitude,
            a.public_at,
            a.period_end.isoformat(),
            [a.source_record],
            jsonable({"audit_opinion": opinion, "period_end": a.period_end}),
        )
    ]


@detector("contingent_liability_spike")
def contingent_liability_spike(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    rows = [a for a in ctx.annuals if a.contingent_liabilities is not None and a.revenue]
    if len(rows) < 2:
        return []
    now, prev = rows[-1], rows[-2]
    assert (
        now.contingent_liabilities is not None
        and now.revenue is not None
        and prev.contingent_liabilities is not None
    )
    share = float(now.contingent_liabilities / now.revenue)
    ratio = (
        float(now.contingent_liabilities / prev.contingent_liabilities)
        if prev.contingent_liabilities > 0
        else float("inf")
    )
    min_share = cfg.param("contingent_liability_spike", "min_share")
    min_ratio = cfg.param("contingent_liability_spike", "min_ratio")
    if share < min_share or ratio < min_ratio:
        return []
    return [
        Candidate(
            "contingent_liability_spike",
            -1,
            clamp01(share / cfg.param("contingent_liability_spike", "magnitude_full_share")),
            now.public_at,
            now.period_end.isoformat(),
            [now.source_record, prev.source_record],
            jsonable(
                {
                    "contingent_liabilities": now.contingent_liabilities,
                    "contingent_liabilities_previous": prev.contingent_liabilities,
                    "share_of_revenue": share,
                    "ratio_to_previous": ratio if ratio != float("inf") else None,
                    "threshold_share": min_share,
                    "threshold_ratio": min_ratio,
                    "period_end": now.period_end,
                }
            ),
        )
    ]


def _is_promoter_discounted_raise(
    ctx: DetectionContext, summary: str, raw_document_id: int
) -> bool:
    if "to_promoters=true" in summary and "discount" in summary:
        return True
    text = ctx.document_text(raw_document_id) or ""
    return bool(
        PROMOTER_DISCOUNT_RE.search(text)
        and DISCOUNT_RE.search(text)
        and re.search(r"warrant|preferential", text, re.IGNORECASE)
    )


@detector("frequent_fund_raise")
def frequent_fund_raise(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    raises = [
        a
        for a in ctx.announcements
        if a.payload.get("category") == "fund_raise"
        and _is_promoter_discounted_raise(ctx, a.payload.get("summary", ""), a.raw_document_id)
    ]
    if len(raises) < 2:
        return []
    lookback = timedelta(days=cfg.param("frequent_fund_raise", "lookback_days"))
    out: list[Candidate] = []
    for i, a in enumerate(raises):
        within = [r for r in raises[: i + 1] if r.public_at > a.public_at - lookback]
        if len(within) < 2:
            continue
        out.append(
            Candidate(
                "frequent_fund_raise",
                -1,
                cfg.param("frequent_fund_raise", "magnitude"),
                a.public_at,
                f"announcement:{a.id}",
                [r.source_record for r in within],
                jsonable(
                    {
                        "raises_in_lookback": len(within),
                        "lookback_days": lookback.days,
                        "subjects": [r.payload.get("subject", "") for r in within],
                    }
                ),
            )
        )
    return out
