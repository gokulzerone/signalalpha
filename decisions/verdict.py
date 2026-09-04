"""A plain-language reading of the scores (deterministic, no model involved).

The scores answer "how does this rank"; this answers "so what does that mean", in the words
a person would use. Every sentence is derived from a measured value, and an unmeasured factor
is said to be unmeasured rather than quietly dropped: a reader must never be able to mistake
"nobody could check this" for "we checked and it was fine".

Nothing here is advice. It describes the research case and its gaps, and the vocabulary stays
on the evidence rather than on what anyone should do about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Factor -> (what it measures in plain words, is a high score good?)
FACTORS: dict[str, tuple[str, bool]] = {
    "inflection": ("How much the business is changing for the better, and how recently", True),
    "quality": ("Whether the returns and the accounting can be trusted", True),
    "valuation": ("How cheap it is against its peers and against its own history", True),
    "attention_gap": (
        "How little attention it gets, so a real change could still be unpriced",
        True,
    ),
    "risk": ("How much could go wrong: flags, pledges, thin trading, volatility", False),
}

#: Bands read from the top down; the first threshold a score clears wins.
BANDS: dict[str, list[tuple[float, str]]] = {
    "inflection": [
        (80, "Changing fast"),
        (60, "Clearly improving"),
        (35, "Some movement"),
        (0.001, "Barely moving"),
        (0, "Nothing is changing"),
    ],
    "quality": [
        (80, "Solid returns and clean accounts"),
        (60, "Reasonable"),
        (35, "Mixed"),
        (0, "Weak"),
    ],
    "valuation": [
        (80, "Much cheaper than its peers"),
        (60, "Cheaper than its peers"),
        (35, "Priced in line"),
        (0, "Expensive"),
    ],
    "attention_gap": [
        (80, "Almost nobody is watching"),
        (60, "Lightly followed"),
        (35, "Reasonably followed"),
        (0, "Widely followed"),
    ],
    "risk": [(70, "High"), (40, "Elevated"), (20, "Moderate"), (0, "Low")],
}
UNMEASURED = "Not measurable from the filings on file"


@dataclass(frozen=True)
class FactorLine:
    key: str
    label: str
    value: float | None
    verdict: str
    measures: str
    higher_is_better: bool
    measured: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "verdict": self.verdict,
            "measures": self.measures,
            "higher_is_better": self.higher_is_better,
            "measured": self.measured,
        }


@dataclass
class Verdict:
    headline: str
    """One line: how many of the checkable measures look strong."""
    summary: list[str]
    """A short paragraph in plain words, one sentence per element of the case."""
    caveats: list[str]
    factors: list[FactorLine] = field(default_factory=list)
    strong: int = 0
    checkable: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "summary": self.summary,
            "caveats": self.caveats,
            "factors": [f.to_json() for f in self.factors],
            "strong": self.strong,
            "checkable": self.checkable,
        }


def _band(key: str, value: float | None) -> str:
    if value is None:
        return UNMEASURED
    for threshold, text in BANDS[key]:
        if value >= threshold:
            return text
    return BANDS[key][-1][1]


#: Readiness gaps arrive as sentences; map each to the concern it raises so a concern is
#: only ever stated once.
GAP_TOPICS: list[tuple[str, str]] = [
    ("one-off", "base_rate"),
    ("daily traded value", "liquidity"),
    ("annual report", "forensic"),
    ("more quarters", "history"),
    ("wait for results", "freshness"),
    ("case against", "contradiction"),
    ("data page", "data_quality"),
    ("confirm the wording", "evidence"),
]


def _topic_of(gap: str) -> str:
    lowered = gap.lower()
    for needle, topic in GAP_TOPICS:
        if needle in lowered:
            return topic
    return "other"


def _label(key: str) -> str:
    return {
        "attention_gap": "Attention",
        "inflection": "Inflection",
        "quality": "Quality",
        "valuation": "Valuation",
        "risk": "Risk",
    }[key]


def build_verdict(
    scores: dict[str, float | None],
    *,
    change_sentence: str | None,
    readiness_gaps: list[str],
    liquidity_days_to_exit: float | None,
    base_rate_known: bool,
    negative_count: int,
    forensic_flags: list[str],
) -> Verdict:
    """Compose the plain reading. ``scores`` maps factor key to value, ``None`` when unmeasured."""
    factors = [
        FactorLine(
            key=key,
            label=_label(key),
            value=scores.get(key),
            verdict=_band(key, scores.get(key)),
            measures=measures,
            higher_is_better=higher,
            measured=scores.get(key) is not None,
        )
        for key, (measures, higher) in FACTORS.items()
    ]

    checkable = [f for f in factors if f.measured and f.key != "risk"]
    strong = [f for f in checkable if (f.value or 0) >= 60]
    unmeasured = [f.label.lower() for f in factors if not f.measured]

    if not checkable:
        headline = "Nothing here could be measured from the filings on file."
    elif len(strong) == len(checkable):
        headline = f"Strong on all {len(checkable)} measures that could be checked."
    elif strong:
        headline = (
            f"Strong on {len(strong)} of the {len(checkable)} measures that could be checked."
        )
    else:
        headline = f"Weak on all {len(checkable)} measures that could be checked."

    summary: list[str] = []
    if change_sentence:
        summary.append(change_sentence)
    infl = scores.get("inflection")
    if infl is not None and infl >= 60:
        summary.append(
            "That puts it among the companies whose fundamentals are moving most in this universe."
        )
    elif infl is not None and infl <= 5:
        summary.append("Against the rest of the universe, almost nothing is changing here.")
    val = scores.get("valuation")
    if val is not None and val >= 60:
        summary.append("It is priced below its peers and below its own recent history.")
    elif val is not None and val < 35:
        summary.append(
            "It is priced above its peers, so the improvement may already be in the price."
        )
    attn = scores.get("attention_gap")
    if attn is not None and attn >= 60:
        summary.append(
            "Few institutions hold it and little is traded, so a real change could still be unnoticed."
        )
    risk = scores.get("risk")
    if risk is not None and risk >= 40:
        summary.append(
            f"Risk reads {_band('risk', risk).lower()}, which is the main thing working against it."
        )
    elif risk is not None:
        summary.append(f"Risk reads {_band('risk', risk).lower()}.")

    # Caveats arrive from two places: what this reading noticed, and what the readiness
    # checklist already flagged. They overlap, so each is tagged with the concern it raises
    # and only the first of each concern is kept: repeating a caveat in two wordings reads
    # as two problems.
    tagged: list[tuple[str, str]] = []

    def add(topic: str, text: str) -> None:
        tagged.append((topic, text))

    if unmeasured:
        add(
            "unmeasured",
            f"{', '.join(unmeasured).capitalize()} could not be measured: the filings on file do not carry the data. "
            "A dash is an unmeasured factor, not a bad one, and this composite is not comparable with a complete one.",
        )
    if forensic_flags:
        add(
            "forensic",
            f"Accounting flags are active: {', '.join(f.replace('_', ' ') for f in forensic_flags)}.",
        )
    if negative_count:
        add(
            "negatives",
            f"{negative_count} signal(s) point the other way; the case against sets them out.",
        )
    if not base_rate_known:
        add(
            "base_rate",
            "There is no reliable record of how signals like this played out before, so treat it as a one-off.",
        )
    if liquidity_days_to_exit is not None and liquidity_days_to_exit >= 5:
        add(
            "liquidity",
            f"Getting out of a ten lakh position would take about {liquidity_days_to_exit:.0f} trading days.",
        )
    for gap in readiness_gaps:
        add(_topic_of(gap), gap)

    seen: set[str] = set()
    caveats: list[str] = []
    for topic, text in tagged:
        key = topic if topic != "other" else text.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        caveats.append(text)

    return Verdict(
        headline=headline,
        summary=summary,
        caveats=caveats,
        factors=factors,
        strong=len(strong),
        checkable=len(checkable),
    )
