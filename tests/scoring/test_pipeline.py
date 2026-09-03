"""Scores on the mock universe (PRD §17 definition of done)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.mock.synth import Story, load_blueprints
from database.models import Company
from database.pit import PointInTimeSession
from scoring.pipeline import run_scores

AS_OF = date(2025, 12, 31)


def _company(session: Session, story: Story, nth: int = 0) -> Company:
    ticker = [b for b in load_blueprints() if b.story is story][nth].ticker
    return session.scalars(select(Company).where(Company.ticker == ticker)).one()


def test_scores_on_mock_universe(mock_session: Session, mock_signals: int) -> None:
    assert mock_signals > 0
    run = run_scores(mock_session, as_of=AS_OF, is_mock=True)
    assert run.rows_written == 6 * len(run.results) and len(run.results) >= 30

    pit = PointInTimeSession(mock_session, AS_OF, is_mock=True)
    values: dict[str, dict[int, float | None]] = {}
    for score_type in (
        "inflection",
        "quality",
        "valuation",
        "risk",
        "attention_gap",
        "opportunity",
    ):
        values[score_type] = {
            s.company_id: (None if s.value is None else float(s.value))
            for s in pit.universe_scores(score_type)
        }
        for s in pit.universe_scores(score_type):
            assert s.components["components"], score_type  # every score exposes its components
            assert s.config_version == run.config_version

    def v(story: Story, score: str) -> float:
        """Score of the first company of ``story`` that is inside the scored universe
        (a story company may have grown out of the market-cap band)."""
        for nth in range(2):
            cid = _company(mock_session, story, nth).id
            if cid in values[score] and values[score][cid] is not None:
                val = values[score][cid]
                assert val is not None
                return val
        raise AssertionError(f"no scored company for {story}")

    opp = [x for x in values["opportunity"].values() if x is not None]
    median_opp = sorted(opp)[len(opp) // 2]
    risk_vals = [x for x in values["risk"].values() if x is not None]
    median_risk = sorted(risk_vals)[len(risk_vals) // 2]

    def top_quartile(story: Story, score: str) -> bool:
        vals = sorted(x for x in values[score].values() if x is not None)
        return v(story, score) >= vals[int(len(vals) * 0.75)]

    # Planted positive stories rank in the top quartile on Inflection.
    for story in (Story.ORDER_BOOK_SURGE, Story.MARGIN_TURNAROUND):
        assert top_quartile(story, "inflection"), story
    # The deceptive-growth story has high Risk and low Opportunity (PRD §17).
    assert v(Story.DECEPTIVE_GROWTH, "risk") > median_risk
    assert v(Story.DECEPTIVE_GROWTH, "opportunity") <= median_opp
    # The forensic story is penalised on Quality and high on Risk.
    assert top_quartile(Story.FORENSIC_RED_FLAG, "risk")
    assert v(Story.FORENSIC_RED_FLAG, "quality") < 50
    # Illiquid company is scored (visible) and has high illiquidity risk component.
    illiquid = _company(mock_session, Story.ILLIQUID)
    risk_row = next(s for s in pit.scores(illiquid.id) if s.score_type == "risk")
    assert risk_row.components["components"]["illiquidity"]["percentile"] >= 90
    # Delisted company is not scored.
    assert _company(mock_session, Story.DELISTED).id not in values["risk"]
    # Re-running replaces rows idempotently.
    again = run_scores(mock_session, as_of=AS_OF, is_mock=True)
    assert again.rows_written == run.rows_written
