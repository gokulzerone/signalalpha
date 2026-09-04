"""The macro stages: read the open web, and carry the page every claim came from.

This is the one part of SignalAlpha that reads outside the exchange's filings, so it is kept
apart from them. Web material never becomes evidence in the PRD §8 sense, is never mixed into
the filing-derived record, and only ever narrows *which* companies to look at. What is then
said about a company still comes from its filings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

SYSTEM = """You are the macro desk of a research terminal covering Indian small and micro caps.
You read the open web and report what you found, with the page behind each claim.

Rules:
- Every factual claim must come from a page you actually retrieved. If you did not find it, say so.
- Be concrete: name commodities, rates, currencies, policies and dates rather than talking in
  generalities.
- You are narrowing where to look, not picking a stock. Do not name individual companies.
- Never use the words buy, sell, target price or recommendation.
- Indian small caps are the audience, so favour what reaches Indian manufacturers, exporters,
  lenders and consumers.
"""


class MacroFinding(BaseModel):
    """One condition, what it changes, and where it lands."""

    condition: str = Field(max_length=400)
    so_what: str = Field(max_length=400)
    sectors: list[str] = Field(default_factory=list, max_length=6)


class MacroReading(BaseModel):
    summary: str = Field(min_length=20, max_length=2000)
    findings: list[MacroFinding] = Field(default_factory=list, max_length=6)


@dataclass
class WebSource:
    title: str
    url: str

    def to_json(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url}


@dataclass
class MacroResult:
    text: str
    reading: MacroReading | None
    sources: list[WebSource] = field(default_factory=list)

    def sectors(self) -> list[str]:
        if self.reading is None:
            return []
        out: list[str] = []
        for f in self.reading.findings:
            for s in f.sectors:
                cleaned = s.strip()
                if cleaned and cleaned.lower() not in {x.lower() for x in out}:
                    out.append(cleaned)
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "reading": self.reading.model_dump() if self.reading else None,
            "sources": [s.to_json() for s in self.sources],
            "sectors": self.sectors(),
        }


class WebResearchUnavailableError(RuntimeError):
    """No model is configured, so the open web cannot be read."""


PROMPTS = {
    "world": (
        "Search the web for the state of the world economy right now. Cover growth, inflation and "
        "policy rates in the large economies, energy and industrial commodity prices, currencies "
        "against the rupee, and trade or tariff measures in force. Report what is actually "
        "happening today, with dates."
    ),
    "impact": (
        "Given the conditions you just described, work out what they change for businesses: input "
        "costs, financing costs, export demand, import competition and household spending. Search "
        "for confirming reporting where you can. Say which of these effects reach India most "
        "directly."
    ),
    "supply_demand": (
        "Now trace supply and demand. Search for where capacity is tight or slack, where inventories "
        "are building or drawing down, and where demand is being pulled forward or deferred. End "
        "with the industry sectors in India most exposed to what you found, named plainly "
        "(for example: chemicals, textiles, capital goods, auto components, pharmaceuticals)."
    ),
}
