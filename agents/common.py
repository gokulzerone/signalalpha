"""Shared snapshot builders and template helpers."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from agents.base import AgentContext, AgentInputs, DocumentRef, document_ref, snapshot_document

__all__ = [
    "add_document",
    "announcement_documents",
    "doc_text",
    "document_ref",
    "financial_snapshot",
    "header",
    "latest_documents",
    "line_containing",
    "money",
    "period_json",
    "sentence_matching",
]
from database.models import AnnouncementCategory, Source
from scoring.ratios import ratios_for
from signals.context import Period


def header(actx: AgentContext) -> dict[str, Any]:
    c = actx.company
    return {
        "company_id": c.id,
        "ticker": c.ticker,
        "name": c.name,
        "sector": c.sector,
        "industry": c.industry,
        "as_of": actx.as_of.isoformat(),
    }


def period_json(p: Period, all_periods: list[Period]) -> dict[str, Any]:
    values = {
        k: (None if getattr(p, k) is None else float(getattr(p, k)))
        for k in (
            "revenue",
            "ebitda",
            "depreciation",
            "pat",
            "cfo",
            "capex",
            "receivables",
            "inventory",
            "payables",
            "cash",
            "total_borrowings",
            "short_term_borrowings",
            "related_party_revenue",
            "contingent_liabilities",
            "shares_outstanding",
        )
    }
    return {
        "financial_id": p.id,
        "filing_id": p.filing_id,
        "document_id": p.raw_document_id,
        "period_end": p.period_end.isoformat(),
        "months": p.months,
        "consolidated": p.consolidated,
        "public_at": p.public_at.isoformat(),
        "values": values,
        "ratios": ratios_for(p, all_periods),
        "audit_opinion": p.audit_opinion,
    }


def financial_snapshot(actx: AgentContext, quarters: int = 16) -> dict[str, Any]:
    ctx = actx.ctx
    all_periods = ctx.quarters + ctx.halves + ctx.annuals
    return {
        "quarters": [period_json(p, all_periods) for p in ctx.quarters[-quarters:]],
        "half_years": [period_json(p, all_periods) for p in ctx.halves[-4:]],
        "annuals": [period_json(p, all_periods) for p in ctx.annuals[-4:]],
        "ttm_revenue": None if ctx.ttm_revenue() is None else float(ctx.ttm_revenue() or 0),
        "ttm_ebitda": None if ctx.ttm_ebitda() is None else float(ctx.ttm_ebitda() or 0),
    }


def add_document(inputs: AgentInputs, ref: DocumentRef | None, actx: AgentContext) -> None:
    if ref is None or ref.id in inputs.documents:
        return
    inputs.documents[ref.id] = ref
    inputs.snapshot.setdefault("documents", []).append(
        snapshot_document(ref, actx.config.document_char_limit)
    )


def latest_documents(
    actx: AgentContext, source: Source, limit: int, title: str
) -> list[DocumentRef]:
    refs: list[DocumentRef] = []
    for raw in actx.pit.raw_documents(actx.company.id, source)[:limit]:
        ref = document_ref(actx, raw.id, raw.title or title)
        if ref is not None:
            refs.append(ref)
    return refs


def announcement_documents(
    actx: AgentContext, categories: list[AnnouncementCategory], days: int, limit: int
) -> list[tuple[dict[str, Any], DocumentRef]]:
    since = actx.as_of - timedelta(days=days)
    out: list[tuple[dict[str, Any], DocumentRef]] = []
    for a in actx.pit.announcements(actx.company.id, since=since, categories=categories)[:limit]:
        ref = document_ref(actx, a.raw_document_id, a.subject)
        if ref is not None:
            out.append(
                (
                    {
                        "announcement_id": a.id,
                        "category": a.category.value,
                        "subject": a.subject,
                        "public_at": a.public_at.date().isoformat(),
                        "document_id": a.raw_document_id,
                    },
                    ref,
                )
            )
    return out


# --------------------------------------------------------------- templates
def line_containing(text: str, needle: str) -> str | None:
    """A verbatim line of ``text`` containing ``needle`` (for template quotes)."""
    for line in text.splitlines():
        if needle in line and len(line.strip()) >= 8:
            return line.strip()
    return None


def sentence_matching(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    if m is None:
        return None
    start = text.rfind("\n", 0, m.start()) + 1
    end_candidates = [i for i in (text.find(".", m.end()), text.find("\n", m.end())) if i != -1]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    s = text[start:end].strip()
    return s if len(s) >= 8 else None


def money(x: float) -> str:
    return f"{x:.2f}"


def doc_text(snapshot: dict[str, Any], document_id: int) -> str:
    for d in snapshot.get("documents", []):
        if d["document_id"] == document_id:
            return str(d["text"])
    return ""
