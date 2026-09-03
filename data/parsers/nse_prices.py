"""Parser for the NSE security-wise bhav data CSV (``sec_bhavdata_full_DDMMYYYY.csv``)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

PARSER_VERSION = "nse-secbhav-1"


@dataclass(frozen=True)
class PriceRecord:
    symbol: str
    series: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    traded_value: Decimal
    delivery_pct: Decimal | None


class ParseError(ValueError):
    pass


def _dec(value: str) -> Decimal:
    try:
        return Decimal(value.strip().replace(",", ""))
    except InvalidOperation as exc:
        raise ParseError(f"bad number {value!r}") from exc


def parse_sec_bhavdata(text: str, series: tuple[str, ...] = ("EQ", "BE")) -> list[PriceRecord]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ParseError("empty file")
    fields = {f.strip(): f for f in reader.fieldnames}
    required = (
        "SYMBOL",
        "SERIES",
        "DATE1",
        "OPEN_PRICE",
        "HIGH_PRICE",
        "LOW_PRICE",
        "CLOSE_PRICE",
        "TTL_TRD_QNTY",
        "TURNOVER_LACS",
        "DELIV_PER",
    )
    missing = [f for f in required if f not in fields]
    if missing:
        raise ParseError(f"missing columns {missing}; the source format may have changed")
    out: list[PriceRecord] = []
    for row in reader:

        def get(k: str, row: dict[str, str | None] = row) -> str:
            return (row.get(fields[k]) or "").strip()

        if get("SERIES") not in series:
            continue
        try:
            trade_date = datetime.strptime(get("DATE1"), "%d-%b-%Y").date()
        except ValueError as exc:
            raise ParseError(f"bad date {get('DATE1')!r}") from exc
        deliv = get("DELIV_PER")
        out.append(
            PriceRecord(
                symbol=get("SYMBOL"),
                series=get("SERIES"),
                trade_date=trade_date,
                open=_dec(get("OPEN_PRICE")),
                high=_dec(get("HIGH_PRICE")),
                low=_dec(get("LOW_PRICE")),
                close=_dec(get("CLOSE_PRICE")),
                volume=int(_dec(get("TTL_TRD_QNTY"))),
                traded_value=_dec(get("TURNOVER_LACS")) * Decimal(100_000),
                delivery_pct=None if deliv in ("", "-") else _dec(deliv),
            )
        )
    return out
