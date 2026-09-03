"""Score pipeline: compute inputs for the universe at ``as_of``, score every company and store
the rows with their components (PRD §9)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.orm import Session

from database.models import Score
from database.pit import IST, coerce_as_of
from scoring.config import ScoreConfig, load_score_config
from scoring.inputs import ScoreInputs, UniverseInputs, compute_universe_inputs
from scoring.scores import CrossSection, ScoreResult, score_company


@dataclass
class ScoreRun:
    as_of: date
    config_version: str
    results: dict[int, dict[str, ScoreResult]] = field(default_factory=dict)
    rows_written: int = 0


def score_universe(
    universe: UniverseInputs, config: ScoreConfig
) -> dict[int, dict[str, ScoreResult]]:
    xs = CrossSection(universe)
    return {
        cid: score_company(ScoreInputs(cid, universe), config, universe.as_of, xs) for cid in xs.ids
    }


def run_scores(
    session: Session,
    *,
    as_of: datetime | date,
    is_mock: bool,
    config: ScoreConfig | None = None,
    replace: bool = True,
) -> ScoreRun:
    config = config or load_score_config()
    universe = compute_universe_inputs(session, as_of=as_of, is_mock=is_mock, config=config)
    results = score_universe(universe, config)
    run = ScoreRun(as_of=universe.as_of, config_version=config.version, results=results)
    on = coerce_as_of(as_of).astimezone(IST).date()
    if replace:
        session.execute(
            delete(Score).where(
                Score.as_of == on, Score.config_version == config.version, Score.is_mock == is_mock
            )
        )
    for cid, per_type in results.items():
        for score_type, res in per_type.items():
            session.add(
                Score(
                    company_id=cid,
                    as_of=on,
                    score_type=score_type,
                    value=None if res.value is None else Decimal(str(round(res.value, 3))),
                    components=res.to_json(),
                    config_version=config.version,
                    signal_ids=res.signal_ids,
                    is_mock=is_mock,
                )
            )
            run.rows_written += 1
    session.flush()
    return run
