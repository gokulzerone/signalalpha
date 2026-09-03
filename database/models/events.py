"""Announcements, credit ratings, corporate actions and surveillance events (PRD §5.1)."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, ProvenanceMixin


class AnnouncementCategory(enum.StrEnum):
    RESULTS = "results"
    ORDER_WIN = "order_win"
    CAPACITY_EXPANSION = "capacity_expansion"
    CREDIT_RATING = "credit_rating"
    BOARD_MEETING = "board_meeting"
    RESIGNATION = "resignation"
    AUDITOR_CHANGE = "auditor_change"
    FUND_RAISE = "fund_raise"
    PLEDGE = "pledge"
    CORPORATE_ACTION = "corporate_action"
    RELATED_PARTY = "related_party"
    OTHER = "other"


class Announcement(ProvenanceMixin, Base):
    __tablename__ = "announcements"
    __table_args__ = (Index("ix_announcements_company_public", "company_id", "public_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[AnnouncementCategory] = mapped_column(
        Enum(AnnouncementCategory, native_enum=False, length=24), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)


class RatingAction(enum.StrEnum):
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    REAFFIRMED = "reaffirmed"
    ASSIGNED = "assigned"
    WITHDRAWN = "withdrawn"


class CreditRating(ProvenanceMixin, Base):
    __tablename__ = "credit_ratings"
    __table_args__ = (Index("ix_credit_ratings_company_public", "company_id", "public_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agency: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument: Mapped[str] = mapped_column(String(128), nullable=False)
    rating: Mapped[str] = mapped_column(String(32), nullable=False)
    outlook: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[RatingAction] = mapped_column(
        Enum(RatingAction, native_enum=False, length=16), nullable=False
    )
    rating_date: Mapped[date] = mapped_column(nullable=False)


class CorporateActionType(enum.StrEnum):
    SPLIT = "split"
    BONUS = "bonus"
    RIGHTS = "rights"
    BUYBACK = "buyback"
    DIVIDEND = "dividend"
    NAME_CHANGE = "name_change"


class CorporateAction(ProvenanceMixin, Base):
    """``public_at`` is the announcement time; ``ex_date`` is stored separately (PRD §5.1)."""

    __tablename__ = "corporate_actions"
    __table_args__ = (Index("ix_corporate_actions_company_ex", "company_id", "ex_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    action_type: Mapped[CorporateActionType] = mapped_column(
        Enum(CorporateActionType, native_enum=False, length=16), nullable=False
    )
    ratio_numerator: Mapped[int | None] = mapped_column(Integer)
    ratio_denominator: Mapped[int | None] = mapped_column(Integer)
    amount_per_share: Mapped[Decimal | None]
    announced_at: Mapped[datetime] = mapped_column(nullable=False)
    ex_date: Mapped[date] = mapped_column(nullable=False)
    details: Mapped[str | None] = mapped_column(String(512))


class SurveillanceFramework(enum.StrEnum):
    GSM = "gsm"
    ASM = "asm"


class SurveillanceEventType(enum.StrEnum):
    ENTRY = "entry"
    EXIT = "exit"
    STAGE_CHANGE = "stage_change"


class SurveillanceEvent(ProvenanceMixin, Base):
    __tablename__ = "surveillance_events"
    __table_args__ = (Index("ix_surveillance_company_public", "company_id", "public_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    framework: Mapped[SurveillanceFramework] = mapped_column(
        Enum(SurveillanceFramework, native_enum=False, length=8), nullable=False
    )
    event: Mapped[SurveillanceEventType] = mapped_column(
        Enum(SurveillanceEventType, native_enum=False, length=16), nullable=False
    )
    stage: Mapped[int | None] = mapped_column(Integer)
    effective_date: Mapped[date] = mapped_column(nullable=False)
