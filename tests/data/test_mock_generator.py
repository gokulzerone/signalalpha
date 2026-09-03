"""Mock universe tests (PRD §5.3, §17)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from data.mock.generator import GenerationReport, MockDataExistsError, generate_mock_universe
from data.mock.synth import Story, load_blueprints, synthesize_company
from data.storage import LocalObjectStore, MemoryObjectStore
from database.models import (
    AnnouncementCategory,
    AuditOpinion,
    Base,
    Company,
    Financial,
    ListingStatus,
    RawDocument,
    SurveillanceEvent,
)
from database.pit import PointInTimeSession

AS_OF = date(2026, 8, 31)


def nn(value: Decimal | None) -> Decimal:
    assert value is not None
    return value


def _company(session: Session, story: Story, nth: int = 0) -> Company:
    ticker = [b for b in load_blueprints() if b.story is story][nth].ticker
    return session.scalars(select(Company).where(Company.ticker == ticker)).one()


def test_report_and_isolation(mock_session: Session, mock_universe: GenerationReport) -> None:
    assert mock_universe.counts["companies"] == 40
    tickers = mock_session.scalars(select(Company.ticker)).all()
    assert len(tickers) == 40 and all(t.startswith("MOCK-") for t in tickers)
    for table in Base.metadata.sorted_tables:
        if "is_mock" in table.c:
            live = mock_session.scalar(
                select(func.count()).select_from(table).where(table.c.is_mock.is_(False))
            )
            assert live == 0, table.name
    assert mock_universe.counts["prices"] > 40_000
    assert mock_universe.counts["financials"] > 40 * 16


def test_generate_refuses_to_run_twice(mock_session: Session) -> None:
    with pytest.raises(MockDataExistsError):
        generate_mock_universe(mock_session, MemoryObjectStore())


def test_accounting_identities_hold_on_stored_rows(mock_session: Session) -> None:
    rows = mock_session.scalars(select(Financial)).all()
    assert rows
    for r in rows:
        assert r.pbt == nn(r.ebitda) - nn(r.depreciation) - nn(r.finance_cost) + nn(r.other_income)
        assert r.pat == nn(r.pbt) - nn(r.tax)
        assert r.total_expenses == nn(r.revenue) + nn(r.other_income) - nn(r.pbt)
        if r.period_months == 12:
            assert r.cfo is not None and r.receivables is not None


def test_annual_row_equals_sum_of_quarters(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    company = _company(mock_session, Story.CONTROL)
    quarters = pit.financials_preferring_consolidated(company.id, period_months=3)
    annuals = pit.financials_preferring_consolidated(company.id, period_months=12)
    assert len(quarters) == 16 and len(annuals) == 4
    for a in annuals:
        qs = [
            q for q in quarters if a.period_end - timedelta(days=360) < q.period_end <= a.period_end
        ]
        assert len(qs) == 4
        assert a.revenue == sum((nn(q.revenue) for q in qs), Decimal(0))
        assert a.pat == sum((nn(q.pat) for q in qs), Decimal(0))


def test_documents_contain_stored_figures_verbatim(
    mock_session: Session, mock_store: LocalObjectStore
) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    company = _company(mock_session, Story.MARGIN_TURNAROUND)
    for row in pit.financials(company.id, period_months=3)[:6]:
        text = pit.document_text(row.raw_document_id)
        assert text is not None
        assert f"{row.revenue:.2f}" in text.text and f"{row.ebitda:.2f}" in text.text
        doc = pit.raw_document(row.raw_document_id)
        assert doc is not None and doc.storage_key.startswith("raw/financial_results/")
        assert mock_store.get(doc.storage_key).decode() == text.text


def test_planted_order_book_surge(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    company = _company(mock_session, Story.ORDER_BOOK_SURGE)
    orders = pit.announcements(company.id, categories=[AnnouncementCategory.ORDER_WIN])
    assert len(orders) >= 3
    values = [Decimal(a.summary.split("=")[1]) for a in orders if a.summary]
    quarters = pit.financials_preferring_consolidated(company.id, period_months=3)
    ttm = sum((nn(q.revenue) for q in quarters[-8:-4]), Decimal(0))
    assert max(values) >= ttm * Decimal("0.2")
    assert nn(quarters[0].revenue) > nn(quarters[7].revenue) * Decimal("1.5")


def test_planted_pledge_unwind(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    company = _company(mock_session, Story.PLEDGE_UNWIND)
    holdings = pit.shareholdings(company.id)
    assert holdings[-1].promoter_pledged_pct == Decimal("65")
    assert holdings[0].promoter_pledged_pct == Decimal("0")
    assert len(pit.pledge_events(company.id)) == 3
    assert len(pit.insider_trades(company.id)) >= 2


def test_planted_margin_turnaround(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    company = _company(mock_session, Story.MARGIN_TURNAROUND)
    q = pit.financials_preferring_consolidated(company.id, period_months=3)
    latest = nn(q[0].ebitda) / nn(q[0].revenue)
    earlier = nn(q[8].ebitda) / nn(q[8].revenue)
    assert latest - earlier >= Decimal("0.06")
    assert any(r.action.value == "upgrade" for r in pit.credit_ratings(company.id))


def test_planted_forensic_red_flag(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    company = _company(mock_session, Story.FORENSIC_RED_FLAG)
    annual = pit.financials_preferring_consolidated(company.id, period_months=12)
    latest, two_years_ago = annual[0], annual[2]
    assert latest.receivables and two_years_ago.receivables
    rec_growth = nn(latest.receivables) / nn(two_years_ago.receivables)
    rev_growth = nn(latest.revenue) / nn(two_years_ago.revenue)
    assert rec_growth > rev_growth * Decimal("1.3")
    assert latest.audit_opinion in {AuditOpinion.QUALIFIED, AuditOpinion.EMPHASIS_OF_MATTER}
    assert nn(latest.short_term_borrowings) > nn(two_years_ago.short_term_borrowings)
    cats = {a.category for a in pit.announcements(company.id)}
    assert {AnnouncementCategory.RESIGNATION, AnnouncementCategory.AUDITOR_CHANGE} <= cats


def test_planted_deceptive_growth(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    company = _company(mock_session, Story.DECEPTIVE_GROWTH)
    annual = pit.financials_preferring_consolidated(company.id, period_months=12)
    assert annual[0].related_party_revenue is not None
    assert nn(annual[0].related_party_revenue) / nn(annual[0].revenue) >= Decimal("0.35")
    holdings = pit.shareholdings(company.id)
    assert holdings[0].retail_shareholders > holdings[6].retail_shareholders * 1.8
    assert len(pit.surveillance_events(company.id)) == 2
    fund_raises = pit.announcements(company.id, categories=[AnnouncementCategory.FUND_RAISE])
    assert len(fund_raises) == 2


def test_delisted_company_survives_in_history(mock_session: Session) -> None:
    company = _company(mock_session, Story.DELISTED)
    assert company.delisted_on == date(2024, 12, 13)
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    before = {s.company_id: s for s in pit.universe(date(2024, 6, 30))}[company.id]
    after = {s.company_id: s for s in pit.universe(date(2025, 3, 31))}[company.id]
    assert before.listing_status is ListingStatus.LISTED
    assert after.listing_status is ListingStatus.DELISTED and not after.in_universe
    prices = pit.prices(company.id, date(2024, 12, 1), date(2025, 1, 31))
    assert prices and prices[-1].trade_date <= company.delisted_on


def test_illiquid_company_is_flagged_not_removed(mock_session: Session) -> None:
    company = _company(mock_session, Story.ILLIQUID)
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    snap = {s.company_id: s for s in pit.universe()}[company.id]
    assert snap.is_illiquid and snap.listing_status is ListingStatus.LISTED


def test_universe_is_mostly_in_cap_band(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    snaps = pit.universe()
    assert len(snaps) == 40
    assert sum(1 for s in snaps if s.in_universe) >= 30
    assert len(pit.index_constituents("MOCK-SMALLCAP")) >= 30


def test_point_in_time_hides_future_filings(mock_session: Session) -> None:
    company = _company(mock_session, Story.CONTROL, 1)
    early = PointInTimeSession(mock_session, date(2023, 6, 30), is_mock=True)
    assert len(early.financials_preferring_consolidated(company.id, period_months=3)) == 4
    fy23 = early.financials_preferring_consolidated(company.id, period_months=12)
    assert len(fy23) == 1 and fy23[0].related_party_revenue is None  # annual report not yet public
    later = PointInTimeSession(mock_session, date(2023, 9, 30), is_mock=True)
    fy23_later = later.financials_preferring_consolidated(company.id, period_months=12)
    assert fy23_later[0].related_party_revenue is not None
    assert fy23_later[0].revenue == fy23[0].revenue


def test_planted_price_effects(mock_session: Session) -> None:
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)

    def window_return(company: Company, start: date, days: int) -> float:
        prices = pit.prices(company.id, start, start + timedelta(days=int(days * 1.6)))
        return float(prices[min(days, len(prices) - 1)].close / prices[0].close) - 1

    positives = [
        _company(mock_session, s, i)
        for s in (Story.ORDER_BOOK_SURGE, Story.MARGIN_TURNAROUND, Story.PLEDGE_UNWIND)
        for i in (0, 1)
    ]
    controls = [_company(mock_session, Story.CONTROL, i) for i in range(10)]
    start = date(2024, 8, 1)
    pos = [window_return(c, start, 200) for c in positives]
    ctl = [window_return(c, start, 200) for c in controls]
    assert sum(pos) / len(pos) > sum(ctl) / len(ctl) + 0.10
    forensic = _company(mock_session, Story.FORENSIC_RED_FLAG)
    assert window_return(forensic, date(2025, 7, 15), 200) < sum(ctl) / len(ctl) - 0.10


def test_synthesis_is_deterministic() -> None:
    bp = load_blueprints()[0]
    a, b = synthesize_company(bp, 7), synthesize_company(bp, 7)
    assert [q.revenue for q in a.quarters] == [q.revenue for q in b.quarters]
    assert [e.on for e in a.plan.events] == [e.on for e in b.plan.events]
    assert synthesize_company(bp, 8).quarters[0].revenue != a.quarters[0].revenue


def test_every_surveillance_event_has_document(mock_session: Session) -> None:
    for ev in mock_session.scalars(select(SurveillanceEvent)).all():
        doc = mock_session.get(RawDocument, ev.raw_document_id)
        assert doc is not None and doc.source.value == "surveillance_lists"
