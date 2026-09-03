"""Point-in-time query layer (PRD §2.5, §11).

All reads of historical state go through :class:`PointInTimeSession`. It binds a session to
an ``as_of`` instant and a mock/live flag, and every method guarantees:

* no returned row has ``public_at > as_of``;
* mock and live rows are never mixed.

Set-valued "latest version per key" reads (financials, shareholdings, universe, prices) are
delegated to the SQL functions in ``database/sql/pit_functions_v1.sql`` so that every
consumer shares one implementation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, time
from typing import TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session

from database.models import (
    Announcement,
    AnnouncementCategory,
    BulkDeal,
    Company,
    CorporateAction,
    CreditRating,
    DocumentText,
    Evidence,
    Filing,
    FilingType,
    Financial,
    IndexConstituent,
    InsiderTrade,
    PledgeEvent,
    Price,
    ProvenanceMixin,
    PublicAtMixin,
    RawDocument,
    Shareholding,
    Signal,
    Source,
    SurveillanceEvent,
    UniverseSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


M = TypeVar("M", bound=PublicAtMixin)
C = TypeVar("C", bound=ProvenanceMixin)


class LookAheadError(ValueError):
    """Raised when a caller asks for state later than the session's ``as_of``."""


def end_of_day(d: date) -> datetime:
    """The instant at which everything published on Indian trading date ``d`` is public."""
    return datetime.combine(d, time(23, 59, 59, 999999), tzinfo=IST).astimezone(UTC)


def coerce_as_of(value: datetime | date) -> datetime:
    """Normalise an as-of value. Dates mean end of that day in IST; datetimes must be aware."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of datetimes must be timezone-aware")
        return value.astimezone(UTC)
    return end_of_day(value)


class PointInTimeSession:
    def __init__(self, session: Session, as_of: datetime | date, *, is_mock: bool) -> None:
        self.session = session
        self.as_of = coerce_as_of(as_of)
        self.is_mock = is_mock

    # ------------------------------------------------------------------ helpers
    @property
    def as_of_date(self) -> date:
        return self.as_of.astimezone(IST).date()

    def restrict(self, stmt: Select[tuple[M]], model: type[M]) -> Select[tuple[M]]:
        """Apply the point-in-time and mock-isolation predicates to a select."""
        return stmt.where(model.public_at <= self.as_of, model.is_mock == self.is_mock)

    def _events(
        self,
        model: type[C],
        company_id: int,
        since: datetime | date | None = None,
    ) -> Sequence[C]:
        stmt = self.restrict(select(model).where(model.company_id == company_id), model)
        if since is not None:
            since_dt = since if isinstance(since, datetime) else end_of_day(since)
            stmt = stmt.where(model.public_at > since_dt)
        stmt = stmt.order_by(model.public_at.desc())
        return self.session.scalars(stmt).all()

    def _check_date(self, on: date | None) -> date:
        if on is None:
            return self.as_of_date
        if on > self.as_of_date:
            raise LookAheadError(f"requested date {on} is after as_of {self.as_of_date}")
        return on

    # ---------------------------------------------------------------- companies
    def company(self, company_id: int) -> Company | None:
        return self.session.scalars(
            select(Company).where(Company.id == company_id, Company.is_mock == self.is_mock)
        ).first()

    def companies(self) -> Sequence[Company]:
        return self.session.scalars(
            select(Company).where(Company.is_mock == self.is_mock).order_by(Company.id)
        ).all()

    # ----------------------------------------------------------------- universe
    def universe(self, on: date | None = None) -> Sequence[UniverseSnapshot]:
        """The versioned universe on ``on`` (default: the as-of date)."""
        stmt = (
            select(UniverseSnapshot)
            .from_statement(text("SELECT * FROM sa_universe_as_of(:d, :mock)"))
            .params(d=self._check_date(on), mock=self.is_mock)
        )
        return self.session.scalars(stmt).all()

    # --------------------------------------------------------------- financials
    def financials(
        self,
        company_id: int,
        *,
        consolidated: bool | None = None,
        period_months: int | None = None,
        periods: int | None = None,
    ) -> list[Financial]:
        """Latest public version of each period, newest period first."""
        stmt = (
            select(Financial)
            .from_statement(text("SELECT * FROM sa_financials_as_of(:cid, :as_of, :cons, :mock)"))
            .params(cid=company_id, as_of=self.as_of, cons=consolidated, mock=self.is_mock)
        )
        rows = list(self.session.scalars(stmt).all())
        if period_months is not None:
            rows = [r for r in rows if r.period_months == period_months]
        rows.sort(key=lambda r: (r.period_end, r.consolidated), reverse=True)
        if periods is not None:
            rows = rows[:periods]
        return rows

    def financial_history(self, company_id: int) -> Sequence[Financial]:
        """Every non-superseded financial row public at as_of, across all filings.

        Unlike :meth:`financials` this does not resolve restatements; consumers that
        materialise earlier instants (the signal runner) resolve per instant with the same
        rule as ``sa_financials_as_of``.
        """
        stmt = self.restrict(
            select(Financial).where(
                Financial.company_id == company_id, Financial.is_superseded.is_(False)
            ),
            Financial,
        )
        return self.session.scalars(stmt.order_by(Financial.public_at, Financial.id)).all()

    def shareholding_history(self, company_id: int) -> Sequence[Shareholding]:
        stmt = self.restrict(
            select(Shareholding).where(
                Shareholding.company_id == company_id, Shareholding.is_superseded.is_(False)
            ),
            Shareholding,
        )
        return self.session.scalars(stmt.order_by(Shareholding.public_at, Shareholding.id)).all()

    def financials_preferring_consolidated(
        self, company_id: int, *, period_months: int = 3, periods: int | None = None
    ) -> list[Financial]:
        """One row per period: consolidated where available, else standalone (PRD §6.2)."""
        by_period: dict[date, Financial] = {}
        for row in self.financials(company_id, period_months=period_months):
            existing = by_period.get(row.period_end)
            if existing is None or (row.consolidated and not existing.consolidated):
                by_period[row.period_end] = row
        rows = sorted(by_period.values(), key=lambda r: r.period_end, reverse=True)
        return rows[:periods] if periods is not None else rows

    # -------------------------------------------------------------- shareholding
    def shareholdings(self, company_id: int, *, periods: int | None = None) -> list[Shareholding]:
        stmt = (
            select(Shareholding)
            .from_statement(text("SELECT * FROM sa_shareholdings_as_of(:cid, :as_of, :mock)"))
            .params(cid=company_id, as_of=self.as_of, mock=self.is_mock)
        )
        rows = sorted(self.session.scalars(stmt).all(), key=lambda r: r.period_end, reverse=True)
        return rows[:periods] if periods is not None else rows

    def pledge_events(self, company_id: int, since: date | None = None) -> Sequence[PledgeEvent]:
        return self._events(PledgeEvent, company_id, since)

    def insider_trades(self, company_id: int, since: date | None = None) -> Sequence[InsiderTrade]:
        return self._events(InsiderTrade, company_id, since)

    def bulk_deals(self, company_id: int, since: date | None = None) -> Sequence[BulkDeal]:
        return self._events(BulkDeal, company_id, since)

    # ------------------------------------------------------------------- events
    def announcements(
        self,
        company_id: int,
        since: date | None = None,
        categories: Iterable[AnnouncementCategory] | None = None,
    ) -> Sequence[Announcement]:
        rows = self._events(Announcement, company_id, since)
        if categories is not None:
            wanted = set(categories)
            rows = [r for r in rows if r.category in wanted]
        return rows

    def credit_ratings(self, company_id: int, since: date | None = None) -> Sequence[CreditRating]:
        return self._events(CreditRating, company_id, since)

    def corporate_actions(
        self, company_id: int, since: date | None = None
    ) -> Sequence[CorporateAction]:
        return self._events(CorporateAction, company_id, since)

    def surveillance_events(
        self, company_id: int, since: date | None = None
    ) -> Sequence[SurveillanceEvent]:
        return self._events(SurveillanceEvent, company_id, since)

    # ------------------------------------------------------------------- market
    def prices(self, company_id: int, start: date, end: date | None = None) -> list[Price]:
        end = self._check_date(end)
        stmt = (
            select(Price)
            .from_statement(
                text("SELECT * FROM sa_prices_as_of(:cid, :start, :end, :as_of, :mock)")
            )
            .params(cid=company_id, start=start, end=end, as_of=self.as_of, mock=self.is_mock)
        )
        return sorted(self.session.scalars(stmt).all(), key=lambda r: r.trade_date)

    def index_constituents(self, index_name: str, on: date | None = None) -> list[int]:
        """Company ids that were members of ``index_name`` on ``on``."""
        on = self._check_date(on)
        stmt = self.restrict(
            select(IndexConstituent).where(
                IndexConstituent.index_name == index_name,
                IndexConstituent.effective_from <= on,
                (IndexConstituent.effective_to.is_(None)) | (IndexConstituent.effective_to > on),
            ),
            IndexConstituent,
        )
        return sorted({row.company_id for row in self.session.scalars(stmt).all()})

    # ------------------------------------------------------------------ signals
    def signals(
        self,
        company_id: int,
        since: date | None = None,
        signal_types: Iterable[str] | None = None,
    ) -> Sequence[Signal]:
        stmt = self.restrict(select(Signal).where(Signal.company_id == company_id), Signal)
        if since is not None:
            stmt = stmt.where(Signal.public_at > end_of_day(since))
        if signal_types is not None:
            stmt = stmt.where(Signal.signal_type.in_(list(signal_types)))
        return self.session.scalars(stmt.order_by(Signal.public_at.desc(), Signal.id)).all()

    # ----------------------------------------------------------------- evidence
    def evidence_record(self, evidence_id: int) -> Evidence | None:
        stmt = self.restrict(select(Evidence).where(Evidence.id == evidence_id), Evidence)
        return self.session.scalars(stmt).first()

    def evidence(self, company_id: int, ids: Iterable[int] | None = None) -> Sequence[Evidence]:
        stmt = self.restrict(select(Evidence).where(Evidence.company_id == company_id), Evidence)
        if ids is not None:
            stmt = stmt.where(Evidence.id.in_(list(ids)))
        return self.session.scalars(stmt.order_by(Evidence.id)).all()

    # ---------------------------------------------------------------- documents
    def filings(self, company_id: int, filing_type: FilingType | None = None) -> Sequence[Filing]:
        stmt = self.restrict(select(Filing).where(Filing.company_id == company_id), Filing)
        if filing_type is not None:
            stmt = stmt.where(Filing.filing_type == filing_type)
        return self.session.scalars(stmt.order_by(Filing.public_at.desc())).all()

    def raw_documents(self, company_id: int, source: Source | None = None) -> Sequence[RawDocument]:
        stmt = self.restrict(
            select(RawDocument).where(RawDocument.company_id == company_id), RawDocument
        )
        if source is not None:
            stmt = stmt.where(RawDocument.source == source)
        return self.session.scalars(stmt.order_by(RawDocument.public_at.desc())).all()

    def raw_document(self, raw_document_id: int) -> RawDocument | None:
        stmt = self.restrict(
            select(RawDocument).where(RawDocument.id == raw_document_id), RawDocument
        )
        return self.session.scalars(stmt).first()

    def document_text(
        self, raw_document_id: int, parser_version: str | None = None
    ) -> DocumentText | None:
        """Extracted text of a document, only if the document itself is public at as_of."""
        stmt = (
            select(DocumentText)
            .join(RawDocument, DocumentText.raw_document_id == RawDocument.id)
            .where(
                DocumentText.raw_document_id == raw_document_id,
                RawDocument.public_at <= self.as_of,
                RawDocument.is_mock == self.is_mock,
            )
            .order_by(DocumentText.parser_version.desc())
        )
        if parser_version is not None:
            stmt = stmt.where(DocumentText.parser_version == parser_version)
        return self.session.scalars(stmt).first()
