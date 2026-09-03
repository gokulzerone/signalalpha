"""Signal detection runner (PRD §6, §11 reporting-lag realism).

For each instant ``T`` at which a company record became public (and at a fixed cadence for
price-derived signals), the runner materialises the state as of ``T`` and keeps only the
candidates whose ``public_at == T``. A signal therefore never depends on anything published
after its own timestamp, and the signal's ``public_at`` is the filing's, not the period end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import Company, DocumentText, Signal
from database.pit import PointInTimeSession
from evidence import SpanError, create_evidence_from_quote
from signals.config import SignalCatalogue, load_catalogue
from signals.context import DetectionContext, HistoryLoader
from signals.detectors.base import FAMILY_ORDER, Candidate, all_detectors

DETECTOR_VERSION = "detectors-v1"
VALIDATOR_VERSION = "validator-v1"


@dataclass
class DetectionResult:
    company_id: int
    created: list[Signal] = field(default_factory=list)
    candidates_seen: int = 0
    duplicates_skipped: int = 0
    evidence_failures: int = 0


def run_detectors(
    ctx: DetectionContext, catalogue: SignalCatalogue, families: tuple[str, ...] = FAMILY_ORDER
) -> list[Candidate]:
    """Run every registered detector in family order; fundamental families first so that
    market detectors can see this instant's fundamental signals via ``ctx.prior_signals``."""
    detectors = all_detectors()
    out: list[Candidate] = []
    for family in families:
        for signal_type, fn in detectors.items():
            if catalogue.spec(signal_type).family != family:
                continue
            for cand in fn(ctx, catalogue):
                out.append(cand)
                if family in ("financial", "business"):
                    ctx.prior_signals.append((cand.signal_type, cand.public_at))
    return out


def market_instants(loader: HistoryLoader, cadence_days: int) -> list[datetime]:
    """Price-derived signals are evaluated at the publication instant of every N-th bar."""
    step = max(1, round(cadence_days * 5 / 7))
    return [b.public_at for i, b in enumerate(loader.prices) if i % step == step - 1]


def detect_company_signals(
    session: Session,
    company: Company,
    *,
    as_of: datetime | date,
    is_mock: bool,
    catalogue: SignalCatalogue | None = None,
) -> DetectionResult:
    catalogue = catalogue or load_catalogue()
    pit = PointInTimeSession(session, as_of, is_mock=is_mock)
    loader = HistoryLoader(pit, company)
    result = DetectionResult(company_id=company.id)

    existing = pit.signals(company.id)
    seen_keys = {(s.signal_type, s.dedupe_key) for s in existing}
    prior: list[tuple[str, datetime]] = sorted((s.signal_type, s.public_at) for s in existing)

    instants = sorted(
        set(loader.event_times())
        | set(market_instants(loader, catalogue.market_signal_cadence_days))
    )
    for at in instants:
        ctx = loader.at(at, [p for p in prior if p[1] < at])
        for cand in run_detectors(ctx, catalogue):
            result.candidates_seen += 1
            if cand.public_at != at:
                continue
            key = (cand.signal_type, cand.dedupe_key)
            if key in seen_keys:
                result.duplicates_skipped += 1
                continue
            signal = _persist(session, pit, company, cand, catalogue, result)
            seen_keys.add(key)
            prior.append((signal.signal_type, signal.public_at))
            result.created.append(signal)
    session.flush()
    return result


def _persist(
    session: Session,
    pit: PointInTimeSession,
    company: Company,
    cand: Candidate,
    catalogue: SignalCatalogue,
    result: DetectionResult,
) -> Signal:
    evidence_ids: list[int] = []
    for req in cand.evidence:
        text: DocumentText | None = pit.document_text(req.raw_document_id)
        if text is None:
            result.evidence_failures += 1
            continue
        try:
            ev = create_evidence_from_quote(
                session,
                document_text=text,
                company_id=company.id,
                quote=req.quote,
                created_by="parser",
            )
        except SpanError:
            result.evidence_failures += 1
            continue
        evidence_ids.append(ev.id)
    signal = Signal(
        company_id=company.id,
        signal_type=cand.signal_type,
        family=catalogue.spec(cand.signal_type).family,
        direction=cand.direction,
        magnitude=Decimal(str(round(cand.magnitude, 4))),
        public_at=cand.public_at,
        dedupe_key=cand.dedupe_key,
        source_records=cand.source_records,
        evidence_ids=evidence_ids,
        parameters=cand.parameters,
        detector_version=DETECTOR_VERSION,
        validator_version=VALIDATOR_VERSION,
        config_version=catalogue.version,
        is_mock=pit.is_mock,
    )
    session.add(signal)
    session.flush()
    return signal


def detect_universe_signals(
    session: Session,
    *,
    as_of: datetime | date,
    is_mock: bool,
    catalogue: SignalCatalogue | None = None,
) -> dict[int, DetectionResult]:
    pit = PointInTimeSession(session, as_of, is_mock=is_mock)
    return {
        c.id: detect_company_signals(session, c, as_of=as_of, is_mock=is_mock, catalogue=catalogue)
        for c in pit.companies()
    }
