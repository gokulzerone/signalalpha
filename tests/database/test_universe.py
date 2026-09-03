from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from database.models import DelistingKind, ListingStatus
from database.pit import LookAheadError, PointInTimeSession
from tests.factories import make_company, make_snapshot


def test_universe_is_versioned_by_date_without_survivorship_bias(session: Session) -> None:
    survivor = make_company(session)
    delisted = make_company(session)
    for d in (date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)):
        make_snapshot(session, survivor, d)
    make_snapshot(session, delisted, date(2024, 1, 31))
    row = make_snapshot(
        session, delisted, date(2024, 2, 15), status=ListingStatus.DELISTED, in_universe=False
    )
    row.delisting_kind = DelistingKind.COMPULSORY
    session.flush()

    pit = PointInTimeSession(session, date(2024, 12, 31), is_mock=True)

    jan = {s.company_id: s for s in pit.universe(date(2024, 2, 10))}
    assert jan[delisted.id].listing_status is ListingStatus.LISTED
    assert jan[delisted.id].in_universe is True
    assert jan[survivor.id].snapshot_date == date(2024, 1, 31)

    mar = {s.company_id: s for s in pit.universe(date(2024, 3, 31))}
    assert mar[delisted.id].listing_status is ListingStatus.DELISTED
    assert mar[delisted.id].delisting_kind is DelistingKind.COMPULSORY
    assert mar[delisted.id].in_universe is False
    assert mar[survivor.id].snapshot_date == date(2024, 3, 31)

    assert pit.universe(date(2023, 12, 31)) == []


def test_universe_cannot_look_past_as_of(session: Session) -> None:
    pit = PointInTimeSession(session, date(2024, 6, 30), is_mock=True)
    with pytest.raises(LookAheadError):
        pit.universe(date(2024, 7, 1))


def test_universe_never_mixes_mock_and_live(session: Session) -> None:
    mock_co = make_company(session, is_mock=True)
    live_co = make_company(session, is_mock=False)
    make_snapshot(session, mock_co, date(2024, 1, 31), is_mock=True)
    make_snapshot(session, live_co, date(2024, 1, 31), is_mock=False)
    mock_ids = {
        s.company_id for s in PointInTimeSession(session, date(2024, 3, 1), is_mock=True).universe()
    }
    live_ids = {
        s.company_id
        for s in PointInTimeSession(session, date(2024, 3, 1), is_mock=False).universe()
    }
    assert mock_ids == {mock_co.id}
    assert live_ids == {live_co.id}
