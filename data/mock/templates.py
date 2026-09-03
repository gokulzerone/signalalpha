"""Text renderers for mock documents. Numbers are rendered exactly as stored (two decimals)
so that evidence spans and agent numeric claims can be verified against the text."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from data.mock.prices import DailyBar
from data.mock.synth import PeriodAggregate, QuarterFin, QuarterHolding
from database.models import AuditOpinion

PAGE = "\f"


def money(d: Decimal) -> str:
    return f"{d:.2f}"


def fdate(d: date) -> str:
    return d.strftime("%d %B %Y")


def _pnl_table(
    label: str, cur: QuarterFin | PeriodAggregate, prev: QuarterFin | PeriodAggregate | None
) -> str:
    def row(name: str, attr: str) -> str:
        left = money(getattr(cur, attr))
        right = money(getattr(prev, attr)) if prev is not None else "-"
        return f"{name} | {left} | {right}"

    header = (
        f"Particulars | {label} ended {fdate(cur.period_end)} | {label} ended {fdate(prev.period_end)}"
        if prev
        else f"Particulars | {label} ended {fdate(cur.period_end)} | Previous period"
    )
    return "\n".join(
        [
            header,
            row("Revenue from operations", "revenue"),
            row("Other income", "other_income"),
            row("Total expenses", "total_expenses"),
            row("EBITDA", "ebitda"),
            row("Depreciation and amortisation expense", "depreciation"),
            row("Finance costs", "finance_cost"),
            row("Profit before tax", "pbt"),
            row("Tax expense", "tax"),
            row("Profit after tax", "pat"),
            row("Earnings per share (Rs.)", "eps"),
        ]
    )


def _balance_sheet(b: QuarterFin) -> str:
    return "\n".join(
        [
            f"Statement of assets and liabilities as at {fdate(b.period_end)}",
            f"Net worth | {money(b.net_worth)}",
            f"Long-term borrowings | {money(b.long_term_borrowings)}",
            f"Short-term borrowings | {money(b.short_term_borrowings)}",
            f"Total borrowings | {money(b.total_borrowings)}",
            f"Trade payables | {money(b.payables)}",
            f"Total assets | {money(b.total_assets)}",
            f"Cash and cash equivalents | {money(b.cash)}",
            f"Trade receivables | {money(b.receivables)}",
            f"Inventories | {money(b.inventory)}",
            f"Equity shares outstanding (crore) | {money(b.shares_cr)}",
        ]
    )


def _cash_flow(a: PeriodAggregate) -> str:
    return "\n".join(
        [
            f"Statement of cash flows for the {a.months} months ended {fdate(a.period_end)}",
            f"Net cash from operating activities | {money(a.cfo)}",
            f"Net cash used in investing activities | {money(a.cfi)}",
            f"Purchase of property, plant and equipment | {money(a.capex)}",
            f"Net cash from financing activities | {money(a.cff)}",
        ]
    )


def results_filing(
    name: str,
    ticker: str,
    q: QuarterFin,
    prev_year_q: QuarterFin | None,
    half: PeriodAggregate | None,
    prev_half: PeriodAggregate | None,
    fy: PeriodAggregate | None,
    prev_fy: PeriodAggregate | None,
    board_date: date,
    consolidated: bool,
) -> str:
    basis = "consolidated" if consolidated else "standalone"
    audited = "audited" if fy is not None else "unaudited"
    parts = [
        f"{name} ({ticker})",
        f"Statement of {audited} {basis} financial results for the quarter ended {fdate(q.period_end)}",
        "(Rs. in crore, except per share data)",
        "",
        _pnl_table("Quarter", q, prev_year_q),
    ]
    if half is not None:
        parts += [
            "",
            _pnl_table("Six months", half, prev_half),
            "",
            _balance_sheet(half.balance),
            "",
            _cash_flow(half),
        ]
    if fy is not None:
        parts += [
            "",
            _pnl_table("Year", fy, prev_fy),
            "",
            _balance_sheet(fy.balance),
            "",
            _cash_flow(fy),
        ]
    parts += [
        PAGE,
        "Notes:",
        f"1. The above results were reviewed by the Audit Committee and approved by the Board of Directors at its meeting held on {fdate(board_date)}.",
        "2. The Company operates in a single reportable segment.",
        f"3. Revenue from operations for the quarter ended {fdate(q.period_end)} was Rs. {money(q.revenue)} crore and EBITDA was Rs. {money(q.ebitda)} crore.",
        "4. Figures for the previous periods have been regrouped where necessary.",
        "This is a fictional mock document generated for SignalAlpha development. It does not describe any real company.",
    ]
    return "\n".join(parts)


def shareholding_pattern(name: str, ticker: str, h: QuarterHolding) -> str:
    lines = [
        f"{name} ({ticker})",
        f"Shareholding pattern as on {fdate(h.period_end)} under Regulation 31 of SEBI (LODR) Regulations, 2015",
        "",
        "Category | Percentage of total equity shares",
        f"Promoter and Promoter Group | {money(h.promoter_pct)}",
        f"Foreign Portfolio Investors | {money(h.fii_pct)}",
        f"Domestic Institutional Investors | {money(h.dii_pct)}",
        f"Public and others | {money(h.public_pct)}",
        "",
        f"Shares pledged or otherwise encumbered by promoters: {money(h.pledged_pct)}% of promoter holding",
        f"Total number of shareholders: {h.total_shareholders}",
        f"Number of public shareholders holding nominal value up to Rs. 2 lakh: {h.retail_shareholders}",
    ]
    if h.holders:
        lines += ["", "Shareholders holding more than 1% of the total number of shares:"]
        lines += [f"{hn} | {money(pct)}" for hn, _, pct in h.holders]
    lines += ["", "This is a fictional mock document generated for SignalAlpha development."]
    return "\n".join(lines)


def _opinion_text(opinion: AuditOpinion) -> str:
    return {
        AuditOpinion.UNQUALIFIED: "In our opinion, the financial statements give a true and fair view in conformity with the accounting principles generally accepted in India. Our opinion is not modified.",
        AuditOpinion.EMPHASIS_OF_MATTER: "Emphasis of Matter: We draw attention to the note on trade receivables outstanding for more than one year, for which no provision has been made. Our opinion is not modified in respect of this matter.",
        AuditOpinion.QUALIFIED: "Qualified Opinion: The Company has not provided for doubtful trade receivables and has not obtained balance confirmations from major customers. We were unable to obtain sufficient appropriate audit evidence regarding their recoverability.",
        AuditOpinion.GOING_CONCERN: "Material uncertainty related to going concern: the Company's current liabilities exceed its current assets and it has defaulted on borrowings.",
        AuditOpinion.ADVERSE: "Adverse Opinion: the financial statements do not give a true and fair view.",
        AuditOpinion.DISCLAIMER: "Disclaimer of Opinion: we do not express an opinion on the financial statements.",
    }[opinion]


def annual_report(
    name: str,
    ticker: str,
    fy: PeriodAggregate,
    prev_fy: PeriodAggregate | None,
    related_party_revenue: Decimal,
    contingent_liabilities: Decimal,
    prev_contingent: Decimal | None,
    opinion: AuditOpinion,
    mdna: list[str],
    auditor: str,
) -> str:
    fy_label = f"FY{fy.period_end.year - 1}-{str(fy.period_end.year)[2:]}"
    parts = [
        f"{name} ({ticker})",
        f"Annual Report {fy_label}",
        "",
        "Management Discussion and Analysis",
        *mdna,
        PAGE,
        "Audited financial statements (Rs. in crore)",
        _pnl_table("Year", fy, prev_fy),
        "",
        _balance_sheet(fy.balance),
        "",
        _cash_flow(fy),
        PAGE,
        "Notes to the financial statements",
        f"Note 32 - Related party transactions: Sale of goods and services to related parties during the year amounted to Rs. {money(related_party_revenue)} crore, against total revenue from operations of Rs. {money(fy.revenue)} crore.",
        f"Note 35 - Contingent liabilities not provided for: Rs. {money(contingent_liabilities)} crore"
        + (
            f" (previous year Rs. {money(prev_contingent)} crore)."
            if prev_contingent is not None
            else "."
        ),
        f"Note 36 - Trade receivables as at {fdate(fy.period_end)} stood at Rs. {money(fy.balance.receivables)} crore.",
        PAGE,
        f"Independent Auditor's Report by {auditor}",
        _opinion_text(opinion),
        "",
        "This is a fictional mock document generated for SignalAlpha development.",
    ]
    return "\n".join(parts)


def board_meeting(name: str, meeting_date: date, period_end: date) -> str:
    return (
        f"{name}\nIntimation of Board Meeting under Regulation 29\n"
        f"A meeting of the Board of Directors of the Company will be held on {fdate(meeting_date)} "
        f"to consider and approve the financial results for the quarter ended {fdate(period_end)}.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def order_win(name: str, on: date, value_cr: Decimal, months: int, customer: str, item: str) -> str:
    return (
        f"{name}\nIntimation under Regulation 30 - Receipt of order\n"
        f"Date: {fdate(on)}\n"
        f"The Company has received an order worth Rs. {money(value_cr)} crore from {customer} for {item}. "
        f"The order is to be executed over {months} months. The order is domestic and no promoter or promoter group entity has any interest in the awarding entity.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def capacity_expansion(name: str, on: date, pct: int, capex_cr: Decimal) -> str:
    return (
        f"{name}\nIntimation under Regulation 30 - Capacity expansion\n"
        f"Date: {fdate(on)}\n"
        f"The Board has approved an expansion of manufacturing capacity by {pct}% at the existing facility "
        f"at an estimated capital outlay of Rs. {money(capex_cr)} crore, to be funded through internal accruals and term debt. "
        "Commercial production from the expanded capacity is expected within 15 months.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def pledge_event(
    name: str,
    on: date,
    holder: str,
    kind: str,
    pct_promoter: Decimal,
    pct_total: Decimal,
    shares: int,
) -> str:
    verb = {
        "release": "released from pledge",
        "creation": "pledged",
        "invocation": "invoked by the lender",
    }[kind]
    return (
        f"{name}\nDisclosure under Regulation 31(1)/(2) of SEBI (SAST) Regulations, 2011 - Pledge of shares\n"
        f"Date: {fdate(on)}\n"
        f"{shares} equity shares held by {holder} (promoter) were {verb} on {fdate(on)}, representing "
        f"{money(pct_promoter)}% of the promoter holding and {money(pct_total)}% of the total share capital.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def insider_trade(
    name: str, on: date, person: str, side: str, quantity: int, value_cr: Decimal, price: Decimal
) -> str:
    return (
        f"{name}\nDisclosure under Regulation 7(2) of SEBI (Prohibition of Insider Trading) Regulations, 2015\n"
        f"Date: {fdate(on)}\n"
        f"{person} (Promoter) has {'acquired' if side == 'buy' else 'disposed of'} {quantity} equity shares through market {'purchase' if side == 'buy' else 'sale'} "
        f"at an average price of Rs. {money(price)} per share, aggregating to Rs. {money(value_cr)} crore.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def rating_rationale(
    agency: str, name: str, action: str, rating: str, outlook: str, on: date, reason: str
) -> str:
    return (
        f"{agency}\nRating rationale - {name}\nDate: {fdate(on)}\n"
        f"{agency} has {action} the long-term bank facilities of {name} at {rating}; outlook {outlook}.\n"
        f"Rationale: {reason}\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def cfo_resignation(name: str, on: date, person: str) -> str:
    return (
        f"{name}\nIntimation under Regulation 30 - Resignation of Chief Financial Officer\n"
        f"Date: {fdate(on)}\n"
        f"{person} has tendered resignation from the position of Chief Financial Officer with effect from {fdate(on)}, citing personal reasons.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def auditor_change(name: str, on: date, old: str, new: str) -> str:
    return (
        f"{name}\nIntimation under Regulation 30 - Resignation of Statutory Auditor\n"
        f"Date: {fdate(on)}\n"
        f"{old}, Statutory Auditors, have resigned before completion of their term citing pre-occupation with other assignments. "
        f"The Board has appointed {new} as Statutory Auditors to fill the casual vacancy.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def fund_raise(name: str, on: date, amount_cr: Decimal, discount_pct: int, price: Decimal) -> str:
    return (
        f"{name}\nOutcome of Board Meeting - Preferential issue of warrants to promoters\n"
        f"Date: {fdate(on)}\n"
        f"The Board has approved the issue of convertible warrants to promoter group entities aggregating to Rs. {money(amount_cr)} crore "
        f"at a price of Rs. {money(price)} per warrant, which is at a discount of about {discount_pct}% to the current market price, subject to shareholder approval.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def dividend(name: str, on: date, per_share: Decimal, ex_date: date) -> str:
    return (
        f"{name}\nRecommendation of dividend\nDate: {fdate(on)}\n"
        f"The Board has recommended a final dividend of Rs. {money(per_share)} per equity share. Record date: {fdate(ex_date)}.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def bonus(name: str, on: date, ratio: int, ex_date: date) -> str:
    return (
        f"{name}\nOutcome of Board Meeting - Bonus issue\nDate: {fdate(on)}\n"
        f"The Board has approved a bonus issue of {ratio} equity share for every 1 equity share held. Record date: {fdate(ex_date)}.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def delisting_notice(name: str, on: date) -> str:
    return (
        f"Exchange notice - Compulsory delisting\nDate: {fdate(on)}\n"
        f"The equity shares of {name} stand compulsorily delisted with effect from {fdate(on)} for non-compliance with listing regulations.\n"
        "This is a fictional mock document generated for SignalAlpha development."
    )


def bhavcopy_csv(trade_date: date, rows: list[tuple[str, DailyBar]]) -> str:
    lines = [
        f"# Mock bhavcopy for {trade_date.isoformat()} (fictional)",
        "SYMBOL,OPEN,HIGH,LOW,CLOSE,VOLUME,TRADED_VALUE,DELIVERY_PCT",
    ]
    for ticker, b in rows:
        lines.append(
            f"{ticker},{money(b.open)},{money(b.high)},{money(b.low)},{money(b.close)},{b.volume},{money(b.traded_value)},{money(b.delivery_pct)}"
        )
    return "\n".join(lines)


def surveillance_csv(on: date, rows: list[tuple[str, str, str, int | None]]) -> str:
    lines = [
        f"# Mock surveillance list for {on.isoformat()} (fictional)",
        "SYMBOL,FRAMEWORK,EVENT,STAGE",
    ]
    lines += [f"{t},{fw},{ev},{st if st is not None else ''}" for t, fw, ev, st in rows]
    return "\n".join(lines)


def index_csv(index_name: str, effective_from: date, tickers: list[str]) -> str:
    lines = [
        f"# {index_name} constituents effective {effective_from.isoformat()} (fictional)",
        "SYMBOL",
    ]
    lines += tickers
    return "\n".join(lines)


def bulk_deal_csv(on: date, rows: list[tuple[str, str, str, int, Decimal]]) -> str:
    lines = [
        f"# Mock bulk deals for {on.isoformat()} (fictional)",
        "SYMBOL,CLIENT,SIDE,QUANTITY,PRICE",
    ]
    lines += [f"{t},{c},{s},{q},{money(p)}" for t, c, s, q, p in rows]
    return "\n".join(lines)
