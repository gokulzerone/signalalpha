"""Row factories for tests. Everything created here is mock data (``is_mock=True``)."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import count
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from data.documents import page_offsets_for
from database.models import (
    Announcement,
    AnnouncementCategory,
    Company,
    DocumentText,
    Exchange,
    ExtractionMethod,
    Filing,
    FilingType,
    Financial,
    ListingStatus,
    Price,
    RawDocument,
    Shareholding,
    Source,
    UniverseSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")
_seq = count(1)


def ist(y: int, m: int, d: int, hh: int = 18, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def make_company(
    session: Session,
    ticker: str | None = None,
    *,
    is_mock: bool = True,
    sector: str = "Capital Goods",
) -> Company:
    n = next(_seq)
    if ticker is None:
        ticker = f"MOCK-T{n:04d}" if is_mock else f"LIVE{n:04d}"
    company = Company(
        name=f"Company {n}", ticker=ticker, exchange=Exchange.NSE, sector=sector, is_mock=is_mock
    )
    session.add(company)
    session.flush()
    return company


def make_raw_document(
    session: Session,
    company: Company | None,
    public_at: datetime,
    *,
    source: Source = Source.NSE_ANNOUNCEMENTS,
    text: str | None = None,
    is_mock: bool = True,
) -> RawDocument:
    n = next(_seq)
    body = (
        text
        if text is not None
        else f"Mock document {n} for {company.ticker if company else 'market'}."
    )
    sha = hashlib.sha256(f"{n}:{body}".encode()).hexdigest()
    doc = RawDocument(
        company_id=company.id if company else None,
        source=source,
        sha256=sha,
        storage_key=f"raw/{source}/{company.id if company else 'market'}/{sha}.txt",
        content_type="text/plain",
        byte_size=len(body.encode()),
        public_at=public_at,
        is_mock=is_mock,
    )
    session.add(doc)
    session.flush()
    session.add(
        DocumentText(
            raw_document_id=doc.id,
            parser_version="test-1",
            extraction_method=ExtractionMethod.TEXT,
            text=body,
            char_count=len(body),
            page_offsets=page_offsets_for(body),
        )
    )
    session.flush()
    return doc


def make_filing(
    session: Session,
    company: Company,
    public_at: datetime,
    *,
    filing_type: FilingType = FilingType.QUARTERLY_RESULTS,
    period_end: date | None = None,
    is_mock: bool = True,
) -> Filing:
    doc = make_raw_document(
        session, company, public_at, source=Source.FINANCIAL_RESULTS, is_mock=is_mock
    )
    filing = Filing(
        company_id=company.id,
        raw_document_id=doc.id,
        filing_type=filing_type,
        period_end=period_end,
        parser_version="test-1",
        public_at=public_at,
        is_mock=is_mock,
    )
    session.add(filing)
    session.flush()
    return filing


def make_financial(
    session: Session,
    company: Company,
    period_end: date,
    public_at: datetime,
    *,
    revenue: Decimal | int = 100,
    ebitda: Decimal | int = 15,
    consolidated: bool = True,
    period_months: int = 3,
    filing: Filing | None = None,
    parser_version: str = "test-1",
    is_mock: bool = True,
) -> Financial:
    filing = filing or make_filing(
        session, company, public_at, period_end=period_end, is_mock=is_mock
    )
    row = Financial(
        company_id=company.id,
        filing_id=filing.id,
        raw_document_id=filing.raw_document_id,
        parser_version=parser_version,
        public_at=public_at,
        period_end=period_end,
        period_months=period_months,
        consolidated=consolidated,
        extraction_method=ExtractionMethod.STRUCTURED,
        confidence=Decimal("1.0"),
        revenue=Decimal(revenue),
        ebitda=Decimal(ebitda),
        is_mock=is_mock,
    )
    session.add(row)
    session.flush()
    return row


def make_shareholding(
    session: Session,
    company: Company,
    period_end: date,
    public_at: datetime,
    *,
    promoter_pct: Decimal | str = "55.0",
    pledged_pct: Decimal | str = "0",
    is_mock: bool = True,
) -> Shareholding:
    filing = make_filing(
        session,
        company,
        public_at,
        filing_type=FilingType.SHAREHOLDING_PATTERN,
        period_end=period_end,
        is_mock=is_mock,
    )
    row = Shareholding(
        company_id=company.id,
        filing_id=filing.id,
        raw_document_id=filing.raw_document_id,
        parser_version="test-1",
        public_at=public_at,
        period_end=period_end,
        promoter_pct=Decimal(promoter_pct),
        promoter_pledged_pct=Decimal(pledged_pct),
        fii_pct=Decimal("2"),
        dii_pct=Decimal("3"),
        public_pct=Decimal("100") - Decimal(promoter_pct) - Decimal("5"),
        total_shareholders=10000,
        retail_shareholders=9500,
        extraction_method=ExtractionMethod.STRUCTURED,
        confidence=Decimal("1.0"),
        is_mock=is_mock,
    )
    session.add(row)
    session.flush()
    return row


def make_announcement(
    session: Session,
    company: Company,
    public_at: datetime,
    *,
    category: AnnouncementCategory = AnnouncementCategory.ORDER_WIN,
    subject: str = "Order win",
    is_mock: bool = True,
) -> Announcement:
    doc = make_raw_document(session, company, public_at, is_mock=is_mock)
    row = Announcement(
        company_id=company.id,
        raw_document_id=doc.id,
        parser_version="test-1",
        public_at=public_at,
        category=category,
        subject=subject,
        is_mock=is_mock,
    )
    session.add(row)
    session.flush()
    return row


def make_price(
    session: Session,
    company: Company,
    trade_date: date,
    *,
    close: Decimal | int = 100,
    raw_document: RawDocument | None = None,
    parser_version: str = "test-1",
    is_mock: bool = True,
) -> Price:
    public_at = datetime.combine(trade_date, datetime.min.time(), tzinfo=IST) + timedelta(hours=18)
    doc = raw_document or make_raw_document(
        session, None, public_at, source=Source.EOD_PRICES, is_mock=is_mock
    )
    row = Price(
        company_id=company.id,
        raw_document_id=doc.id,
        parser_version=parser_version,
        public_at=public_at,
        trade_date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=10000,
        traded_value=Decimal(close) * 10000,
        delivery_pct=Decimal("40"),
        is_mock=is_mock,
    )
    session.add(row)
    session.flush()
    return row


def make_snapshot(
    session: Session,
    company: Company,
    snapshot_date: date,
    *,
    status: ListingStatus = ListingStatus.LISTED,
    market_cap_cr: Decimal | int = 800,
    in_universe: bool = True,
    is_mock: bool = True,
) -> UniverseSnapshot:
    row = UniverseSnapshot(
        company_id=company.id,
        snapshot_date=snapshot_date,
        market_cap_cr=Decimal(market_cap_cr),
        median_traded_value_30d=Decimal("5000000"),
        is_illiquid=False,
        listing_status=status,
        in_cap_band=in_universe,
        in_universe=in_universe,
        config_version="test",
        is_mock=is_mock,
    )
    session.add(row)
    session.flush()
    return row
