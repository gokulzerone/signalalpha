"""Financial agent (PRD §7)."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agents.base import (
    Agent,
    AgentClaim,
    AgentContext,
    AgentInputs,
    NoInputsError,
    ValidationFailure,
    check_numbers,
    collect_numbers,
    numbers_in,
    signal_summaries,
)
from agents.common import (
    add_document,
    doc_text,
    document_ref,
    financial_snapshot,
    header,
    latest_documents,
    line_containing,
    money,
)
from agents.llm import template
from database.models import Source
from signals.validators import ProposedSignal, validate_proposed_signal


class ProposedSignalOut(BaseModel):
    signal_type: str
    dedupe_key: str


class FinancialOutput(BaseModel):
    narrative: str = Field(min_length=20, max_length=4000)
    trajectory: str = Field(pattern="^(improving|stable|deteriorating|mixed)$")
    proposed_signals: list[ProposedSignalOut] = Field(default_factory=list)
    claims: list[AgentClaim] = Field(min_length=1)


class FinancialAgent(Agent):
    name: ClassVar[str] = "financial"
    output_model: ClassVar[type[BaseModel]] = FinancialOutput

    def build_inputs(self, actx: AgentContext) -> AgentInputs:
        if not actx.ctx.quarters:
            raise NoInputsError("no quarterly financials are loaded for this company")
        snap = {
            **header(actx),
            "financials": financial_snapshot(actx),
            "computed_signals": signal_summaries(actx, ("financial",)),
        }
        inputs = AgentInputs(snapshot=snap)
        if actx.ctx.quarters:
            add_document(
                inputs,
                document_ref(actx, actx.ctx.quarters[-1].raw_document_id, "Latest results filing"),
                actx,
            )
        for ref in latest_documents(actx, Source.ANNUAL_REPORT, 1, "Annual report"):
            add_document(inputs, ref, actx)
        allowed = collect_numbers(snap["financials"])
        inputs.allowed_numbers = allowed + [x * 100 for x in allowed if -5 < x < 5]
        return inputs

    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        assert isinstance(output, FinancialOutput)
        errors: list[str] = []
        claims, claim_errors = self.resolve_claims(actx, inputs, output.claims)
        errors += claim_errors
        allowed = list(inputs.allowed_numbers)
        for c in claims:
            for q in c["quotes"]:
                allowed += [v for v, _ in numbers_in(q["quote"])]
        errors += [
            f"narrative: {e}"
            for e in check_numbers(output.narrative, allowed, actx.config.numeric_tolerance)
        ]
        for i, c in enumerate(claims):
            errors += [
                f"claim {i}: {e}"
                for e in check_numbers(c["text"], allowed, actx.config.numeric_tolerance)
            ]
        accepted: list[dict[str, Any]] = []
        for ps in output.proposed_signals:
            outcome = validate_proposed_signal(
                actx.pit,
                actx.company.id,
                ProposedSignal(signal_type=ps.signal_type, dedupe_key=ps.dedupe_key),
            )
            if not outcome.accepted:
                errors.append(
                    f"proposed signal {ps.signal_type}/{ps.dedupe_key} rejected: {outcome.reason}"
                )
            else:
                accepted.append(
                    {
                        "signal_type": ps.signal_type,
                        "dedupe_key": ps.dedupe_key,
                        "signal_id": outcome.signal_id,
                    }
                )
        if errors:
            raise ValidationFailure(errors)
        return {
            "narrative": output.narrative,
            "trajectory": output.trajectory,
            "proposed_signals": accepted,
            "claims": claims,
        }


@template("financial")
def financial_template(snap: dict[str, Any]) -> dict[str, Any]:
    quarters = snap["financials"]["quarters"]
    latest = quarters[-1]
    doc_id = latest["document_id"]
    text = doc_text(snap, doc_id)
    rev, ebitda = latest["values"]["revenue"], latest["values"]["ebitda"]
    r = latest["ratios"]
    parts = [
        f"Revenue from operations for the quarter ended {latest['period_end']} was Rs. {money(rev)} crore and EBITDA was Rs. {money(ebitda)} crore."
    ]
    if r.get("revenue_yoy") is not None:
        parts.append(f"Revenue grew {r['revenue_yoy'] * 100:.2f}% year on year.")
    if r.get("ebitda_margin") is not None:
        parts.append(f"The EBITDA margin was {r['ebitda_margin'] * 100:.2f}%.")
    yoys = [q["ratios"].get("revenue_yoy") for q in quarters[-4:]]
    margins = [q["ratios"].get("ebitda_margin") for q in quarters[-8:]]
    trajectory = "stable"
    if (
        all(v is not None for v in yoys)
        and all(v > 0.08 for v in yoys if v is not None)
        and margins[-1]
        and margins[0]
        and margins[-1] > margins[0] + 0.02
    ):
        trajectory = "improving"
    elif margins[-1] and margins[0] and margins[-1] < margins[0] - 0.02:
        trajectory = "deteriorating"
    elif any(v is not None and v < 0 for v in yoys):
        trajectory = "mixed"
    claims = []
    for label, value in (("Revenue from operations", rev), ("EBITDA", ebitda)):
        # Tabular filings print "Revenue from operations | 86.67"; an Ind-AS XBRL filing
        # carries the same fact in rupees, so look for both forms.
        line = line_containing(text, f"{label} | {money(value)}")
        if line is None and value is not None:
            line = line_containing(text, f"{value * 10_000_000:.2f}")
        if line:
            claims.append(
                {
                    "text": f"{label} for the quarter was Rs. {money(value)} crore.",
                    "quotes": [{"document_id": doc_id, "quote": line.strip()}],
                }
            )
    if not claims:
        claims.append(
            {
                "text": "The results were approved by the board.",
                "quotes": [
                    {
                        "document_id": doc_id,
                        "quote": line_containing(text, "approved by the Board") or text[:60],
                    }
                ],
            }
        )
    proposed = [
        {"signal_type": s["signal_type"], "dedupe_key": s["dedupe_key"]}
        for s in snap["computed_signals"][:5]
    ]
    return {
        "narrative": " ".join(parts),
        "trajectory": trajectory,
        "proposed_signals": proposed,
        "claims": claims,
    }
