"""Celery application (PRD §13): queues ingest, parse, signals, agents, scores, backtest."""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from pipelines.settings import PipelineSettings

settings = PipelineSettings()
celery_app = Celery("signalalpha", broker=settings.broker_url, backend=settings.result_backend)
celery_app.conf.task_queues = tuple(
    Queue(name) for name in ("ingest", "parse", "signals", "agents", "scores", "backtest")
)
celery_app.conf.task_default_queue = "signals"
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.autodiscover_tasks(["pipelines"])
