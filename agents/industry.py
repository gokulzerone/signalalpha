"""Industry agent (PRD §7). Peer sets are the same-sector companies in the database
(hand-curation can override via a peer-set file later, PRD §18)."""

from __future__ import annotations

import statistics
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
)
from agents.common import add_document, header, latest_documents, sentence_matching
from agents.llm import template
from database.models import Source
from signals.context import DetectionContext, HistoryLoader


class PeerComparison(BaseModel):
    company_id: int
    metric: str
    company_value: float | None
    peer_value: float | None
    comment: str = Field(max_length=300)


class IndustryOutput(BaseModel):
    sector_context: str = Field(min_length=20, max_length=3000)
    position: dict[str, str]
    peer_comparisons: list[PeerComparison] = Field(default_factory=list)
    tailwinds: list[str] = Field(default_factory=list)
    headwinds: list[str] = Field(default_factory=list)
    claims: list[AgentClaim] = Field(min_length=1)


def metrics_for(ctx: DetectionContext, mcap: float | None) -> dict[str, float | None]:
    q = ctx.quarters
    ttm = ctx.ttm_revenue()
    ttm_e = ctx.ttm_ebitda()
    prior = None
    if len(q) >= 8:
        prev = [x.revenue for x in q[-8:-4]]
        if all(v is not None for v in prev):
            prior = sum(v for v in prev if v is not None)
    growth = float((ttm - prior) / prior) if ttm is not None and prior else None
    margin = float(ttm_e / ttm) if ttm and ttm_e is not None else None
    ev_ebitda = None
    bps = ctx.balance_periods
    if (
        mcap
        and ttm_e
        and ttm_e > 0
        and bps
        and bps[-1].total_borrowings is not None
        and bps[-1].cash is not None
    ):
        ev_ebitda = (mcap + float(bps[-1].total_borrowings - bps[-1].cash)) / float(ttm_e)
    return {
        "ttm_revenue_growth": growth,
        "ebitda_margin": margin,
        "ev_ebitda": ev_ebitda,
        "market_cap_cr": mcap,
    }


class IndustryAgent(Agent):
    name: ClassVar[str] = "industry"
    output_model: ClassVar[type[BaseModel]] = IndustryOutput

    def build_inputs(self, actx: AgentContext) -> AgentInputs:
        snaps = {s.company_id: s for s in actx.pit.universe()}
        mcap = snaps.get(actx.company.id)
        company_metrics = metrics_for(
            actx.ctx, float(mcap.market_cap_cr) if mcap and mcap.market_cap_cr else None
        )
        peers: list[dict[str, Any]] = []
        for peer in actx.pit.companies():
            if peer.sector != actx.company.sector or peer.id == actx.company.id:
                continue
            ps = snaps.get(peer.id)
            if ps is None or ps.listing_status.value != "listed":
                continue
            pctx = HistoryLoader(actx.pit, peer).at(actx.pit.as_of)
            peers.append(
                {
                    "company_id": peer.id,
                    "ticker": peer.ticker,
                    "industry": peer.industry,
                    **metrics_for(pctx, float(ps.market_cap_cr) if ps.market_cap_cr else None),
                }
            )
        medians = {}
        for key in ("ttm_revenue_growth", "ebitda_margin", "ev_ebitda"):
            vals = [p[key] for p in peers if p[key] is not None]
            medians[key] = statistics.median(vals) if vals else None
        snap = {
            **header(actx),
            "company_metrics": company_metrics,
            "peers": peers,
            "peer_medians": medians,
        }
        inputs = AgentInputs(snapshot=snap)
        for ref in latest_documents(actx, Source.ANNUAL_REPORT, 1, "Annual report"):
            add_document(inputs, ref, actx)
        for ref in latest_documents(actx, Source.CREDIT_RATING, 2, "Rating rationale"):
            add_document(inputs, ref, actx)
        if not inputs.documents:
            raise NoInputsError("no annual report or rating rationale is loaded for this company")
        allowed = collect_numbers({"c": company_metrics, "p": peers, "m": medians})
        inputs.allowed_numbers = allowed + [x * 100 for x in allowed if -5 < x < 5]
        return inputs

    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        assert isinstance(output, IndustryOutput)
        errors: list[str] = []
        peer_ids = {p["company_id"] for p in inputs.snapshot["peers"]}
        for pc in output.peer_comparisons:
            if pc.company_id not in peer_ids:
                errors.append(
                    f"peer comparison references company {pc.company_id}, not a peer in the database"
                )
        claims, claim_errors = self.resolve_claims(actx, inputs, output.claims)
        errors += claim_errors
        allowed = list(inputs.allowed_numbers)
        for c in claims:
            for q in c["quotes"]:
                allowed += [v for v, _ in numbers_in(q["quote"])]
        for text in (
            output.sector_context,
            *output.tailwinds,
            *output.headwinds,
            *(pc.comment for pc in output.peer_comparisons),
            *(c["text"] for c in claims),
        ):
            errors += check_numbers(text, allowed, actx.config.numeric_tolerance)
        if errors:
            raise ValidationFailure(errors)
        return {**output.model_dump(), "claims": claims}


@template("industry")
def industry_template(snap: dict[str, Any]) -> dict[str, Any]:
    cm, med = snap["company_metrics"], snap["peer_medians"]

    def pos(key: str, higher_better: bool = True) -> str:
        a, b = cm.get(key), med.get(key)
        if a is None or b is None:
            return "unknown"
        if abs(a - b) <= 0.02 * max(abs(b), 1e-9):
            return "inline"
        return "above" if (a > b) == higher_better else "below"

    position = {
        "growth": pos("ttm_revenue_growth"),
        "margin": pos("ebitda_margin"),
        "valuation": pos("ev_ebitda", higher_better=False),
    }
    comps = []
    for p in snap["peers"][:4]:
        comps.append(
            {
                "company_id": p["company_id"],
                "metric": "ebitda_margin",
                "company_value": cm["ebitda_margin"],
                "peer_value": p["ebitda_margin"],
                "comment": f"Peer {p['ticker']} margin comparison.",
            }
        )
    docs = snap.get("documents", [])
    claims = []
    tail: list[str] = []
    head: list[str] = []
    for d in docs:
        sent = sentence_matching(d["text"], r"Rationale: [^\n]+")
        if sent:
            claims.append(
                {
                    "text": "The rating agency's rationale describes the credit profile.",
                    "quotes": [{"document_id": d["document_id"], "quote": sent}],
                }
            )
            (tail if "improvement" in sent or "established" in sent else head).append(
                "Rating rationale: " + sent[:120]
            )
        mdna = sentence_matching(d["text"], r"Revenue from operations for the year")
        if mdna:
            claims.append(
                {
                    "text": "The annual report reports the year's revenue.",
                    "quotes": [{"document_id": d["document_id"], "quote": mdna}],
                }
            )
    if not claims and docs:
        claims.append(
            {
                "text": "Documents were reviewed.",
                "quotes": [
                    {
                        "document_id": docs[0]["document_id"],
                        "quote": docs[0]["text"].splitlines()[0],
                    }
                ],
            }
        )
    context = f"The company operates in the {snap['sector']} sector ({snap['industry']}) with {len(snap['peers'])} listed peers in the database."
    return {
        "sector_context": context,
        "position": position,
        "peer_comparisons": comps,
        "tailwinds": tail,
        "headwinds": head,
        "claims": claims,
    }
