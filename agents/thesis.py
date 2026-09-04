"""Thesis agent (PRD §7): runs only after Contradiction; strongest_negative must reference it."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agents.base import (
    Agent,
    AgentClaim,
    AgentContext,
    AgentInputs,
    ValidationFailure,
    check_numbers,
    collect_numbers,
    collect_text_numbers,
    numbers_in,
)
from agents.common import add_document, document_ref, header
from agents.contradiction import UPSTREAM
from agents.llm import template

BANNED = ("buy", "sell", "target price", "recommendation")


class ThesisOutput(BaseModel):
    key_change: str = Field(min_length=10, max_length=600)
    why_now: str = Field(min_length=10, max_length=1000)
    what_market_may_be_missing: str = Field(min_length=10, max_length=1000)
    strongest_positive: str = Field(min_length=10, max_length=600)
    strongest_negative: str = Field(min_length=10, max_length=1000)
    contradiction_claim_index: int = Field(ge=0)
    what_would_break_this: str = Field(min_length=10, max_length=1000)
    time_horizon: str = Field(min_length=3, max_length=100)
    confidence: str = Field(pattern="^(low|medium|high)$")
    claims: list[AgentClaim] = Field(min_length=1)


class ThesisAgent(Agent):
    name: ClassVar[str] = "thesis"
    output_model: ClassVar[type[BaseModel]] = ThesisOutput
    requires: ClassVar[tuple[str, ...]] = ("financial", "contradiction")

    def build_inputs(self, actx: AgentContext) -> AgentInputs:
        wanted = (*UPSTREAM, "contradiction")
        outputs = {
            name: (actx.outputs[name].output if name in actx.outputs else None) for name in wanted
        }
        snap = {**header(actx), "agent_outputs": outputs}
        inputs = AgentInputs(snapshot=snap)
        cited: set[int] = set()
        for out in outputs.values():
            for claim in (out or {}).get("claims", []):
                for q in claim.get("quotes", []):
                    cited.add(int(q["document_id"]))
        for doc_id in sorted(cited)[:8]:
            add_document(inputs, document_ref(actx, doc_id, "Cited document"), actx)
        allowed = collect_numbers(outputs)
        inputs.allowed_numbers = (
            allowed + [x * 100 for x in allowed if -5 < x < 5] + collect_text_numbers(outputs)
        )
        return inputs

    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        assert isinstance(output, ThesisOutput)
        errors: list[str] = []
        contradiction = inputs.snapshot["agent_outputs"]["contradiction"] or {}
        disputes = contradiction.get("disputed_claims", [])
        if output.contradiction_claim_index >= len(disputes):
            errors.append("contradiction_claim_index is out of range")
        else:
            dispute = disputes[output.contradiction_claim_index]["dispute"]
            if dispute[:60].lower() not in output.strongest_negative.lower():
                errors.append(
                    "strongest_negative must restate the referenced Contradiction dispute"
                )
        lowered = " ".join(
            [
                output.key_change,
                output.why_now,
                output.what_market_may_be_missing,
                output.strongest_positive,
                output.strongest_negative,
                output.what_would_break_this,
            ]
        ).lower()
        errors += [f"banned word {w!r}" for w in BANNED if w in lowered]
        claims, claim_errors = self.resolve_claims(actx, inputs, output.claims)
        errors += claim_errors
        allowed = list(inputs.allowed_numbers)
        for c in claims:
            for q in c["quotes"]:
                allowed += [v for v, _ in numbers_in(q["quote"])]
        for text in (
            output.key_change,
            output.why_now,
            output.what_market_may_be_missing,
            output.strongest_positive,
            output.strongest_negative,
            output.what_would_break_this,
            *(c["text"] for c in claims),
        ):
            errors += check_numbers(text, allowed, actx.config.numeric_tolerance)
        if errors:
            raise ValidationFailure(errors)
        return {
            **output.model_dump(),
            "claims": claims,
            "contradiction_run_id": actx.outputs["contradiction"].id,
        }


@template("thesis")
def thesis_template(snap: dict[str, Any]) -> dict[str, Any]:
    o = snap["agent_outputs"]
    fin, prom, bus, contra = (
        o["financial"] or {},
        o["promoter"] or {},
        o["business"] or {},
        o["contradiction"] or {},
    )
    disputes = contra.get("disputed_claims", [])
    idx = len(disputes) - 1 if disputes else 0
    strongest_negative = disputes[idx]["dispute"] if disputes else "No contradiction available."
    positives = []
    if bus.get("order_book_estimate_cr"):
        positives.append(
            f"Verified order wins total Rs. {bus['order_book_estimate_cr']:.2f} crore."
        )
    if fin.get("trajectory") == "improving":
        positives.append("Revenue growth and margins are both improving.")
    if prom.get("promoter_behaviour") == "accumulating":
        positives.append("The promoter is accumulating.")
    strongest_positive = (
        positives[0]
        if positives
        else "Financial trajectory is described in the Financial agent narrative."
    )
    survives = contra.get("thesis_survives", "weakened")
    confidence = {"yes": "medium", "weakened": "low", "no": "low"}[survives]
    claims = []
    for name in ("financial", "business", "promoter"):
        for c in (o[name] or {}).get("claims", [])[:1]:
            claims.append({"text": c["text"], "quotes": c["quotes"]})
    if not claims:
        claims = [
            {
                "text": "See agent outputs.",
                "quotes": (fin.get("claims") or [{}])[0].get("quotes", []),
            }
        ]
    return {
        "key_change": (fin.get("narrative") or "Financial trajectory under review.")[:400],
        "why_now": "The latest filings are the most recent public disclosures; the signals below were detected on their publication dates.",
        "what_market_may_be_missing": "Whether the change in fundamentals persists beyond the quarters already reported.",
        "strongest_positive": strongest_positive,
        "strongest_negative": strongest_negative,
        "contradiction_claim_index": idx,
        "what_would_break_this": disputes[0]["resolving_evidence"]
        if disputes
        else "Contrary evidence in subsequent filings.",
        "time_horizon": "2 to 4 quarters",
        "confidence": confidence,
        "claims": claims,
    }
