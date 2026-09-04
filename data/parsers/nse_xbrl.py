"""Ind-AS XBRL results parser (PRD §5.1 "XBRL where available").

NSE publishes one XBRL document per results filing. This parser reads the primary
(non-segmented) contexts, returns one record per reporting duration found, and leaves every
derived figure to Python: EBITDA is reconstructed from the reported lines as
``PBT + depreciation + finance cost - other income`` (PRD §2.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree as SafeET

PARSER_VERSION = "nse-xbrl-1"

#: Ind-AS element -> our column. Local names only; namespaces vary by filer.
FIELDS = {
    "RevenueFromOperations": "revenue",
    "OtherIncome": "other_income",
    "Expenses": "total_expenses",
    "DepreciationDepletionAndAmortisationExpense": "depreciation",
    "FinanceCosts": "finance_cost",
    "ProfitBeforeTax": "pbt",
    "TaxExpense": "tax",
    "ProfitLossForPeriod": "pat",
    "BasicEarningsLossPerShareFromContinuingOperations": "eps",
    "PaidUpValueOfEquityShareCapital": "paid_up_capital",
    "FaceValueOfEquityShareCapital": "face_value",
}
META = {
    "Symbol": "symbol",
    "NameOfTheCompany": "company_name",
    "NatureOfReportStandaloneConsolidated": "consolidated_flag",
    "ISIN": "isin",
}
CRORE = Decimal(10_000_000)


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class XbrlResult:
    symbol: str
    company_name: str
    isin: str | None
    consolidated: bool
    period_start: date
    period_end: date
    months: int
    #: Every figure in ₹ crore, as stored (PRD §5.2). ``None`` when the filer omitted it.
    revenue: Decimal | None
    other_income: Decimal | None
    total_expenses: Decimal | None
    ebitda: Decimal | None
    depreciation: Decimal | None
    finance_cost: Decimal | None
    pbt: Decimal | None
    tax: Decimal | None
    pat: Decimal | None
    eps: Decimal | None
    shares_outstanding_cr: Decimal | None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _dec(text: str | None) -> Decimal | None:
    if text is None or not text.strip():
        return None
    try:
        return Decimal(text.strip().replace(",", ""))
    except InvalidOperation:
        return None


def _months(start: date, end: date) -> int:
    days = (end - start).days + 1
    return max(1, round(days / 30.44))


def parse_results_xbrl(data: bytes) -> list[XbrlResult]:
    """Parse one filing into a record per reporting duration (quarter, half, year)."""
    try:
        root = SafeET.fromstring(data)
    except Exception as exc:
        raise ParseError(f"malformed XBRL: {exc}") from exc

    # Contexts without an explicit dimension are the primary (whole-entity) figures.
    contexts: dict[str, tuple[date, date]] = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context":
            continue
        cid = ctx.get("id")
        if cid is None or any(_local(e.tag) == "explicitMember" for e in ctx.iter()):
            continue
        start = end = None
        for child in ctx.iter():
            name, text = _local(child.tag), (child.text or "").strip()
            if name == "startDate":
                start = text
            elif name == "endDate":
                end = text
        if start and end:
            try:
                contexts[cid] = (date.fromisoformat(start), date.fromisoformat(end))
            except ValueError:
                continue
    if not contexts:
        raise ParseError("no primary reporting contexts in the document")

    meta: dict[str, str] = {}
    by_period: dict[tuple[date, date], dict[str, Decimal]] = {}
    for el in root.iter():
        name = _local(el.tag)
        if name in META and el.text and META[name] not in meta:
            meta[META[name]] = el.text.strip()
        if name not in FIELDS:
            continue
        period = contexts.get(el.get("contextRef") or "")
        value = _dec(el.text)
        if period is None or value is None:
            continue
        by_period.setdefault(period, {}).setdefault(FIELDS[name], value)

    symbol = meta.get("symbol", "").strip().upper()
    if not symbol:
        raise ParseError("filing has no Symbol element")
    consolidated = meta.get("consolidated_flag", "").strip().lower().startswith("cons")

    out: list[XbrlResult] = []
    for (start, end), vals in sorted(by_period.items()):
        # Per-share and capital figures are absolute; money lines are rupees -> ₹ crore.
        skip = ("eps", "face_value", "paid_up_capital")
        money = {k: (v / CRORE) for k, v in vals.items() if k not in skip}
        shares = None
        paid_up, face = vals.get("paid_up_capital"), vals.get("face_value")
        if paid_up and face and face > 0:
            shares = paid_up / face / CRORE
        ebitda = None
        if money.get("pbt") is not None:
            ebitda = (
                money["pbt"]
                + (money.get("depreciation") or Decimal(0))
                + (money.get("finance_cost") or Decimal(0))
                - (money.get("other_income") or Decimal(0))
            )
        out.append(
            XbrlResult(
                symbol=symbol,
                company_name=meta.get("company_name", symbol),
                isin=meta.get("isin"),
                consolidated=consolidated,
                period_start=start,
                period_end=end,
                months=_months(start, end),
                revenue=money.get("revenue"),
                other_income=money.get("other_income"),
                total_expenses=money.get("total_expenses"),
                ebitda=ebitda,
                depreciation=money.get("depreciation"),
                finance_cost=money.get("finance_cost"),
                pbt=money.get("pbt"),
                tax=money.get("tax"),
                pat=money.get("pat"),
                eps=vals.get("eps"),
                shares_outstanding_cr=shares,
            )
        )
    return out


@dataclass(frozen=True)
class ResultsFeedRow:
    symbol: str
    company_name: str
    isin: str | None
    consolidated: bool
    from_date: date
    to_date: date
    audited: str
    broadcast_at: datetime
    xbrl_url: str
    seq_number: str


def _feed_time(value: str) -> datetime:
    from zoneinfo import ZoneInfo

    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        except ValueError:
            continue
    raise ParseError(f"bad broadcast timestamp {value!r}")


def parse_results_feed(payload: object) -> list[ResultsFeedRow]:
    """Rows of the index-wide results feed that carry an XBRL link."""
    if not isinstance(payload, list):
        raise ParseError("results feed is not a list; the endpoint may have changed")
    out: list[ResultsFeedRow] = []
    for item in payload:
        if not isinstance(item, dict) or "symbol" not in item:
            continue
        xbrl = str(item.get("xbrl") or "").strip()
        if not xbrl.startswith("http"):
            continue
        try:
            from_date = datetime.strptime(str(item["fromDate"]).strip(), "%d-%b-%Y").date()
            to_date = datetime.strptime(str(item["toDate"]).strip(), "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        out.append(
            ResultsFeedRow(
                symbol=str(item["symbol"]).strip().upper(),
                company_name=str(item.get("companyName") or "").strip(),
                isin=(str(item.get("isin")).strip() or None) if item.get("isin") else None,
                consolidated=str(item.get("consolidated", "")).lower().startswith("cons"),
                from_date=from_date,
                to_date=to_date,
                audited=str(item.get("audited") or ""),
                broadcast_at=_feed_time(
                    str(item.get("broadCastDate") or item.get("filingDate") or "")
                ),
                xbrl_url=xbrl,
                seq_number=str(item.get("seqNumber") or ""),
            )
        )
    return out


NUMBER_ONLY = re.compile(r"^[\d.,\-]+$")
