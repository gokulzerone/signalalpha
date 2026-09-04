"""Reading the open web through Claude's server-side search tool.

Kept separate from :mod:`agents.llm`, which exists for filing-grounded agents with strict
schemas. This one is allowed outside, and in exchange it must return the pages it read.
"""

from __future__ import annotations

from typing import Any

from agents.config import AgentSettings, load_agent_config
from investigations.macro import (
    PROMPTS,
    SYSTEM,
    MacroReading,
    MacroResult,
    WebResearchUnavailableError,
    WebSource,
)

#: Server-side search, run by Anthropic rather than by us (claude-api: web search tool).
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}
MODEL = "claude-opus-5"


def web_research_available() -> bool:
    """True when a model is configured to read the web on our behalf."""
    settings = AgentSettings()
    provider = settings.llm_provider or load_agent_config().provider
    if provider != "anthropic":
        return False
    import os

    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _client() -> Any:
    import anthropic

    return anthropic.Anthropic()


def read_the_web(stage_key: str, context: str = "") -> MacroResult:
    """Run one macro stage: search, then restate the finding in a fixed shape.

    Two calls on purpose. The first is free to search and reason in prose; the second turns
    that prose into fields without touching the web, so a schema is never the thing standing
    between the model and a search result.
    """
    if not web_research_available():
        raise WebResearchUnavailableError(
            "Reading the open web needs a Claude API key. Set ANTHROPIC_API_KEY and "
            "SIGNALALPHA_LLM_PROVIDER=anthropic on the API and worker."
        )
    client = _client()
    prompt = PROMPTS[stage_key]
    if context:
        prompt = f"{prompt}\n\nWhat the earlier steps found:\n{context}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": prompt}],
    )
    text_parts: list[str] = []
    sources: list[WebSource] = []
    for block in response.content:
        kind = getattr(block, "type", "")
        if kind == "text":
            text_parts.append(block.text)
        elif kind == "web_search_tool_result":
            content = getattr(block, "content", None)
            # An error arrives as a single object rather than a list of results.
            if isinstance(content, list):
                for result in content:
                    url = getattr(result, "url", None)
                    if url:
                        sources.append(
                            WebSource(title=getattr(result, "title", "") or url, url=url)
                        )
    text = "\n\n".join(t.strip() for t in text_parts if t.strip())

    reading: MacroReading | None = None
    if text:
        try:
            parsed = client.messages.parse(
                model=MODEL,
                max_tokens=3000,
                system="Restate the analysis you are given. Add nothing that is not in it.",
                messages=[{"role": "user", "content": text}],
                output_format=MacroReading,
            )
            reading = parsed.parsed_output
        except Exception:
            reading = None

    seen: set[str] = set()
    unique = [s for s in sources if not (s.url in seen or seen.add(s.url))]
    return MacroResult(text=text, reading=reading, sources=unique)
