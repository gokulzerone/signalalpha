"""FastAPI dependencies: session, API key, dataset selection, point-in-time binding."""

from __future__ import annotations

import enum
from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from apps.api.settings import ApiSettings
from database.pit import UTC, PointInTimeSession


class Dataset(enum.StrEnum):
    MOCK = "mock"
    LIVE = "live"


def get_settings(request: Request) -> ApiSettings:
    settings: ApiSettings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.sessionmaker()
    try:
        yield session
    finally:
        session.close()


def require_api_key(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if settings.api_key is not None and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def get_dataset(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    dataset: Annotated[Dataset | None, Query(description="mock or live; never both")] = None,
) -> Dataset:
    return dataset or Dataset(settings.default_dataset)


def parse_as_of(value: str) -> datetime | date:
    """``YYYY-MM-DD`` means end of that day in IST; otherwise an ISO instant with offset."""
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid as_of: {value!r}") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of datetimes must carry a UTC offset")
    return parsed


def get_as_of(
    as_of: Annotated[
        str | None,
        Query(description="View data as of this date (end of day IST) or ISO instant with offset."),
    ] = None,
) -> datetime | date:
    if as_of is None:
        return datetime.now(tz=UTC)
    return parse_as_of(as_of)


def get_pit(
    session: Annotated[Session, Depends(get_session)],
    dataset: Annotated[Dataset, Depends(get_dataset)],
    as_of: Annotated[datetime | date, Depends(get_as_of)],
) -> PointInTimeSession:
    try:
        return PointInTimeSession(session, as_of, is_mock=dataset is Dataset.MOCK)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


SessionDep = Annotated[Session, Depends(get_session)]
PitDep = Annotated[PointInTimeSession, Depends(get_pit)]
DatasetDep = Annotated[Dataset, Depends(get_dataset)]
