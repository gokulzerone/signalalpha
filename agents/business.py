"""Business agent (PRD §7): contractual order book, capacity, concentration."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
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
    numbers_in,
    signal_summaries,
)
from agents.common import (
    add_document,
    announcement_documents,
    doc_text,
    header,
    latest_documents,
    sentence_matching,
)
from agents.llm import template
from database.models import AnnouncementCategory, Source
from evidence import SpanError, create_evidence_from_quote
from signals.detectors.business import parse_order_value

MONEY_RE = re.compile(r"Rs\.?\s?([0-9][0-9,]*(?:\.[0-9]+)?)\s*crore", re.IGNORECASE)


def parse_money(quote: str) -> Decimal | None:
    """The ₹ crore amount inside a quoted span such as 'Rs. 45.20 crore'."""
    m = MONEY_RE.search(quote)
    if m is None:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None


class OrderRow(BaseModel):
    document_id: int
    quote: str = Field(min_length=6, max_length=200)
    value_cr: float = Field(gt=0)
    execution_months: int | None = None
    customer: str = ""


class BusinessOutput(BaseModel):
    orders: list[OrderRow] = Field(default_factory=list)
    order_book_estimate_cr: float = Field(ge=0)
    capacity_story: str = Field(max_length=2000)
    concentration: str = Field(max_length=2000)
    claims: list[AgentClaim] = Field(min_length=1)


class BusinessAgent(Agent):
    name: ClassVar[str] = "business"
    output_model: ClassVar[type[BaseModel]] = BusinessOutput

    def build_inputs(self, actx: AgentContext) -> AgentInputs:
        snap: dict[str, Any] = {
            **header(actx),
            "ttm_revenue_cr": None
            if actx.ctx.ttm_revenue() is None
            else float(actx.ctx.ttm_revenue() or 0),
            "announcements": [],
            "computed_signals": signal_summaries(actx, ("business",), 1095),
        }
        inputs = AgentInputs(snapshot=snap)
        for meta, ref in announcement_documents(
            actx,
            [AnnouncementCategory.ORDER_WIN, AnnouncementCategory.CAPACITY_EXPANSION],
            1095,
            12,
        ):
            snap["announcements"].append(meta)
            add_document(inputs, ref, actx)
        for ref in latest_documents(actx, Source.ANNUAL_REPORT, 1, "Annual report"):
            add_document(inputs, ref, actx)
        for ref in latest_documents(actx, Source.CREDIT_RATING, 2, "Rating rationale"):
            add_document(inputs, ref, actx)
        if not inputs.documents:
            raise NoInputsError("no announcements or reports are loaded for this company")
        inputs.allowed_numbers = [snap["ttm_revenue_cr"] or 0.0] + [
            float(v)
            for s in snap["computed_signals"]
            for v in s["parameters"].values()
            if isinstance(v, int | float)
        ]
        return inputs

    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        assert isinstance(output, BusinessOutput)
        errors: list[str] = []
        rows: list[dict[str, Any]] = []
        total = 0.0
        for i, row in enumerate(output.orders):
            doc = inputs.documents.get(row.document_id)
            if doc is None:
                errors.append(f"order {i}: document {row.document_id} not given")
                continue
            amount = parse_money(row.quote)
            if amount is None:
                errors.append(f"order {i}: quote does not contain a rupee crore amount")
                continue
            if abs(float(amount) - row.value_cr) > 0.005:
                errors.append(
                    f"order {i}: stated value {row.value_cr} differs from quoted {amount}"
                )
                continue
            try:
                ev = create_evidence_from_quote(
                    actx.session,
                    document_text=doc.text,
                    company_id=actx.company.id,
                    quote=row.quote,
                    created_by=f"agent:{self.name}",
                )
            except SpanError:
                errors.append(f"order {i}: quote not verbatim in document {row.document_id}")
                continue
            total += float(amount)
            rows.append({**row.model_dump(), "value_cr": float(amount), "evidence_id": ev.id})
        total = round(total, 2)
        if abs(total - output.order_book_estimate_cr) > 0.5:
            errors.append(
                f"order_book_estimate_cr {output.order_book_estimate_cr} does not equal the Python sum {total}"
            )
        claims, claim_errors = self.resolve_claims(actx, inputs, output.claims)
        errors += claim_errors
        allowed = list(inputs.allowed_numbers) + [r["value_cr"] for r in rows] + [total]
        for c in claims:
            for q in c["quotes"]:
                allowed += [v for v, _ in numbers_in(q["quote"])]
        for text in (output.capacity_story, output.concentration, *(c["text"] for c in claims)):
            errors += check_numbers(text, allowed, actx.config.numeric_tolerance)
        if errors:
            raise ValidationFailure(errors)
        return {
            "orders": rows,
            "order_book_estimate_cr": total,
            "agent_stated_estimate_cr": output.order_book_estimate_cr,
            "capacity_story": output.capacity_story,
            "concentration": output.concentration,
            "claims": claims,
        }


@template("business")
def business_template(snap: dict[str, Any]) -> dict[str, Any]:
    orders: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    capacity = (
        "No capacity expansion was announced in the period covered by the provided documents."
    )
    for a in snap["announcements"]:
        text = doc_text(snap, a["document_id"])
        if a["category"] == "order_win":
            parsed = parse_order_value(text)
            if parsed is None:
                continue
            months = sentence_matching(text, r"executed over (\d+) months")
            m = None
            if months:
                import re

                mm = re.search(r"(\d+) months", months)
                m = int(mm.group(1)) if mm else None
            orders.append(
                {
                    "document_id": a["document_id"],
                    "quote": parsed[1],
                    "value_cr": float(parsed[0]),
                    "execution_months": m,
                    "customer": "",
                }
            )
            sent = sentence_matching(text, r"received an order")
            if sent:
                claims.append(
                    {
                        "text": f"An order worth Rs. {float(parsed[0]):.2f} crore was received.",
                        "quotes": [{"document_id": a["document_id"], "quote": sent}],
                    }
                )
        elif a["category"] == "capacity_expansion":
            sent = sentence_matching(text, r"expansion of manufacturing capacity")
            if sent:
                capacity = "The board approved a capacity expansion; see the cited announcement."
                claims.append(
                    {
                        "text": "A capacity expansion was approved by the board.",
                        "quotes": [{"document_id": a["document_id"], "quote": sent}],
                    }
                )
    if not claims:
        docs = snap.get("documents", [])
        if docs:
            first = docs[0]
            claims.append(
                {
                    "text": "The annual report describes the year's operations.",
                    "quotes": [
                        {
                            "document_id": first["document_id"],
                            "quote": first["text"].splitlines()[0],
                        }
                    ],
                }
            )
    total = round(sum(o["value_cr"] for o in orders), 2)
    return {
        "orders": orders,
        "order_book_estimate_cr": total,
        "capacity_story": capacity,
        "concentration": "Customer concentration is not quantified in the provided documents.",
        "claims": claims,
    }
