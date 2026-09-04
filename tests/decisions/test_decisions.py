"""Decision-layer tests: narration, readiness and liquidity arithmetic."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from decisions.narrate import NARRATORS, narrate_signal, narrate_summary
from decisions.readiness import ReadinessInputs, assess_readiness, next_review_default
from decisions.sizing import liquidity_profile
from signals.config import load_catalogue

IST = ZoneInfo("Asia/Kolkata")
BANNED = ("buy", "sell", "target price", "recommendation")


def test_every_signal_type_has_a_sentence() -> None:
    assert set(NARRATORS) == set(load_catalogue().signals)


def test_narration_uses_the_detectors_numbers() -> None:
    s = narrate_signal("revenue_acceleration", {"yoy_growth_latest": 0.34, "excess_pp": 18.0})
    assert "34%" in s and "18pp" in s
    s = narrate_signal("order_win", {"order_value_cr": 120.0, "pct_of_ttm_revenue": 0.30})
    assert "Rs 120 crore" in s and "30%" in s
    s = narrate_signal("margin_inflection", {"delta_bp_latest": 420.0, "margin_latest": 0.17})
    assert "420bp" in s and "17.0%" in s
    assert "fell" in narrate_signal("margin_inflection", {"delta_bp_latest": -300.0})
    # Missing parameters degrade to the definition rather than inventing a figure.
    plain = narrate_signal("revenue_acceleration", {})
    assert "%" not in plain and plain.endswith(".")
    assert narrate_signal("not_a_signal", {}) == "Not a signal."


def test_narration_never_uses_trading_words() -> None:
    for stype in NARRATORS:
        text = narrate_signal(stype, {}).lower()
        for word in BANNED:
            assert word not in text, (stype, word)


def test_narrate_summary_ranks_by_magnitude() -> None:
    sigs = [
        ("order_win", {"order_value_cr": 10.0, "pct_of_ttm_revenue": 0.05}, 1, 0.2),
        ("margin_inflection", {"delta_bp_latest": 500.0}, 1, 0.9),
    ]
    assert narrate_summary(sigs, limit=1).startswith("Operating margin rose")
    assert narrate_summary([]) == "No signals in this window."


def _inputs(**kw: object) -> ReadinessInputs:
    base = dict(
        as_of=date(2026, 3, 31),
        latest_period_end=date(2025, 12, 31),
        latest_results_public_at=datetime(2026, 2, 10, tzinfo=IST),
        quarter_count=8,
        driving_signals=[("margin_inflection", 0), ("order_win", 2)],
        has_contradiction=True,
        forensic_flag_types=[],
        is_illiquid=False,
        median_traded_value=5e7,
        base_rates={"margin_inflection": (45, False), "order_win": (60, False)},
        data_quality_failures=0,
    )
    base.update(kw)
    return ReadinessInputs(**base)  # type: ignore[arg-type]


def test_readiness_ready_case() -> None:
    r = assess_readiness(_inputs())
    assert r.status == "ready" and not r.blocking
    assert r.headline == "Everything needed for a view is here."
    assert {c.key for c in r.checks} >= {
        "fundamentals",
        "history",
        "contradiction",
        "liquidity",
        "base_rate",
    }


def test_readiness_names_what_is_missing() -> None:
    stale = assess_readiness(_inputs(latest_period_end=date(2024, 12, 31)))
    assert stale.status == "not_ready"
    assert "days old" in stale.blocking[0].to_resolve

    thin = assess_readiness(_inputs(quarter_count=3))
    assert thin.status == "not_ready"
    history = next(c for c in thin.checks if c.key == "history")
    assert "2 more quarters" in history.to_resolve

    no_contra = assess_readiness(_inputs(has_contradiction=False))
    assert no_contra.status == "not_ready"
    assert any("case against is written" in c.to_resolve for c in no_contra.blocking)

    # Non-critical gaps degrade to "partial", not "not ready".
    flagged = assess_readiness(
        _inputs(forensic_flag_types=["audit_qualification"], is_illiquid=True)
    )
    assert flagged.status == "partial" and not flagged.blocking
    assert any("annual report" in c.to_resolve for c in flagged.checks)

    unknown = assess_readiness(_inputs(base_rates={}))
    assert unknown.status == "partial"
    assert any("one-off" in c.to_resolve for c in unknown.checks)


def test_readiness_serialises_and_defaults_a_review_date() -> None:
    payload = assess_readiness(_inputs()).to_json()
    assert payload["status"] == "ready" and payload["checks"][0]["key"] == "fundamentals"
    assert next_review_default(date(2026, 3, 31), date(2025, 12, 31)) == date(2026, 5, 15)
    assert next_review_default(date(2026, 3, 31), None) == date(2026, 5, 15)


def test_liquidity_profile_is_arithmetic() -> None:
    p = liquidity_profile([1e7] * 20)  # Rs 1 crore a day
    assert p.adv_inr == 1e7
    # 5% participation of Rs 1 crore = Rs 5 lakh a day; Rs 10 lakh therefore takes 2 days.
    assert p.comfortable_position_inr == 5e5
    assert p.days_to_exit["10L"] == 2.0 and p.days_to_exit["1L"] == 0.2
    assert p.round_trip_cost_pct is not None and 0 < p.round_trip_cost_pct < 0.05
    thin = liquidity_profile([2e5] * 20, illiquid=True)
    assert thin.days_to_exit["10L"] > p.days_to_exit["10L"] and thin.illiquid
    assert liquidity_profile([]).adv_inr is None
