"""Valuation agent (PRD §7): the model proposes assumption parameters only."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agents.base import Agent, AgentContext, AgentInputs, ValidationFailure
from agents.common import header
from agents.industry import metrics_for
from agents.llm import template
from scoring.config import load_score_config
from scoring.valuation import (
    ScenarioAssumptions,
    ScenarioInputs,
    compute_scenario,
    default_assumptions,
    scenario_json,
    within_bounds,
)

BANNED = ("buy", "sell", "target price", "recommendation")


class ValuationOutput(BaseModel):
    scenarios: list[ScenarioAssumptions] = Field(min_length=3, max_length=3)
    rationale: str = Field(max_length=2000)


class ValuationAgent(Agent):
    name: ClassVar[str] = "valuation"
    output_model: ClassVar[type[BaseModel]] = ValuationOutput
    requires: ClassVar[tuple[str, ...]] = ("business",)

    def _inputs(self, actx: AgentContext) -> ScenarioInputs | None:
        ctx = actx.ctx
        ttm_rev, ttm_e = ctx.ttm_revenue(), ctx.ttm_ebitda()
        bps = ctx.balance_periods
        prices = actx.pit.prices(actx.company.id, actx.as_of - timedelta(days=30))
        if (
            ttm_rev is None
            or ttm_e is None
            or not bps
            or not prices
            or bps[-1].total_borrowings is None
            or bps[-1].cash is None
            or not ctx.quarters[-1].shares_outstanding
        ):
            return None
        price = float(prices[-1].close)
        shares = float(ctx.quarters[-1].shares_outstanding or 0)
        m = metrics_for(ctx, price * shares)
        return ScenarioInputs(
            float(ttm_rev),
            float(ttm_e),
            float(bps[-1].total_borrowings - bps[-1].cash),
            shares,
            price,
            m["ttm_revenue_growth"],
            m["ev_ebitda"],
        )

    def build_inputs(self, actx: AgentContext) -> AgentInputs:
        si = self._inputs(actx)
        if si is None:
            raise ValidationFailure(["insufficient data for valuation scenarios"])
        cfg = load_score_config().valuation_scenarios
        business = actx.outputs["business"].output or {}
        snap = {
            **header(actx),
            "inputs": si.__dict__,
            "bounds": cfg.bounds,
            "horizon_years": cfg.horizon_years,
            "order_book_estimate_cr": business.get("order_book_estimate_cr"),
            "defaults": [a.model_dump() for a in default_assumptions(si, load_score_config())],
        }
        return AgentInputs(snapshot=snap)

    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        assert isinstance(output, ValuationOutput)
        errors: list[str] = []
        names = [s.name for s in output.scenarios]
        if sorted(names) != ["base", "bear", "bull"]:
            errors.append(f"scenarios must be bear, base and bull; got {names}")
        cfg = load_score_config().valuation_scenarios
        for a in output.scenarios:
            errors += within_bounds(a, cfg)
        lowered = (output.rationale + " " + " ".join(s.rationale for s in output.scenarios)).lower()
        errors += [f"banned word {w!r} in rationale" for w in BANNED if w in lowered]
        if errors:
            raise ValidationFailure(errors)
        si = ScenarioInputs(**inputs.snapshot["inputs"])
        computed = [
            scenario_json(compute_scenario(si, a))
            for a in sorted(output.scenarios, key=lambda s: ["bear", "base", "bull"].index(s.name))
        ]
        return {
            "scenarios": [a.model_dump() for a in output.scenarios],
            "computed": computed,
            "rationale": output.rationale,
            "inputs": inputs.snapshot["inputs"],
        }


@template("valuation")
def valuation_template(snap: dict[str, Any]) -> dict[str, Any]:
    scenarios = []
    for d in snap["defaults"]:
        scenarios.append(
            {
                **d,
                "rationale": f"{d['name'].capitalize()} case around trailing growth and margin; order book of Rs. {snap['order_book_estimate_cr'] or 0:.2f} crore informs the growth assumption.",
            }
        )
    return {
        "scenarios": scenarios,
        "rationale": "Scenarios bracket the trailing revenue growth, EBITDA margin and current EV/EBITDA multiple.",
    }
