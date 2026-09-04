"""Contradiction agent (PRD §7): the strongest case against the thesis. Cannot be skipped."""

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
    signal_summaries,
)
from agents.common import add_document, document_ref, header, latest_documents, sentence_matching
from agents.llm import template
from database.models import Source

UPSTREAM = ("financial", "promoter", "business", "industry", "forensic", "valuation")


class Dispute(BaseModel):
    agent: str
    claim: str = Field(max_length=600)
    dispute: str = Field(min_length=10, max_length=1000)
    resolving_evidence: str = Field(min_length=10, max_length=600)


class ContradictionOutput(BaseModel):
    case_against: str = Field(min_length=20, max_length=4000)
    disputed_claims: list[Dispute] = Field(min_length=1)
    cited_negative_signal_ids: list[int] = Field(default_factory=list)
    thesis_survives: str = Field(pattern="^(yes|weakened|no)$")
    claims: list[AgentClaim] = Field(min_length=1)


class ContradictionAgent(Agent):
    name: ClassVar[str] = "contradiction"
    output_model: ClassVar[type[BaseModel]] = ContradictionOutput
    requires: ClassVar[tuple[str, ...]] = ("financial",)

    def build_inputs(self, actx: AgentContext) -> AgentInputs:
        outputs = {
            name: (actx.outputs[name].output if name in actx.outputs else None) for name in UPSTREAM
        }
        missing = sorted(
            name for name, out in outputs.items() if out is None or out.get("status") == "no_data"
        )
        negatives = [s for s in signal_summaries(actx, None, 730) if s["direction"] < 0]
        snap = {
            **header(actx),
            "agent_outputs": outputs,
            "negative_signals": negatives,
            "forensic_flags": (outputs["forensic"] or {}).get("flags", []),
            "unavailable_agents": missing,
        }
        inputs = AgentInputs(snapshot=snap)
        for ref in latest_documents(actx, Source.ANNUAL_REPORT, 1, "Annual report"):
            add_document(inputs, ref, actx)
        cited: set[int] = set()
        for out in outputs.values():
            for claim in (out or {}).get("claims", []):
                for q in claim.get("quotes", []):
                    cited.add(int(q["document_id"]))
        for doc_id in sorted(cited)[:8]:
            add_document(inputs, document_ref(actx, doc_id, "Cited document"), actx)
        allowed = collect_numbers({"o": outputs, "n": negatives})
        inputs.allowed_numbers = (
            allowed + [x * 100 for x in allowed if -5 < x < 5] + collect_text_numbers(outputs)
        )
        return inputs

    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        assert isinstance(output, ContradictionOutput)
        errors: list[str] = []
        negative_ids = {s["signal_id"] for s in inputs.snapshot["negative_signals"]}
        if negative_ids and not output.cited_negative_signal_ids:
            errors.append("negative signals exist but none were cited")
        for sid in output.cited_negative_signal_ids:
            if sid not in negative_ids:
                errors.append(f"cited signal {sid} is not a negative signal of this company")
        for d in output.disputed_claims:
            if d.agent not in UPSTREAM:
                errors.append(f"disputed claim references unknown agent {d.agent!r}")
        claims, claim_errors = self.resolve_claims(actx, inputs, output.claims)
        errors += claim_errors
        allowed = list(inputs.allowed_numbers)
        for c in claims:
            for q in c["quotes"]:
                allowed += [v for v, _ in numbers_in(q["quote"])]
        for text in (
            output.case_against,
            *(d.dispute for d in output.disputed_claims),
            *(c["text"] for c in claims),
        ):
            errors += check_numbers(text, allowed, actx.config.numeric_tolerance)
        if errors:
            raise ValidationFailure(errors)
        return {**output.model_dump(), "claims": claims}


@template("contradiction")
def contradiction_template(snap: dict[str, Any]) -> dict[str, Any]:
    negatives = snap["negative_signals"]
    flags = snap["forensic_flags"]
    fin = snap["agent_outputs"]["financial"] or {}
    disputes = [
        {
            "agent": "financial",
            "claim": fin.get("narrative", "")[:300],
            "dispute": "The reported trajectory rests on a small number of quarters and may not persist; the base effect and one-off items are not separable from the filings alone.",
            "resolving_evidence": "Two further quarters of results at comparable margins and cash conversion.",
        }
    ]
    for s in negatives[:3]:
        disputes.append(
            {
                "agent": "forensic" if s["family"] == "forensic" else "promoter",
                "claim": f"Signal {s['signal_type']} dated {s['public_at']}.",
                "dispute": f"The {s['signal_type'].replace('_', ' ')} signal (magnitude {s['magnitude']:.2f}) argues against the thesis until it reverses.",
                "resolving_evidence": "A subsequent filing showing the metric reverting.",
            }
        )
    docs = snap.get("documents", [])
    claims = []
    for d in docs:
        sent = sentence_matching(
            d["text"], r"(Emphasis of Matter|Qualified Opinion|Our opinion is not modified)[^\n]*"
        )
        if sent:
            claims.append(
                {
                    "text": "The auditor's report states the opinion basis.",
                    "quotes": [{"document_id": d["document_id"], "quote": sent}],
                }
            )
            break
    if not claims and docs:
        claims.append(
            {
                "text": "The annual report was reviewed for counter-evidence.",
                "quotes": [
                    {
                        "document_id": docs[0]["document_id"],
                        "quote": docs[0]["text"].splitlines()[0],
                    }
                ],
            }
        )
    survives = "no" if len(flags) >= 2 else "weakened" if negatives or flags else "yes"
    absent = snap.get("unavailable_agents") or []
    gap = (
        " No "
        + ", ".join(a.replace("_", " ") for a in absent)
        + " analysis was possible: those sources are not loaded for this company, so part of"
        " the case against cannot be assessed."
        if absent
        else ""
    )
    case = (
        f"There are {len(negatives)} negative signals and {len(flags)} forensic flags.{gap} "
        + disputes[0]["dispute"]
    )
    return {
        "case_against": case,
        "disputed_claims": disputes,
        "cited_negative_signal_ids": [s["signal_id"] for s in negatives[:5]],
        "thesis_survives": survives,
        "claims": claims,
    }
