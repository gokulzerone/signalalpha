"""Promoter agent (PRD §7)."""

from __future__ import annotations

from datetime import timedelta
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
    numbers_in,
    signal_summaries,
)
from agents.common import (
    add_document,
    doc_text,
    document_ref,
    header,
    latest_documents,
    line_containing,
    money,
)
from agents.llm import template
from database.models import Source

POSITIVE = {"promoter_stake_increase", "pledge_reduction", "institutional_entry"}
SELLING = {"promoter_stake_decrease"}
DISTRESS = {"pledge_increase", "pledge_invocation"}


class PromoterOutput(BaseModel):
    narrative: str = Field(min_length=20, max_length=4000)
    promoter_behaviour: str = Field(pattern="^(accumulating|stable|distributing|distressed)$")
    claims: list[AgentClaim] = Field(min_length=1)


def classify(signal_types: set[str], pledged_pct: float | None) -> str:
    if signal_types & DISTRESS or (pledged_pct is not None and pledged_pct >= 50):
        return "distressed"
    if signal_types & SELLING:
        return "distributing"
    if signal_types & POSITIVE:
        return "accumulating"
    return "stable"


class PromoterAgent(Agent):
    name: ClassVar[str] = "promoter"
    output_model: ClassVar[type[BaseModel]] = PromoterOutput

    def build_inputs(self, actx: AgentContext) -> AgentInputs:
        ctx = actx.ctx
        holdings = [
            {
                "shareholding_id": h.id,
                "document_id": h.raw_document_id,
                "period_end": h.period_end.isoformat(),
                "promoter_pct": float(h.promoter_pct),
                "pledged_pct_of_promoter_holding": float(h.pledged_pct),
                "fii_pct": float(h.fii_pct),
                "dii_pct": float(h.dii_pct),
                "retail_shareholders": h.retail_shareholders,
                "holders": [{"name": n, "category": c, "pct": float(p)} for n, c, p in h.holders],
            }
            for h in ctx.holdings[-8:]
        ]
        since = actx.as_of - timedelta(days=730)
        pledges = [
            {
                "id": e.id,
                "document_id": e.raw_document_id,
                "event_type": e.payload["event_type"],
                "pct_of_promoter_holding": float(e.payload["pct_of_promoter_holding"]),
                "public_at": e.public_at.date().isoformat(),
            }
            for e in ctx.pledge_events
            if e.public_at.date() >= since
        ]
        insiders = [
            {
                "id": t.id,
                "document_id": t.raw_document_id,
                "side": t.payload["side"],
                "mode": t.payload["mode"],
                "value_cr": round(float(t.payload["value_inr"]) / 1e7, 2),
                "public_at": t.public_at.date().isoformat(),
            }
            for t in ctx.insider_trades
            if t.public_at.date() >= since
        ]
        bulks = [
            {
                "id": b.id,
                "client": b.payload["client_name"],
                "side": b.payload["side"],
                "value_cr": round(float(b.payload["value_inr"]) / 1e7, 2),
                "public_at": b.public_at.date().isoformat(),
            }
            for b in ctx.bulk_deals
            if b.public_at.date() >= since
        ]
        if not holdings and not pledges and not insiders:
            raise ValidationFailure(["no ownership disclosures are loaded for this company"])
        snap = {
            **header(actx),
            "shareholdings": holdings,
            "pledge_events": pledges,
            "insider_trades": insiders,
            "bulk_deals": bulks,
            "computed_signals": signal_summaries(actx, ("ownership",), 365),
        }
        inputs = AgentInputs(snapshot=snap)
        for ref in latest_documents(actx, Source.SHAREHOLDING_PATTERN, 1, "Shareholding pattern"):
            add_document(inputs, ref, actx)
        for e in [*ctx.pledge_events[-3:], *ctx.insider_trades[-3:]]:
            add_document(inputs, document_ref(actx, e.raw_document_id, "Disclosure"), actx)
        allowed = collect_numbers(
            {k: snap[k] for k in ("shareholdings", "pledge_events", "insider_trades", "bulk_deals")}
        )
        inputs.allowed_numbers = allowed
        return inputs

    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        assert isinstance(output, PromoterOutput)
        errors: list[str] = []
        types = {s["signal_type"] for s in inputs.snapshot["computed_signals"]}
        pledged = (
            inputs.snapshot["shareholdings"][-1]["pledged_pct_of_promoter_holding"]
            if inputs.snapshot["shareholdings"]
            else None
        )
        expected = classify(types, pledged)
        if output.promoter_behaviour != expected:
            errors.append(
                f"classification {output.promoter_behaviour!r} inconsistent with signals {sorted(types)} (expected {expected!r})"
            )
        claims, claim_errors = self.resolve_claims(actx, inputs, output.claims)
        errors += claim_errors
        allowed = list(inputs.allowed_numbers)
        for c in claims:
            for q in c["quotes"]:
                allowed += [v for v, _ in numbers_in(q["quote"])]
        errors += check_numbers(output.narrative, allowed, actx.config.numeric_tolerance)
        for c in claims:
            errors += check_numbers(c["text"], allowed, actx.config.numeric_tolerance)
        if errors:
            raise ValidationFailure(errors)
        return {
            "narrative": output.narrative,
            "promoter_behaviour": output.promoter_behaviour,
            "claims": claims,
        }


@template("promoter")
def promoter_template(snap: dict[str, Any]) -> dict[str, Any]:
    holdings = snap["shareholdings"]
    latest = holdings[-1]
    types = {s["signal_type"] for s in snap["computed_signals"]}
    behaviour = classify(types, latest["pledged_pct_of_promoter_holding"])
    text = doc_text(snap, latest["document_id"])
    narrative = f"Promoter holding was {money(latest['promoter_pct'])}% as on {latest['period_end']}, with {money(latest['pledged_pct_of_promoter_holding'])}% of the promoter holding pledged."
    if len(holdings) >= 5:
        narrative += f" Four quarters earlier the promoter holding was {money(holdings[-5]['promoter_pct'])}%."
    claims = []
    line = line_containing(text, f"Promoter and Promoter Group | {money(latest['promoter_pct'])}")
    if line:
        claims.append(
            {
                "text": f"Promoter and promoter group held {money(latest['promoter_pct'])}% of equity.",
                "quotes": [{"document_id": latest["document_id"], "quote": line}],
            }
        )
    pledge_line = line_containing(text, "pledged or otherwise encumbered")
    if pledge_line:
        claims.append(
            {
                "text": f"{money(latest['pledged_pct_of_promoter_holding'])}% of the promoter holding was pledged.",
                "quotes": [{"document_id": latest["document_id"], "quote": pledge_line}],
            }
        )
    return {
        "narrative": narrative,
        "promoter_behaviour": behaviour,
        "claims": claims
        or [
            {
                "text": "Shareholding pattern filed.",
                "quotes": [{"document_id": latest["document_id"], "quote": text.splitlines()[0]}],
            }
        ],
    }
