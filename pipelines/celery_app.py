"""Celery application (PRD §13): queues ingest, parse, signals, agents, scores, backtest."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
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
# PRD §5.1 cadences: announcements every 15 minutes in market hours, hourly otherwise;
# prices once after the daily bhavcopy is published. Tasks no-op unless their flag is on.
celery_app.conf.beat_schedule = {
    "announcements-market-hours": {
        "task": "ingest.nse_announcements",
        "schedule": crontab(minute="*/15", hour="9-15", day_of_week="mon-fri"),
        "kwargs": {"days": 2},
    },
    "announcements-off-hours": {
        "task": "ingest.nse_announcements",
        "schedule": crontab(minute="5", hour="0-8,16-23"),
        "kwargs": {"days": 2},
    },
    "eod-prices": {
        "task": "ingest.eod_prices",
        "schedule": crontab(minute="30", hour="18", day_of_week="mon-fri"),
    },
}
celery_app.conf.timezone = "Asia/Kolkata"
