"""Live ingestion orchestration (PRD §5.2 raw first, provenance, visible failures).

Each function: checks its feature flag, fetches through the transport, stores the fetched
bytes raw-first, parses with a versioned parser, writes derived rows with provenance, and
updates ``data_quality``. Any fetch or parse problem is recorded and then re-raised so the
scheduler sees it (fail loudly).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.documents import DocumentWriter
from data.fetchers.settings import (
    IngestionFlags,
    LiveCompany,
    SourceRegistry,
    load_live_universe,
    load_sources,
)
from data.fetchers.transport import FetchError, Transport
from data.parsers import nse_announcements, nse_prices, pdf_text
from data.storage import ObjectStore, raw_document_key
from database.models import Announcement, Company, DataQuality, Exchange, Price, RawDocument, Source

IST = ZoneInfo("Asia/Kolkata")


class FeatureDisabledError(RuntimeError):
    pass


@dataclass
class IngestReport:
    source: Source
    fetched: int = 0
    created_documents: int = 0
    rows: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)


def sync_live_universe(
    session: Session, companies: list[LiveCompany] | None = None
) -> dict[str, Company]:
    """Create/refresh live ``companies`` rows from the configured universe. Never mock."""
    out: dict[str, Company] = {}
    for lc in companies if companies is not None else load_live_universe():
        if lc.ticker.startswith("MOCK-"):
            raise ValueError("live universe tickers cannot start with MOCK-")
        row = session.scalars(
            select(Company).where(Company.ticker == lc.ticker, Company.is_mock.is_(False))
        ).first()
        if row is None:
            row = Company(
                name=lc.name,
                ticker=lc.ticker,
                isin=lc.isin,
                exchange=Exchange.NSE,
                sector=lc.sector,
                industry=lc.industry,
                is_mock=False,
            )
            session.add(row)
        else:
            row.name, row.sector, row.industry = lc.name, lc.sector, lc.industry
        session.flush()
        out[lc.ticker] = row
    return out


def _quality(session: Session, company_id: int | None, source: Source) -> DataQuality:
    row = session.scalars(
        select(DataQuality).where(
            DataQuality.company_id == company_id,
            DataQuality.source == source,
            DataQuality.is_mock.is_(False),
        )
    ).first()
    if row is None:
        row = DataQuality(company_id=company_id, source=source, is_mock=False)
        session.add(row)
        session.flush()
    return row


def _record_failure(
    session: Session, company_id: int | None, source: Source, kind: str, error: str
) -> None:
    q = _quality(session, company_id, source)
    q.last_fetch_at = datetime.now(tz=IST)
    if kind == "fetch":
        q.fetch_failure_count += 1
    else:
        q.parse_failure_count += 1
    q.last_error = error[:2000]
    session.flush()


def _record_success(
    session: Session, company_id: int | None, source: Source, latest_public_at: datetime | None
) -> None:
    q = _quality(session, company_id, source)
    now = datetime.now(tz=IST)
    q.last_fetch_at, q.last_success_at, q.last_error = now, now, None
    if latest_public_at is not None and (
        q.latest_public_at is None or latest_public_at > q.latest_public_at
    ):
        q.latest_public_at = latest_public_at
    session.flush()


# ------------------------------------------------------------------ EOD prices
def ingest_eod_prices(
    session: Session,
    store: ObjectStore,
    transport: Transport,
    trade_date: date,
    *,
    flags: IngestionFlags | None = None,
    registry: SourceRegistry | None = None,
    companies: dict[str, Company] | None = None,
) -> IngestReport:
    flags = flags or IngestionFlags()
    if not flags.live_eod_prices:
        raise FeatureDisabledError("SIGNALALPHA_LIVE_EOD_PRICES is off")
    registry = registry or load_sources()
    src = registry.eod_prices
    report = IngestReport(Source.EOD_PRICES)
    url = src.url_template.format(ddmmyyyy=trade_date.strftime("%d%m%Y"))
    hh, mm = (int(x) for x in src.publication_time_ist.split(":"))
    public_at = datetime.combine(trade_date, time(hh, mm), tzinfo=IST)
    try:
        fetched = transport.get(url)
    except FetchError as exc:
        _record_failure(session, None, Source.EOD_PRICES, "fetch", str(exc))
        raise
    report.fetched = 1
    text = fetched.content.decode("utf-8", errors="replace")
    writer = DocumentWriter(session, store, is_mock=False)
    doc = writer.write_text_document(
        company=None,
        source=Source.EOD_PRICES,
        text=text,
        public_at=public_at,
        parser_version=src.parser_version,
        title=f"NSE sec_bhavdata {trade_date.isoformat()}",
        url=url,
        ext="csv",
        content_type="text/csv",
    )
    report.created_documents += int(doc.created)
    try:
        records = nse_prices.parse_sec_bhavdata(text, tuple(src.series))
    except nse_prices.ParseError as exc:
        _record_failure(session, None, Source.EOD_PRICES, "parse", str(exc))
        raise
    companies = (
        companies
        if companies is not None
        else {
            c.ticker: c
            for c in session.scalars(select(Company).where(Company.is_mock.is_(False))).all()
        }
    )
    for rec in records:
        company = companies.get(rec.symbol)
        if company is None:
            continue
        exists = session.scalars(
            select(Price.id).where(
                Price.company_id == company.id,
                Price.trade_date == rec.trade_date,
                Price.parser_version == src.parser_version,
            )
        ).first()
        if exists is not None:
            report.skipped += 1
            continue
        session.add(
            Price(
                company_id=company.id,
                raw_document_id=doc.raw_document.id,
                parser_version=src.parser_version,
                public_at=public_at,
                trade_date=rec.trade_date,
                open=rec.open,
                high=rec.high,
                low=rec.low,
                close=rec.close,
                volume=rec.volume,
                traded_value=rec.traded_value,
                delivery_pct=rec.delivery_pct,
                is_mock=False,
            )
        )
        report.rows += 1
        _record_success(session, company.id, Source.EOD_PRICES, public_at)
    _record_success(session, None, Source.EOD_PRICES, public_at)
    session.flush()
    return report


# ---------------------------------------------------------------- announcements
def ingest_announcements(
    session: Session,
    store: ObjectStore,
    transport: Transport,
    company: Company,
    since: date,
    until: date | None = None,
    *,
    flags: IngestionFlags | None = None,
    registry: SourceRegistry | None = None,
) -> IngestReport:
    flags = flags or IngestionFlags()
    if not flags.live_nse_announcements:
        raise FeatureDisabledError("SIGNALALPHA_LIVE_NSE_ANNOUNCEMENTS is off")
    if company.is_mock:
        raise ValueError("live ingestion never targets mock companies")
    registry = registry or load_sources()
    src = registry.nse_announcements
    until = until or date.today()
    report = IngestReport(Source.NSE_ANNOUNCEMENTS)
    url = src.url_template.format(
        symbol=company.ticker,
        from_ddmmyyyy=since.strftime("%d-%m-%Y"),
        to_ddmmyyyy=until.strftime("%d-%m-%Y"),
    )
    try:
        fetched = transport.get(url)
    except FetchError as exc:
        _record_failure(session, company.id, Source.NSE_ANNOUNCEMENTS, "fetch", str(exc))
        raise
    report.fetched = 1
    try:
        records = nse_announcements.parse_announcements(
            fetched.content.decode("utf-8", errors="replace")
        )
    except nse_announcements.ParseError as exc:
        _record_failure(session, company.id, Source.NSE_ANNOUNCEMENTS, "parse", str(exc))
        raise
    writer = DocumentWriter(session, store, is_mock=False)
    latest: datetime | None = None
    for rec in records:
        if rec.symbol != company.ticker:
            continue
        text = nse_announcements.render_announcement_text(rec)
        attachment_failed = False
        if rec.attachment_url:
            try:
                pdf = transport.get(rec.attachment_url)
                report.fetched += 1
                try:
                    body = pdf_text.extract_pdf_text(pdf.content)
                    _store_raw_bytes(
                        session,
                        store,
                        company,
                        pdf.content,
                        rec.attachment_url,
                        rec.disseminated_at,
                    )
                    text = f"{text}\n\f{body}"
                except pdf_text.NoTextLayerError as exc:
                    attachment_failed = True
                    _record_failure(
                        session,
                        company.id,
                        Source.NSE_ANNOUNCEMENTS,
                        "parse",
                        f"{rec.attachment_url}: {exc}",
                    )
            except FetchError as exc:
                attachment_failed = True
                _record_failure(session, company.id, Source.NSE_ANNOUNCEMENTS, "fetch", str(exc))
        doc = writer.write_text_document(
            company=company,
            source=Source.NSE_ANNOUNCEMENTS,
            text=text,
            public_at=rec.disseminated_at,
            parser_version=src.parser_version,
            title=rec.subject[:500],
            url=rec.attachment_url,
        )
        if not doc.created:
            report.skipped += 1
            continue
        report.created_documents += 1
        session.add(
            Announcement(
                company_id=company.id,
                raw_document_id=doc.raw_document.id,
                parser_version=src.parser_version,
                public_at=rec.disseminated_at,
                category=rec.category,
                subject=rec.subject[:512],
                summary=("attachment_unavailable=true" if attachment_failed else None),
                is_mock=False,
            )
        )
        report.rows += 1
        latest = rec.disseminated_at if latest is None or rec.disseminated_at > latest else latest
    _record_success(session, company.id, Source.NSE_ANNOUNCEMENTS, latest)
    session.flush()
    return report


def _store_raw_bytes(
    session: Session,
    store: ObjectStore,
    company: Company,
    data: bytes,
    url: str,
    public_at: datetime,
) -> RawDocument:
    """Keep the original PDF bytes in object storage (raw first) alongside the text document."""
    sha = hashlib.sha256(data).hexdigest()
    existing = session.scalars(select(RawDocument).where(RawDocument.sha256 == sha)).first()
    if existing is not None:
        return existing
    key = raw_document_key(Source.NSE_ANNOUNCEMENTS.value, company.id, public_at, sha, "pdf")
    store.put(key, data, "application/pdf")
    row = RawDocument(
        company_id=company.id,
        source=Source.NSE_ANNOUNCEMENTS,
        sha256=sha,
        storage_key=key,
        url=url,
        content_type="application/pdf",
        byte_size=len(data),
        title="attachment",
        public_at=public_at,
        is_mock=False,
    )
    session.add(row)
    session.flush()
    return row


def previous_trading_day(today: date | None = None) -> date:
    d = (today or datetime.now(tz=IST).date()) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _unused(_: Decimal, __: Any) -> None:
    return None
