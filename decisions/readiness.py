"""Is there enough here to decide? (and if not, exactly what is missing)

A score hides gaps; a checklist names them. Each check returns whether it passed and, when
it did not, the one thing that would fix it. Nothing here judges whether the company is
attractive: it judges whether the *research* is complete enough for a person to form a view.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

Status = Literal["ready", "partial", "not_ready"]


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    label: str
    passed: bool
    detail: str
    #: What the reader would have to obtain or wait for. Empty when the check passed.
    to_resolve: str = ""
    critical: bool = True


@dataclass
class Readiness:
    status: Status
    checks: list[ReadinessCheck] = field(default_factory=list)

    @property
    def blocking(self) -> list[ReadinessCheck]:
        return [c for c in self.checks if not c.passed and c.critical]

    @property
    def headline(self) -> str:
        if self.status == "ready":
            return "Everything needed for a view is here."
        blockers = self.blocking
        if not blockers:
            return "Usable, with gaps worth knowing about."
        if len(blockers) == 1:
            return f"Not ready: {blockers[0].to_resolve or blockers[0].detail}"
        return f"Not ready: {len(blockers)} things missing, starting with {blockers[0].to_resolve or blockers[0].detail}"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "headline": self.headline,
            "checks": [
                {
                    "key": c.key,
                    "label": c.label,
                    "passed": c.passed,
                    "detail": c.detail,
                    "to_resolve": c.to_resolve,
                    "critical": c.critical,
                }
                for c in self.checks
            ],
        }


@dataclass(frozen=True)
class ReadinessInputs:
    as_of: date
    latest_period_end: date | None
    latest_results_public_at: datetime | None
    quarter_count: int
    driving_signals: Sequence[tuple[str, int]]
    """(signal_type, evidence_count) for the signals carrying the case."""
    has_contradiction: bool
    forensic_flag_types: Sequence[str]
    is_illiquid: bool
    median_traded_value: float | None
    base_rates: dict[str, tuple[int, bool]]
    """signal_type -> (sample size, low_sample flag) from the backtest."""
    data_quality_failures: int


#: A quarterly filer is "current" within roughly two quarters; beyond that the picture is stale.
STALE_AFTER_DAYS = 200
MIN_QUARTERS = 5


def assess_readiness(inp: ReadinessInputs) -> Readiness:
    checks: list[ReadinessCheck] = []

    if inp.latest_period_end is None:
        checks.append(
            ReadinessCheck(
                "fundamentals",
                "Financials on file",
                False,
                "No results have been parsed for this company.",
                "Load a quarterly results filing.",
                True,
            )
        )
    else:
        age = (inp.as_of - inp.latest_period_end).days
        fresh = age <= STALE_AFTER_DAYS
        checks.append(
            ReadinessCheck(
                "fundamentals",
                "Financials current",
                fresh,
                f"Latest reported quarter ends {inp.latest_period_end.isoformat()}, {age} days before this view.",
                ""
                if fresh
                else f"Wait for results after {inp.latest_period_end.isoformat()}; the numbers here are {age} days old.",
                True,
            )
        )

    enough = inp.quarter_count >= MIN_QUARTERS
    checks.append(
        ReadinessCheck(
            "history",
            "Enough history to compare",
            enough,
            f"{inp.quarter_count} quarters on file; {MIN_QUARTERS} are needed for a year-on-year comparison.",
            ""
            if enough
            else f"Load {MIN_QUARTERS - inp.quarter_count} more quarters before trusting growth signals.",
            True,
        )
    )

    unevidenced = [t for t, n in inp.driving_signals if n == 0]
    text_signals = {"order_win", "capacity_expansion", "key_person_exit", "auditor_change"}
    unevidenced = [t for t in unevidenced if t in text_signals]
    checks.append(
        ReadinessCheck(
            "evidence",
            "Claims trace to filings",
            not unevidenced,
            "Every text-derived signal links to a passage in a filing."
            if not unevidenced
            else f"No stored passage for: {', '.join(sorted(set(unevidenced)))}.",
            "" if not unevidenced else "Open the announcement and confirm the wording yourself.",
            False,
        )
    )

    checks.append(
        ReadinessCheck(
            "contradiction",
            "Case against written",
            inp.has_contradiction,
            "A contradiction analysis has been produced for this company."
            if inp.has_contradiction
            else "No contradiction analysis has been run.",
            ""
            if inp.has_contradiction
            else "Run the research job so the case against is written before you decide.",
            True,
        )
    )

    liquid = not inp.is_illiquid
    traded = f"Rs {inp.median_traded_value:,.0f} a day" if inp.median_traded_value else "unknown"
    checks.append(
        ReadinessCheck(
            "liquidity",
            "Tradeable size",
            liquid,
            f"30-day median traded value is {traded}."
            + ("" if liquid else " That is below the configured floor."),
            ""
            if liquid
            else "Size any position against daily traded value; exiting may take many days.",
            False,
        )
    )

    known = [(t, inp.base_rates.get(t)) for t, _ in inp.driving_signals]
    solid = [t for t, br in known if br and not br[1]]
    thin = [t for t, br in known if br and br[1]]
    missing = [t for t, br in known if br is None]
    has_base = bool(solid)
    detail = (
        "No backtest statistics for the signals behind this case."
        if not (solid or thin)
        else (
            f"{len(solid)} signal type(s) have a backtest sample above the minimum"
            + (f"; {len(thin) + len(missing)} do not." if (thin or missing) else ".")
        )
    )
    checks.append(
        ReadinessCheck(
            "base_rate",
            "History of this signal type",
            has_base,
            detail,
            ""
            if has_base
            else "Treat this as a one-off: there is no reliable record of how signals like this played out.",
            False,
        )
    )

    flags = list(inp.forensic_flag_types)
    checks.append(
        ReadinessCheck(
            "accounting",
            "No unresolved accounting flags",
            not flags,
            "No forensic flags are active."
            if not flags
            else f"Active forensic flags: {', '.join(sorted(set(flags)))}.",
            ""
            if not flags
            else "Read the flagged notes in the annual report before going further.",
            False,
        )
    )

    if inp.data_quality_failures:
        checks.append(
            ReadinessCheck(
                "data_quality",
                "Sources complete",
                False,
                f"{inp.data_quality_failures} fetch or parse failures recorded for this company.",
                "Check the data page: part of this company's picture is missing.",
                False,
            )
        )

    critical_failed = [c for c in checks if not c.passed and c.critical]
    any_failed = [c for c in checks if not c.passed]
    status: Status = "ready" if not any_failed else ("not_ready" if critical_failed else "partial")
    return Readiness(status=status, checks=checks)


def next_review_default(as_of: date, latest_period_end: date | None) -> date:
    """A sensible default review date: shortly after the next quarterly filing is due."""
    if latest_period_end is None:
        return as_of + timedelta(days=45)
    return max(as_of + timedelta(days=14), latest_period_end + timedelta(days=135))
