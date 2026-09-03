"""Runner tests against the mock universe (PRD §6, §14)."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from data.mock.synth import Story, load_blueprints
from database.models import Company, Evidence, Signal
from database.pit import IST, PointInTimeSession
from signals.config import load_catalogue
from signals.context import HistoryLoader, prefer_consolidated, resolve_periods
from signals.detectors.base import all_detectors
from signals.runner import detect_company_signals
from signals.validators import ProposedSignal, validate_proposed_signal

AS_OF = date(2026, 8, 31)


def _company(session: Session, story: Story, nth: int = 0) -> Company:
    ticker = [b for b in load_blueprints() if b.story is story][nth].ticker
    return session.scalars(select(Company).where(Company.ticker == ticker)).one()


def test_catalogue_covers_every_detector_and_vice_versa() -> None:
    assert set(all_detectors()) == set(load_catalogue().signals)
    assert len(all_detectors()) == 30


def test_python_restatement_resolution_matches_sql(mock_session: Session) -> None:
    rng = random.Random(4)
    company = _company(mock_session, Story.CONTROL, 1)
    loader = HistoryLoader(PointInTimeSession(mock_session, AS_OF, is_mock=True), company)
    for _ in range(12):
        at = datetime(2022, 8, 1, tzinfo=IST) + timedelta(
            days=rng.randint(0, 1450), hours=rng.randint(0, 23)
        )
        sql = PointInTimeSession(mock_session, at, is_mock=True).financials_preferring_consolidated(
            company.id, period_months=12
        )
        py = prefer_consolidated(resolve_periods(loader.financial_rows, at), 12)
        assert [(p.period_end, p.filing_id, p.public_at) for p in reversed(py)] == [
            (r.period_end, r.filing_id, r.public_at) for r in sql
        ]


def _reset(session: Session, company: Company) -> None:
    """Remove any committed signals for the company so detection runs from scratch."""
    session.execute(delete(Signal).where(Signal.company_id == company.id))
    session.flush()


def _types(session: Session, company: Company) -> dict[str, list]:  # type: ignore[type-arg]
    out: dict[str, list] = {}  # type: ignore[type-arg]
    for s in PointInTimeSession(session, AS_OF, is_mock=True).signals(company.id):
        out.setdefault(s.signal_type, []).append(s)
    return out


def test_planted_stories_produce_expected_signals(mock_session: Session) -> None:
    order = _company(mock_session, Story.ORDER_BOOK_SURGE)
    _reset(mock_session, order)
    result = detect_company_signals(mock_session, order, as_of=AS_OF, is_mock=True)
    types = _types(mock_session, order)
    assert {"order_win", "capacity_expansion", "revenue_acceleration"} <= set(types), set(types)
    assert len(types["order_win"]) >= 3
    ev_ids = [e for s in types["order_win"] for e in s.evidence_ids]
    assert ev_ids
    ev = mock_session.get(Evidence, ev_ids[0])
    assert ev is not None and ev.created_by == "parser" and ev.extracted_text.startswith("Rs.")
    for s in result.created:
        assert s.public_at <= PointInTimeSession(mock_session, AS_OF, is_mock=True).as_of
    # Re-running is idempotent.
    again = detect_company_signals(mock_session, order, as_of=AS_OF, is_mock=True)
    assert again.created == [] and again.duplicates_skipped > 0

    margin = _company(mock_session, Story.MARGIN_TURNAROUND)
    _reset(mock_session, margin)
    detect_company_signals(mock_session, margin, as_of=AS_OF, is_mock=True)
    types = _types(mock_session, margin)
    assert {"margin_inflection", "operating_leverage", "credit_rating_upgrade"} <= set(types), set(
        types
    )
    assert all(s.direction == 1 for s in types["margin_inflection"])

    pledge = _company(mock_session, Story.PLEDGE_UNWIND)
    _reset(mock_session, pledge)
    detect_company_signals(mock_session, pledge, as_of=AS_OF, is_mock=True)
    types = _types(mock_session, pledge)
    assert {"pledge_reduction", "promoter_stake_increase"} <= set(types), set(types)

    forensic = _company(mock_session, Story.FORENSIC_RED_FLAG)
    _reset(mock_session, forensic)
    detect_company_signals(mock_session, forensic, as_of=AS_OF, is_mock=True)
    types = _types(mock_session, forensic)
    assert {
        "receivables_outrunning_revenue",
        "cash_vs_debt_anomaly",
        "audit_qualification",
        "contingent_liability_spike",
        "key_person_exit",
        "auditor_change",
        "credit_rating_downgrade",
    } <= set(types), set(types)

    deceptive = _company(mock_session, Story.DECEPTIVE_GROWTH)
    _reset(mock_session, deceptive)
    detect_company_signals(mock_session, deceptive, as_of=AS_OF, is_mock=True)
    types = _types(mock_session, deceptive)
    assert {
        "related_party_revenue",
        "shareholder_count_spike",
        "promoter_stake_decrease",
        "frequent_fund_raise",
        "surveillance_entry",
        "surveillance_exit",
    } <= set(types), set(types)

    control = _company(mock_session, Story.CONTROL, 2)
    _reset(mock_session, control)
    detect_company_signals(mock_session, control, as_of=AS_OF, is_mock=True)
    types = _types(mock_session, control)
    forensic_types = {
        t for t, spec in load_catalogue().signals.items() if spec.family == "forensic"
    }
    assert not (forensic_types & set(types)), forensic_types & set(types)


def test_signals_respect_point_in_time(mock_session: Session) -> None:
    company = _company(mock_session, Story.ORDER_BOOK_SURGE, 1)
    _reset(mock_session, company)
    early = date(2024, 3, 31)
    result = detect_company_signals(mock_session, company, as_of=early, is_mock=True)
    limit = PointInTimeSession(mock_session, early, is_mock=True).as_of
    assert all(s.public_at <= limit for s in result.created)
    assert not any(s.signal_type == "order_win" for s in result.created)  # orders start Apr 2024
    later = detect_company_signals(mock_session, company, as_of=AS_OF, is_mock=True)
    assert any(s.signal_type == "order_win" for s in later.created)


def test_validator_only_accepts_computed_signals(mock_session: Session) -> None:
    company = _company(mock_session, Story.ORDER_BOOK_SURGE)
    _reset(mock_session, company)
    detect_company_signals(mock_session, company, as_of=AS_OF, is_mock=True)
    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    real = pit.signals(company.id, signal_types=["order_win"])[0]
    ok = validate_proposed_signal(
        pit, company.id, ProposedSignal(signal_type="order_win", dedupe_key=real.dedupe_key)
    )
    assert ok.accepted and ok.signal_id == real.id
    by_time = validate_proposed_signal(
        pit,
        company.id,
        ProposedSignal(signal_type="order_win", public_at=real.public_at + timedelta(hours=3)),
    )
    assert by_time.accepted
    assert not validate_proposed_signal(
        pit, company.id, ProposedSignal(signal_type="order_win", dedupe_key="announcement:0")
    ).accepted
    assert not validate_proposed_signal(
        pit, company.id, ProposedSignal(signal_type="hidden_signal", dedupe_key="x")
    ).accepted
    assert not validate_proposed_signal(
        pit, company.id, ProposedSignal(signal_type="audit_qualification", public_at=real.public_at)
    ).accepted
