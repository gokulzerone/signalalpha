"""Valuation scenarios (PRD §7 Valuation agent, §12.2 section 7).

The LLM only proposes *assumption parameters*; every number here is computed in Python.
The formula is also served as a JSON spec so the frontend recomputes with the same steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from scoring.config import ScoreConfig, ValuationScenarioConfig


class ScenarioAssumptions(BaseModel):
    name: str = Field(pattern="^(bear|base|bull)$")
    revenue_growth: float
    """Annual revenue growth applied for ``horizon_years``."""
    ebitda_margin: float
    exit_ev_ebitda: float
    horizon_years: int = 2
    rationale: str = ""


@dataclass(frozen=True)
class ScenarioInputs:
    ttm_revenue: float
    ttm_ebitda: float
    net_debt: float
    shares_outstanding_cr: float
    price: float
    trailing_revenue_growth: float | None
    current_ev_ebitda: float | None


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    assumptions: ScenarioAssumptions
    forward_revenue: float
    forward_ebitda: float
    enterprise_value: float
    equity_value: float
    value_per_share: float
    implied_change_vs_price: float
    implied_annualised_change: float


SPEC: dict[str, Any] = {
    "version": "valuation-v1",
    "inputs": ["ttm_revenue", "ttm_ebitda", "net_debt", "shares_outstanding_cr", "price"],
    "parameters": ["revenue_growth", "ebitda_margin", "exit_ev_ebitda", "horizon_years"],
    "steps": [
        {"forward_revenue": "ttm_revenue * (1 + revenue_growth) ** horizon_years"},
        {"forward_ebitda": "forward_revenue * ebitda_margin"},
        {"enterprise_value": "forward_ebitda * exit_ev_ebitda"},
        {"equity_value": "enterprise_value - net_debt"},
        {"value_per_share": "equity_value / shares_outstanding_cr"},
        {"implied_change_vs_price": "value_per_share / price - 1"},
        {"implied_annualised_change": "(1 + implied_change_vs_price) ** (1 / horizon_years) - 1"},
    ],
    "units": {"money": "INR crore", "shares": "crore", "price": "INR"},
    "note": "Research scenarios, not forecasts or advice.",
}


def compute_scenario(inputs: ScenarioInputs, a: ScenarioAssumptions) -> ScenarioResult:
    forward_revenue = inputs.ttm_revenue * (1 + a.revenue_growth) ** a.horizon_years
    forward_ebitda = forward_revenue * a.ebitda_margin
    ev = forward_ebitda * a.exit_ev_ebitda
    equity = ev - inputs.net_debt
    per_share = equity / inputs.shares_outstanding_cr if inputs.shares_outstanding_cr else 0.0
    change = per_share / inputs.price - 1 if inputs.price > 0 else 0.0
    annualised = (1 + change) ** (1 / a.horizon_years) - 1 if change > -1 else -1.0
    return ScenarioResult(
        a.name, a, forward_revenue, forward_ebitda, ev, equity, per_share, change, annualised
    )


def within_bounds(a: ScenarioAssumptions, cfg: ValuationScenarioConfig) -> list[str]:
    """PRD §7: the LLM's assumption parameters must fall within configurable sanity bounds."""
    problems: list[str] = []
    for name in ("revenue_growth", "ebitda_margin", "exit_ev_ebitda", "horizon_years"):
        lo, hi = cfg.bounds[name]
        value = float(getattr(a, name))
        if not lo <= value <= hi:
            problems.append(f"{a.name}.{name}={value} outside [{lo}, {hi}]")
    return problems


def default_assumptions(inputs: ScenarioInputs, config: ScoreConfig) -> list[ScenarioAssumptions]:
    """Bear / base / bull around trailing values, used until a validated agent run exists."""
    cfg = config.valuation_scenarios
    growth = inputs.trailing_revenue_growth if inputs.trailing_revenue_growth is not None else 0.0
    margin = inputs.ttm_ebitda / inputs.ttm_revenue if inputs.ttm_revenue > 0 else 0.0
    multiple = (
        inputs.current_ev_ebitda
        if inputs.current_ev_ebitda and inputs.current_ev_ebitda > 0
        else 8.0
    )
    out: list[ScenarioAssumptions] = []
    for name in ("bear", "base", "bull"):
        d: Any = getattr(cfg, name)
        out.append(
            ScenarioAssumptions(
                name=name,
                revenue_growth=round(growth + d.growth_delta, 4),
                ebitda_margin=round(margin + d.margin_delta, 4),
                exit_ev_ebitda=round(multiple * (1 + d.multiple_pct), 2),
                horizon_years=cfg.horizon_years,
                rationale="Default around trailing values (no validated Valuation agent run).",
            )
        )
    return out


def scenario_json(r: ScenarioResult) -> dict[str, Any]:
    return {
        "name": r.name,
        "assumptions": r.assumptions.model_dump(),
        "forward_revenue": round(r.forward_revenue, 2),
        "forward_ebitda": round(r.forward_ebitda, 2),
        "enterprise_value": round(r.enterprise_value, 2),
        "equity_value": round(r.equity_value, 2),
        "value_per_share": round(r.value_per_share, 2),
        "implied_change_vs_price": round(r.implied_change_vs_price, 4),
        "implied_annualised_change": round(r.implied_annualised_change, 4),
    }
