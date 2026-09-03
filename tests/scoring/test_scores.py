"""Unit and property-based tests for score functions (PRD §14)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from scoring.config import load_score_config
from scoring.inputs import CompanyInputs, ScoreInputs, SignalView, UniverseInputs
from scoring.scores import (
    CrossSection,
    ScoreResult,
    attention_gap,
    inflection,
    opportunity,
    percentile_ranks,
    quality,
    risk,
    risk_penalty,
    score_company,
    valuation,
)

CFG = load_score_config()
AS_OF = date(2025, 3, 31)
IST = ZoneInfo("Asia/Kolkata")


def company(cid: int, **kw: object) -> CompanyInputs:
    base = CompanyInputs(
        company_id=cid, sector="S", market_cap_cr=1000.0, in_universe=True, is_illiquid=False
    )
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def sig(
    sid: int, stype: str, family: str, direction: int, magnitude: float, days_ago: int
) -> SignalView:
    return SignalView(
        sid,
        stype,
        family,
        direction,
        magnitude,
        datetime(2025, 3, 31, 12, tzinfo=IST) - timedelta(days=days_ago),
    )


def universe(*cs: CompanyInputs) -> UniverseInputs:
    return UniverseInputs(as_of=AS_OF, companies={c.company_id: c for c in cs})


def test_percentile_ranks_hand_checked() -> None:
    assert percentile_ranks({1: 10.0, 2: 20.0, 3: 30.0}) == {1: 0.0, 2: 50.0, 3: 100.0}
    assert percentile_ranks({1: 10.0, 2: 20.0, 3: 30.0}, higher_is_better=False) == {
        1: 100.0,
        2: 50.0,
        3: 0.0,
    }
    assert percentile_ranks({1: 5.0, 2: 5.0, 3: 9.0}) == {1: 0.0, 2: 0.0, 3: 100.0}
    assert percentile_ranks({1: 5.0, 2: 5.0, 3: 9.0}, higher_is_better=False) == {
        1: 50.0,
        2: 50.0,
        3: 0.0,
    }
    assert percentile_ranks({1: 5.0, 2: None}) == {1: 50.0, 2: None}
    assert percentile_ranks({}) == {}


def test_inflection_recency_weighting_and_bonus() -> None:
    a = company(1, signals=[sig(1, "revenue_acceleration", "financial", 1, 1.0, 0)])
    b = company(
        2, signals=[sig(2, "revenue_acceleration", "financial", 1, 1.0, 90)]
    )  # one half-life old
    c = company(
        3,
        signals=[
            sig(3, "revenue_acceleration", "financial", 1, 0.5, 0),
            sig(4, "order_win", "business", 1, 0.5, 0),
        ],
    )
    d = company(4, signals=[sig(5, "audit_qualification", "forensic", -1, 1.0, 0)])
    u = universe(a, b, c, d)
    xs = CrossSection(u)
    ra = inflection(ScoreInputs(1, u), CFG, AS_OF, xs)
    rb = inflection(ScoreInputs(2, u), CFG, AS_OF, xs)
    rc = inflection(ScoreInputs(3, u), CFG, AS_OF, xs)
    rd = inflection(ScoreInputs(4, u), CFG, AS_OF, xs)
    assert abs(rb.components["recency_weighted_positive_magnitude"].raw - 0.5) < 0.01  # type: ignore[operator]
    assert (
        rc.intermediates["families_agreeing"] == 2
        and rc.intermediates["consistency_multiplier"] == 1.25
    )
    assert abs(rc.components["recency_weighted_positive_magnitude"].raw - 1.25) < 0.01  # type: ignore[operator]
    assert rc.value == 100.0 and ra.value > rb.value > rd.value == 0.0  # type: ignore[operator]
    assert rc.signal_ids == [3, 4] and rd.signal_ids == []


def test_quality_weights_and_forensic_penalty() -> None:
    good = company(
        1, roce_3y=0.25, cfo_to_ebitda_ttm=0.9, receivable_days_trend=-5.0, promoter_pct=60.0
    )
    mid = company(
        2, roce_3y=0.15, cfo_to_ebitda_ttm=0.7, receivable_days_trend=0.0, promoter_pct=50.0
    )
    bad = company(
        3,
        roce_3y=0.05,
        cfo_to_ebitda_ttm=0.2,
        receivable_days_trend=20.0,
        promoter_pct=30.0,
        signals=[sig(1, "audit_qualification", "forensic", -1, 1.0, 10)],
    )
    flagged_good = company(
        4,
        roce_3y=0.25,
        cfo_to_ebitda_ttm=0.9,
        receivable_days_trend=-5.0,
        promoter_pct=60.0,
        signals=[sig(2, "related_party_revenue", "forensic", -1, 0.8, 30)],
    )
    u = universe(good, mid, bad, flagged_good)
    xs = CrossSection(u)
    r_good = quality(ScoreInputs(1, u), CFG, AS_OF, xs)
    r_bad = quality(ScoreInputs(3, u), CFG, AS_OF, xs)
    r_flag = quality(ScoreInputs(4, u), CFG, AS_OF, xs)
    # good and flagged_good tie on every metric: two strictly below -> 66.67; x0.7 if flagged
    assert abs(r_good.intermediates["weighted_percentile"] - 66.6667) < 0.01
    assert r_good.value == r_good.intermediates["weighted_percentile"]
    assert abs(r_flag.value - r_good.value * 0.7) < 1e-9  # type: ignore[operator]
    assert r_flag.intermediates["penalties"] == {"related_party_revenue": 0.7}
    assert r_bad.value == 0.0 and r_bad.intermediates["penalty_multiplier"] == 0.5
    assert sum(c.weight for c in r_good.components.values()) == 1.0
    assert all(c.contribution is not None for c in r_good.components.values())


def test_quality_renormalises_missing_components() -> None:
    a = company(
        1, roce_3y=0.2, cfo_to_ebitda_ttm=None, receivable_days_trend=None, promoter_pct=60.0
    )
    b = company(
        2, roce_3y=0.1, cfo_to_ebitda_ttm=None, receivable_days_trend=None, promoter_pct=40.0
    )
    u = universe(a, b)
    r = quality(ScoreInputs(1, u), CFG, AS_OF)
    assert r.value is not None and abs(r.value - 100.0) < 1e-9
    assert r.components["cfo_to_ebitda_ttm"].percentile is None


def test_valuation_lower_multiples_score_higher() -> None:
    cheap = company(
        1,
        ev_ebitda=5.0,
        pe=8.0,
        ev_ebitda_own_median=8.0,
        pe_own_median=12.0,
        peg_trailing=0.5,
        sector_ev_ebitda_median=8.0,
        sector_pe_median=12.0,
    )
    dear = company(
        2,
        ev_ebitda=15.0,
        pe=30.0,
        ev_ebitda_own_median=8.0,
        pe_own_median=12.0,
        peg_trailing=2.0,
        sector_ev_ebitda_median=8.0,
        sector_pe_median=12.0,
    )
    lossmaking = company(
        3, ev_ebitda=None, pe=None, sector_ev_ebitda_median=8.0, sector_pe_median=12.0
    )
    u = universe(cheap, dear, lossmaking)
    assert valuation(ScoreInputs(1, u), CFG, AS_OF).value == 100.0
    assert valuation(ScoreInputs(2, u), CFG, AS_OF).value == 0.0
    assert valuation(ScoreInputs(3, u), CFG, AS_OF).value is None


def test_risk_higher_is_worse() -> None:
    safe = company(
        1,
        pledge_pct=0.0,
        median_traded_value=5e7,
        surveillance_stage=0,
        audit_qualification=0.0,
        volatility_90d=0.2,
    )
    risky = company(
        2,
        pledge_pct=60.0,
        median_traded_value=5e5,
        surveillance_stage=1,
        audit_qualification=1.0,
        volatility_90d=0.6,
        signals=[
            sig(1, "cash_vs_debt_anomaly", "forensic", -1, 1.0, 5),
            sig(2, "pledge_increase", "ownership", -1, 0.5, 5),
            sig(3, "key_person_exit", "business", -1, 0.7, 5),
        ],
    )
    u = universe(safe, risky)
    r_safe, r_risky = risk(ScoreInputs(1, u), CFG, AS_OF), risk(ScoreInputs(2, u), CFG, AS_OF)
    assert r_safe.value == 0.0 and r_risky.value == 100.0
    assert (
        r_risky.components["forensic_severity"].raw == 1.0
        and r_risky.components["negative_ownership"].raw == 1.0
    )
    assert r_risky.components["key_person_exits"].raw == 1.0 and sorted(r_risky.signal_ids) == [
        1,
        2,
    ]


def test_attention_gap() -> None:
    hidden = company(
        1,
        institutional_pct=0.0,
        turnover=0.0002,
        days_since_reaction=730.0,
        annual_report_chars=20000,
        sector_report_chars_median=10000.0,
        signals=[sig(1, "price_lagging_fundamentals", "market", 1, 0.8, 10)],
    )
    crowded = company(
        2,
        institutional_pct=12.0,
        turnover=0.01,
        days_since_reaction=5.0,
        annual_report_chars=8000,
        sector_report_chars_median=10000.0,
    )
    u = universe(hidden, crowded)
    assert attention_gap(ScoreInputs(1, u), CFG, AS_OF).value == 100.0
    assert attention_gap(ScoreInputs(2, u), CFG, AS_OF).value == 0.0


def _result(name: str, value: float | None) -> ScoreResult:
    return ScoreResult(name, 1, AS_OF, value)


def test_opportunity_form_and_risk_penalty() -> None:
    scores = {k: _result(k, 50.0) for k in ("inflection", "quality", "valuation", "attention_gap")}
    scores["risk"] = _result("risk", 20.0)
    r = opportunity(scores, CFG, AS_OF)
    assert abs(r.value - 50.0) < 1e-9 and r.intermediates["risk_penalty"] == 0.0  # type: ignore[operator]
    scores["risk"] = _result("risk", 70.0)  # halfway between start 40 and full 100 -> 0.4 penalty
    r = opportunity(scores, CFG, AS_OF)
    assert abs(r.value - 30.0) < 1e-9  # type: ignore[operator]
    assert risk_penalty(100.0, CFG) == 0.8 and risk_penalty(None, CFG) == 0.0
    scores["quality"] = _result("quality", 0.0)
    assert opportunity(scores, CFG, AS_OF).value == 0.0
    scores["quality"] = _result("quality", None)
    r = opportunity(scores, CFG, AS_OF)
    assert r.value == 0.0 and r.intermediates["zero_or_missing_components"] == ["quality"]


# ------------------------------------------------------------ property tests
scores_st = st.one_of(st.none(), st.floats(min_value=0, max_value=100))


@given(st.lists(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False), min_size=1, max_size=40))
def test_percentiles_are_within_bounds(values: list[float]) -> None:
    ranks = percentile_ranks(dict(enumerate(values)))
    assert all(r is not None and 0.0 <= r <= 100.0 for r in ranks.values())


@given(inf=scores_st, q=scores_st, v=scores_st, a=scores_st, r=scores_st)
def test_opportunity_zero_when_any_component_zero_or_missing(
    inf: float | None, q: float | None, v: float | None, a: float | None, r: float | None
) -> None:
    scores = {
        "inflection": _result("inflection", inf),
        "quality": _result("quality", q),
        "valuation": _result("valuation", v),
        "attention_gap": _result("attention_gap", a),
        "risk": _result("risk", r),
    }
    value = opportunity(scores, CFG, AS_OF).value
    assert value is not None and 0.0 <= value <= 100.0
    if any(x is None or x == 0 for x in (inf, q, v, a)):
        assert value == 0.0


@settings(max_examples=60, deadline=None)
@given(
    base=st.lists(st.floats(min_value=0, max_value=1), min_size=2, max_size=6),
    extra=st.floats(min_value=0.01, max_value=1.0),
)
def test_more_positive_signals_never_lower_inflection(base: list[float], extra: float) -> None:
    companies = [
        company(i + 1, signals=[sig(i * 10 + 1, "revenue_acceleration", "financial", 1, m, 30)])
        for i, m in enumerate(base)
    ]
    u = universe(*companies)
    before = inflection(ScoreInputs(1, u), CFG, AS_OF).value
    companies[0].signals.append(sig(999, "order_win", "business", 1, extra, 10))
    after = inflection(ScoreInputs(1, u), CFG, AS_OF).value
    assert before is not None and after is not None and after >= before


def test_score_company_returns_all_six_with_components() -> None:
    a = company(
        1,
        roce_3y=0.2,
        cfo_to_ebitda_ttm=0.8,
        receivable_days_trend=1.0,
        promoter_pct=55.0,
        ev_ebitda=6.0,
        pe=10.0,
        sector_ev_ebitda_median=8.0,
        sector_pe_median=12.0,
        pledge_pct=0.0,
        median_traded_value=1e7,
        volatility_90d=0.3,
        institutional_pct=1.0,
        turnover=0.001,
        days_since_reaction=100.0,
        signals=[sig(1, "margin_inflection", "financial", 1, 0.6, 20)],
    )
    b = company(
        2,
        roce_3y=0.1,
        cfo_to_ebitda_ttm=0.5,
        receivable_days_trend=10.0,
        promoter_pct=45.0,
        ev_ebitda=9.0,
        pe=15.0,
        sector_ev_ebitda_median=8.0,
        sector_pe_median=12.0,
        pledge_pct=10.0,
        median_traded_value=5e6,
        volatility_90d=0.4,
        institutional_pct=3.0,
        turnover=0.002,
        days_since_reaction=10.0,
    )
    results = score_company(ScoreInputs(1, universe(a, b)), CFG, AS_OF)
    assert set(results) == {
        "inflection",
        "quality",
        "valuation",
        "risk",
        "attention_gap",
        "opportunity",
    }
    for r in results.values():
        assert r.components and r.config_version == CFG.version
        assert r.value is not None and 0 <= r.value <= 100
