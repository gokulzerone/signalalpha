"""The steps of an investigation, and the words shown while each one runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StageStatus = Literal["pending", "running", "done", "skipped", "failed"]


@dataclass(frozen=True)
class Stage:
    key: str
    #: Present tense, shown while the step is working.
    running: str
    #: What the step produced, shown once it is done.
    done: str
    #: Whether the step needs the open web (and therefore a configured model).
    needs_web: bool = False


STAGES: tuple[Stage, ...] = (
    Stage(
        "world", "Scanning the world for economic conditions", "World conditions", needs_web=True
    ),
    Stage(
        "impact", "Working out what those conditions change", "What that changes", needs_web=True
    ),
    Stage(
        "supply_demand",
        "Tracing the effect on supply and demand",
        "Supply and demand",
        needs_web=True,
    ),
    Stage("india", "Scanning India for companies in the path of it", "Where that lands in India"),
    Stage("company", "Finalising the company", "The company"),
    Stage("value", "Checking what the market is paying for it", "What the market pays"),
    Stage("fundamentals", "Reading its filings", "What the filings say"),
    Stage("threats", "Looking for what could go wrong", "What could go wrong"),
    Stage("case", "Writing up why it is worth the work", "The case"),
)

BY_KEY = {s.key: s for s in STAGES}
