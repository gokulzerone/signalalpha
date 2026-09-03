"""Business signals (PRD §6.2). Order values are extracted from the announcement text by a
deterministic parser and stored as parser evidence; the Business agent (step 8) may propose
additional orders, which must match these extractions to become signals."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from signals.config import SignalCatalogue
from signals.context import DetectionContext
from signals.detectors.base import Candidate, EvidenceRequest, clamp01, detector, jsonable

ORDER_VALUE_RE = re.compile(
    r"orders?\s+(?:worth|valued at|aggregating to|of)\s+"
    r"(Rs\.?\s?([0-9][0-9,]*(?:\.[0-9]+)?)\s*crore)",
    re.IGNORECASE,
)
CAPACITY_RE = re.compile(r"capacity\s+by\s+(([0-9]+(?:\.[0-9]+)?)\s*%)", re.IGNORECASE)
KEY_PERSON_RE = re.compile(
    r"chief financial officer|\bcfo\b|statutory auditor|independent director", re.IGNORECASE
)
ROUTINE_ROTATION_RE = re.compile(
    r"(?<!before )completion of (?:their|its|the) term|mandatory rotation", re.IGNORECASE
)


def parse_order_value(text: str) -> tuple[Decimal, str] | None:
    """Return (value in ₹ crore, verbatim quote) of the first order value in ``text``."""
    m = ORDER_VALUE_RE.search(text)
    if m is None:
        return None
    try:
        return Decimal(m.group(2).replace(",", "")), m.group(1)
    except InvalidOperation:
        return None


@detector("order_win")
def order_win(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    out: list[Candidate] = []
    min_pct = cfg.param("order_win", "min_pct_ttm_revenue")
    full = cfg.param("order_win", "magnitude_full_pct")
    for a in ctx.announcements:
        if a.payload.get("category") != "order_win":
            continue
        text = ctx.document_text(a.raw_document_id)
        if not text:
            continue
        parsed = parse_order_value(text)
        if parsed is None:
            continue
        value, quote = parsed
        ttm = ctx.ttm_revenue()
        if ttm is None or ttm <= 0:
            continue
        pct = float(value / ttm)
        if pct < min_pct:
            continue
        out.append(
            Candidate(
                "order_win",
                1,
                clamp01(pct / full),
                a.public_at,
                f"announcement:{a.id}",
                [a.source_record],
                jsonable(
                    {
                        "order_value_cr": value,
                        "ttm_revenue_cr": ttm,
                        "pct_of_ttm_revenue": pct,
                        "threshold_pct": min_pct,
                        "quote": quote,
                    }
                ),
                evidence=[EvidenceRequest(a.raw_document_id, quote)],
            )
        )
    return out


@detector("capacity_expansion")
def capacity_expansion(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    out: list[Candidate] = []
    full = cfg.param("capacity_expansion", "magnitude_full_pct")
    for a in ctx.announcements:
        if a.payload.get("category") != "capacity_expansion":
            continue
        text = ctx.document_text(a.raw_document_id)
        m = CAPACITY_RE.search(text) if text else None
        if m is None:
            continue
        pct = float(m.group(2))
        out.append(
            Candidate(
                "capacity_expansion",
                1,
                clamp01(pct / full),
                a.public_at,
                f"announcement:{a.id}",
                [a.source_record],
                jsonable({"capacity_increase_pct": pct, "quote": m.group(0)}),
                evidence=[EvidenceRequest(a.raw_document_id, m.group(0))],
            )
        )
    return out


def _rating(
    ctx: DetectionContext, cfg: SignalCatalogue, signal_type: str, action: str, direction: int
) -> list[Candidate]:
    return [
        Candidate(
            signal_type,
            direction,
            cfg.param(signal_type, "magnitude"),
            r.public_at,
            f"rating:{r.id}",
            [r.source_record],
            jsonable(
                {"agency": r.payload["agency"], "rating": r.payload["rating"], "action": action}
            ),
        )
        for r in ctx.ratings
        if r.payload["action"] == action
    ]


@detector("credit_rating_upgrade")
def credit_rating_upgrade(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    return _rating(ctx, cfg, "credit_rating_upgrade", "upgrade", 1)


@detector("credit_rating_downgrade")
def credit_rating_downgrade(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    return _rating(ctx, cfg, "credit_rating_downgrade", "downgrade", -1)


@detector("key_person_exit")
def key_person_exit(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    out: list[Candidate] = []
    for a in ctx.announcements:
        if a.payload.get("category") != "resignation":
            continue
        haystack = f"{a.payload.get('subject', '')} {a.payload.get('summary', '')}"
        m = KEY_PERSON_RE.search(haystack)
        if m is None:
            continue
        evidence: list[EvidenceRequest] = []
        text = ctx.document_text(a.raw_document_id)
        if text:
            tm = KEY_PERSON_RE.search(text)
            if tm:
                evidence.append(EvidenceRequest(a.raw_document_id, tm.group(0)))
        out.append(
            Candidate(
                "key_person_exit",
                -1,
                cfg.param("key_person_exit", "magnitude"),
                a.public_at,
                f"announcement:{a.id}",
                [a.source_record],
                jsonable({"role": m.group(0).lower(), "subject": a.payload.get("subject", "")}),
                evidence=evidence,
            )
        )
    return out


@detector("auditor_change")
def auditor_change(ctx: DetectionContext, cfg: SignalCatalogue) -> list[Candidate]:
    out: list[Candidate] = []
    for a in ctx.announcements:
        if a.payload.get("category") != "auditor_change":
            continue
        text = ctx.document_text(a.raw_document_id) or ""
        routine = "routine=true" in a.payload.get("summary", "") or bool(
            ROUTINE_ROTATION_RE.search(text)
        )
        if routine:
            continue
        evidence: list[EvidenceRequest] = []
        m = re.search(r"resign\w*[^.]*", text, re.IGNORECASE)
        if m:
            evidence.append(EvidenceRequest(a.raw_document_id, m.group(0)))
        out.append(
            Candidate(
                "auditor_change",
                -1,
                cfg.param("auditor_change", "magnitude"),
                a.public_at,
                f"announcement:{a.id}",
                [a.source_record],
                jsonable({"routine_rotation": False, "subject": a.payload.get("subject", "")}),
                evidence=evidence,
            )
        )
    return out
