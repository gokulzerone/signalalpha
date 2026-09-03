from __future__ import annotations

from apps.api.quality import data_quality_summary
from apps.api.schemas import Envelope
from database.pit import PointInTimeSession


def wrap[T](pit: PointInTimeSession, data: T, *, company_id: int | None = None) -> Envelope[T]:
    return Envelope(
        as_of=pit.as_of,
        dataset="mock" if pit.is_mock else "live",
        data_quality=data_quality_summary(pit.session, company_id, is_mock=pit.is_mock),
        data=data,
    )
