"""Parser and deterministic classifier for the NSE corporate announcements JSON feed."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from database.models import AnnouncementCategory

PARSER_VERSION = "nse-ann-1"
IST = ZoneInfo("Asia/Kolkata")

CATEGORY_RULES: list[tuple[AnnouncementCategory, re.Pattern[str]]] = [
    (
        AnnouncementCategory.RESULTS,
        re.compile(r"financial results|unaudited results|audited results", re.I),
    ),
    (
        AnnouncementCategory.ORDER_WIN,
        re.compile(r"\border\b|\bcontract\b|letter of award|\bLoA\b|work order", re.I),
    ),
    (
        AnnouncementCategory.CAPACITY_EXPANSION,
        re.compile(r"capacity|expansion|new plant|commissioning", re.I),
    ),
    (
        AnnouncementCategory.CREDIT_RATING,
        re.compile(r"credit rating|rating action|CRISIL|ICRA|CARE Ratings|India Ratings", re.I),
    ),
    (AnnouncementCategory.AUDITOR_CHANGE, re.compile(r"auditor", re.I)),
    (AnnouncementCategory.RESIGNATION, re.compile(r"resignation|cessation|resigned", re.I)),
    (
        AnnouncementCategory.FUND_RAISE,
        re.compile(
            r"preferential|warrants?|QIP|qualified institutions|rights issue|fund rais", re.I
        ),
    ),
    (AnnouncementCategory.PLEDGE, re.compile(r"pledge|encumbrance|SAST", re.I)),
    (
        AnnouncementCategory.CORPORATE_ACTION,
        re.compile(r"dividend|bonus|split|buy ?back|record date", re.I),
    ),
    (AnnouncementCategory.BOARD_MEETING, re.compile(r"board meeting", re.I)),
    (AnnouncementCategory.RELATED_PARTY, re.compile(r"related party", re.I)),
]


def classify(subject: str, details: str = "") -> AnnouncementCategory:
    haystack = f"{subject} {details}"
    for category, pattern in CATEGORY_RULES:
        if pattern.search(haystack):
            return category
    return AnnouncementCategory.OTHER


@dataclass(frozen=True)
class AnnouncementRecord:
    symbol: str
    subject: str
    details: str
    category: AnnouncementCategory
    disseminated_at: datetime
    attachment_url: str | None
    attachment_text: str


class ParseError(ValueError):
    pass


def _parse_time(value: str) -> datetime:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    raise ParseError(f"bad timestamp {value!r}")


def parse_announcements(payload: str | list[dict[str, Any]]) -> list[AnnouncementRecord]:
    """Parse the feed from raw JSON text or from already-decoded items."""
    if isinstance(payload, str):
        try:
            raw: Any = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ParseError("feed is not JSON; the endpoint may have changed") from exc
    else:
        raw = payload
    items = raw if isinstance(raw, list) else raw.get("data", []) if isinstance(raw, dict) else None
    if items is None:
        raise ParseError("unexpected feed shape")
    out: list[AnnouncementRecord] = []
    for item in items:
        if not isinstance(item, dict) or "symbol" not in item or "an_dt" not in item:
            raise ParseError(
                "announcement item missing symbol/an_dt; the feed format may have changed"
            )
        subject = str(item.get("desc") or item.get("subject") or "").strip()
        details = str(item.get("attchmntText") or item.get("details") or "").strip()
        out.append(
            AnnouncementRecord(
                symbol=str(item["symbol"]).strip(),
                subject=subject,
                details=details,
                category=classify(subject, details),
                disseminated_at=_parse_time(str(item["an_dt"])),
                attachment_url=(str(item["attchmntFile"]).strip() or None)
                if item.get("attchmntFile")
                else None,
                attachment_text=details,
            )
        )
    return out


def render_announcement_text(rec: AnnouncementRecord) -> str:
    """Canonical text of the announcement metadata (stored as its own raw document)."""
    return (
        f"{rec.symbol}\n{rec.subject}\nDisseminated: {rec.disseminated_at.isoformat()}\n"
        f"Category: {rec.category.value}\n\n{rec.details}\n"
    )
