"""Data-quality summaries attached to every response (PRD §5.2, §10)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.schemas import DataQualitySummary, SourceQuality
from database.models import DataQuality


def data_quality_summary(
    session: Session, company_id: int | None, *, is_mock: bool
) -> DataQualitySummary:
    stmt = select(DataQuality).where(DataQuality.is_mock == is_mock)
    stmt = (
        stmt.where(DataQuality.company_id == company_id)
        if company_id is not None
        else stmt.where(DataQuality.company_id.is_(None))
    )
    rows = session.scalars(stmt.order_by(DataQuality.source)).all()
    sources = [
        SourceQuality(
            source=r.source.value,
            last_success_at=r.last_success_at,
            latest_public_at=r.latest_public_at,
            fetch_failure_count=r.fetch_failure_count,
            parse_failure_count=r.parse_failure_count,
        )
        for r in rows
    ]
    latest = [r.latest_public_at for r in rows if r.latest_public_at is not None]
    return DataQualitySummary(
        sources=sources,
        total_failures=sum(r.fetch_failure_count + r.parse_failure_count for r in rows),
        latest_public_at=max(latest) if latest else None,
    )
