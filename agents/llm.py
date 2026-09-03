"""Provider-agnostic LLM layer (PRD §13): structured output, cost accounting, no framework.

Three clients share one interface:

* :class:`AnthropicClient` calls the Claude API with a Pydantic output schema.
* :class:`RecordedClient` replays fixtures keyed by the input hash (CI, PRD §14).
* :class:`TemplateClient` is a deterministic stand-in that writes schema-valid output from
  the structured snapshot with no model at all. It is clearly labelled ``template-v1`` and
  exists so the whole pipeline runs offline; it is not an LLM.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from agents.config import AgentConfig, AgentSettings, load_agent_config


@dataclass(frozen=True)
class LLMResponse:
    output: dict[str, Any]
    model_id: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


class LLMClient(Protocol):
    model_id: str

    def complete(
        self, *, system: str, user: str, output_model: type[BaseModel], max_tokens: int
    ) -> LLMResponse: ...


def cost_for(model_id: str, tokens_in: int, tokens_out: int, config: AgentConfig) -> Decimal:
    price_in, price_out = config.pricing_usd_per_million.get(model_id, (0.0, 0.0))
    return Decimal(str(round((tokens_in * price_in + tokens_out * price_out) / 1_000_000, 6)))


def input_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\n\n" + user).encode("utf-8")).hexdigest()


TemplateFn = Callable[[dict[str, Any]], dict[str, Any]]
TEMPLATES: dict[str, TemplateFn] = {}


def template(agent_name: str) -> Callable[[TemplateFn], TemplateFn]:
    def register(fn: TemplateFn) -> TemplateFn:
        TEMPLATES[agent_name] = fn
        return fn

    return register


class TemplateClient:
    model_id = "template-v1"

    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or load_agent_config()

    def complete(
        self, *, system: str, user: str, output_model: type[BaseModel], max_tokens: int
    ) -> LLMResponse:
        snapshot = json.loads(user)
        fn = TEMPLATES.get(snapshot["agent"])
        if fn is None:
            raise LookupError(f"no template for agent {snapshot['agent']!r}")
        output = fn(snapshot)
        tokens_in = len(user) // 4
        tokens_out = len(json.dumps(output)) // 4
        return LLMResponse(
            output,
            self.model_id,
            tokens_in,
            tokens_out,
            cost_for(self.model_id, tokens_in, tokens_out, self.config),
        )


class RecordedClient:
    """Replays ``<fixture_dir>/<agent>/<input_hash>.json``; records when ``inner`` is given."""

    model_id = "recorded"

    def __init__(self, fixture_dir: Path, inner: LLMClient | None = None) -> None:
        self.fixture_dir = fixture_dir
        self.inner = inner
        if inner is not None:
            self.model_id = inner.model_id

    def complete(
        self, *, system: str, user: str, output_model: type[BaseModel], max_tokens: int
    ) -> LLMResponse:
        agent = json.loads(user)["agent"]
        path = self.fixture_dir / agent / f"{input_hash(system, user)}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return LLMResponse(
                data["output"],
                data.get("model_id", "recorded"),
                data.get("tokens_in", 0),
                data.get("tokens_out", 0),
                Decimal("0"),
            )
        if self.inner is None:
            raise LookupError(f"no recorded fixture at {path}")
        response = self.inner.complete(
            system=system, user=user, output_model=output_model, max_tokens=max_tokens
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "output": response.output,
                    "model_id": response.model_id,
                    "tokens_in": response.tokens_in,
                    "tokens_out": response.tokens_out,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return response


class AnthropicClient:
    """Claude API via the official SDK with a Pydantic output schema (structured output)."""

    def __init__(self, model_id: str, config: AgentConfig | None = None) -> None:
        import anthropic

        self.model_id = model_id
        self.config = config or load_agent_config()
        self._client = anthropic.Anthropic()

    def complete(
        self, *, system: str, user: str, output_model: type[BaseModel], max_tokens: int
    ) -> LLMResponse:
        response = self._client.messages.parse(
            model=self.model_id,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=output_model,
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("model declined the request")
        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError("model returned no structured output")
        tokens_in = int(response.usage.input_tokens)
        tokens_out = int(response.usage.output_tokens)
        return LLMResponse(
            parsed.model_dump(mode="json"),
            self.model_id,
            tokens_in,
            tokens_out,
            cost_for(self.model_id, tokens_in, tokens_out, self.config),
        )


def get_client(
    config: AgentConfig | None = None, settings: AgentSettings | None = None
) -> LLMClient:
    config = config or load_agent_config()
    settings = settings or AgentSettings()
    provider = settings.llm_provider or config.provider
    model_id = settings.llm_model_id or config.model_id
    if provider == "anthropic":
        return AnthropicClient(model_id, config)
    if provider == "recorded":
        if settings.llm_fixture_dir is None:
            raise ValueError("SIGNALALPHA_LLM_FIXTURE_DIR is required for the recorded provider")
        return RecordedClient(settings.llm_fixture_dir)
    return TemplateClient(config)
