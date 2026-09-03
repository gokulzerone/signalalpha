from __future__ import annotations

from scoring.config import load_score_config
from scoring.valuation import (
    SPEC,
    ScenarioAssumptions,
    ScenarioInputs,
    compute_scenario,
    default_assumptions,
    within_bounds,
)

CFG = load_score_config()


def test_scenario_arithmetic_hand_checked() -> None:
    inputs = ScenarioInputs(
        ttm_revenue=400.0,
        ttm_ebitda=60.0,
        net_debt=40.0,
        shares_outstanding_cr=10.0,
        price=90.0,
        trailing_revenue_growth=0.1,
        current_ev_ebitda=15.0,
    )
    a = ScenarioAssumptions(
        name="base", revenue_growth=0.10, ebitda_margin=0.15, exit_ev_ebitda=12.0, horizon_years=2
    )
    r = compute_scenario(inputs, a)
    assert abs(r.forward_revenue - 484.0) < 1e-9
    assert abs(r.forward_ebitda - 72.6) < 1e-9
    assert abs(r.enterprise_value - 871.2) < 1e-9
    assert abs(r.equity_value - 831.2) < 1e-9
    assert abs(r.value_per_share - 83.12) < 1e-9
    assert abs(r.implied_change_vs_price - (83.12 / 90 - 1)) < 1e-12
    assert SPEC["steps"][0] == {
        "forward_revenue": "ttm_revenue * (1 + revenue_growth) ** horizon_years"
    }


def test_defaults_and_bounds() -> None:
    inputs = ScenarioInputs(400.0, 60.0, 40.0, 10.0, 90.0, 0.1, 15.0)
    bear, base, bull = default_assumptions(inputs, CFG)
    assert bear.revenue_growth < base.revenue_growth < bull.revenue_growth
    assert base.ebitda_margin == 0.15 and base.exit_ev_ebitda == 15.0
    assert within_bounds(base, CFG.valuation_scenarios) == []
    wild = ScenarioAssumptions(
        name="bull", revenue_growth=3.0, ebitda_margin=0.9, exit_ev_ebitda=200.0, horizon_years=9
    )
    problems = within_bounds(wild, CFG.valuation_scenarios)
    assert len(problems) == 4 and all("outside" in p for p in problems)
