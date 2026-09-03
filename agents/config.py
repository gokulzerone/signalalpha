from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_PATH = Path(__file__).with_name("config.yaml")
PROMPT_DIR = Path(__file__).with_name("prompts")


class AgentConfig(BaseModel):
    version: str
    provider: str
    model_id: str
    max_tokens: int
    daily_budget_usd_per_company: float
    document_char_limit: int
    pricing_usd_per_million: dict[str, tuple[float, float]]
    numeric_tolerance: float


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNALALPHA_", extra="ignore")

    llm_provider: str | None = None
    llm_model_id: str | None = None
    llm_fixture_dir: Path | None = None


@lru_cache(maxsize=4)
def load_agent_config(path: Path | None = None) -> AgentConfig:
    with (path or CONFIG_PATH).open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return AgentConfig.model_validate(raw)
