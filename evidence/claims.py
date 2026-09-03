"""Claim validation (PRD §8.2 rule 2): a claim without evidence is rejected at the schema
level; evidence must belong to the claim's company and be public at the run's as-of date."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Evidence


class Claim(BaseModel):
    """A factual statement by an AI component, with the evidence it rests on."""

    text: str = Field(min_length=1)
    evidence_ids: list[int] = Field(min_length=1)


class ClaimValidationError(ValueError):
    pass


def validate_claims(
    session: Session,
    claims: Sequence[Claim],
    *,
    company_id: int,
    as_of: datetime,
    is_mock: bool,
) -> dict[int, Evidence]:
    """Return the referenced evidence records, or raise if any claim is invalid."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    wanted = {eid for claim in claims for eid in claim.evidence_ids}
    if not wanted:
        return {}
    rows = session.scalars(select(Evidence).where(Evidence.id.in_(wanted))).all()
    found = {row.id: row for row in rows}
    problems: list[str] = []
    for eid in sorted(wanted):
        row = found.get(eid)
        if row is None:
            problems.append(f"evidence {eid} does not exist")
            continue
        if row.company_id != company_id:
            problems.append(f"evidence {eid} belongs to company {row.company_id}, not {company_id}")
        if row.is_mock != is_mock:
            problems.append(
                f"evidence {eid} is from the {'mock' if row.is_mock else 'live'} dataset"
            )
        if row.public_at > as_of:
            problems.append(
                f"evidence {eid} was published at {row.public_at.isoformat()}, after as_of"
            )
    if problems:
        raise ClaimValidationError("; ".join(problems))
    return found
