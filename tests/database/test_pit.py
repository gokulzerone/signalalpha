"""Point-in-time guarantees (PRD §2.5, §11, §14)."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from database.models import AnnouncementCategory, Company, FilingType, PublicAtMixin, Source
from database.pit import IST, PointInTimeSession, coerce_as_of, end_of_day
from tests.factories import (
    ist,
    make_announcement,
    make_company,
    make_filing,
    make_financial,
    make_price,
    make_raw_document,
    make_shareholding,
)


def test_coerce_as_of_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        coerce_as_of(datetime(2024, 1, 1))


def test_coerce_as_of_date_means_end_of_day_ist() -> None:
    as_of = coerce_as_of(date(2024, 3, 31))
    assert as_of == end_of_day(date(2024, 3, 31))
    assert as_of.astimezone(IST).date() == date(2024, 3, 31)
    assert as_of.astimezone(IST).hour == 23
    assert as_of.tzinfo == ZoneInfo("UTC")


def test_restatement_resolves_to_latest_filing_public_at_as_of(session: Session) -> None:
    company = make_company(session)
    q = date(2024, 3, 31)
    make_financial(session, company, q, ist(2024, 5, 10), revenue=100)
    make_financial(session, company, q, ist(2024, 8, 12), revenue=95)  # restated

    before = PointInTimeSession(session, ist(2024, 6, 1), is_mock=True).financials(company.id)
    after = PointInTimeSession(session, ist(2024, 9, 1), is_mock=True).financials(company.id)
    too_early = PointInTimeSession(session, ist(2024, 5, 1), is_mock=True).financials(company.id)

    assert [r.revenue for r in before] == [Decimal(100)]
    assert [r.revenue for r in after] == [Decimal(95)]
    assert too_early == []


def test_superseded_parser_output_is_excluded(session: Session) -> None:
    company = make_company(session)
    q = date(2024, 3, 31)
    filing = make_filing(session, company, ist(2024, 5, 10), period_end=q)
    old = make_financial(
        session, company, q, ist(2024, 5, 10), revenue=100, filing=filing, parser_version="v1"
    )
    old.is_superseded = True
    make_financial(
        session, company, q, ist(2024, 5, 10), revenue=101, filing=filing, parser_version="v2"
    )
    rows = PointInTimeSession(session, ist(2024, 6, 1), is_mock=True).financials(company.id)
    assert [r.revenue for r in rows] == [Decimal(101)]


def test_financials_prefer_consolidated_but_fall_back(session: Session) -> None:
    company = make_company(session)
    make_financial(
        session, company, date(2023, 12, 31), ist(2024, 2, 1), revenue=50, consolidated=False
    )
    make_financial(
        session, company, date(2024, 3, 31), ist(2024, 5, 1), revenue=60, consolidated=False
    )
    make_financial(
        session, company, date(2024, 3, 31), ist(2024, 5, 1), revenue=65, consolidated=True
    )
    pit = PointInTimeSession(session, date(2024, 6, 30), is_mock=True)
    rows = pit.financials_preferring_consolidated(company.id)
    assert [(r.period_end, r.consolidated, r.revenue) for r in rows] == [
        (date(2024, 3, 31), True, Decimal(65)),
        (date(2023, 12, 31), False, Decimal(50)),
    ]
    assert len(pit.financials(company.id, consolidated=False)) == 2
    assert len(pit.financials(company.id, consolidated=True)) == 1
    assert len(pit.financials(company.id, periods=1)) == 1


def test_prices_return_latest_parser_version_per_day(session: Session) -> None:
    company = make_company(session)
    d = date(2024, 4, 1)
    make_price(session, company, d, close=100, parser_version="v1")
    make_price(session, company, d, close=101, parser_version="v2")
    make_price(session, company, d + timedelta(days=1), close=102)
    pit = PointInTimeSession(session, date(2024, 4, 30), is_mock=True)
    rows = pit.prices(company.id, d, d + timedelta(days=1))
    assert [(r.trade_date, r.close) for r in rows] == [
        (d, Decimal(101)),
        (d + timedelta(days=1), Decimal(102)),
    ]
    # A price published at 18:00 IST on the trade date is not visible at as_of = noon that day.
    noon = datetime(2024, 4, 2, 12, 0, tzinfo=IST)
    assert PointInTimeSession(session, noon, is_mock=True).prices(company.id, d) == [rows[0]]


def test_document_text_is_hidden_until_document_is_public(session: Session) -> None:
    company = make_company(session)
    doc = make_raw_document(
        session, company, ist(2024, 7, 15), text="Order worth Rs 120 crore received."
    )
    assert (
        PointInTimeSession(session, date(2024, 7, 14), is_mock=True).document_text(doc.id) is None
    )
    got = PointInTimeSession(session, date(2024, 7, 15), is_mock=True).document_text(doc.id)
    assert got is not None and got.text == "Order worth Rs 120 crore received."
    assert PointInTimeSession(session, date(2024, 7, 14), is_mock=True).raw_document(doc.id) is None


def test_announcement_filters(session: Session) -> None:
    company = make_company(session)
    make_announcement(session, company, ist(2024, 1, 5), category=AnnouncementCategory.ORDER_WIN)
    make_announcement(session, company, ist(2024, 2, 5), category=AnnouncementCategory.RESIGNATION)
    pit = PointInTimeSession(session, date(2024, 3, 1), is_mock=True)
    assert len(pit.announcements(company.id)) == 2
    assert len(pit.announcements(company.id, since=date(2024, 1, 31))) == 1
    only = pit.announcements(company.id, categories=[AnnouncementCategory.ORDER_WIN])
    assert [a.category for a in only] == [AnnouncementCategory.ORDER_WIN]


def test_mock_and_live_rows_never_mix(session: Session) -> None:
    mock_co = make_company(session, is_mock=True)
    live_co = make_company(session, is_mock=False)
    make_financial(session, mock_co, date(2024, 3, 31), ist(2024, 5, 1), is_mock=True)
    make_financial(session, live_co, date(2024, 3, 31), ist(2024, 5, 1), is_mock=False)
    live = PointInTimeSession(session, date(2024, 6, 1), is_mock=False)
    mock = PointInTimeSession(session, date(2024, 6, 1), is_mock=True)
    assert live.financials(mock_co.id) == []
    assert mock.financials(live_co.id) == []
    assert live.company(mock_co.id) is None
    assert {c.id for c in mock.companies()} >= {mock_co.id}
    assert live_co.id not in {c.id for c in mock.companies()}


def _seed_random_history(session: Session, rng: random.Random) -> list[Company]:
    companies = [make_company(session) for _ in range(3)]
    start = datetime(2022, 1, 1, 9, tzinfo=IST)
    for company in companies:
        for i in range(12):
            q_end = date(2022, 3, 31) + timedelta(days=91 * i)
            public = start + timedelta(days=rng.randint(0, 1400), hours=rng.randint(0, 23))
            make_financial(session, company, q_end, public, revenue=100 + i)
            make_shareholding(session, company, q_end, start + timedelta(days=rng.randint(0, 1400)))
        for _ in range(15):
            make_announcement(session, company, start + timedelta(days=rng.randint(0, 1400)))
        for _ in range(20):
            make_price(session, company, date(2022, 1, 3) + timedelta(days=rng.randint(0, 1400)))
        for _ in range(5):
            make_raw_document(session, company, start + timedelta(days=rng.randint(0, 1400)))
    return companies


def test_no_query_returns_rows_public_after_as_of(session: Session) -> None:
    """PRD §11 / §14: for random as_of dates, nothing with public_at > as_of comes back."""
    rng = random.Random(20240903)
    companies = _seed_random_history(session, rng)
    for _ in range(25):
        as_of = datetime(2022, 1, 1, tzinfo=IST) + timedelta(
            days=rng.randint(0, 1500), hours=rng.randint(0, 23)
        )
        pit = PointInTimeSession(session, as_of, is_mock=True)
        for company in companies:
            rows: list[PublicAtMixin] = [
                *pit.financials(company.id),
                *pit.shareholdings(company.id),
                *pit.announcements(company.id),
                *pit.prices(company.id, date(2022, 1, 1)),
                *pit.raw_documents(company.id),
                *pit.filings(company.id),
            ]
            for row in rows:
                assert row.public_at <= pit.as_of, (type(row).__name__, row.public_at, pit.as_of)
            for f in pit.financials(company.id):
                assert f.filing_id is not None
            assert all(
                f.filing_type is FilingType.QUARTERLY_RESULTS
                for f in pit.filings(company.id, FilingType.QUARTERLY_RESULTS)
            )
            assert all(
                d.source is Source.EOD_PRICES
                for d in pit.raw_documents(company.id, Source.EOD_PRICES)
            )
