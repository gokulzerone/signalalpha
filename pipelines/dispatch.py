"""Job dispatch: Celery when a broker is configured, otherwise an in-process worker thread
(development, tests, and the no-network CI stack of PRD §14)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from pipelines.research import execute_run
from pipelines.settings import PipelineSettings


class Dispatcher(Protocol):
    def enqueue_research(self, run_id: str, agents: list[str] | None = None) -> None: ...


class InlineDispatcher:
    """Runs each job in a daemon thread with its own session."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory
        self.threads: list[threading.Thread] = []

    def enqueue_research(self, run_id: str, agents: list[str] | None = None) -> None:
        def work() -> None:
            with self.factory() as session:
                execute_run(session, run_id, agents=agents)
                session.commit()

        t = threading.Thread(target=work, daemon=True, name=f"research-{run_id}")
        self.threads.append(t)
        t.start()

    def join(self, timeout: float = 60) -> None:
        for t in self.threads:
            t.join(timeout)


class CeleryDispatcher:
    def __init__(self) -> None:
        from pipelines.tasks import research_task

        self._task = research_task

    def enqueue_research(self, run_id: str, agents: list[str] | None = None) -> None:
        self._task.apply_async(kwargs={"run_id": run_id, "agents": agents}, queue="agents")


def build_dispatcher(
    factory: sessionmaker[Session], settings: PipelineSettings | None = None
) -> Dispatcher:
    settings = settings or PipelineSettings()
    if settings.broker_url:
        return CeleryDispatcher()
    return InlineDispatcher(factory)


DispatcherFactory = Callable[[sessionmaker[Session]], Dispatcher]
