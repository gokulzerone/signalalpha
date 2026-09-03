"""Writes the synthesized mock universe through the real ingestion path (PRD §5.3).

Every figure lands in the database via a raw document + document text + provenance-bearing
row, exactly as live data would, so the evidence pipeline is exercised end to end.
"""

from __future__ import annotations

import bisect
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from data.documents import DocumentWriter
from data.mock import templates as tpl
from data.mock.prices import DailyBar, synth_bars, synth_market_returns, trading_days
from data.mock.synth import (
    N_QUARTERS,
    PRICE_END,
    PRICE_START,
    CompanyHistory,
    EventKind,
    PeriodAggregate,
    QuarterFin,
    Story,
    annual_report_public_date,
    load_blueprints,
    q2,
    quarter_end,
    results_public_date,
    shareholding_public_date,
    synthesize_company,
)
from data.storage import ObjectStore
from database.models import (
    Announcement,
    AnnouncementCategory,
    AuditOpinion,
    Base,
    BulkDeal,
    Company,
    CorporateAction,
    CorporateActionType,
    CreditRating,
    DataQuality,
    DealType,
    DelistingKind,
    Exchange,
    ExtractionMethod,
    Filing,
    FilingType,
    Financial,
    HolderCategory,
    IndexConstituent,
    InsiderTrade,
    InstitutionalHolding,
    PersonCategory,
    PledgeEvent,
    PledgeEventType,
    Price,
    RatingAction,
    RawDocument,
    Shareholding,
    Source,
    SurveillanceEvent,
    SurveillanceEventType,
    SurveillanceFramework,
    TradeMode,
    TradeSide,
)
from database.universe import UniverseConfig, build_universe_snapshots, load_universe_config

IST = ZoneInfo("Asia/Kolkata")
PARSER_VERSION = "mock-1"
INDEX_NAME = "MOCK-SMALLCAP"
AGENCY = "Mock Ratings (fictional agency)"
DEFAULT_SEED = 20240903


class MockDataExistsError(RuntimeError):
    pass


@dataclass
class GenerationReport:
    seed: int
    counts: dict[str, int] = field(default_factory=dict)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=IST)


def delete_mock_data(session: Session) -> None:
    for table in reversed(Base.metadata.sorted_tables):
        if "is_mock" in table.c:
            session.execute(delete(table).where(table.c.is_mock.is_(True)))
    session.flush()


@dataclass
class _CompanyBars:
    bars: list[DailyBar]
    dates: list[date]

    def close_on_or_after(self, d: date) -> Decimal:
        i = bisect.bisect_left(self.dates, d)
        i = min(i, len(self.bars) - 1)
        return self.bars[i].close


class MockUniverseGenerator:
    def __init__(
        self,
        session: Session,
        store: ObjectStore,
        *,
        seed: int = DEFAULT_SEED,
        blueprint_path: Path | None = None,
        universe_config: UniverseConfig | None = None,
    ) -> None:
        self.session = session
        self.writer = DocumentWriter(session, store, is_mock=True)
        self.seed = seed
        self.blueprints = load_blueprints(blueprint_path)
        self.config = universe_config or load_universe_config()
        self.rng = random.Random(seed)
        self.nprng = np.random.default_rng(seed)
        self.report = GenerationReport(seed=seed)
        self.companies: dict[str, Company] = {}
        self.histories: dict[str, CompanyHistory] = {}
        self.bars: dict[str, _CompanyBars] = {}
        self.surveillance: dict[
            date, list[tuple[str, SurveillanceFramework, SurveillanceEventType, int | None]]
        ] = defaultdict(list)
        self.bulk: dict[date, list[tuple[str, str, TradeSide, int, Decimal]]] = defaultdict(list)

    def _count(self, key: str, n: int = 1) -> None:
        self.report.counts[key] = self.report.counts.get(key, 0) + n

    # ------------------------------------------------------------------ orchestration
    def run(self) -> GenerationReport:
        for i, bp in enumerate(self.blueprints):
            self.histories[bp.ticker] = synthesize_company(bp, self.seed)
            self.companies[bp.ticker] = self._create_company(i, bp)
        self.session.flush()
        self._synthesize_prices()
        for ticker, history in self.histories.items():
            self._write_filings(self.companies[ticker], history)
            self._write_events(self.companies[ticker], history)
        self._write_prices()
        self._write_market_files()
        self._write_universe()
        self._write_data_quality()
        self.session.flush()
        return self.report

    def _create_company(self, i: int, bp: object) -> Company:
        from data.mock.synth import Blueprint

        assert isinstance(bp, Blueprint)
        history = self.histories[bp.ticker]
        company = Company(
            name=bp.name,
            ticker=bp.ticker,
            isin=f"MOCK{i + 1:08d}",
            exchange=Exchange.BOTH if i % 2 == 0 else Exchange.NSE,
            bse_code=f"9{i + 1:05d}",
            sector=bp.sector,
            industry=bp.industry,
            listed_on=date(2010, 1, 1) + timedelta(days=self.rng.randint(0, 3000)),
            delisted_on=history.plan.delisted_on,
            delisting_kind=DelistingKind.COMPULSORY if history.plan.delisted_on else None,
            is_mock=True,
        )
        self.session.add(company)
        self._count("companies")
        return company

    # ------------------------------------------------------------------------ prices
    def _synthesize_prices(self) -> None:
        days = trading_days(PRICE_START, PRICE_END)
        market = synth_market_returns(self.nprng, len(days))
        for ticker, h in self.histories.items():
            bonus: tuple[date, int] | None = None
            for ev in h.plan.events:
                if ev.kind is EventKind.BONUS:
                    bonus = (ev.payload["ex_date"], int(ev.payload["ratio"]))
            shares = np.array(
                [float(h.plan.shares_cr[min(_quarter_index_for(d), N_QUARTERS - 1)]) for d in days]
            )
            if bonus is not None:
                shares = np.array(
                    [
                        s * (1 + bonus[1]) if d >= bonus[0] else s / 1
                        for s, d in zip(shares, days, strict=True)
                    ]
                )
                shares = np.array(
                    [
                        float(h.params.shares_cr) * ((1 + bonus[1]) if d >= bonus[0] else 1)
                        for d in days
                    ]
                )
            bars = synth_bars(
                self.nprng,
                days,
                price0=h.params.price0,
                shares_cr_by_day=shares,
                beta=h.params.beta,
                vol=h.params.vol,
                turnover=h.params.turnover,
                market=market,
                effects=h.plan.price_effects,
                stop_on=h.plan.delisted_on,
                bonus=bonus,
            )
            self.bars[ticker] = _CompanyBars(bars, [b.trade_date for b in bars])

    def _write_prices(self) -> None:
        by_day: dict[date, list[tuple[str, DailyBar]]] = defaultdict(list)
        for ticker, cb in self.bars.items():
            for b in cb.bars:
                by_day[b.trade_date].append((ticker, b))
        rows: list[dict[str, object]] = []
        for d in sorted(by_day):
            entries = by_day[d]
            doc = self.writer.write_text_document(
                company=None,
                source=Source.EOD_PRICES,
                text=tpl.bhavcopy_csv(d, entries),
                public_at=at(d, 18, 0),
                parser_version=PARSER_VERSION,
                title=f"Bhavcopy {d.isoformat()}",
                extraction_method=ExtractionMethod.STRUCTURED,
                ext="csv",
                content_type="text/csv",
            )
            for ticker, b in entries:
                rows.append(
                    {
                        "company_id": self.companies[ticker].id,
                        "raw_document_id": doc.raw_document.id,
                        "parser_version": PARSER_VERSION,
                        "public_at": at(d, 18, 0),
                        "trade_date": d,
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "volume": b.volume,
                        "traded_value": b.traded_value,
                        "delivery_pct": b.delivery_pct,
                        "is_mock": True,
                    }
                )
            self._count("raw_documents")
        for i in range(0, len(rows), 5000):
            self.session.execute(insert(Price), rows[i : i + 5000])
        self._count("prices", len(rows))

    # ----------------------------------------------------------------------- filings
    def _financial_row(
        self,
        company: Company,
        filing: Filing,
        *,
        period_end: date,
        months: int,
        consolidated: bool,
        pnl: QuarterFin | PeriodAggregate,
        balance: QuarterFin | None,
        cashflow: PeriodAggregate | None,
        shares: Decimal,
        related_party: Decimal | None = None,
        contingent: Decimal | None = None,
        opinion: AuditOpinion | None = None,
    ) -> Financial:
        row = Financial(
            company_id=company.id,
            filing_id=filing.id,
            raw_document_id=filing.raw_document_id,
            parser_version=PARSER_VERSION,
            public_at=filing.public_at,
            period_end=period_end,
            period_months=months,
            consolidated=consolidated,
            extraction_method=ExtractionMethod.TABLE,
            confidence=Decimal("0.95"),
            revenue=pnl.revenue,
            other_income=pnl.other_income,
            total_expenses=pnl.total_expenses,
            ebitda=pnl.ebitda,
            depreciation=pnl.depreciation,
            finance_cost=pnl.finance_cost,
            pbt=pnl.pbt,
            tax=pnl.tax,
            pat=pnl.pat,
            eps=pnl.eps,
            shares_outstanding=shares,
            related_party_revenue=related_party,
            contingent_liabilities=contingent,
            audit_opinion=opinion,
            is_mock=True,
        )
        if balance is not None:
            row.total_borrowings = balance.total_borrowings
            row.short_term_borrowings = balance.short_term_borrowings
            row.long_term_borrowings = balance.long_term_borrowings
            row.cash_and_equivalents = balance.cash
            row.receivables = balance.receivables
            row.inventory = balance.inventory
            row.payables = balance.payables
            row.net_worth = balance.net_worth
            row.total_assets = balance.total_assets
        if cashflow is not None:
            row.cfo = cashflow.cfo
            row.cfi = cashflow.cfi
            row.cff = cashflow.cff
            row.capex = cashflow.capex
        self.session.add(row)
        self._count("financials")
        return row

    def _bases(self, company: Company) -> list[bool]:
        """Reporting basis: some companies consolidated only, some standalone only, some both."""
        i = company.id % 5
        return [True, False] if i == 0 else [True] if i in (1, 2) else [False]

    def _write_filings(self, company: Company, h: CompanyHistory) -> None:
        bp = h.blueprint
        quarters = h.quarters
        for q in quarters:
            t = q.index
            pub_date = results_public_date(t)
            board_date = pub_date
            prev_year_q = quarters[t - 4] if t >= 4 else None
            half = h.half_year(t)
            prev_half = h.half_year(t - 4) if t >= 4 else None
            fy = h.fiscal_year(t)
            prev_fy = h.fiscal_year(t - 4) if t >= 4 else None
            # Board meeting intimation a week before the results.
            bm = self.writer.write_text_document(
                company=company,
                source=Source.NSE_ANNOUNCEMENTS,
                text=tpl.board_meeting(bp.name, board_date, q.period_end),
                public_at=at(pub_date - timedelta(days=7), 16, 30),
                parser_version=PARSER_VERSION,
                title="Board meeting intimation",
            )
            self._announce(
                company,
                bm.raw_document,
                AnnouncementCategory.BOARD_MEETING,
                f"Board meeting on {tpl.fdate(board_date)} to consider results",
            )
            for consolidated in self._bases(company):
                text = tpl.results_filing(
                    bp.name,
                    bp.ticker,
                    q,
                    prev_year_q,
                    half,
                    prev_half,
                    fy,
                    prev_fy,
                    board_date,
                    consolidated,
                )
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.FINANCIAL_RESULTS,
                    text=text,
                    public_at=at(pub_date, 17, 30),
                    parser_version=PARSER_VERSION,
                    title=f"Financial results for quarter ended {q.period_end.isoformat()}",
                )
                filing = Filing(
                    company_id=company.id,
                    raw_document_id=doc.raw_document.id,
                    filing_type=FilingType.ANNUAL_RESULTS if fy else FilingType.QUARTERLY_RESULTS,
                    period_end=q.period_end,
                    parser_version=PARSER_VERSION,
                    public_at=doc.raw_document.public_at,
                    is_mock=True,
                )
                self.session.add(filing)
                self.session.flush()
                self._count("filings")
                self._financial_row(
                    company,
                    filing,
                    period_end=q.period_end,
                    months=3,
                    consolidated=consolidated,
                    pnl=q,
                    balance=None,
                    cashflow=None,
                    shares=q.shares_cr,
                )
                if half is not None:
                    self._financial_row(
                        company,
                        filing,
                        period_end=q.period_end,
                        months=6,
                        consolidated=consolidated,
                        pnl=half,
                        balance=half.balance,
                        cashflow=half,
                        shares=q.shares_cr,
                    )
                if fy is not None:
                    self._financial_row(
                        company,
                        filing,
                        period_end=q.period_end,
                        months=12,
                        consolidated=consolidated,
                        pnl=fy,
                        balance=fy.balance,
                        cashflow=fy,
                        shares=q.shares_cr,
                    )
                if consolidated == self._bases(company)[0]:
                    self._announce(
                        company,
                        doc.raw_document,
                        AnnouncementCategory.RESULTS,
                        f"Financial results for the quarter ended {tpl.fdate(q.period_end)}",
                    )
            if fy is not None:
                self._write_annual_report(company, h, t, fy, prev_fy)
            self._write_shareholding(company, h, t)

    def _write_annual_report(
        self,
        company: Company,
        h: CompanyHistory,
        t: int,
        fy: PeriodAggregate,
        prev_fy: PeriodAggregate | None,
    ) -> None:
        bp = h.blueprint
        related = q2(float(fy.revenue) * h.plan.related_party_ratio[t])
        contingent = q2(float(fy.revenue) * h.plan.contingent_ratio[t])
        prev_contingent = (
            q2(float(prev_fy.revenue) * h.plan.contingent_ratio[t - 4]) if prev_fy else None
        )
        opinion = h.plan.audit_opinion[t]
        pub = annual_report_public_date(t)
        orders = [
            e
            for e in h.plan.events
            if e.kind is EventKind.ORDER_WIN
            and quarter_end(t - 3) - timedelta(days=92) < e.on <= quarter_end(t)
        ]
        order_total = sum((Decimal(e.payload["value_cr"]) for e in orders), Decimal(0))
        mdna = _mdna(bp.story, fy, prev_fy, order_total, h.plan.margin[t])
        auditor = "Mock & Associates, Chartered Accountants"
        if bp.story is Story.FORENSIC_RED_FLAG and t >= 13:
            auditor = "Fictional Auditors LLP"
        doc = self.writer.write_text_document(
            company=company,
            source=Source.ANNUAL_REPORT,
            text=tpl.annual_report(
                bp.name,
                bp.ticker,
                fy,
                prev_fy,
                related,
                contingent,
                prev_contingent,
                opinion,
                mdna,
                auditor,
            ),
            public_at=at(pub, 15, 0),
            parser_version=PARSER_VERSION,
            title=f"Annual report FY ending {fy.period_end.isoformat()}",
        )
        filing = Filing(
            company_id=company.id,
            raw_document_id=doc.raw_document.id,
            filing_type=FilingType.ANNUAL_REPORT,
            period_end=fy.period_end,
            parser_version=PARSER_VERSION,
            public_at=doc.raw_document.public_at,
            is_mock=True,
        )
        self.session.add(filing)
        self.session.flush()
        self._count("filings")
        for consolidated in self._bases(company):
            self._financial_row(
                company,
                filing,
                period_end=fy.period_end,
                months=12,
                consolidated=consolidated,
                pnl=fy,
                balance=fy.balance,
                cashflow=fy,
                shares=fy.balance.shares_cr,
                related_party=related,
                contingent=contingent,
                opinion=opinion,
            )

    def _write_shareholding(self, company: Company, h: CompanyHistory, t: int) -> None:
        bp = h.blueprint
        hold = h.holdings[t]
        pub = shareholding_public_date(t)
        doc = self.writer.write_text_document(
            company=company,
            source=Source.SHAREHOLDING_PATTERN,
            text=tpl.shareholding_pattern(bp.name, bp.ticker, hold),
            public_at=at(pub, 16, 0),
            parser_version=PARSER_VERSION,
            title=f"Shareholding pattern {hold.period_end.isoformat()}",
        )
        filing = Filing(
            company_id=company.id,
            raw_document_id=doc.raw_document.id,
            filing_type=FilingType.SHAREHOLDING_PATTERN,
            period_end=hold.period_end,
            parser_version=PARSER_VERSION,
            public_at=doc.raw_document.public_at,
            is_mock=True,
        )
        self.session.add(filing)
        self.session.flush()
        row = Shareholding(
            company_id=company.id,
            filing_id=filing.id,
            raw_document_id=doc.raw_document.id,
            parser_version=PARSER_VERSION,
            public_at=filing.public_at,
            period_end=hold.period_end,
            promoter_pct=hold.promoter_pct,
            promoter_pledged_pct=hold.pledged_pct,
            fii_pct=hold.fii_pct,
            dii_pct=hold.dii_pct,
            public_pct=hold.public_pct,
            total_shareholders=hold.total_shareholders,
            retail_shareholders=hold.retail_shareholders,
            extraction_method=ExtractionMethod.TABLE,
            confidence=Decimal("0.95"),
            is_mock=True,
        )
        for name, category, pct in hold.holders:
            row.institutional_holders.append(
                InstitutionalHolding(holder_name=name, category=HolderCategory(category), pct=pct)
            )
        self.session.add(row)
        self._count("filings")
        self._count("shareholdings")

    # ------------------------------------------------------------------------ events
    def _announce(
        self,
        company: Company,
        doc: RawDocument,
        category: AnnouncementCategory,
        subject: str,
        summary: str | None = None,
    ) -> Announcement:
        row = Announcement(
            company_id=company.id,
            raw_document_id=doc.id,
            parser_version=PARSER_VERSION,
            public_at=doc.public_at,
            category=category,
            subject=subject,
            summary=summary,
            is_mock=True,
        )
        self.session.add(row)
        self._count("announcements")
        return row

    def _write_events(self, company: Company, h: CompanyHistory) -> None:
        bp = h.blueprint
        name = bp.name
        promoter = f"{name.split(' ')[0]} Family Holdings (Mock promoter)"
        for ev in h.plan.events:
            on = ev.on
            public_at = at(on, self.rng.randint(10, 17), self.rng.choice([0, 15, 30, 45]))
            price = self.bars[bp.ticker].close_on_or_after(on)
            shares_total = int(float(h.plan.shares_cr[min(ev.quarter, N_QUARTERS - 1)]) * 1e7)
            if ev.kind is EventKind.ORDER_WIN:
                value = Decimal(ev.payload["value_cr"])
                customer = self.rng.choice(
                    [
                        "a public sector undertaking",
                        "a leading domestic OEM",
                        "a state government agency",
                        "an overseas customer",
                    ]
                )
                item = self.rng.choice(
                    [
                        "supply and installation of equipment",
                        "engineering, procurement and construction",
                        "supply of components",
                        "system integration services",
                    ]
                )
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.NSE_ANNOUNCEMENTS,
                    text=tpl.order_win(name, on, value, int(ev.payload["months"]), customer, item),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Receipt of order",
                )
                self._announce(
                    company,
                    doc.raw_document,
                    AnnouncementCategory.ORDER_WIN,
                    f"Receipt of order worth Rs. {tpl.money(value)} crore",
                    summary=f"value_cr={value}",
                )
            elif ev.kind is EventKind.CAPACITY_EXPANSION:
                capex = q2(float(h.quarters[ev.quarter].revenue) * 1.2)
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.NSE_ANNOUNCEMENTS,
                    text=tpl.capacity_expansion(name, on, int(ev.payload["capacity_pct"]), capex),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Capacity expansion",
                )
                self._announce(
                    company,
                    doc.raw_document,
                    AnnouncementCategory.CAPACITY_EXPANSION,
                    f"Capacity expansion by {ev.payload['capacity_pct']}%",
                    summary=f"capex_cr={capex}",
                )
            elif ev.kind in (EventKind.PLEDGE_RELEASE, EventKind.PLEDGE_CREATION):
                kind = "release" if ev.kind is EventKind.PLEDGE_RELEASE else "creation"
                pct_promoter = Decimal(str(ev.payload["pct_of_promoter"]))
                promoter_pct = h.holdings[min(ev.quarter, len(h.holdings) - 1)].promoter_pct
                pct_total = q2(pct_promoter * promoter_pct / 100)
                shares = int(shares_total * float(pct_total) / 100)
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.PLEDGE_DISCLOSURE,
                    text=tpl.pledge_event(
                        name, on, promoter, kind, pct_promoter, pct_total, shares
                    ),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Pledge disclosure",
                )
                self.session.add(
                    PledgeEvent(
                        company_id=company.id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=PARSER_VERSION,
                        public_at=public_at,
                        event_type=PledgeEventType.RELEASE
                        if kind == "release"
                        else PledgeEventType.CREATION,
                        holder_name=promoter,
                        shares=shares,
                        pct_of_promoter_holding=pct_promoter,
                        pct_of_total_shares=pct_total,
                        event_date=on,
                        is_mock=True,
                    )
                )
                self._announce(
                    company,
                    doc.raw_document,
                    AnnouncementCategory.PLEDGE,
                    f"Pledge {kind}: {tpl.money(pct_promoter)}% of promoter holding",
                )
                self._count("pledge_events")
            elif ev.kind in (EventKind.INSIDER_BUY, EventKind.INSIDER_SELL):
                side = TradeSide.BUY if ev.kind is EventKind.INSIDER_BUY else TradeSide.SELL
                value = Decimal(ev.payload["value_cr"])
                qty = int(float(value) * 1e7 / float(price))
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.INSIDER_TRADING,
                    text=tpl.insider_trade(name, on, promoter, side.value, qty, value, price),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Insider trading disclosure",
                )
                self.session.add(
                    InsiderTrade(
                        company_id=company.id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=PARSER_VERSION,
                        public_at=public_at,
                        person_name=promoter,
                        person_category=PersonCategory.PROMOTER,
                        side=side,
                        mode=TradeMode.MARKET,
                        quantity=qty,
                        value_inr=value * Decimal(10_000_000),
                        trade_date=on,
                        is_mock=True,
                    )
                )
                self._count("insider_trades")
            elif ev.kind in (
                EventKind.RATING_ASSIGNED,
                EventKind.RATING_UPGRADE,
                EventKind.RATING_DOWNGRADE,
            ):
                action = {
                    EventKind.RATING_ASSIGNED: RatingAction.ASSIGNED,
                    EventKind.RATING_UPGRADE: RatingAction.UPGRADE,
                    EventKind.RATING_DOWNGRADE: RatingAction.DOWNGRADE,
                }[ev.kind]
                verb = {
                    RatingAction.ASSIGNED: "assigned",
                    RatingAction.UPGRADE: "upgraded",
                    RatingAction.DOWNGRADE: "downgraded",
                }[action]
                reason = {
                    RatingAction.ASSIGNED: "established track record and moderate leverage.",
                    RatingAction.UPGRADE: "sustained improvement in operating margins and cash accruals, and reduction in debt.",
                    RatingAction.DOWNGRADE: "stretched receivables, rising short-term borrowings and weakening liquidity.",
                }[action]
                outlook = "negative" if action is RatingAction.DOWNGRADE else "stable"
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.CREDIT_RATING,
                    text=tpl.rating_rationale(
                        AGENCY, name, verb, str(ev.payload["rating"]), outlook, on, reason
                    ),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Rating rationale",
                )
                self.session.add(
                    CreditRating(
                        company_id=company.id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=PARSER_VERSION,
                        public_at=public_at,
                        agency=AGENCY,
                        instrument="Long-term bank facilities",
                        rating=str(ev.payload["rating"]),
                        outlook=outlook,
                        action=action,
                        rating_date=on,
                        is_mock=True,
                    )
                )
                self._announce(
                    company,
                    doc.raw_document,
                    AnnouncementCategory.CREDIT_RATING,
                    f"Credit rating {verb}: {ev.payload['rating']}",
                )
                self._count("credit_ratings")
            elif ev.kind is EventKind.CFO_RESIGNATION:
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.NSE_ANNOUNCEMENTS,
                    text=tpl.cfo_resignation(name, on, "Mr. Fictional Person, CFO"),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Resignation of CFO",
                )
                self._announce(
                    company,
                    doc.raw_document,
                    AnnouncementCategory.RESIGNATION,
                    "Resignation of Chief Financial Officer",
                    summary="role=cfo",
                )
            elif ev.kind is EventKind.AUDITOR_CHANGE:
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.NSE_ANNOUNCEMENTS,
                    text=tpl.auditor_change(
                        name, on, "Mock & Associates", "Fictional Auditors LLP"
                    ),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Resignation of statutory auditor",
                )
                self._announce(
                    company,
                    doc.raw_document,
                    AnnouncementCategory.AUDITOR_CHANGE,
                    "Resignation of statutory auditor before term",
                    summary="routine=false",
                )
            elif ev.kind is EventKind.FUND_RAISE:
                amount = Decimal(ev.payload["amount_cr"])
                issue_price = q2(float(price) * (1 - int(ev.payload["discount_pct"]) / 100))
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.NSE_ANNOUNCEMENTS,
                    text=tpl.fund_raise(
                        name, on, amount, int(ev.payload["discount_pct"]), issue_price
                    ),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Preferential issue of warrants",
                )
                self._announce(
                    company,
                    doc.raw_document,
                    AnnouncementCategory.FUND_RAISE,
                    f"Preferential warrants to promoters: Rs. {tpl.money(amount)} crore",
                    summary=f"amount_cr={amount};discount_pct={ev.payload['discount_pct']};to_promoters=true",
                )
            elif ev.kind in (EventKind.ASM_ENTRY, EventKind.ASM_EXIT, EventKind.GSM_ENTRY):
                fw = (
                    SurveillanceFramework.GSM
                    if ev.kind is EventKind.GSM_ENTRY
                    else SurveillanceFramework.ASM
                )
                event = (
                    SurveillanceEventType.EXIT
                    if ev.kind is EventKind.ASM_EXIT
                    else SurveillanceEventType.ENTRY
                )
                self.surveillance[on].append((bp.ticker, fw, event, ev.payload.get("stage")))
            elif ev.kind is EventKind.BONUS:
                ex_date = ev.payload["ex_date"]
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.CORPORATE_ACTIONS,
                    text=tpl.bonus(name, on, int(ev.payload["ratio"]), ex_date),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Bonus issue",
                )
                self.session.add(
                    CorporateAction(
                        company_id=company.id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=PARSER_VERSION,
                        public_at=public_at,
                        action_type=CorporateActionType.BONUS,
                        ratio_numerator=int(ev.payload["ratio"]),
                        ratio_denominator=1,
                        announced_at=public_at,
                        ex_date=ex_date,
                        details="Bonus 1:1",
                        is_mock=True,
                    )
                )
                self._announce(
                    company,
                    doc.raw_document,
                    AnnouncementCategory.CORPORATE_ACTION,
                    "Bonus issue 1:1",
                )
                self._count("corporate_actions")
            elif ev.kind is EventKind.DIVIDEND:
                ex_date = on + timedelta(days=20)
                per_share = Decimal(ev.payload["per_share"])
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.CORPORATE_ACTIONS,
                    text=tpl.dividend(name, on, per_share, ex_date),
                    public_at=public_at,
                    parser_version=PARSER_VERSION,
                    title="Dividend",
                )
                self.session.add(
                    CorporateAction(
                        company_id=company.id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=PARSER_VERSION,
                        public_at=public_at,
                        action_type=CorporateActionType.DIVIDEND,
                        amount_per_share=per_share,
                        announced_at=public_at,
                        ex_date=ex_date,
                        is_mock=True,
                    )
                )
                self._count("corporate_actions")
            elif ev.kind is EventKind.BULK_DEAL:
                qty = int(shares_total * float(ev.payload["pct"]) / 100)
                self.bulk[on].append(
                    (
                        bp.ticker,
                        "Kalinga Mutual Fund (Mock) Small Cap Scheme",
                        TradeSide.BUY,
                        qty,
                        price,
                    )
                )
            elif ev.kind is EventKind.DELISTING:
                doc = self.writer.write_text_document(
                    company=company,
                    source=Source.NSE_ANNOUNCEMENTS,
                    text=tpl.delisting_notice(name, on),
                    public_at=at(on, 9, 0),
                    parser_version=PARSER_VERSION,
                    title="Compulsory delisting",
                )
                self._announce(
                    company, doc.raw_document, AnnouncementCategory.OTHER, "Compulsory delisting"
                )

    # ------------------------------------------------------------------- market files
    def _write_market_files(self) -> None:
        for on, rows in sorted(self.surveillance.items()):
            doc = self.writer.write_text_document(
                company=None,
                source=Source.SURVEILLANCE_LISTS,
                text=tpl.surveillance_csv(
                    on, [(t, fw.value, ev.value, st) for t, fw, ev, st in rows]
                ),
                public_at=at(on, 17, 0),
                parser_version=PARSER_VERSION,
                title=f"Surveillance list {on.isoformat()}",
                extraction_method=ExtractionMethod.STRUCTURED,
                ext="csv",
                content_type="text/csv",
            )
            for ticker, fw, ev, stage in rows:
                self.session.add(
                    SurveillanceEvent(
                        company_id=self.companies[ticker].id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=PARSER_VERSION,
                        public_at=doc.raw_document.public_at,
                        framework=fw,
                        event=ev,
                        stage=stage,
                        effective_date=on + timedelta(days=1),
                        is_mock=True,
                    )
                )
                self._count("surveillance_events")
        for on, deals in sorted(self.bulk.items()):
            doc = self.writer.write_text_document(
                company=None,
                source=Source.BULK_BLOCK_DEALS,
                text=tpl.bulk_deal_csv(on, [(t, c, s.value, q, p) for t, c, s, q, p in deals]),
                public_at=at(on, 19, 0),
                parser_version=PARSER_VERSION,
                title=f"Bulk deals {on.isoformat()}",
                extraction_method=ExtractionMethod.STRUCTURED,
                ext="csv",
                content_type="text/csv",
            )
            for ticker, client, side, qty, price in deals:
                self.session.add(
                    BulkDeal(
                        company_id=self.companies[ticker].id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=PARSER_VERSION,
                        public_at=doc.raw_document.public_at,
                        deal_type=DealType.BULK,
                        trade_date=on,
                        client_name=client,
                        side=side,
                        quantity=qty,
                        price=price,
                        value_inr=q2(price * qty),
                        is_mock=True,
                    )
                )
                self._count("bulk_deals")
        # Index constituents: monthly, from the prior month-end market cap.
        month_starts = []
        d = date(2022, 5, 1)
        while d <= PRICE_END:
            month_starts.append(d)
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        lo, hi = float(self.config.market_cap_min_cr), float(self.config.market_cap_max_cr)
        for i, start in enumerate(month_starts):
            members: list[str] = []
            for ticker, cb in self.bars.items():
                h = self.histories[ticker]
                if h.plan.delisted_on is not None and h.plan.delisted_on < start:
                    continue
                idx = bisect.bisect_left(cb.dates, start) - 1
                if idx < 0:
                    continue
                shares = float(h.plan.shares_cr[min(_quarter_index_for(start), N_QUARTERS - 1)])
                mcap = float(cb.bars[idx].close) * shares
                if lo <= mcap <= hi:
                    members.append(ticker)
            end = month_starts[i + 1] if i + 1 < len(month_starts) else None
            doc = self.writer.write_text_document(
                company=None,
                source=Source.INDEX_CONSTITUENTS,
                text=tpl.index_csv(INDEX_NAME, start, members),
                public_at=at(start - timedelta(days=1), 18, 30),
                parser_version=PARSER_VERSION,
                title=f"{INDEX_NAME} constituents {start.isoformat()}",
                extraction_method=ExtractionMethod.STRUCTURED,
                ext="csv",
                content_type="text/csv",
            )
            for ticker in members:
                self.session.add(
                    IndexConstituent(
                        index_name=INDEX_NAME,
                        company_id=self.companies[ticker].id,
                        raw_document_id=doc.raw_document.id,
                        parser_version=PARSER_VERSION,
                        public_at=doc.raw_document.public_at,
                        effective_from=start,
                        effective_to=end,
                        is_mock=True,
                    )
                )
                self._count("index_constituents")
        self.session.flush()

    def _write_universe(self) -> None:
        dates: list[date] = []
        d = date(2022, 6, 30)
        while d <= PRICE_END:
            dates.append(d)
            nxt = (d + timedelta(days=1)).replace(day=28) + timedelta(days=4)
            d = nxt.replace(day=1) - timedelta(days=1)
        for h in self.histories.values():
            if h.plan.delisted_on is not None:
                dates.append(h.plan.delisted_on)
        n = build_universe_snapshots(
            self.session, is_mock=True, snapshot_dates=sorted(set(dates)), config=self.config
        )
        self._count("universe_snapshots", n)

    def _write_data_quality(self) -> None:
        now = at(PRICE_END, 18, 0)
        for company in self.companies.values():
            latest = self.session.scalar(
                select(func.max(RawDocument.public_at)).where(RawDocument.company_id == company.id)
            )
            for source in (
                Source.NSE_ANNOUNCEMENTS,
                Source.FINANCIAL_RESULTS,
                Source.SHAREHOLDING_PATTERN,
                Source.ANNUAL_REPORT,
                Source.EOD_PRICES,
            ):
                self.session.add(
                    DataQuality(
                        company_id=company.id,
                        source=source,
                        last_fetch_at=now,
                        last_success_at=now,
                        latest_public_at=latest,
                        fetch_failure_count=0,
                        parse_failure_count=0,
                        is_mock=True,
                    )
                )
                self._count("data_quality")
        self.session.flush()


def _quarter_index_for(d: date) -> int:
    for i in range(N_QUARTERS):
        if d <= quarter_end(i):
            return i
    return N_QUARTERS - 1


def _mdna(
    story: Story,
    fy: PeriodAggregate,
    prev_fy: PeriodAggregate | None,
    order_total: Decimal,
    margin: float,
) -> list[str]:
    paras = [
        f"Revenue from operations for the year was Rs. {tpl.money(fy.revenue)} crore"
        + (
            f" against Rs. {tpl.money(prev_fy.revenue)} crore in the previous year."
            if prev_fy
            else "."
        )
    ]
    paras.append(
        f"EBITDA for the year was Rs. {tpl.money(fy.ebitda)} crore and profit after tax was Rs. {tpl.money(fy.pat)} crore."
    )
    if story is Story.ORDER_BOOK_SURGE and order_total > 0:
        paras.append(
            f"Orders received during the year aggregated to Rs. {tpl.money(order_total)} crore, the highest in the Company's history, providing revenue visibility for the next 18 to 24 months."
        )
    if story is Story.MARGIN_TURNAROUND:
        paras.append(
            "Operating margins improved on account of a richer product mix, backward integration of key intermediates and the pass-through of raw material costs."
        )
    if story is Story.PLEDGE_UNWIND:
        paras.append(
            "The promoters have released the pledge on their shareholding following repayment of promoter-level borrowings."
        )
    if story is Story.FORENSIC_RED_FLAG:
        paras.append(
            "Trade receivables have increased on account of delayed certification by government customers. The management is confident of recovery."
        )
    if story is Story.DECEPTIVE_GROWTH:
        paras.append(
            "Strong growth was driven by new engagements with group companies and affiliated entities, which the management expects to scale further."
        )
    if story is Story.CONTROL:
        paras.append(
            "The business environment remained stable during the year and the Company continued to invest in maintenance capital expenditure."
        )
    return paras


def generate_mock_universe(
    session: Session,
    store: ObjectStore,
    *,
    seed: int = DEFAULT_SEED,
    replace: bool = False,
    blueprint_path: Path | None = None,
) -> GenerationReport:
    existing = session.scalar(select(func.count(Company.id)).where(Company.is_mock.is_(True))) or 0
    if existing:
        if not replace:
            raise MockDataExistsError(f"{existing} mock companies already exist; pass replace=True")
        delete_mock_data(session)
    return MockUniverseGenerator(session, store, seed=seed, blueprint_path=blueprint_path).run()
