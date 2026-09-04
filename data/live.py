"""Live NSE ingestion (PRD §15 step 10).

Fetches, stores raw-first, parses with versioned parsers and writes provenance-bearing rows
for the real universe. Everything here is feature-flagged; nothing runs unless the operator
turns the source on. Mock and live rows never mix: every row written here has
``is_mock = False``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.documents import DocumentWriter
from data.fetchers.nse import NseClient
from data.fetchers.settings import IngestionFlags, SourceRegistry, load_sources
from data.fetchers.transport import FetchError
from data.ingest import FeatureDisabledError, record_failure, record_success
from data.parsers import nse_announcements, nse_equity_list, nse_prices, nse_xbrl
from data.storage import ObjectStore
from database.models import (
    Announcement,
    Company,
    Exchange,
    ExtractionMethod,
    Filing,
    FilingType,
    Financial,
    Price,
    Source,
)

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class LiveReport:
    step: str
    fetched: int = 0
    rows: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)

    def line(self) -> str:
        f = f", {len(self.failures)} failures" if self.failures else ""
        return f"{self.step}: {self.rows} rows, {self.fetched} fetches, {self.skipped} skipped{f}"


def client(
    registry: SourceRegistry | None = None, flags: IngestionFlags | None = None
) -> NseClient:
    registry = registry or load_sources()
    return NseClient(registry, (flags or IngestionFlags()).contact)


# ------------------------------------------------------------------- universe
def ingest_equity_list(
    session: Session, store: ObjectStore, nse: NseClient, *, registry: SourceRegistry | None = None
) -> dict[str, Company]:
    """Create or refresh live ``companies`` rows from NSE's list of listed equities."""
    registry = registry or load_sources()
    src = registry.equity_list
    fetched = nse.get(src.url_template)
    text = fetched.content.decode("utf-8", errors="replace")
    DocumentWriter(session, store, is_mock=False).write_text_document(
        company=None,
        source=Source.INDEX_CONSTITUENTS,
        text=text,
        public_at=datetime.now(tz=IST),
        parser_version=src.parser_version,
        title="NSE listed equities",
        url=src.url_template,
        ext="csv",
        content_type="text/csv",
    )
    listed = nse_equity_list.parse_equity_list(text)
    existing = {
        c.ticker: c
        for c in session.scalars(select(Company).where(Company.is_mock.is_(False))).all()
    }
    out: dict[str, Company] = {}
    for eq in listed:
        row = existing.get(eq.symbol)
        if row is None:
            row = Company(
                name=eq.name,
                ticker=eq.symbol,
                isin=eq.isin or None,
                exchange=Exchange.NSE,
                sector="Unclassified",
                listed_on=date.fromisoformat(eq.listed_on) if eq.listed_on else None,
                is_mock=False,
            )
            session.add(row)
        else:
            row.name = eq.name
        out[eq.symbol] = row
    session.flush()
    return out


# --------------------------------------------------------------------- prices
def ingest_prices_for_date(
    session: Session,
    store: ObjectStore,
    nse: NseClient,
    on: date,
    companies: dict[str, Company],
    *,
    flags: IngestionFlags | None = None,
    registry: SourceRegistry | None = None,
) -> LiveReport:
    flags = flags or IngestionFlags()
    if not flags.live_eod_prices:
        raise FeatureDisabledError("SIGNALALPHA_LIVE_EOD_PRICES is off")
    registry = registry or load_sources()
    src = registry.eod_prices
    rep = LiveReport(f"prices {on.isoformat()}")
    url = src.url_template.format(ddmmyyyy=on.strftime("%d%m%Y"))
    hh, mm = (int(x) for x in src.publication_time_ist.split(":"))
    public_at = datetime.combine(on, time(hh, mm), tzinfo=IST)
    try:
        fetched = nse.get(url)
    except FetchError as exc:
        # A non-trading day has no file; that is not a data-quality failure.
        if exc.status == 404:
            rep.skipped = 1
            return rep
        record_failure(session, None, Source.EOD_PRICES, "fetch", str(exc))
        rep.failures.append(str(exc))
        return rep
    rep.fetched = 1
    text = fetched.content.decode("utf-8", errors="replace")
    doc = DocumentWriter(session, store, is_mock=False).write_text_document(
        company=None,
        source=Source.EOD_PRICES,
        text=text,
        public_at=public_at,
        parser_version=src.parser_version,
        title=f"NSE sec_bhavdata {on.isoformat()}",
        url=url,
        ext="csv",
        content_type="text/csv",
    )
    if not doc.created:
        rep.skipped = 1
        return rep
    try:
        records = nse_prices.parse_sec_bhavdata(text, tuple(src.series))
    except nse_prices.ParseError as exc:
        record_failure(session, None, Source.EOD_PRICES, "parse", str(exc))
        rep.failures.append(str(exc))
        return rep
    rows: list[dict[str, Any]] = []
    for rec in records:
        company = companies.get(rec.symbol)
        if company is None:
            continue
        rows.append(
            {
                "company_id": company.id,
                "raw_document_id": doc.raw_document.id,
                "parser_version": src.parser_version,
                "public_at": public_at,
                "trade_date": rec.trade_date,
                "open": rec.open,
                "high": rec.high,
                "low": rec.low,
                "close": rec.close,
                "volume": rec.volume,
                "traded_value": rec.traded_value,
                "delivery_pct": rec.delivery_pct,
                "is_mock": False,
            }
        )
    if rows:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(Price)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_prices_company_date")
        )
        session.execute(stmt)
        rep.rows = len(rows)
    record_success(session, None, Source.EOD_PRICES, public_at)
    session.flush()
    return rep


# ------------------------------------------------------------------- results
def ingest_results_for_symbol(
    session: Session,
    store: ObjectStore,
    nse: NseClient,
    company: Company,
    *,
    quarters: int = 9,
    flags: IngestionFlags | None = None,
    registry: SourceRegistry | None = None,
) -> LiveReport:
    """Fetch a company's quarterly filing history and store each filing's XBRL figures."""
    flags = flags or IngestionFlags()
    if not flags.live_financial_results:
        raise FeatureDisabledError("SIGNALALPHA_LIVE_FINANCIAL_RESULTS is off")
    registry = registry or load_sources()
    src = registry.financial_results
    rep = LiveReport(f"results {company.ticker}")
    url = f"{src.url_template.format(period='Quarterly')}&symbol={company.ticker}"
    try:
        payload, _ = nse.get_json(url, src.warmup_url)
        rep.fetched += 1
        feed = nse_xbrl.parse_results_feed(payload)
    except (FetchError, nse_xbrl.ParseError) as exc:
        record_failure(session, company.id, Source.FINANCIAL_RESULTS, "fetch", str(exc))
        rep.failures.append(str(exc))
        return rep

    # Newest filings first; one filing per (period, basis), consolidated preferred.
    feed.sort(key=lambda r: (r.to_date, r.broadcast_at), reverse=True)
    wanted: dict[tuple[date, bool], nse_xbrl.ResultsFeedRow] = {}
    for row in feed:
        wanted.setdefault((row.to_date, row.consolidated), row)
    periods = sorted({p for p, _ in wanted}, reverse=True)[:quarters]
    writer = DocumentWriter(session, store, is_mock=False)
    for period_end in periods:
        for consolidated in (True, False):
            feed_row = wanted.get((period_end, consolidated))
            if feed_row is None:
                continue
            row = feed_row
            have = session.scalars(
                select(Financial.id).where(
                    Financial.company_id == company.id,
                    Financial.period_end == period_end,
                    Financial.consolidated == consolidated,
                    Financial.parser_version == src.parser_version,
                    Financial.is_mock.is_(False),
                )
            ).first()
            if have is not None:
                rep.skipped += 1
                continue
            try:
                fetched = nse.get(row.xbrl_url)
                rep.fetched += 1
                results = nse_xbrl.parse_results_xbrl(fetched.content)
            except (FetchError, nse_xbrl.ParseError) as exc:
                record_failure(
                    session, company.id, Source.FINANCIAL_RESULTS, "parse", f"{row.xbrl_url}: {exc}"
                )
                rep.failures.append(f"{company.ticker} {period_end}: {exc}")
                continue
            doc = writer.write_text_document(
                company=company,
                source=Source.FINANCIAL_RESULTS,
                text=fetched.content.decode("utf-8", errors="replace"),
                public_at=row.broadcast_at,
                parser_version=src.parser_version,
                title=f"Results XBRL {period_end.isoformat()}{' (consolidated)' if consolidated else ''}",
                url=row.xbrl_url,
                ext="xml",
                content_type="application/xml",
                extraction_method=ExtractionMethod.STRUCTURED,
            )
            filing = Filing(
                company_id=company.id,
                raw_document_id=doc.raw_document.id,
                filing_type=FilingType.QUARTERLY_RESULTS,
                period_end=period_end,
                parser_version=src.parser_version,
                public_at=row.broadcast_at,
                is_mock=False,
            )
            session.add(filing)
            session.flush()
            for res in results:
                if res.period_end != period_end:
                    continue
                session.add(
                    Financial(
                        company_id=company.id,
                        filing_id=filing.id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=src.parser_version,
                        public_at=row.broadcast_at,
                        period_end=res.period_end,
                        period_months=res.months,
                        consolidated=res.consolidated,
                        extraction_method=ExtractionMethod.STRUCTURED,
                        confidence=Decimal("1.0"),
                        revenue=res.revenue,
                        other_income=res.other_income,
                        total_expenses=res.total_expenses,
                        ebitda=res.ebitda,
                        depreciation=res.depreciation,
                        finance_cost=res.finance_cost,
                        pbt=res.pbt,
                        tax=res.tax,
                        pat=res.pat,
                        eps=res.eps,
                        shares_outstanding=res.shares_outstanding_cr,
                        is_mock=False,
                    )
                )
                rep.rows += 1
            if company.isin is None and results and results[0].isin:
                company.isin = results[0].isin
    record_success(
        session,
        company.id,
        Source.FINANCIAL_RESULTS,
        max((r.broadcast_at for r in feed), default=None),
    )
    session.flush()
    return rep


# -------------------------------------------------------------- announcements
def ingest_announcements_feed(
    session: Session,
    store: ObjectStore,
    nse: NseClient,
    companies: dict[str, Company],
    *,
    flags: IngestionFlags | None = None,
    registry: SourceRegistry | None = None,
    fetch_attachments: bool = False,
) -> LiveReport:
    """Ingest the index-wide announcements feed, keeping rows for companies we track."""
    flags = flags or IngestionFlags()
    if not flags.live_nse_announcements:
        raise FeatureDisabledError("SIGNALALPHA_LIVE_NSE_ANNOUNCEMENTS is off")
    registry = registry or load_sources()
    src = registry.nse_announcements
    rep = LiveReport("announcements")
    try:
        payload, _ = nse.get_json(src.url_template, src.warmup_url)
        rep.fetched += 1
    except FetchError as exc:
        record_failure(session, None, Source.NSE_ANNOUNCEMENTS, "fetch", str(exc))
        rep.failures.append(str(exc))
        return rep
    if not isinstance(payload, list):
        record_failure(session, None, Source.NSE_ANNOUNCEMENTS, "parse", "feed is not a list")
        rep.failures.append("feed is not a list")
        return rep
    writer = DocumentWriter(session, store, is_mock=False)
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        company = companies.get(symbol)
        if company is None:
            continue
        try:
            rec = nse_announcements.parse_announcements([item])[0]
        except (nse_announcements.ParseError, IndexError) as exc:
            rep.failures.append(f"{symbol}: {exc}")
            continue
        text = nse_announcements.render_announcement_text(rec)
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
            rep.skipped += 1
            continue
        session.add(
            Announcement(
                company_id=company.id,
                raw_document_id=doc.raw_document.id,
                parser_version=src.parser_version,
                public_at=rec.disseminated_at,
                category=rec.category,
                subject=rec.subject[:512],
                is_mock=False,
            )
        )
        rep.rows += 1
        record_success(session, company.id, Source.NSE_ANNOUNCEMENTS, rec.disseminated_at)
    session.flush()
    return rep
