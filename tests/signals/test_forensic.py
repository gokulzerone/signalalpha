from __future__ import annotations

from signals.config import load_catalogue
from signals.detectors.forensic import (
    audit_qualification,
    cash_vs_debt_anomaly,
    contingent_liability_spike,
    frequent_fund_raise,
    receivables_outrunning_revenue,
    related_party_revenue,
)
from tests.signals.helpers import event, make_ctx, period, public, qend, quarters

CFG = load_catalogue()


def annual(i: int, **kw: float | str | None) -> object:
    return period(qend(i), months=12, **kw)  # type: ignore[arg-type]


def test_related_party_revenue() -> None:
    [sig] = related_party_revenue(
        make_ctx(annuals=[period(qend(3), months=12, revenue=400, related_party_revenue=100)]), CFG
    )
    assert sig.direction == -1 and sig.parameters["share"] == 0.25
    assert (
        related_party_revenue(
            make_ctx(annuals=[period(qend(3), months=12, revenue=400, related_party_revenue=10)]),
            CFG,
        )
        == []
    )


def test_receivables_outrunning_revenue() -> None:
    bad = [
        period(qend(3), months=12, revenue=400, receivables=80),
        period(qend(7), months=12, revenue=440, receivables=130),
        period(qend(11), months=12, revenue=480, receivables=200),
    ]
    [sig] = receivables_outrunning_revenue(make_ctx(annuals=bad), CFG)
    assert sig.parameters["gap_latest"] >= 0.15
    ok = [
        period(qend(3), months=12, revenue=400, receivables=80),
        period(qend(7), months=12, revenue=440, receivables=90),
        period(qend(11), months=12, revenue=480, receivables=200),
    ]
    assert receivables_outrunning_revenue(make_ctx(annuals=ok), CFG) == []  # only one bad year


def test_cash_vs_debt_anomaly() -> None:
    q = quarters([100.0] * 12)
    prev = period(
        qend(3),
        months=12,
        revenue=400,
        receivables=50,
        cash=90,
        short_term_borrowings=40,
        total_borrowings=60,
    )
    now = period(
        qend(7),
        months=12,
        revenue=400,
        receivables=50,
        cash=95,
        short_term_borrowings=70,
        total_borrowings=90,
    )
    [sig] = cash_vs_debt_anomaly(make_ctx(quarters=q, annuals=[prev, now]), CFG)
    assert (
        sig.parameters["st_debt_growth"] == 0.75 and sig.parameters["cash_to_ttm_revenue"] >= 0.15
    )
    low_cash = period(
        qend(7),
        months=12,
        revenue=400,
        receivables=50,
        cash=20,
        short_term_borrowings=70,
        total_borrowings=90,
    )
    assert cash_vs_debt_anomaly(make_ctx(quarters=q, annuals=[prev, low_cash]), CFG) == []


def test_audit_qualification() -> None:
    assert (
        audit_qualification(
            make_ctx(annuals=[period(qend(3), months=12, audit_opinion="unqualified")]), CFG
        )
        == []
    )
    [eom] = audit_qualification(
        make_ctx(annuals=[period(qend(3), months=12, audit_opinion="emphasis_of_matter")]), CFG
    )
    [qual] = audit_qualification(
        make_ctx(annuals=[period(qend(3), months=12, audit_opinion="qualified")]), CFG
    )
    assert eom.magnitude == 0.5 and qual.magnitude == 1.0


def test_contingent_liability_spike() -> None:
    prev = period(qend(3), months=12, revenue=400, contingent_liabilities=10)
    spike = period(qend(7), months=12, revenue=400, contingent_liabilities=60)
    [sig] = contingent_liability_spike(make_ctx(annuals=[prev, spike]), CFG)
    assert sig.parameters["ratio_to_previous"] == 6.0
    mild = period(qend(7), months=12, revenue=400, contingent_liabilities=15)
    assert contingent_liability_spike(make_ctx(annuals=[prev, mild]), CFG) == []


def test_frequent_fund_raise() -> None:
    first = event(
        "announcements",
        public(qend(1), 5),
        category="fund_raise",
        subject="Warrants",
        summary="to_promoters=true;discount_pct=18",
    )
    second = event(
        "announcements",
        public(qend(5), 5),
        category="fund_raise",
        subject="Warrants",
        summary="to_promoters=true;discount_pct=15",
    )
    sigs = frequent_fund_raise(make_ctx(announcements=[first, second]), CFG)
    assert [s.dedupe_key for s in sigs] == [f"announcement:{second.id}"] and sigs[0].parameters[
        "raises_in_lookback"
    ] == 2
    assert frequent_fund_raise(make_ctx(announcements=[first]), CFG) == []
    far = event(
        "announcements",
        public(qend(13), 5),
        category="fund_raise",
        subject="Warrants",
        summary="to_promoters=true;discount_pct=15",
    )
    assert frequent_fund_raise(make_ctx(announcements=[first, far]), CFG) == []
    qip = event(
        "announcements", public(qend(5), 6), 941, category="fund_raise", subject="QIP", summary=""
    )
    assert (
        frequent_fund_raise(
            make_ctx(
                announcements=[first, qip],
                texts={941: "Qualified institutions placement at market price."},
            ),
            CFG,
        )
        == []
    )
