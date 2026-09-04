"""Forensic agent (PRD §7)."""

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
    financial_snapshot,
    header,
    latest_documents,
    sentence_matching,
)
from agents.llm import template

FORENSIC_TYPES = (
    "related_party_revenue",
    "receivables_outrunning_revenue",
    "cash_vs_debt_anomaly",
    "audit_qualification",
    "contingent_liability_spike",
    "frequent_fund_raise",
)


class Flag(BaseModel):
    signal_type: str = Field(pattern="^(" + "|".join(FORENSIC_TYPES) + "|unclassified)$")
    severity: str = Field(pattern="^(low|medium|high)$")
    mechanism: str = Field(min_length=10, max_length=1000)
    claims: list[AgentClaim] = Field(min_length=1)


class ForensicOutput(BaseModel):
    flags: list[Flag] = Field(default_factory=list)
    summary: str = Field(min_length=10, max_length=2000)


class ForensicAgent(Agent):
    name: ClassVar[str] = "forensic"
    output_model: ClassVar[type[BaseModel]] = ForensicOutput

    def build_inputs(self, actx: AgentContext) -> AgentInputs:
        fin = financial_snapshot(actx, quarters=8)
        snap = {
            **header(actx),
            "annuals": fin["annuals"],
            "half_years": fin["half_years"],
            "computed_signals": signal_summaries(actx, ("forensic",), 730),
        }
        inputs = AgentInputs(snapshot=snap)
        for ref in latest_documents(actx, Source.ANNUAL_REPORT, 2, "Annual report"):
            add_document(inputs, ref, actx)
        if not inputs.documents:
            raise NoInputsError("no annual report is loaded for this company")
        allowed = collect_numbers(
            {"a": snap["annuals"], "h": snap["half_years"], "s": snap["computed_signals"]}
        )
        inputs.allowed_numbers = allowed + [x * 100 for x in allowed if -5 < x < 5]
        return inputs

    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        assert isinstance(output, ForensicOutput)
        errors: list[str] = []
        computed = {s["signal_type"] for s in inputs.snapshot["computed_signals"]}
        flags: list[dict[str, Any]] = []
        for i, flag in enumerate(output.flags):
            if flag.signal_type != "unclassified" and flag.signal_type not in computed:
                errors.append(
                    f"flag {i}: {flag.signal_type} has no computed forensic signal; label it unclassified"
                )
            claims, claim_errors = self.resolve_claims(actx, inputs, flag.claims)
            errors += [f"flag {i}: {e}" for e in claim_errors]
            allowed = list(inputs.allowed_numbers)
            for c in claims:
                for q in c["quotes"]:
                    allowed += [v for v, _ in numbers_in(q["quote"])]
            errors += [
                f"flag {i}: {e}"
                for e in check_numbers(flag.mechanism, allowed, actx.config.numeric_tolerance)
            ]
            for c in claims:
                errors += [
                    f"flag {i}: {e}"
                    for e in check_numbers(c["text"], allowed, actx.config.numeric_tolerance)
                ]
            flags.append(
                {
                    "signal_type": flag.signal_type,
                    "severity": flag.severity,
                    "mechanism": flag.mechanism,
                    "claims": claims,
                    "classified": flag.signal_type != "unclassified",
                }
            )
        errors += check_numbers(
            output.summary, list(inputs.allowed_numbers), actx.config.numeric_tolerance
        )
        if errors:
            raise ValidationFailure(errors)
        return {"flags": flags, "summary": output.summary}


from database.models import Source  # noqa: E402  (placed after the agent for readability)

MECHANISMS = {
    "related_party_revenue": (
        "high",
        "A large share of revenue is billed to related parties, so reported growth may not reflect arm's-length demand.",
        r"Note 32 - Related party transactions[^\n]*",
    ),
    "receivables_outrunning_revenue": (
        "high",
        "Receivables are growing faster than revenue for two years, consistent with aggressive revenue recognition or uncollectable sales.",
        r"Trade receivables as at[^\n]*",
    ),
    "cash_vs_debt_anomaly": (
        "medium",
        "Reported cash is large while short-term borrowings keep rising, which is inconsistent unless the cash is restricted or overstated.",
        r"Trade receivables have increased[^\n]*|Cash and cash equivalents \|[^\n]*",
    ),
    "audit_qualification": (
        "high",
        "The auditor has modified or drawn attention to matters in the opinion, indicating unresolved accounting uncertainty.",
        r"(Emphasis of Matter|Qualified Opinion|Material uncertainty)[^\n]*",
    ),
    "contingent_liability_spike": (
        "medium",
        "Contingent liabilities jumped relative to revenue, signalling disputes or guarantees not yet provided for.",
        r"Note 35 - Contingent liabilities[^\n]*",
    ),
    "frequent_fund_raise": (
        "medium",
        "Repeated discounted preferential issues to promoters dilute public shareholders and can mask cash shortfalls.",
        r"Note 32 - Related party transactions[^\n]*",
    ),
}


@template("forensic")
def forensic_template(snap: dict[str, Any]) -> dict[str, Any]:
    docs = snap.get("documents", [])
    flags = []
    seen: set[str] = set()
    for s in snap["computed_signals"]:
        st = s["signal_type"]
        if st in seen or st not in MECHANISMS:
            continue
        seen.add(st)
        severity, mechanism, pattern = MECHANISMS[st]
        quote = None
        doc_id = None
        for d in docs:
            quote = sentence_matching(d["text"], pattern)
            if quote:
                doc_id = d["document_id"]
                break
        if quote is None or doc_id is None:
            continue
        flags.append(
            {
                "signal_type": st,
                "severity": severity,
                "mechanism": mechanism,
                "claims": [
                    {
                        "text": f"The annual report discloses the basis for the {st.replace('_', ' ')} flag.",
                        "quotes": [{"document_id": doc_id, "quote": quote}],
                    }
                ],
            }
        )
    summary = (
        f"{len(flags)} forensic flag(s) mapped to computed signals."
        if flags
        else "No forensic red flags were identified from the computed signals."
    )
    return {"flags": flags, "summary": summary}
