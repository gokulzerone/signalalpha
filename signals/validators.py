"""Validator for agent-proposed signals (PRD §6, §7).

An LLM may *propose* a signal; it becomes real only if a deterministic detector already
produced a matching signal for the company. Nothing here creates signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from database.models import Signal
from database.pit import PointInTimeSession
from signals.config import SignalCatalogue, load_catalogue


class ProposedSignal(BaseModel):
    signal_type: str
    dedupe_key: str | None = None
    public_at: datetime | None = None
    rationale: str = Field(default="", max_length=2000)
    evidence_ids: list[int] = Field(default_factory=list)


@dataclass(frozen=True)
class ValidationOutcome:
    accepted: bool
    reason: str
    signal_id: int | None = None


def validate_proposed_signal(
    pit: PointInTimeSession,
    company_id: int,
    proposal: ProposedSignal,
    *,
    catalogue: SignalCatalogue | None = None,
    tolerance: timedelta = timedelta(days=1),
) -> ValidationOutcome:
    catalogue = catalogue or load_catalogue()
    if proposal.signal_type not in catalogue.signals:
        return ValidationOutcome(False, f"unknown signal type {proposal.signal_type!r}")
    computed: list[Signal] = list(pit.signals(company_id, signal_types=[proposal.signal_type]))
    if not computed:
        return ValidationOutcome(
            False, "no deterministic signal of this type exists for the company"
        )
    if proposal.dedupe_key is not None:
        match = next((s for s in computed if s.dedupe_key == proposal.dedupe_key), None)
        if match is None:
            return ValidationOutcome(False, f"no computed signal with key {proposal.dedupe_key!r}")
        return ValidationOutcome(True, "matched by key", match.id)
    if proposal.public_at is not None:
        if proposal.public_at.tzinfo is None:
            return ValidationOutcome(False, "public_at must be timezone-aware")
        match = min(computed, key=lambda s: abs(s.public_at - proposal.public_at), default=None)  # type: ignore[operator]
        if match is None or abs(match.public_at - proposal.public_at) > tolerance:
            return ValidationOutcome(
                False, "no computed signal within tolerance of the proposed time"
            )
        return ValidationOutcome(True, "matched by time", match.id)
    return ValidationOutcome(False, "proposal must carry a dedupe_key or public_at")
