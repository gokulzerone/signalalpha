"""All ORM models. Import this module to register every table on ``Base.metadata``."""

from database.models.base import (
    Base,
    CompanyScopedMixin,
    ExtractionMethod,
    MockFlagMixin,
    ProvenanceMixin,
    PublicAtMixin,
    Source,
)
from database.models.company import (
    Company,
    DelistingKind,
    Exchange,
    ListingStatus,
    UniverseSnapshot,
)
from database.models.documents import DocumentText, Filing, FilingType, RawDocument
from database.models.events import (
    Announcement,
    AnnouncementCategory,
    CorporateAction,
    CorporateActionType,
    CreditRating,
    RatingAction,
    SurveillanceEvent,
    SurveillanceEventType,
    SurveillanceFramework,
)
from database.models.evidence import AGENT_CREATOR_PREFIX, PARSER_CREATOR, Evidence
from database.models.financials import AuditOpinion, Financial
from database.models.market import IndexConstituent, Price
from database.models.ownership import (
    BulkDeal,
    DealType,
    HolderCategory,
    InsiderTrade,
    InstitutionalHolding,
    PersonCategory,
    PledgeEvent,
    PledgeEventType,
    Shareholding,
    TradeMode,
    TradeSide,
)
from database.models.quality import DataQuality
from database.models.scores import Score
from database.models.signals import Signal

#: Every model that carries ``public_at`` and is therefore subject to point-in-time filtering.
POINT_IN_TIME_MODELS: tuple[type[PublicAtMixin], ...] = (
    RawDocument,
    Filing,
    Financial,
    Shareholding,
    PledgeEvent,
    InsiderTrade,
    BulkDeal,
    Announcement,
    CreditRating,
    CorporateAction,
    SurveillanceEvent,
    Price,
    IndexConstituent,
    Evidence,
    Signal,
)

__all__ = [
    "AGENT_CREATOR_PREFIX",
    "PARSER_CREATOR",
    "POINT_IN_TIME_MODELS",
    "Announcement",
    "AnnouncementCategory",
    "AuditOpinion",
    "Base",
    "BulkDeal",
    "Company",
    "CompanyScopedMixin",
    "CorporateAction",
    "CorporateActionType",
    "CreditRating",
    "DataQuality",
    "DealType",
    "DelistingKind",
    "DocumentText",
    "Evidence",
    "Exchange",
    "ExtractionMethod",
    "Filing",
    "FilingType",
    "Financial",
    "HolderCategory",
    "IndexConstituent",
    "InsiderTrade",
    "InstitutionalHolding",
    "ListingStatus",
    "MockFlagMixin",
    "PersonCategory",
    "PledgeEvent",
    "PledgeEventType",
    "Price",
    "ProvenanceMixin",
    "PublicAtMixin",
    "RatingAction",
    "RawDocument",
    "Score",
    "Shareholding",
    "Signal",
    "Source",
    "SurveillanceEvent",
    "SurveillanceEventType",
    "SurveillanceFramework",
    "TradeMode",
    "TradeSide",
    "UniverseSnapshot",
]
