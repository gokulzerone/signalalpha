"""Detector registry and shared helpers."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from signals.config import SignalCatalogue
from signals.context import DetectionContext


@dataclass(frozen=True)
class EvidenceRequest:
    """Ask the runner to create parser evidence for a verbatim quote of a document."""

    raw_document_id: int
    quote: str


@dataclass
class Candidate:
    signal_type: str
    direction: int
    magnitude: float
    public_at: datetime
    dedupe_key: str
    source_records: list[dict[str, Any]]
    parameters: dict[str, Any]
    evidence: list[EvidenceRequest] = field(default_factory=list)


Detector = Callable[[DetectionContext, SignalCatalogue], list[Candidate]]
REGISTRY: dict[str, Detector] = {}
FAMILY_ORDER = ("financial", "ownership", "business", "forensic", "market")


def detector(signal_type: str) -> Callable[[Detector], Detector]:
    def register(fn: Detector) -> Detector:
        REGISTRY[signal_type] = fn
        return fn

    return register


def all_detectors() -> dict[str, Detector]:
    for module in ("financial", "ownership", "business", "market", "forensic"):
        importlib.import_module(f"signals.detectors.{module}")
    return dict(REGISTRY)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def f(x: Decimal | float | None) -> float | None:
    return None if x is None else float(x)


def pct_change(new: Decimal | None, old: Decimal | None) -> float | None:
    """Fractional change; ``None`` when undefined (missing or non-positive base)."""
    if new is None or old is None or old <= 0:
        return None
    return float((new - old) / old)


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def jsonable(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, Decimal):
            out[k] = round(float(v), 6)
        elif isinstance(v, float):
            out[k] = round(v, 6)
        elif isinstance(v, date | datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def year_before(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)
