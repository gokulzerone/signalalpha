"""Plain-language rendering of signals (deterministic, no model involved).

Every sentence is built from the signal's stored ``parameters``, which the detector computed
in Python. If a parameter is missing the sentence degrades to the signal's definition rather
than inventing a number.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

Params = dict[str, Any]


def _pct(v: Any, digits: int = 0) -> str:
    return f"{float(v) * 100:.{digits}f}%"


def _pp(v: Any, digits: int = 0) -> str:
    return f"{float(v):.{digits}f}pp"


def _cr(v: Any) -> str:
    return f"Rs {float(v):,.0f} crore"


def _num(v: Any, digits: int = 1) -> str:
    return f"{float(v):.{digits}f}"


def _get(p: Params, *names: str) -> Any:
    for n in names:
        if p.get(n) is not None:
            return p[n]
    return None


def _revenue_acceleration(p: Params) -> str:
    latest, excess = _get(p, "yoy_growth_latest"), _get(p, "excess_pp")
    if latest is None or excess is None:
        return "Revenue growth stepped up against its own recent trend."
    return f"Revenue grew {_pct(latest)} year on year, {_pp(excess)} faster than its average of the previous four quarters."


def _margin_inflection(p: Params) -> str:
    bp, margin = _get(p, "delta_bp_latest"), _get(p, "margin_latest")
    direction = "rose" if (bp or 0) > 0 else "fell"
    if bp is None:
        return (
            "Operating margin moved away from its recent average and stayed there for two quarters."
        )
    tail = f" to {_pct(margin, 1)}" if margin is not None else ""
    return f"Operating margin {direction} {abs(float(bp)):.0f}bp against its four-quarter average{tail}, and held for two quarters."


def _operating_leverage(p: Params) -> str:
    ratio, rev, eb = (
        _get(p, "ebitda_to_revenue_growth_ratio_latest"),
        _get(p, "revenue_yoy_latest"),
        _get(p, "ebitda_yoy_latest"),
    )
    if rev is None or eb is None:
        return "Profits grew faster than sales for two consecutive quarters."
    return f"EBITDA grew {_pct(eb)} against revenue growth of {_pct(rev)}, so profit is growing {_num(ratio or 0)}x as fast as sales."


def _cash_conversion(p: Params) -> str:
    now, before = _get(p, "cfo_to_ebitda_ttm"), _get(p, "cfo_to_ebitda_previous")
    if now is None:
        return "Cash generation crossed above the level the configuration treats as healthy."
    tail = f", up from {_pct(before)}" if before is not None else ""
    return f"Operating cash flow is now {_pct(now)} of EBITDA{tail}: reported profit is turning into cash."


def _working_capital(p: Params) -> str:
    comp, days = _get(p, "component"), _get(p, "days_fall")
    if days is None:
        return "Working capital was released compared with a year earlier."
    return f"{str(comp or 'Working capital').replace('_', ' ').capitalize()} days fell by {float(days):.0f} versus a year earlier, freeing up cash."


def _deleveraging(p: Params) -> str:
    if _get(p, "turned_net_cash"):
        return "Net debt turned into net cash."
    now, before = _get(p, "net_debt_to_ebitda"), _get(p, "net_debt_to_ebitda_previous")
    if now is None:
        return "Leverage fell below the configured threshold."
    tail = f" from {_num(before)}x" if before is not None else ""
    return f"Net debt fell to {_num(now)}x EBITDA{tail}."


def _capex(p: Params) -> str:
    ratio = _get(p, "capex_to_depreciation")
    if ratio is None:
        return "Capital spending stepped up for the first time in years."
    return f"Capital spending reached {_num(ratio)}x depreciation, the first time in {int(_get(p, 'lookback_quarters') or 8)} quarters: the company is investing in capacity."


def _promoter_stake(p: Params, up: bool) -> str:
    if p.get("trigger") == "insider_trade":
        value = _get(p, "value_cr")
        verb = "bought" if up else "sold"
        return f"A promoter {verb} {_cr(value or 0)} of stock in the open market."
    change, now = _get(p, "change_pp"), _get(p, "promoter_pct")
    verb = "raised" if up else "cut"
    if change is None:
        return f"Promoters {verb} their holding this quarter."
    return f"Promoters {verb} their stake by {_pp(abs(float(change)), 1)} to {_num(now or 0)}% of the company."


def _pledge(p: Params, released: bool) -> str:
    if p.get("trigger") == "pledge_disclosure":
        pct = _get(p, "pct_of_promoter_holding")
        verb = "released" if released else "pledged"
        return f"Promoters {verb} {_num(pct or 0)}% of their holding{'' if released else ' as loan collateral'}."
    now, change = _get(p, "pledged_pct"), _get(p, "change_pp")
    if change is None:
        return "The share of promoter holding under pledge moved materially."
    verb = "fell" if released else "rose"
    return f"Pledged promoter shares {verb} by {_pp(abs(float(change)), 1)} to {_num(now or 0)}% of their holding."


def _institutional(p: Params) -> str:
    holder, pct = _get(p, "holder"), _get(p, "pct")
    if p.get("trigger") == "bulk_deal":
        return f"{holder or 'An institution'} bought a block in the open market."
    return f"{holder or 'A new institution'} appeared on the register with {_num(pct or 0)}% of the company."


def _shareholder_spike(p: Params) -> str:
    growth = _get(p, "growth")
    if growth is None:
        return "The retail shareholder count jumped, which usually marks late retail interest."
    return f"Retail shareholders rose {_pct(growth)} in a quarter, which usually marks late retail buying rather than fundamentals."


def _order_win(p: Params) -> str:
    value, share = _get(p, "order_value_cr"), _get(p, "pct_of_ttm_revenue")
    if value is None:
        return "The company announced a contract win."
    tail = f", worth {_pct(share)} of its annual revenue" if share is not None else ""
    return f"Won an order of {_cr(value)}{tail}."


def _capacity(p: Params) -> str:
    pct = _get(p, "capacity_increase_pct")
    return (
        f"Announced a {float(pct):.0f}% capacity expansion."
        if pct is not None
        else "Announced a capacity expansion."
    )


def _rating(p: Params, up: bool) -> str:
    rating, agency = _get(p, "rating"), _get(p, "agency")
    word = "upgraded" if up else "downgraded"
    return f"{agency or 'The rating agency'} {word} its credit rating to {rating or 'a new level'}."


def _key_person(p: Params) -> str:
    role = (
        str(_get(p, "role") or "a key officer").upper()
        if str(_get(p, "role") or "").lower() == "cfo"
        else str(_get(p, "role") or "a key officer")
    )
    return f"The {role} resigned."


def _auditor(p: Params) -> str:
    return "The statutory auditor changed outside the normal rotation, which is worth explaining."


def _delivery(p: Params) -> str:
    d, v = _get(p, "delivery_uplift"), _get(p, "value_uplift")
    if d is None or v is None:
        return "Delivery-based volume and traded value both stepped up against their own trend."
    return f"Delivery volumes are {_pct(d)} above their 90-day average and traded value {_pct(v)} above, so buyers are taking delivery rather than trading."


def _surveillance(p: Params, entry: bool) -> str:
    fw = str(_get(p, "framework") or "surveillance").upper()
    return (
        f"The exchange placed the stock under {fw} surveillance."
        if entry
        else f"The exchange removed the stock from {fw} surveillance."
    )


def _price_lag(p: Params) -> str:
    gap, trigger = _get(p, "gap"), _get(p, "trigger_signal")
    reason = str(trigger or "a fundamental signal").replace("_", " ")
    if gap is None:
        return "The share price has lagged its sector while fundamentals improved."
    return f"The price has lagged its sector by {_pct(gap)} over 90 days despite {reason}."


def _related_party(p: Params) -> str:
    share = _get(p, "share")
    if share is None:
        return "A large share of revenue is billed to related parties."
    return f"{_pct(share)} of revenue is billed to related parties, so reported growth may not be arm's length."


def _receivables(p: Params) -> str:
    gap = _get(p, "gap_latest")
    if gap is None:
        return "Receivables have grown faster than revenue for two years."
    return f"Receivables grew {_pp(float(gap) * 100)} faster than revenue for a second year: sales are being booked but not collected."


def _cash_vs_debt(p: Params) -> str:
    growth, ratio = _get(p, "st_debt_growth"), _get(p, "cash_to_ttm_revenue")
    if growth is None:
        return "The company reports large cash while short-term borrowing keeps rising."
    return f"Short-term borrowing rose {_pct(growth)} while reported cash sits at {_pct(ratio or 0)} of revenue, a combination that usually needs explaining."


def _audit(p: Params) -> str:
    opinion = str(_get(p, "audit_opinion") or "").replace("_", " ")
    return (
        f"The auditor's opinion was modified ({opinion})."
        if opinion
        else "The auditor modified the opinion."
    )


def _contingent(p: Params) -> str:
    share, ratio = _get(p, "share_of_revenue"), _get(p, "ratio_to_previous")
    if share is None:
        return "Contingent liabilities jumped against the prior year."
    tail = f", {_num(ratio)}x the prior year" if ratio else ""
    return f"Contingent liabilities reached {_pct(share)} of revenue{tail}: disputes or guarantees are building up."


def _fund_raise(p: Params) -> str:
    n = _get(p, "raises_in_lookback")
    return f"Promoters were issued discounted shares {int(n or 2)} times in two years, diluting outside shareholders."


NARRATORS: dict[str, Callable[[Params], str]] = {
    "revenue_acceleration": _revenue_acceleration,
    "margin_inflection": _margin_inflection,
    "operating_leverage": _operating_leverage,
    "cash_conversion_improvement": _cash_conversion,
    "working_capital_release": _working_capital,
    "deleveraging": _deleveraging,
    "capex_cycle_start": _capex,
    "promoter_stake_increase": lambda p: _promoter_stake(p, True),
    "promoter_stake_decrease": lambda p: _promoter_stake(p, False),
    "pledge_reduction": lambda p: _pledge(p, True),
    "pledge_increase": lambda p: _pledge(p, False),
    "pledge_invocation": lambda p: (
        "A lender invoked pledged promoter shares, which is a distress signal."
    ),
    "institutional_entry": _institutional,
    "shareholder_count_spike": _shareholder_spike,
    "order_win": _order_win,
    "capacity_expansion": _capacity,
    "credit_rating_upgrade": lambda p: _rating(p, True),
    "credit_rating_downgrade": lambda p: _rating(p, False),
    "key_person_exit": _key_person,
    "auditor_change": _auditor,
    "delivery_volume_shift": _delivery,
    "surveillance_entry": lambda p: _surveillance(p, True),
    "surveillance_exit": lambda p: _surveillance(p, False),
    "price_lagging_fundamentals": _price_lag,
    "related_party_revenue": _related_party,
    "receivables_outrunning_revenue": _receivables,
    "cash_vs_debt_anomaly": _cash_vs_debt,
    "audit_qualification": _audit,
    "contingent_liability_spike": _contingent,
    "frequent_fund_raise": _fund_raise,
}


def narrate_signal(signal_type: str, parameters: Params | None = None) -> str:
    """One plain sentence for a signal, built from the numbers the detector computed."""
    fn = NARRATORS.get(signal_type)
    if fn is None:
        return signal_type.replace("_", " ").capitalize() + "."
    try:
        return fn(parameters or {})
    except (TypeError, ValueError):
        return signal_type.replace("_", " ").capitalize() + "."


def narrate_summary(signals: Sequence[tuple[str, Params, int, float]], limit: int = 3) -> str:
    """A short paragraph from the strongest signals: ``(type, parameters, direction, magnitude)``."""
    ranked = sorted(signals, key=lambda s: -s[3])[:limit]
    if not ranked:
        return "No signals in this window."
    return " ".join(narrate_signal(t, p) for t, p, _, _ in ranked)
