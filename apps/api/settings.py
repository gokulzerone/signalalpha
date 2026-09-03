"""API settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNALALPHA_", extra="ignore")

    api_key: str | None = None
    """Single API key (PRD §10). When unset, authentication is disabled (development only)."""
    default_dataset: str = "mock"
    """``mock`` or ``live``. Mock and live data are never returned in one response."""


def get_api_settings() -> ApiSettings:
    return ApiSettings()
