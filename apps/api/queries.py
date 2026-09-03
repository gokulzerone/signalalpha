"""Row builders shared by the company, discovery and thesis endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select

from apps.api.schemas import AgentOutputOut, CompanyRow, ScoreBrief
from database.models import AgentRun, Company, DataQuality, RunStatus, Signal, UniverseSnapshot
from database.pit import PointInTimeSession
from scoring.ratios import ratios_for

SCORE_TYPES = ("opportunity", "inflection", "quality", "valuation", "risk", "attention_gap")
NEGATIVE_OWNERSHIP = {
    "promoter_stake_decrease",
    "pledge_increase",
    "pledge_invocation",
    "shareholder_count_spike",
}


def score_map(
    pit: PointInTimeSession,
) -> tuple[dict[int, dict[str, float | None]], datetime | None]:
    out: dict[int, dict[str, float | None]] = {}
    as_of: datetime | None = None
    for score_type in SCORE_TYPES:
        for s in pit.universe_scores(score_type):
            out.setdefault(s.company_id, {})[score_type] = (
                None if s.value is None else float(s.value)
            )
            as_of = datetime.combine(s.as_of, datetime.min.time(), tzinfo=pit.as_of.tzinfo)
    return out, as_of


def brief(scores: dict[str, float | None], as_of: datetime | None) -> ScoreBrief:
    return ScoreBrief(
        opportunity=scores.get("opportunity"),
        inflection=scores.get("inflection"),
        quality=scores.get("quality"),
        valuation=scores.get("valuation"),
        risk=scores.get("risk"),
        attention_gap=scores.get("attention_gap"),
        scores_as_of=as_of,
    )


def failures_map(pit: PointInTimeSession) -> dict[int, int]:
    rows = pit.session.execute(
        select(
            DataQuality.company_id,
            func.sum(DataQuality.fetch_failure_count + DataQuality.parse_failure_count),
        )
        .where(DataQuality.is_mock == pit.is_mock)
        .group_by(DataQuality.company_id)
    ).all()
    return {cid: int(total or 0) for cid, total in rows if cid is not None}


def latest_agent_output(
    pit: PointInTimeSession, company_id: int, agent_name: str
) -> AgentRun | None:
    stmt = (
        select(AgentRun)
        .where(
            AgentRun.company_id == company_id,
            AgentRun.agent_name == agent_name,
            AgentRun.as_of <= pit.as_of_date,
            AgentRun.is_mock == pit.is_mock,
            AgentRun.status == RunStatus.COMPLETED,
            AgentRun.validated.is_(True),
        )
        .order_by(AgentRun.as_of.desc(), AgentRun.id.desc())
    )
    return pit.session.scalars(stmt).first()


def agent_output_out(run: AgentRun) -> AgentOutputOut:
    return AgentOutputOut(
        agent_run_id=run.id,
        agent_name=run.agent_name,
        as_of=datetime.combine(
            run.as_of, datetime.min.time(), tzinfo=__import__("zoneinfo").ZoneInfo("UTC")
        ),
        model_id=run.model_id,
        prompt_version=run.prompt_version,
        validated=run.validated,
        output=run.output,
    )


def signal_window(pit: PointInTimeSession, since_days: int) -> dict[int, list[Signal]]:
    cutoff = pit.as_of - timedelta(days=since_days)
    stmt = (
        select(Signal)
        .where(
            Signal.is_mock == pit.is_mock, Signal.public_at <= pit.as_of, Signal.public_at > cutoff
        )
        .order_by(Signal.public_at.desc())
    )
    out: dict[int, list[Signal]] = {}
    for s in pit.session.scalars(stmt).all():
        out.setdefault(s.company_id, []).append(s)
    return out


def strongest(signals: Sequence[Signal], direction: int) -> str | None:
    best = max(
        (s for s in signals if s.direction == direction),
        key=lambda s: float(s.magnitude),
        default=None,
    )
    return None if best is None else f"{best.signal_type} ({float(best.magnitude):.2f})"


def company_row(
    pit: PointInTimeSession,
    company: Company,
    snapshot: UniverseSnapshot | None,
    scores: dict[str, float | None],
    scores_as_of: datetime | None,
    recent: Sequence[Signal],
    failures: int,
) -> CompanyRow:
    thesis = latest_agent_output(pit, company.id, "thesis")
    out = thesis.output if thesis and thesis.output else {}
    return CompanyRow(
        id=company.id,
        name=company.name,
        ticker=company.ticker,
        sector=company.sector,
        industry=company.industry,
        market_cap_cr=None
        if snapshot is None or snapshot.market_cap_cr is None
        else float(snapshot.market_cap_cr),
        listing_status=snapshot.listing_status.value if snapshot else "unknown",
        is_illiquid=bool(snapshot.is_illiquid) if snapshot else True,
        in_universe=bool(snapshot.in_universe) if snapshot else False,
        gsm_stage=snapshot.gsm_stage if snapshot else None,
        asm_stage=snapshot.asm_stage if snapshot else None,
        scores=brief(scores, scores_as_of),
        key_change=out.get("key_change"),
        strongest_positive=out.get("strongest_positive") or strongest(recent, 1),
        strongest_negative=out.get("strongest_negative") or strongest(recent, -1),
        new_signal_types=sorted({s.signal_type for s in recent}),
        data_quality_failures=failures,
    )


__all__ = ["ratios_for"]
