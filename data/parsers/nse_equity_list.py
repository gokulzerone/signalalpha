"""Parser for NSE's list of listed equities (``EQUITY_L.csv``)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

PARSER_VERSION = "nse-equity-list-1"


@dataclass(frozen=True)
class ListedEquity:
    symbol: str
    name: str
    series: str
    isin: str
    face_value: float
    listed_on: str


class ParseError(ValueError):
    pass


def parse_equity_list(text: str) -> list[ListedEquity]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ParseError("empty equity list")
    fields = {f.strip(): f for f in reader.fieldnames}
    required = ("SYMBOL", "NAME OF COMPANY", "SERIES", "ISIN NUMBER")
    missing = [f for f in required if f not in fields]
    if missing:
        raise ParseError(f"missing columns {missing}; the equity list format may have changed")
    out: list[ListedEquity] = []
    for row in reader:

        def get(key: str, row: dict[str, str | None] = row) -> str:
            return (row.get(fields[key]) or "").strip()

        if get("SERIES") != "EQ":
            continue
        listed = get("DATE OF LISTING") if "DATE OF LISTING" in fields else ""
        try:
            listed_iso = datetime.strptime(listed, "%d-%b-%Y").date().isoformat() if listed else ""
        except ValueError:
            listed_iso = ""
        try:
            face = float(get("FACE VALUE") or 0) if "FACE VALUE" in fields else 0.0
        except ValueError:
            face = 0.0
        out.append(
            ListedEquity(
                symbol=get("SYMBOL"),
                name=get("NAME OF COMPANY"),
                series=get("SERIES"),
                isin=get("ISIN NUMBER"),
                face_value=face,
                listed_on=listed_iso,
            )
        )
    return out
