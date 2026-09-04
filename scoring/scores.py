"""Score functions (PRD §9). Pure Python; every result carries its components, weights and
intermediate values. All scores are cross-sectional percentiles (0-100) within the universe
on the as-of date. Risk is "higher = worse"; the others are "higher = better"."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from database.pit import end_of_day
from scoring.config import ScoreConfig
from scoring.inputs import CompanyInputs, ScoreInputs, UniverseInputs

SCORE_TYPES = ("inflection", "quality", "valuation", "risk", "attention_gap")


@dataclass
class Component:
    raw: float | None
    percentile: float | None
    weight: float
    higher_is_better: bool
    contribution: float | None = None


@dataclass
class ScoreResult:
    score_type: str
    company_id: int
    as_of: date
    value: float | None
    components: dict[str, Component] = field(default_factory=dict)
    intermediates: dict[str, Any] = field(default_factory=dict)
    signal_ids: list[int] = field(default_factory=list)
    config_version: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "components": {
                name: {
                    "raw": c.raw,
                    "percentile": c.percentile,
                    "weight": c.weight,
                    "higher_is_better": c.higher_is_better,
                    "contribution": c.contribution,
                }
                for name, c in self.components.items()
            },
            "intermediates": self.intermediates,
        }


# --------------------------------------------------------------- percentiles
def percentile_ranks(
    values: Mapping[int, float | None], *, higher_is_better: bool = True
) -> dict[int, float | None]:
    """Percentile (0-100) of each value within the non-missing values.

    The percentile is the share of *other* companies that are strictly worse, so tied values
    share the lowest rank of their group: a metric that is zero for most of the universe gives
    those companies 0, not a mid-rank. A single value scores 50. Missing values stay missing.
    """
    present = sorted((v, cid) for cid, v in values.items() if v is not None and not math.isnan(v))
    out: dict[int, float | None] = {cid: None for cid in values}
    n = len(present)
    if n == 0:
        return out
    if n == 1:
        out[present[0][1]] = 50.0
        return out
    i = 0
    while i < n:
        j = i
        while j + 1 < n and present[j + 1][0] == present[i][0]:
            j += 1
        below = i  # count strictly lower
        above = n - 1 - j  # count strictly higher
        pct = 100.0 * (below if higher_is_better else above) / (n - 1)
        for k in range(i, j + 1):
            out[present[k][1]] = pct
        i = j + 1
    return out


class CrossSection:
    """Percentile ranks for a metric across the scored universe, computed once per metric."""

    def __init__(self, universe: UniverseInputs) -> None:
        self.universe = universe
        self.ids = universe.scored_ids()
        self._cache: dict[tuple[str, bool], dict[int, float | None]] = {}

    def ranks(
        self, name: str, metric: Callable[[CompanyInputs], float | None], *, higher_is_better: bool
    ) -> dict[int, float | None]:
        key = (name, higher_is_better)
        if key not in self._cache:
            values = {cid: metric(self.universe.companies[cid]) for cid in self.ids}
            self._cache[key] = percentile_ranks(values, higher_is_better=higher_is_better)
        return self._cache[key]


def _weighted(components: dict[str, Component]) -> float | None:
    """Weighted mean of available percentiles; weights renormalised over available ones."""
    available = [
        (c.percentile, c.weight)
        for c in components.values()
        if c.percentile is not None and c.weight > 0
    ]
    total = sum(w for _, w in available)
    if not available or total <= 0:
        return None
    value = sum(p * w for p, w in available) / total
    for c in components.values():
        c.contribution = None if c.percentile is None else c.percentile * c.weight / total
    return value


def _metric_components(
    xs: CrossSection,
    company_id: int,
    specs: dict[str, tuple[Callable[[CompanyInputs], float | None], bool]],
    weights: Mapping[str, float],
) -> dict[str, Component]:
    out: dict[str, Component] = {}
    for name, (metric, higher) in specs.items():
        ranks = xs.ranks(name, metric, higher_is_better=higher)
        out[name] = Component(
            raw=metric(xs.universe.companies[company_id]),
            percentile=ranks.get(company_id),
            weight=weights.get(name, 0.0),
            higher_is_better=higher,
        )
    return out


# ---------------------------------------------------------------- inflection
def _inflection_raw(
    c: CompanyInputs, config: ScoreConfig, as_of: datetime
) -> tuple[float, dict[str, float], list[int]]:
    w = config.windows
    cutoff = as_of - timedelta(days=w.inflection_days)
    by_family: dict[str, float] = {f: 0.0 for f in config.inflection.families}
    ids: list[int] = []
    for s in c.signals:
        if (
            s.family not in by_family
            or s.direction <= 0
            or s.public_at <= cutoff
            or s.public_at > as_of
        ):
            continue
        age = (as_of - s.public_at).total_seconds() / 86400
        by_family[s.family] += s.magnitude * 0.5 ** (age / w.inflection_half_life_days)
        ids.append(s.id)
    agreeing = sum(1 for v in by_family.values() if v > 0)
    bonus = 1 + config.inflection.consistency_bonus if agreeing >= 2 else 1.0
    return (
        sum(by_family.values()) * bonus,
        {**by_family, "families_agreeing": agreeing, "consistency_multiplier": bonus},
        ids,
    )


def inflection(
    inputs: ScoreInputs, config: ScoreConfig, as_of: date, xs: CrossSection | None = None
) -> ScoreResult:
    xs = xs or CrossSection(inputs.universe)
    at = _as_of_dt(inputs.universe, as_of)
    raw, parts, ids = _inflection_raw(inputs.company, config, at)
    ranks = xs.ranks(
        "inflection_raw", lambda c: _inflection_raw(c, config, at)[0], higher_is_better=True
    )
    result = ScoreResult(
        "inflection",
        inputs.company_id,
        as_of,
        ranks.get(inputs.company_id),
        config_version=config.version,
        signal_ids=ids,
    )
    result.components["recency_weighted_positive_magnitude"] = Component(
        raw=raw,
        percentile=ranks.get(inputs.company_id),
        weight=1.0,
        higher_is_better=True,
        contribution=ranks.get(inputs.company_id),
    )
    result.intermediates = {
        **parts,
        "window_days": config.windows.inflection_days,
        "half_life_days": config.windows.inflection_half_life_days,
    }
    if inputs.company_id not in xs.ids:
        result.value = None
    return result


# ------------------------------------------------------------------- quality
def _active_forensic(c: CompanyInputs, config: ScoreConfig, as_of: datetime) -> dict[str, float]:
    cutoff = as_of - timedelta(days=config.windows.forensic_flag_days)
    flags: dict[str, float] = {}
    for s in c.signals:
        if s.family == "forensic" and cutoff < s.public_at <= as_of:
            flags[s.signal_type] = max(flags.get(s.signal_type, 0.0), s.magnitude)
    return flags


def quality(
    inputs: ScoreInputs, config: ScoreConfig, as_of: date, xs: CrossSection | None = None
) -> ScoreResult:
    xs = xs or CrossSection(inputs.universe)
    at = _as_of_dt(inputs.universe, as_of)
    specs: dict[str, tuple[Callable[[CompanyInputs], float | None], bool]] = {
        "roce_3y": (lambda c: c.roce_3y, True),
        "cfo_to_ebitda_ttm": (lambda c: c.cfo_to_ebitda_ttm, True),
        "receivable_days_trend": (lambda c: c.receivable_days_trend, False),
        "promoter_pct": (lambda c: c.promoter_pct, True),
    }
    components = _metric_components(xs, inputs.company_id, specs, config.quality.weights)
    base = _weighted(components)
    flags = _active_forensic(inputs.company, config, at)
    multiplier = 1.0
    penalties: dict[str, float] = {}
    for flag in flags:
        p = config.quality.forensic_penalties.get(flag, 1.0)
        penalties[flag] = p
        multiplier *= p
    value = None if base is None else base * multiplier
    ids = [s.id for s in inputs.company.signals if s.signal_type in flags]
    result = ScoreResult(
        "quality",
        inputs.company_id,
        as_of,
        value,
        components,
        {
            "weighted_percentile": base,
            "forensic_flags": flags,
            "penalties": penalties,
            "penalty_multiplier": multiplier,
        },
        ids,
        config.version,
    )
    if inputs.company_id not in xs.ids:
        result.value = None
    return result


# ----------------------------------------------------------------- valuation
def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0 or num <= 0:
        return None
    return num / den


def valuation(
    inputs: ScoreInputs, config: ScoreConfig, as_of: date, xs: CrossSection | None = None
) -> ScoreResult:
    xs = xs or CrossSection(inputs.universe)
    specs: dict[str, tuple[Callable[[CompanyInputs], float | None], bool]] = {
        "ev_ebitda_vs_sector": (lambda c: _ratio(c.ev_ebitda, c.sector_ev_ebitda_median), False),
        "pe_vs_sector": (lambda c: _ratio(c.pe, c.sector_pe_median), False),
        "ev_ebitda_vs_own_history": (lambda c: _ratio(c.ev_ebitda, c.ev_ebitda_own_median), False),
        "pe_vs_own_history": (lambda c: _ratio(c.pe, c.pe_own_median), False),
        "peg_trailing": (lambda c: c.peg_trailing, False),
    }
    components = _metric_components(xs, inputs.company_id, specs, config.valuation.weights)
    value = _weighted(components)
    c = inputs.company
    result = ScoreResult(
        "valuation",
        inputs.company_id,
        as_of,
        value,
        components,
        {
            "ev_ebitda": c.ev_ebitda,
            "pe": c.pe,
            "sector_ev_ebitda_median": c.sector_ev_ebitda_median,
            "sector_pe_median": c.sector_pe_median,
            "ev_ebitda_own_3y_median": c.ev_ebitda_own_median,
            "pe_own_3y_median": c.pe_own_median,
        },
        [],
        config.version,
    )
    if inputs.company_id not in xs.ids:
        result.value = None
    return result


# ---------------------------------------------------------------------- risk
def _negative_ownership(c: CompanyInputs, config: ScoreConfig, as_of: datetime) -> float:
    cutoff = as_of - timedelta(days=config.windows.negative_ownership_days)
    return float(
        sum(
            1
            for s in c.signals
            if s.family == "ownership" and s.direction < 0 and cutoff < s.public_at <= as_of
        )
    )


def _key_person_exits(c: CompanyInputs, config: ScoreConfig, as_of: datetime) -> float:
    cutoff = as_of - timedelta(days=config.windows.key_person_exit_days)
    return float(
        sum(
            1
            for s in c.signals
            if s.signal_type in ("key_person_exit", "auditor_change")
            and cutoff < s.public_at <= as_of
        )
    )


def risk(
    inputs: ScoreInputs, config: ScoreConfig, as_of: date, xs: CrossSection | None = None
) -> ScoreResult:
    xs = xs or CrossSection(inputs.universe)
    at = _as_of_dt(inputs.universe, as_of)
    specs: dict[str, tuple[Callable[[CompanyInputs], float | None], bool]] = {
        "forensic_severity": (lambda c: sum(_active_forensic(c, config, at).values()), True),
        "pledge_pct": (lambda c: c.pledge_pct, True),
        "illiquidity": (
            lambda c: (
                None
                if c.median_traded_value is None or c.median_traded_value <= 0
                else -math.log(c.median_traded_value)
            ),
            True,
        ),
        "surveillance": (lambda c: float(c.surveillance_stage), True),
        "negative_ownership": (lambda c: _negative_ownership(c, config, at), True),
        "audit_qualification": (lambda c: c.audit_qualification, True),
        "key_person_exits": (lambda c: _key_person_exits(c, config, at), True),
        "volatility": (lambda c: c.volatility_90d, True),
    }
    components = _metric_components(xs, inputs.company_id, specs, config.risk.weights)
    value = _weighted(components)
    flags = _active_forensic(inputs.company, config, at)
    ids = [
        s.id
        for s in inputs.company.signals
        if s.signal_type in flags or (s.family == "ownership" and s.direction < 0)
    ]
    result = ScoreResult(
        "risk",
        inputs.company_id,
        as_of,
        value,
        components,
        {"forensic_flags": flags, "higher_is_worse": True},
        ids,
        config.version,
    )
    if inputs.company_id not in xs.ids:
        result.value = None
    return result


# ------------------------------------------------------------- attention gap
def _price_lag(c: CompanyInputs, config: ScoreConfig, as_of: datetime) -> float:
    cutoff = as_of - timedelta(days=config.windows.price_lag_days)
    return max(
        (
            s.magnitude
            for s in c.signals
            if s.signal_type == "price_lagging_fundamentals" and cutoff < s.public_at <= as_of
        ),
        default=0.0,
    )


def attention_gap(
    inputs: ScoreInputs, config: ScoreConfig, as_of: date, xs: CrossSection | None = None
) -> ScoreResult:
    xs = xs or CrossSection(inputs.universe)
    at = _as_of_dt(inputs.universe, as_of)
    specs: dict[str, tuple[Callable[[CompanyInputs], float | None], bool]] = {
        "institutional_absence": (lambda c: c.institutional_pct, False),
        "low_turnover": (lambda c: c.turnover, False),
        "days_since_reaction": (lambda c: c.days_since_reaction, True),
        "filing_complexity": (
            lambda c: _ratio(
                float(c.annual_report_chars) if c.annual_report_chars else None,
                c.sector_report_chars_median,
            ),
            True,
        ),
        "price_lag": (lambda c: _price_lag(c, config, at), True),
    }
    components = _metric_components(xs, inputs.company_id, specs, config.attention_gap.weights)
    value = _weighted(components)
    ids = [s.id for s in inputs.company.signals if s.signal_type == "price_lagging_fundamentals"]
    result = ScoreResult(
        "attention_gap", inputs.company_id, as_of, value, components, {}, ids, config.version
    )
    if inputs.company_id not in xs.ids:
        result.value = None
    return result


# --------------------------------------------------------------- opportunity
def risk_penalty(risk_value: float | None, config: ScoreConfig) -> float:
    rp = config.opportunity.risk_penalty
    if risk_value is None:
        return 0.0
    if risk_value <= rp.start:
        return 0.0
    if risk_value >= rp.full:
        return rp.max_penalty
    return rp.max_penalty * (risk_value - rp.start) / (rp.full - rp.start)


def opportunity(scores: Mapping[str, ScoreResult], config: ScoreConfig, as_of: date) -> ScoreResult:
    """Weighted geometric mean of Inflection, Quality, Valuation and Attention gap (as
    fractions of 100), times ``1 - risk_penalty(Risk)``.

    A component measured as zero makes the whole thing zero: that is the PRD's multiplicative
    form, and it is the point of it. A component that could not be *measured at all* is a
    different thing and is not treated as a zero, because reporting zero would assert that the
    company scored badly on something nobody looked at. The mean is taken over the components
    that exist, and the result is marked ``partial`` with the ones that are missing named, so a
    reader knows a partial score is not comparable with a complete one.
    """
    company_id = next(iter(scores.values())).company_id
    weights = config.opportunity.weights
    components: dict[str, Component] = {}
    measured: list[tuple[float, float]] = []
    missing: list[str] = []
    zeroed: list[str] = []
    for name, w in weights.items():
        v = scores[name].value if name in scores else None
        components[name] = Component(raw=v, percentile=v, weight=w, higher_is_better=True)
        # Branch on the fraction actually used, so a value that underflows to zero when
        # divided is treated as the zero it becomes rather than reaching log().
        fraction = 0.0 if v is None else v / 100
        if v is None:
            missing.append(name)
        elif fraction <= 0:
            zeroed.append(name)
        else:
            measured.append((fraction, w))

    value: float | None
    if zeroed:
        geometric = 0.0
    elif measured:
        total_w = sum(w for _, w in measured)
        geometric = math.exp(sum(w * math.log(f) for f, w in measured) / total_w)
    else:
        geometric = 0.0

    risk_value = scores["risk"].value if "risk" in scores else None
    penalty = risk_penalty(risk_value, config)
    components["risk"] = Component(
        raw=risk_value,
        percentile=risk_value,
        weight=0.0,
        higher_is_better=False,
        contribution=-penalty,
    )
    # Nothing measurable at all: a number here would be an invention.
    value = None if not measured and not zeroed else geometric * (1 - penalty) * 100
    ids = sorted({sid for s in scores.values() for sid in s.signal_ids})
    return ScoreResult(
        "opportunity",
        company_id,
        as_of,
        value,
        components,
        {
            "geometric_mean_fraction": geometric,
            "risk_penalty": penalty,
            "measured_components": sorted(n for n in weights if n not in missing),
            "missing_components": sorted(missing),
            "zero_components": sorted(zeroed),
            "partial": bool(missing),
            "form": "geometric(measured components) * (1 - risk_penalty)",
        },
        ids,
        config.version,
    )


def score_company(
    inputs: ScoreInputs, config: ScoreConfig, as_of: date, xs: CrossSection | None = None
) -> dict[str, ScoreResult]:
    xs = xs or CrossSection(inputs.universe)
    results = {
        "inflection": inflection(inputs, config, as_of, xs),
        "quality": quality(inputs, config, as_of, xs),
        "valuation": valuation(inputs, config, as_of, xs),
        "risk": risk(inputs, config, as_of, xs),
        "attention_gap": attention_gap(inputs, config, as_of, xs),
    }
    results["opportunity"] = opportunity(results, config, as_of)
    return results


def _as_of_dt(universe: UniverseInputs, as_of: date) -> datetime:
    return end_of_day(as_of)
