"""Celery tasks. Idempotent by design: the research pipeline re-runs signals and scores
without creating duplicates, and agent runs are cached by their input hash."""

from __future__ import annotations

from database.engine import session_scope
from pipelines.celery_app import celery_app
from pipelines.research import execute_run


@celery_app.task(name="research.run", queue="agents")
def research_task(run_id: str, agents: list[str] | None = None) -> str:
    with session_scope() as session:
        run = execute_run(session, run_id, agents=agents)
        return run.status.value
