from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNALALPHA_", extra="ignore")

    broker_url: str | None = None
    """Redis URL for Celery. When unset, jobs run inline in a background thread."""
    result_backend: str | None = None
