"""Live ingestion (PRD §15 step 10): parsers against golden files, feature flags, raw-first
storage, data-quality bookkeeping, loud failures, and no network in CI."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from data.fetchers.settings import IngestionFlags, LiveCompany, load_live_universe, load_sources
from data.fetchers.transport import FakeTransport, FetchError
from data.ingest import (
    FeatureDisabledError,
    ingest_announcements,
    ingest_eod_prices,
    previous_trading_day,
    sync_live_universe,
)
from data.parsers import nse_announcements, nse_prices
from data.storage import MemoryObjectStore
from database.models import (
    Announcement,
    AnnouncementCategory,
    DataQuality,
    Price,
    RawDocument,
    Source,
)

GOLDEN = Path(__file__).parent / "golden"
FLAGS_ON = IngestionFlags(live_eod_prices=True, live_nse_announcements=True)


def test_price_parser_golden_file() -> None:
    rows = nse_prices.parse_sec_bhavdata((GOLDEN / "sec_bhavdata_sample.csv").read_text())
    assert [(r.symbol, r.series) for r in rows] == [
        ("TESTCO", "EQ"),
        ("OTHERCO", "EQ"),
        ("THINCO", "BE"),
    ]
    first = rows[0]
    assert (
        first.trade_date == date(2026, 9, 2)
        and first.close == Decimal("103.00")
        and first.volume == 125000
    )
    assert first.traded_value == Decimal("12763000") and first.delivery_pct == Decimal("49.00")
    with pytest.raises(nse_prices.ParseError, match="missing columns"):
        nse_prices.parse_sec_bhavdata("SYMBOL,SERIES\nX,EQ\n")


def test_announcement_parser_and_classifier() -> None:
    rows = nse_announcements.parse_announcements((GOLDEN / "announcements_sample.json").read_text())
    assert [r.category for r in rows] == [
        AnnouncementCategory.ORDER_WIN,
        AnnouncementCategory.RESULTS,
        AnnouncementCategory.RESIGNATION,
        AnnouncementCategory.CREDIT_RATING,
    ]
    assert (
        rows[0].disseminated_at.isoformat() == "2026-09-02T14:05:31+05:30"
        and rows[0].attachment_url
    )
    assert rows[1].attachment_url is None
    assert (
        nse_announcements.classify("Intimation of Board Meeting")
        is AnnouncementCategory.BOARD_MEETING
    )
    assert nse_announcements.classify("Something else entirely") is AnnouncementCategory.OTHER
    with pytest.raises(nse_announcements.ParseError):
        nse_announcements.parse_announcements("<html>blocked</html>")


def test_live_universe_config_is_empty_by_default_and_rejects_mock(session: Session) -> None:
    assert load_live_universe() == []
    with pytest.raises(ValueError, match="MOCK-"):
        sync_live_universe(session, [LiveCompany(ticker="MOCK-X", name="x")])


def test_feature_flags_default_off(session: Session) -> None:
    transport = FakeTransport({})
    with pytest.raises(FeatureDisabledError):
        ingest_eod_prices(
            session, MemoryObjectStore(), transport, date(2026, 9, 2), flags=IngestionFlags()
        )
    assert transport.requested == []


def test_eod_prices_end_to_end_with_fake_transport(session: Session) -> None:
    registry = load_sources()
    companies = sync_live_universe(
        session, [LiveCompany(ticker="TESTCO", name="TestCo Limited", sector="Engineering")]
    )
    url = registry.eod_prices.url_template.format(ddmmyyyy="02092026")
    transport = FakeTransport({url: (GOLDEN / "sec_bhavdata_sample.csv").read_bytes()})
    store = MemoryObjectStore()
    report = ingest_eod_prices(
        session,
        store,
        transport,
        date(2026, 9, 2),
        flags=FLAGS_ON,
        registry=registry,
        companies=companies,
    )
    assert report.rows == 1 and report.created_documents == 1
    price = session.scalars(select(Price).where(Price.company_id == companies["TESTCO"].id)).one()
    assert (
        price.close == Decimal("103.00")
        and price.is_mock is False
        and price.parser_version == "nse-secbhav-1"
    )
    raw = session.get(RawDocument, price.raw_document_id)
    assert (
        raw is not None
        and raw.url == url
        and store.get(raw.storage_key) == (GOLDEN / "sec_bhavdata_sample.csv").read_bytes()
    )
    assert price.public_at.hour == 18 and price.public_at.tzinfo is not None
    dq = session.scalars(
        select(DataQuality).where(
            DataQuality.company_id == companies["TESTCO"].id,
            DataQuality.source == Source.EOD_PRICES,
        )
    ).one()
    assert (
        dq.last_success_at is not None
        and dq.fetch_failure_count == 0
        and dq.latest_public_at == price.public_at
    )
    # Re-running the same day is a no-op (raw dedup by sha256, rows by trade date).
    again = ingest_eod_prices(
        session,
        store,
        transport,
        date(2026, 9, 2),
        flags=FLAGS_ON,
        registry=registry,
        companies=companies,
    )
    assert again.rows == 0 and again.skipped == 1 and again.created_documents == 0


def test_fetch_failure_is_recorded_and_raised(session: Session) -> None:
    registry = load_sources()
    transport = FakeTransport({})  # every URL 404s
    with pytest.raises(FetchError, match="404"):
        ingest_eod_prices(
            session,
            MemoryObjectStore(),
            transport,
            date(2026, 9, 3),
            flags=FLAGS_ON,
            registry=registry,
            companies={},
        )
    dq = session.scalars(
        select(DataQuality).where(
            DataQuality.company_id.is_(None), DataQuality.source == Source.EOD_PRICES
        )
    ).one()
    assert dq.fetch_failure_count == 1 and dq.last_error and "404" in dq.last_error
    bad_format = registry.eod_prices.url_template.format(ddmmyyyy="04092026")
    with pytest.raises(nse_prices.ParseError):
        ingest_eod_prices(
            session,
            MemoryObjectStore(),
            FakeTransport({bad_format: b"totally,different\n1,2\n"}),
            date(2026, 9, 4),
            flags=FLAGS_ON,
            registry=registry,
            companies={},
        )
    session.refresh(dq)
    assert dq.parse_failure_count == 1


def test_announcements_end_to_end(session: Session) -> None:
    registry = load_sources()
    companies = sync_live_universe(session, [LiveCompany(ticker="TESTCO", name="TestCo Limited")])
    company = companies["TESTCO"]
    url = registry.nse_announcements.url_template.format(
        symbol="TESTCO", from_ddmmyyyy="01-08-2026", to_ddmmyyyy="03-09-2026"
    )
    transport = FakeTransport(
        {url: (GOLDEN / "announcements_sample.json").read_bytes()}
    )  # attachment 404s
    report = ingest_announcements(
        session,
        MemoryObjectStore(),
        transport,
        company,
        date(2026, 8, 1),
        date(2026, 9, 3),
        flags=FLAGS_ON,
        registry=registry,
    )
    assert report.rows == 3  # OTHERCO's row is ignored for this company
    anns = session.scalars(
        select(Announcement)
        .where(Announcement.company_id == company.id)
        .order_by(Announcement.public_at)
    ).all()
    assert [a.category for a in anns] == [
        AnnouncementCategory.RESIGNATION,
        AnnouncementCategory.RESULTS,
        AnnouncementCategory.ORDER_WIN,
    ]
    order = anns[-1]
    assert order.summary == "attachment_unavailable=true"  # the PDF fetch failed and was recorded
    dq = session.scalars(
        select(DataQuality).where(
            DataQuality.company_id == company.id, DataQuality.source == Source.NSE_ANNOUNCEMENTS
        )
    ).one()
    assert dq.fetch_failure_count == 1 and dq.last_success_at is not None
    raw = session.get(RawDocument, order.raw_document_id)
    assert raw is not None and "order worth Rs. 45.20 crore" in raw.texts[0].text
    again = ingest_announcements(
        session,
        MemoryObjectStore(),
        transport,
        company,
        date(2026, 8, 1),
        date(2026, 9, 3),
        flags=FLAGS_ON,
        registry=registry,
    )
    assert again.rows == 0 and again.skipped == 3


def test_previous_trading_day_skips_weekends() -> None:
    assert previous_trading_day(date(2026, 9, 7)) == date(2026, 9, 4)  # Monday -> Friday
    assert previous_trading_day(date(2026, 9, 3)) == date(2026, 9, 2)
