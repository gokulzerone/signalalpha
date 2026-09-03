from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.mock.synth import Story, load_blueprints
from database.models import Company, RunStatus
from pipelines.research import create_run, execute_run


def test_execute_run_records_steps_and_failures(mock_session: Session, mock_signals: int) -> None:
    ticker = next(b.ticker for b in load_blueprints() if b.story is Story.CONTROL)
    company = mock_session.scalars(select(Company).where(Company.ticker == ticker)).one()
    run = create_run(mock_session, company, date(2026, 8, 31), is_mock=True)
    done = execute_run(mock_session, run.id)
    assert done.status is RunStatus.COMPLETED and done.finished_at is not None
    assert [s["status"] for s in done.steps] == ["skipped", "completed", "skipped", "completed"]

    bad = create_run(mock_session, company, date(1990, 1, 1), is_mock=True)
    bad.company_id = company.id
    import pipelines.research as research

    def boom(*_: object, **__: object) -> list[dict[str, object]]:
        raise RuntimeError("agent exploded")

    research.AGENT_STAGE = boom
    try:
        failed = execute_run(mock_session, bad.id)
    finally:
        research.AGENT_STAGE = None
    assert failed.status is RunStatus.FAILED and failed.error and "agent exploded" in failed.error
