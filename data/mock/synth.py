"""Synthesis of internally consistent company histories with planted stories (PRD §5.3).

Everything here is deterministic given a seed. Figures are ₹ crore, quantised to two decimals
so that accounting identities hold exactly on the stored Decimals:

    pbt = ebitda - depreciation - finance_cost + other_income
    pat = pbt - tax
    total_expenses = revenue + other_income - pbt
    cash_t = cash_{t-1} + cfo + cfi + cff
"""

from __future__ import annotations

import calendar
import enum
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

from database.models import AuditOpinion

BLUEPRINT_PATH = Path(__file__).with_name("universe.yaml")
N_QUARTERS = 16
FIRST_QUARTER_END = date(2022, 6, 30)
INFLECTION_Q = 9  # quarter index at which planted stories turn (period end 2024-09-30)
PRICE_START = date(2022, 4, 1)
PRICE_END = date(2026, 8, 31)
CENT = Decimal("0.01")


def q2(x: Decimal | float) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def quarter_end(i: int) -> date:
    months = 6 + 3 * i
    year = 2022 + (months - 1) // 12
    month = (months - 1) % 12 + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def quarter_start(i: int) -> date:
    return PRICE_START if i == 0 else quarter_end(i - 1) + timedelta(days=1)


def is_half_year_end(i: int) -> bool:
    return quarter_end(i).month in (9, 3)


def is_fiscal_year_end(i: int) -> bool:
    return quarter_end(i).month == 3


def results_public_date(i: int) -> date:
    return quarter_end(i) + timedelta(days=55 if is_fiscal_year_end(i) else 40)


def shareholding_public_date(i: int) -> date:
    return quarter_end(i) + timedelta(days=14)


def annual_report_public_date(i: int) -> date:
    return quarter_end(i) + timedelta(days=150)


class Story(enum.StrEnum):
    CONTROL = "control"
    ORDER_BOOK_SURGE = "order_book_surge"
    PLEDGE_UNWIND = "pledge_unwind"
    MARGIN_TURNAROUND = "margin_turnaround"
    FORENSIC_RED_FLAG = "forensic_red_flag"
    DECEPTIVE_GROWTH = "deceptive_growth"
    DELISTED = "delisted"
    ILLIQUID = "illiquid"


POSITIVE_STORIES = {Story.ORDER_BOOK_SURGE, Story.PLEDGE_UNWIND, Story.MARGIN_TURNAROUND}
NEGATIVE_STORIES = {Story.FORENSIC_RED_FLAG, Story.DECEPTIVE_GROWTH, Story.DELISTED}


@dataclass(frozen=True)
class Blueprint:
    ticker: str
    name: str
    sector: str
    industry: str
    story: Story
    bonus_issue: bool = False


def load_blueprints(path: Path | None = None) -> list[Blueprint]:
    with (path or BLUEPRINT_PATH).open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    out: list[Blueprint] = []
    for item in raw["companies"]:
        out.append(
            Blueprint(
                ticker=str(item["ticker"]),
                name=str(item["name"]),
                sector=str(item["sector"]),
                industry=str(item["industry"]),
                story=Story(item.get("story", "control")),
                bonus_issue=bool(item.get("bonus_issue", False)),
            )
        )
    return out


# --------------------------------------------------------------------------- parameters
@dataclass
class Params:
    base_revenue_q: float  # ₹ crore per quarter at t = 0
    growth: float  # annual revenue growth
    margin: float  # EBITDA / revenue
    dep_pct: float  # depreciation / revenue
    interest_rate: float
    tax_rate: float
    rec_days: float
    inv_days: float
    pay_days: float
    lt_debt: float
    st_debt: float
    cash: float
    net_worth: float
    shares_cr: float
    price0: float
    promoter_pct: float
    pledge_pct: float
    fii_pct: float
    dii_pct: float
    shareholders: int
    capex_to_dep: float
    related_party_ratio: float
    contingent_ratio: float
    beta: float
    vol: float
    turnover: float  # daily traded value / market cap
    rating: str


SECTOR_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "Capital Goods": {
        "rev": (25, 120),
        "margin": (0.10, 0.16),
        "growth": (0.08, 0.18),
        "rec": (70, 110),
        "inv": (60, 100),
    },
    "Chemicals": {
        "rev": (40, 160),
        "margin": (0.12, 0.20),
        "growth": (0.06, 0.16),
        "rec": (55, 85),
        "inv": (70, 110),
    },
    "Pharma": {
        "rev": (40, 150),
        "margin": (0.14, 0.22),
        "growth": (0.07, 0.15),
        "rec": (60, 95),
        "inv": (80, 130),
    },
    "IT Services": {
        "rev": (30, 110),
        "margin": (0.14, 0.22),
        "growth": (0.10, 0.20),
        "rec": (60, 90),
        "inv": (0, 5),
    },
    "Auto Ancillaries": {
        "rev": (50, 200),
        "margin": (0.09, 0.14),
        "growth": (0.06, 0.14),
        "rec": (50, 75),
        "inv": (45, 75),
    },
    "Textiles": {
        "rev": (60, 220),
        "margin": (0.07, 0.12),
        "growth": (0.03, 0.10),
        "rec": (45, 75),
        "inv": (60, 100),
    },
    "Infrastructure": {
        "rev": (60, 250),
        "margin": (0.08, 0.13),
        "growth": (0.05, 0.15),
        "rec": (90, 140),
        "inv": (30, 60),
    },
    "Consumer": {
        "rev": (40, 180),
        "margin": (0.08, 0.14),
        "growth": (0.08, 0.16),
        "rec": (20, 45),
        "inv": (40, 70),
    },
    "Defence": {
        "rev": (20, 100),
        "margin": (0.12, 0.20),
        "growth": (0.10, 0.22),
        "rec": (90, 150),
        "inv": (80, 130),
    },
    "Engineering": {
        "rev": (25, 110),
        "margin": (0.09, 0.15),
        "growth": (0.05, 0.14),
        "rec": (65, 100),
        "inv": (55, 90),
    },
}
RATINGS = ["BBB-", "BBB", "BBB+", "A-", "A"]


def draw_params(rng: random.Random, bp: Blueprint) -> Params:
    r = SECTOR_RANGES[bp.sector]
    rev = rng.uniform(*r["rev"])
    margin = rng.uniform(*r["margin"])
    price0 = rng.uniform(60, 900)
    target_mcap = rng.uniform(160, 2200)
    if bp.story in POSITIVE_STORIES | NEGATIVE_STORIES:
        # Story companies must stay inside the market-cap band through their planted moves.
        target_mcap = min(target_mcap, 700.0)
    annual_rev = rev * 4
    p = Params(
        base_revenue_q=rev,
        growth=rng.uniform(*r["growth"]),
        margin=margin,
        dep_pct=rng.uniform(0.02, 0.045),
        interest_rate=rng.uniform(0.085, 0.11),
        tax_rate=0.2517,
        rec_days=rng.uniform(*r["rec"]),
        inv_days=rng.uniform(*r["inv"]),
        pay_days=rng.uniform(35, 70),
        lt_debt=annual_rev * rng.uniform(0.05, 0.30),
        st_debt=annual_rev * rng.uniform(0.03, 0.15),
        cash=annual_rev * rng.uniform(0.03, 0.12),
        net_worth=annual_rev * rng.uniform(0.35, 0.80),
        shares_cr=target_mcap / price0,
        price0=price0,
        promoter_pct=rng.uniform(45, 72),
        pledge_pct=rng.choice([0.0, 0.0, 0.0, rng.uniform(5, 30)]),
        fii_pct=rng.choice([0.0, 0.0, rng.uniform(0.3, 4)]),
        dii_pct=rng.choice([0.0, rng.uniform(0.2, 5)]),
        shareholders=int(rng.uniform(8000, 60000)),
        capex_to_dep=rng.uniform(0.8, 1.4),
        related_party_ratio=rng.uniform(0.0, 0.04),
        contingent_ratio=rng.uniform(0.01, 0.06),
        beta=rng.uniform(0.8, 1.2),
        vol=rng.uniform(0.011, 0.018),
        turnover=rng.uniform(0.0006, 0.0035),
        rating=rng.choice(RATINGS),
    )
    if bp.story is Story.MARGIN_TURNAROUND:
        p.margin = 0.085
    if bp.story is Story.PLEDGE_UNWIND:
        p.pledge_pct = 65.0
        p.promoter_pct = rng.uniform(50, 62)
    if bp.story is Story.ILLIQUID:
        p.turnover = 0.00004
        p.shares_cr = 250 / price0
    if bp.story is Story.DECEPTIVE_GROWTH:
        p.related_party_ratio = 0.05
    if bp.story is Story.DELISTED:
        p.margin = 0.05
        p.lt_debt = annual_rev * 0.6
        p.st_debt = annual_rev * 0.3
    return p


# ------------------------------------------------------------------------------ events
class EventKind(enum.StrEnum):
    ORDER_WIN = "order_win"
    CAPACITY_EXPANSION = "capacity_expansion"
    PLEDGE_RELEASE = "pledge_release"
    PLEDGE_CREATION = "pledge_creation"
    INSIDER_BUY = "insider_buy"
    INSIDER_SELL = "insider_sell"
    RATING_ASSIGNED = "rating_assigned"
    RATING_UPGRADE = "rating_upgrade"
    RATING_DOWNGRADE = "rating_downgrade"
    CFO_RESIGNATION = "cfo_resignation"
    AUDITOR_CHANGE = "auditor_change"
    FUND_RAISE = "fund_raise"
    ASM_ENTRY = "asm_entry"
    ASM_EXIT = "asm_exit"
    GSM_ENTRY = "gsm_entry"
    BONUS = "bonus"
    DIVIDEND = "dividend"
    BULK_DEAL = "bulk_deal"
    DELISTING = "delisting"


@dataclass(frozen=True)
class PlannedEvent:
    kind: EventKind
    on: date
    quarter: int
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceEffect:
    start: date
    daily_drift: float
    trading_days: int


@dataclass
class StoryPlan:
    rev_mult: list[float]
    margin: list[float]
    rec_days: list[float]
    inv_days: list[float]
    lt_debt: list[float]
    st_debt: list[float]
    capex_to_dep: list[float]
    shares_cr: list[float]
    equity_infusion: list[float]
    pledge_pct: list[float]
    promoter_pct: list[float]
    retail_mult: list[float]
    related_party_ratio: list[float]
    contingent_ratio: list[float]
    audit_opinion: list[AuditOpinion]
    events: list[PlannedEvent]
    price_effects: list[PriceEffect]
    stop_after_quarter: int | None = None  # last quarter with filings (delisting)
    delisted_on: date | None = None


def _in_quarter(rng: random.Random, i: int, lo: int = 5, hi: int = 80) -> date:
    return quarter_start(i) + timedelta(days=rng.randint(lo, hi))


def baseline_revenue(p: Params, rng: random.Random) -> list[float]:
    season = [0.97, 1.0, 1.02, 1.04]
    out = []
    for t in range(N_QUARTERS):
        trend = p.base_revenue_q * (1 + p.growth) ** (t / 4)
        out.append(trend * season[t % 4] * (1 + rng.gauss(0, 0.025)))
    return out


def build_plan(bp: Blueprint, p: Params, rng: random.Random, base_rev: list[float]) -> StoryPlan:
    n = N_QUARTERS
    plan = StoryPlan(
        rev_mult=[1.0] * n,
        margin=[p.margin + rng.gauss(0, 0.006) for _ in range(n)],
        rec_days=[p.rec_days + rng.gauss(0, 3) for _ in range(n)],
        inv_days=[p.inv_days + rng.gauss(0, 3) for _ in range(n)],
        lt_debt=[p.lt_debt * (1 + 0.01 * t) for t in range(n)],
        st_debt=[p.st_debt * (1 + rng.gauss(0, 0.05)) for _ in range(n)],
        capex_to_dep=[p.capex_to_dep + rng.gauss(0, 0.1) for _ in range(n)],
        shares_cr=[p.shares_cr] * n,
        equity_infusion=[0.0] * n,
        pledge_pct=[p.pledge_pct] * n,
        promoter_pct=[p.promoter_pct + rng.gauss(0, 0.05) for _ in range(n)],
        retail_mult=[1 + 0.01 * t + rng.gauss(0, 0.01) for t in range(n)],
        related_party_ratio=[p.related_party_ratio] * n,
        contingent_ratio=[p.contingent_ratio] * n,
        audit_opinion=[AuditOpinion.UNQUALIFIED] * n,
        events=[],
        price_effects=[],
    )
    ev = plan.events
    ev.append(PlannedEvent(EventKind.RATING_ASSIGNED, _in_quarter(rng, 1), 1, {"rating": p.rating}))
    s = INFLECTION_Q

    if bp.story is Story.ORDER_BOOK_SURGE:
        ttm = sum(base_rev[s - 4 : s])
        first: date | None = None
        for k, pct in enumerate((0.28, 0.35, 0.22)):
            on = _in_quarter(rng, s - 1 + (k // 2), 10 + 30 * (k % 2), 40 + 30 * (k % 2))
            first = first or on
            ev.append(
                PlannedEvent(
                    EventKind.ORDER_WIN,
                    on,
                    s - 1 + (k // 2),
                    {"value_cr": q2(ttm * pct), "months": 12 + 6 * k, "pct_ttm": pct},
                )
            )
        ev.append(
            PlannedEvent(
                EventKind.CAPACITY_EXPANSION, _in_quarter(rng, s, 20, 60), s, {"capacity_pct": 40}
            )
        )
        for t in range(s + 1, n):
            plan.rev_mult[t] = 1 + 0.12 * (t - s)
            plan.margin[t] += 0.004 * (t - s)
            plan.capex_to_dep[t] = 2.5
        assert first is not None
        plan.price_effects.append(PriceEffect(first, 0.0016, 200))

    elif bp.story is Story.PLEDGE_UNWIND:
        for t in range(n):
            plan.pledge_pct[t] = 65.0 if t < s - 1 else {s - 1: 45.0, s: 20.0}.get(t, 0.0)
            if t >= s:
                plan.promoter_pct[t] = p.promoter_pct + 0.8 * min(t - s + 1, 2)
        for t, released in ((s - 1, 20.0), (s, 25.0), (s + 1, 20.0)):
            ev.append(
                PlannedEvent(
                    EventKind.PLEDGE_RELEASE,
                    _in_quarter(rng, t, 20, 70),
                    t,
                    {"pct_of_promoter": released},
                )
            )
        for t in (s, s + 1):
            ev.append(
                PlannedEvent(
                    EventKind.INSIDER_BUY,
                    _in_quarter(rng, t, 10, 60),
                    t,
                    {"value_cr": q2(rng.uniform(2, 4))},
                )
            )
        for t in range(s, n):
            plan.lt_debt[t] = p.lt_debt * max(0.3, 1 - 0.12 * (t - s + 1))
        plan.price_effects.append(PriceEffect(quarter_start(s) + timedelta(days=25), 0.0015, 180))

    elif bp.story is Story.MARGIN_TURNAROUND:
        for t in range(s - 1, n):
            plan.margin[t] = min(0.085 + 0.022 * (t - s + 2), 0.17) + rng.gauss(0, 0.003)
        ev.append(
            PlannedEvent(
                EventKind.RATING_UPGRADE, _in_quarter(rng, s + 2, 10, 50), s + 2, {"rating": "A-"}
            )
        )
        plan.price_effects.append(PriceEffect(results_public_date(s), 0.0016, 180))

    elif bp.story is Story.FORENSIC_RED_FLAG:
        for t in range(n):
            plan.rec_days[t] = 70 + max(0, t - 3) * 8
            plan.st_debt[t] = p.st_debt * (1 + 0.18 * max(0, t - 3))
            # Cash is kept large by ever-rising term debt while short-term debt also climbs.
            plan.lt_debt[t] = (p.lt_debt + p.base_revenue_q * 0.8) * (1 + 0.30 * max(0, t - 3))
            plan.contingent_ratio[t] = p.contingent_ratio * (5 if t >= s + 2 else 1)
            if t >= s + 2:
                plan.audit_opinion[t] = AuditOpinion.EMPHASIS_OF_MATTER
            if t >= n - 1:
                plan.audit_opinion[t] = AuditOpinion.QUALIFIED
        ev.append(PlannedEvent(EventKind.CFO_RESIGNATION, _in_quarter(rng, s + 3, 10, 40), s + 3))
        ev.append(
            PlannedEvent(
                EventKind.RATING_DOWNGRADE,
                _in_quarter(rng, s + 3, 45, 80),
                s + 3,
                {"rating": "BB+"},
            )
        )
        ev.append(PlannedEvent(EventKind.AUDITOR_CHANGE, _in_quarter(rng, s + 4, 10, 60), s + 4))
        plan.price_effects.append(
            PriceEffect(quarter_start(s + 3) + timedelta(days=10), -0.0015, 220)
        )

    elif bp.story is Story.DECEPTIVE_GROWTH:
        for t in range(n):
            if t >= 6:
                plan.rev_mult[t] = (1.45 / (1 + p.growth)) ** ((t - 5) / 4)
            plan.rec_days[t] = 80 + max(0, t - 5) * 9
            plan.related_party_ratio[t] = 0.05 if t < 7 else 0.42
        plan.retail_mult[s + 1] = plan.retail_mult[s] * 1.6
        for t in range(s + 2, n):
            plan.retail_mult[t] = plan.retail_mult[s + 1] * 1.35
        for t in (s + 1, s + 2):
            plan.promoter_pct[t:] = [p.promoter_pct - 1.6 * (t - s)] * (n - t)
            ev.append(
                PlannedEvent(
                    EventKind.INSIDER_SELL,
                    _in_quarter(rng, t, 10, 60),
                    t,
                    {"value_cr": q2(rng.uniform(6, 12))},
                )
            )
        for t in (6, s + 3):
            ev.append(
                PlannedEvent(
                    EventKind.FUND_RAISE,
                    _in_quarter(rng, t, 10, 60),
                    t,
                    {"amount_cr": q2(base_rev[t] * 0.6), "discount_pct": 18},
                )
            )
            plan.equity_infusion[t] = base_rev[t] * 0.6
        ev.append(
            PlannedEvent(EventKind.ASM_ENTRY, _in_quarter(rng, s + 2, 10, 40), s + 2, {"stage": 1})
        )
        ev.append(PlannedEvent(EventKind.ASM_EXIT, _in_quarter(rng, s + 4, 10, 40), s + 4))
        plan.price_effects.append(PriceEffect(quarter_start(s - 1), 0.0018, 150))
        plan.price_effects.append(PriceEffect(quarter_start(s + 2), -0.0022, 200))

    elif bp.story is Story.DELISTED:
        for t in range(n):
            plan.margin[t] = 0.05 - 0.006 * max(0, t - 2)
            plan.st_debt[t] = p.st_debt * (1 + 0.15 * t)
        delisted_on = date(2024, 12, 13)
        plan.stop_after_quarter = s
        plan.delisted_on = delisted_on
        ev.append(PlannedEvent(EventKind.GSM_ENTRY, _in_quarter(rng, 7, 10, 40), 7, {"stage": 1}))
        ev.append(PlannedEvent(EventKind.DELISTING, delisted_on, s + 1))
        plan.price_effects.append(PriceEffect(quarter_start(6), -0.0035, 600))

    if bp.story is Story.CONTROL:
        for t in range(2, n):
            if (
                bp.sector in {"Capital Goods", "Infrastructure", "Defence", "Engineering"}
                and rng.random() < 0.25
            ):
                ev.append(
                    PlannedEvent(
                        EventKind.ORDER_WIN,
                        _in_quarter(rng, t),
                        t,
                        {
                            "value_cr": q2(base_rev[t] * rng.uniform(0.04, 0.10)),
                            "months": rng.choice([6, 9, 12]),
                            "pct_ttm": 0.02,
                        },
                    )
                )
            if rng.random() < 0.08:
                kind = rng.choice([EventKind.INSIDER_BUY, EventKind.INSIDER_SELL])
                ev.append(
                    PlannedEvent(
                        kind, _in_quarter(rng, t), t, {"value_cr": q2(rng.uniform(0.1, 0.6))}
                    )
                )
            if rng.random() < 0.05:
                ev.append(
                    PlannedEvent(
                        EventKind.BULK_DEAL, _in_quarter(rng, t), t, {"pct": rng.uniform(0.5, 1.5)}
                    )
                )
        if bp.bonus_issue:
            t_b = 7
            on = _in_quarter(rng, t_b, 20, 50)
            ev.append(
                PlannedEvent(
                    EventKind.BONUS, on, t_b, {"ratio": 1, "ex_date": on + timedelta(days=30)}
                )
            )
            for t in range(t_b + 1, n):
                plan.shares_cr[t] = p.shares_cr * 2
    if (
        bp.story in {Story.CONTROL, Story.MARGIN_TURNAROUND, Story.ORDER_BOOK_SURGE}
        and rng.random() < 0.7
    ):
        for t in range(3, n, 4):
            ev.append(
                PlannedEvent(
                    EventKind.DIVIDEND,
                    results_public_date(t),
                    t,
                    {"per_share": q2(rng.uniform(0.5, 4))},
                )
            )
    plan.events.sort(key=lambda e: e.on)
    return plan


# ------------------------------------------------------------------------- financials
@dataclass
class QuarterFin:
    index: int
    period_end: date
    revenue: Decimal
    other_income: Decimal
    total_expenses: Decimal
    ebitda: Decimal
    depreciation: Decimal
    finance_cost: Decimal
    pbt: Decimal
    tax: Decimal
    pat: Decimal
    eps: Decimal
    shares_cr: Decimal
    total_borrowings: Decimal
    short_term_borrowings: Decimal
    long_term_borrowings: Decimal
    cash: Decimal
    receivables: Decimal
    inventory: Decimal
    payables: Decimal
    net_worth: Decimal
    total_assets: Decimal
    cfo: Decimal
    cfi: Decimal
    cff: Decimal
    capex: Decimal


@dataclass
class PeriodAggregate:
    """P&L and cash flow summed over several quarters; balance sheet at the last quarter."""

    period_end: date
    months: int
    revenue: Decimal
    other_income: Decimal
    total_expenses: Decimal
    ebitda: Decimal
    depreciation: Decimal
    finance_cost: Decimal
    pbt: Decimal
    tax: Decimal
    pat: Decimal
    eps: Decimal
    balance: QuarterFin
    cfo: Decimal
    cfi: Decimal
    cff: Decimal
    capex: Decimal


def aggregate(quarters: list[QuarterFin], months: int) -> PeriodAggregate:
    last = quarters[-1]

    def s(attr: str) -> Decimal:
        return sum((getattr(q, attr) for q in quarters), Decimal(0))

    pat = s("pat")
    return PeriodAggregate(
        period_end=last.period_end,
        months=months,
        revenue=s("revenue"),
        other_income=s("other_income"),
        total_expenses=s("total_expenses"),
        ebitda=s("ebitda"),
        depreciation=s("depreciation"),
        finance_cost=s("finance_cost"),
        pbt=s("pbt"),
        tax=s("tax"),
        pat=pat,
        eps=q2(pat / last.shares_cr),
        balance=last,
        cfo=s("cfo"),
        cfi=s("cfi"),
        cff=s("cff"),
        capex=s("capex"),
    )


def synthesize_financials(p: Params, plan: StoryPlan, base_rev: list[float]) -> list[QuarterFin]:
    out: list[QuarterFin] = []
    cash = q2(p.cash)
    net_worth = q2(p.net_worth)
    prev_debt = q2(plan.lt_debt[0] + plan.st_debt[0])
    prev_wc: Decimal | None = None
    last = plan.stop_after_quarter if plan.stop_after_quarter is not None else N_QUARTERS - 1
    for t in range(last + 1):
        rev = q2(base_rev[t] * plan.rev_mult[t])
        ebitda = q2(float(rev) * plan.margin[t])
        dep = q2(float(rev) * p.dep_pct)
        lt = q2(plan.lt_debt[t])
        st = q2(plan.st_debt[t])
        debt = lt + st
        fin = q2(float((prev_debt + debt) / 2) * p.interest_rate / 4)
        oi = q2(float(cash) * 0.05 / 4)
        pbt = ebitda - dep - fin + oi
        tax = q2(float(max(pbt, Decimal(0))) * p.tax_rate)
        pat = pbt - tax
        total_expenses = rev + oi - pbt
        shares = q2(plan.shares_cr[t])
        eps = q2(pat / shares)

        window = [q.revenue for q in out[-3:]] + [rev]
        ttm = sum(window, Decimal(0)) * Decimal(4) / Decimal(len(window))
        cogs = ttm * Decimal(1 - plan.margin[t])
        rec = q2(float(ttm) * plan.rec_days[t] / 365)
        inv = q2(float(cogs) * plan.inv_days[t] / 365)
        pay = q2(float(cogs) * p.pay_days / 365)
        wc = rec + inv - pay
        d_wc = Decimal(0) if prev_wc is None else wc - prev_wc
        capex = q2(float(dep) * plan.capex_to_dep[t])
        infusion = q2(plan.equity_infusion[t])
        cfo = ebitda - tax - d_wc + oi
        cfi = -capex
        cff = (debt - prev_debt) - fin + infusion
        cash = cash + cfo + cfi + cff
        # A company cannot hold negative cash: shortfalls are funded by short-term borrowing.
        min_cash = q2(float(rev) * 0.05)
        if cash < min_cash:
            shortfall = min_cash - cash
            st += shortfall
            debt += shortfall
            cff += shortfall
            cash = min_cash
        net_worth = net_worth + pat + infusion
        total_assets = net_worth + debt + pay
        out.append(
            QuarterFin(
                index=t,
                period_end=quarter_end(t),
                revenue=rev,
                other_income=oi,
                total_expenses=total_expenses,
                ebitda=ebitda,
                depreciation=dep,
                finance_cost=fin,
                pbt=pbt,
                tax=tax,
                pat=pat,
                eps=eps,
                shares_cr=shares,
                total_borrowings=debt,
                short_term_borrowings=st,
                long_term_borrowings=lt,
                cash=cash,
                receivables=rec,
                inventory=inv,
                payables=pay,
                net_worth=net_worth,
                total_assets=total_assets,
                cfo=cfo,
                cfi=cfi,
                cff=cff,
                capex=capex,
            )
        )
        prev_debt = debt
        prev_wc = wc
    return out


# ----------------------------------------------------------------------- shareholding
@dataclass
class QuarterHolding:
    index: int
    period_end: date
    promoter_pct: Decimal
    pledged_pct: Decimal
    fii_pct: Decimal
    dii_pct: Decimal
    public_pct: Decimal
    total_shareholders: int
    retail_shareholders: int
    holders: list[tuple[str, str, Decimal]]  # (name, category, pct)


def synthesize_holdings(
    p: Params, plan: StoryPlan, rng: random.Random, bp: Blueprint
) -> list[QuarterHolding]:
    out: list[QuarterHolding] = []
    fii = p.fii_pct
    dii = p.dii_pct
    last = plan.stop_after_quarter if plan.stop_after_quarter is not None else N_QUARTERS - 1
    for t in range(last + 1):
        fii = max(0.0, fii + rng.gauss(0, 0.15))
        dii = max(0.0, dii + rng.gauss(0, 0.15))
        promoter = q2(plan.promoter_pct[t])
        fii_d = q2(fii)
        dii_d = q2(dii)
        public = Decimal(100) - promoter - fii_d - dii_d
        total = int(p.shareholders * plan.retail_mult[t])
        holders: list[tuple[str, str, Decimal]] = []
        if fii_d >= 1:
            holders.append((f"Meridian Frontier Fund (Mock FPI) for {bp.ticker}", "fii", fii_d))
        if dii_d >= 1:
            holders.append(("Kalinga Mutual Fund (Mock) Small Cap Scheme", "mutual_fund", dii_d))
        out.append(
            QuarterHolding(
                index=t,
                period_end=quarter_end(t),
                promoter_pct=promoter,
                pledged_pct=q2(plan.pledge_pct[t]),
                fii_pct=fii_d,
                dii_pct=dii_d,
                public_pct=public,
                total_shareholders=total,
                retail_shareholders=int(total * 0.96),
                holders=holders,
            )
        )
    return out


@dataclass
class CompanyHistory:
    blueprint: Blueprint
    params: Params
    plan: StoryPlan
    quarters: list[QuarterFin]
    holdings: list[QuarterHolding]

    def half_year(self, t: int) -> PeriodAggregate | None:
        if not is_half_year_end(t) or t < 1:
            return None
        return aggregate(self.quarters[t - 1 : t + 1], 6)

    def fiscal_year(self, t: int) -> PeriodAggregate | None:
        if not is_fiscal_year_end(t) or t < 3:
            return None
        return aggregate(self.quarters[t - 3 : t + 1], 12)


def synthesize_company(bp: Blueprint, seed: int) -> CompanyHistory:
    rng = random.Random(f"{seed}:{bp.ticker}")
    params = draw_params(rng, bp)
    base_rev = baseline_revenue(params, rng)
    plan = build_plan(bp, params, rng, base_rev)
    quarters = synthesize_financials(params, plan, base_rev)
    holdings = synthesize_holdings(params, plan, rng, bp)
    return CompanyHistory(bp, params, plan, quarters, holdings)
