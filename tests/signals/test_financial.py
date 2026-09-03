from __future__ import annotations

from signals.config import load_catalogue
from signals.detectors.financial import (
    capex_cycle_start,
    cash_conversion_improvement,
    deleveraging,
    margin_inflection,
    operating_leverage,
    revenue_acceleration,
    working_capital_release,
)
from tests.signals.helpers import make_ctx, period, qend, quarters

CFG = load_catalogue()


def test_revenue_acceleration_positive_and_negative() -> None:
    steady = [100 * 1.1 ** (i / 4) for i in range(9)]
    assert revenue_acceleration(make_ctx(quarters=quarters(steady)), CFG) == []
    surge = [*steady[:-1], steady[-1] * 1.3]
    [sig] = revenue_acceleration(make_ctx(quarters=quarters(surge)), CFG)
    assert sig.direction == 1 and 0 < sig.magnitude <= 1
    assert sig.parameters["excess_pp"] >= CFG.param("revenue_acceleration", "min_excess_pp")
    assert sig.public_at == quarters(surge)[-1].public_at
    assert (
        revenue_acceleration(make_ctx(quarters=quarters(surge[:8])), CFG) == []
    )  # too little history


def test_margin_inflection_both_directions() -> None:
    rev = [100.0] * 8
    flat = [15.0] * 8
    assert margin_inflection(make_ctx(quarters=quarters(rev, flat)), CFG) == []
    up = [15.0] * 6 + [19.0, 20.0]
    [sig] = margin_inflection(make_ctx(quarters=quarters(rev, up)), CFG)
    assert sig.direction == 1 and sig.parameters["delta_bp_latest"] >= 200
    one_quarter = [15.0] * 7 + [20.0]  # not sustained
    assert margin_inflection(make_ctx(quarters=quarters(rev, one_quarter)), CFG) == []
    down = [15.0] * 6 + [11.0, 10.0]
    [sig] = margin_inflection(make_ctx(quarters=quarters(rev, down)), CFG)
    assert sig.direction == -1


def test_operating_leverage() -> None:
    rev = [100, 100, 100, 100, 110, 110, 110, 110]
    ebitda_lev = [15, 15, 15, 15, 17, 19, 21, 21]  # last two quarters: ebitda +40% vs revenue +10%
    [sig] = operating_leverage(make_ctx(quarters=quarters(rev, ebitda_lev)), CFG)
    assert sig.direction == 1 and sig.parameters["ratio_previous"] >= 1.5
    ebitda_flat = [15, 15, 15, 15, 16.5, 16.5, 16.5, 16.5]  # ebitda grows in line with revenue
    assert operating_leverage(make_ctx(quarters=quarters(rev, ebitda_flat)), CFG) == []
    rev_down = [100] * 4 + [90] * 4
    assert operating_leverage(make_ctx(quarters=quarters(rev_down, ebitda_lev)), CFG) == []


def _balance_rows(
    cfo_by_end: dict[int, float],
    rec: float = 20,
    cash: float = 10,
    debt: float = 30,
    capex: float = 3,
) -> list:  # type: ignore[type-arg]
    rows = []
    for i, cfo in cfo_by_end.items():
        months = 12 if qend(i).month == 3 else 6
        rows.append(
            period(
                qend(i),
                months=months,
                revenue=100 * (2 if months == 6 else 4),
                ebitda=15 * (2 if months == 6 else 4),
                depreciation=3 * (2 if months == 6 else 4),
                cfo=cfo,
                capex=capex,
                receivables=rec,
                inventory=10,
                payables=8,
                cash=cash,
                total_borrowings=debt,
                short_term_borrowings=debt / 2,
            )
        )
    return rows


def test_cash_conversion_improvement() -> None:
    q = quarters([100.0] * 12)
    # FY (Mar-23): CFO 20/60 = 0.33. H1 (Sep-23): 40 + 20 - 10 = 50 over EBITDA 60 -> 0.83
    rows = _balance_rows({1: 10, 3: 20, 5: 40})
    halves = [r for r in rows if r.months == 6]
    annuals = [r for r in rows if r.months == 12]
    [sig] = cash_conversion_improvement(make_ctx(quarters=q, halves=halves, annuals=annuals), CFG)
    assert (
        sig.direction == 1
        and sig.parameters["cfo_to_ebitda_previous"] < 0.7 <= sig.parameters["cfo_to_ebitda_ttm"]
    )
    rows_flat = _balance_rows({1: 40, 3: 80, 5: 40})  # already above threshold before
    assert (
        cash_conversion_improvement(
            make_ctx(
                quarters=q,
                halves=[r for r in rows_flat if r.months == 6],
                annuals=[r for r in rows_flat if r.months == 12],
            ),
            CFG,
        )
        == []
    )


def test_working_capital_release() -> None:
    q = quarters([100.0] * 12)
    a1 = period(
        qend(3),
        months=12,
        revenue=400,
        receivables=110,
        inventory=40,
        payables=20,
        cash=10,
        total_borrowings=30,
        short_term_borrowings=10,
    )
    a2_release = period(
        qend(7),
        months=12,
        revenue=400,
        receivables=80,
        inventory=40,
        payables=20,
        cash=10,
        total_borrowings=30,
        short_term_borrowings=10,
    )
    [sig] = working_capital_release(make_ctx(quarters=q, annuals=[a1, a2_release]), CFG)
    assert sig.parameters["component"] == "receivables" and sig.parameters["days_fall"] >= 15
    a2_same = period(
        qend(7),
        months=12,
        revenue=400,
        receivables=105,
        inventory=40,
        payables=20,
        cash=10,
        total_borrowings=30,
        short_term_borrowings=10,
    )
    assert working_capital_release(make_ctx(quarters=q, annuals=[a1, a2_same]), CFG) == []


def test_deleveraging() -> None:
    q = quarters([100.0] * 8)
    high = period(
        qend(3),
        months=12,
        revenue=400,
        ebitda=60,
        receivables=50,
        cash=10,
        total_borrowings=100,
        short_term_borrowings=20,
    )
    low = period(
        qend(7),
        months=12,
        revenue=400,
        ebitda=60,
        receivables=50,
        cash=10,
        total_borrowings=50,
        short_term_borrowings=20,
    )
    [sig] = deleveraging(make_ctx(quarters=q, annuals=[high, low]), CFG)
    assert (
        sig.parameters["net_debt_to_ebitda_previous"] >= 1.0 > sig.parameters["net_debt_to_ebitda"]
    )
    net_cash = period(
        qend(7),
        months=12,
        revenue=400,
        ebitda=60,
        receivables=50,
        cash=120,
        total_borrowings=100,
        short_term_borrowings=20,
    )
    [sig] = deleveraging(make_ctx(quarters=q, annuals=[high, net_cash]), CFG)
    assert sig.parameters["turned_net_cash"] is True and sig.magnitude == 1.0
    still_high = period(
        qend(7),
        months=12,
        revenue=400,
        ebitda=60,
        receivables=50,
        cash=10,
        total_borrowings=95,
        short_term_borrowings=20,
    )
    assert deleveraging(make_ctx(quarters=q, annuals=[high, still_high]), CFG) == []


def test_capex_cycle_start() -> None:
    q = quarters([100.0] * 12)
    prior = [
        period(
            qend(i),
            months=12 if qend(i).month == 3 else 6,
            revenue=100,
            depreciation=10,
            capex=8,
            receivables=1,
        )
        for i in (1, 3, 5)
    ]
    start = period(qend(7), months=12, revenue=100, depreciation=10, capex=30, receivables=1)
    [sig] = capex_cycle_start(
        make_ctx(
            quarters=q,
            halves=[p for p in prior if p.months == 6],
            annuals=[p for p in prior if p.months == 12] + [start],
        ),
        CFG,
    )
    assert sig.parameters["capex_to_depreciation"] == 3.0
    already = [
        period(
            qend(i),
            months=12 if qend(i).month == 3 else 6,
            revenue=100,
            depreciation=10,
            capex=25,
            receivables=1,
        )
        for i in (1, 3, 5)
    ]
    assert (
        capex_cycle_start(
            make_ctx(
                quarters=q,
                halves=[p for p in already if p.months == 6],
                annuals=[p for p in already if p.months == 12] + [start],
            ),
            CFG,
        )
        == []
    )
