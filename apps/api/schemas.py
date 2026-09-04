"""Response schemas. Every response is an :class:`Envelope` carrying ``as_of``, the dataset and
a data-quality summary (PRD §10)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SourceQuality(BaseModel):
    source: str
    last_success_at: datetime | None
    latest_public_at: datetime | None
    fetch_failure_count: int
    parse_failure_count: int


class DataQualitySummary(BaseModel):
    sources: list[SourceQuality]
    total_failures: int
    latest_public_at: datetime | None


class Envelope[T](BaseModel):
    as_of: datetime
    dataset: str
    data_quality: DataQualitySummary | None
    data: T


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_document_id: int
    document_text_id: int
    company_id: int
    filing_id: int | None
    source: str
    url: str | None
    public_at: datetime
    extracted_text: str
    char_start: int
    char_end: int
    page_number: int | None
    extraction_method: str
    confidence: Decimal
    created_by: str
    document_url: str


class HighlightOut(BaseModel):
    evidence_id: int
    char_start: int
    char_end: int
    page_number: int | None
    text: str


class DocumentOut(BaseModel):
    raw_document_id: int
    company_id: int | None
    source: str
    title: str | None
    public_at: datetime
    content_type: str
    parser_version: str
    text: str
    page_offsets: list[int]
    highlight: HighlightOut | None


# ------------------------------------------------------------------- paging
class Page[T](BaseModel):
    items: list[T]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------- companies
class ScoreBrief(BaseModel):
    opportunity: float | None
    inflection: float | None
    quality: float | None
    valuation: float | None
    risk: float | None
    attention_gap: float | None
    scores_as_of: datetime | None


class CompanyRow(BaseModel):
    id: int
    name: str
    ticker: str
    sector: str
    industry: str | None
    market_cap_cr: float | None
    listing_status: str
    is_illiquid: bool
    in_universe: bool
    gsm_stage: int | None
    asm_stage: int | None
    scores: ScoreBrief
    key_change: str | None
    strongest_positive: str | None
    strongest_negative: str | None
    new_signal_types: list[str]
    data_quality_failures: int


class CompanyProfile(CompanyRow):
    isin: str | None
    exchange: str
    bse_code: str | None
    listed_on: datetime | None
    delisted_on: datetime | None
    price: float | None
    price_date: datetime | None
    median_traded_value_30d: float | None


class FinancialRow(BaseModel):
    id: int
    filing_id: int
    raw_document_id: int
    period_end: datetime
    period_months: int
    consolidated: bool
    public_at: datetime
    extraction_method: str
    confidence: Decimal
    values: dict[str, Decimal | None]
    ratios: dict[str, float | None]
    audit_opinion: str | None


class ShareholdingOut(BaseModel):
    id: int
    filing_id: int
    period_end: datetime
    public_at: datetime
    promoter_pct: Decimal
    promoter_pledged_pct: Decimal
    fii_pct: Decimal
    dii_pct: Decimal
    public_pct: Decimal
    total_shareholders: int
    retail_shareholders: int
    holders: list[dict[str, str | Decimal]]


class EventOut(BaseModel):
    id: int
    table: str
    public_at: datetime
    raw_document_id: int
    fields: dict[str, str | int | float | None]


class OwnershipOut(BaseModel):
    shareholdings: list[ShareholdingOut]
    pledge_events: list[EventOut]
    insider_trades: list[EventOut]
    bulk_deals: list[EventOut]


class PriceRow(BaseModel):
    trade_date: datetime
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int
    traded_value: float
    delivery_pct: float | None


class SignalOut(BaseModel):
    id: int
    signal_type: str
    family: str
    direction: int
    magnitude: float
    public_at: datetime
    dedupe_key: str
    source_records: list[dict[str, object]]
    evidence_ids: list[int]
    parameters: dict[str, object]
    detector_version: str
    config_version: str
    active: bool
    performance: dict[str, object] | None


class ScoreOut(BaseModel):
    score_type: str
    value: float | None
    as_of: datetime
    config_version: str
    components: dict[str, object]
    signal_ids: list[int]


class ValuationOut(BaseModel):
    inputs: dict[str, float | None]
    scenarios: list[dict[str, object]]
    source: str
    agent_run_id: int | None
    spec: dict[str, object]


class AgentOutputOut(BaseModel):
    agent_run_id: int
    agent_name: str
    as_of: datetime
    model_id: str
    prompt_version: str
    validated: bool
    output: dict[str, object] | None


class ThesisOut(BaseModel):
    thesis: AgentOutputOut | None
    contradiction: AgentOutputOut | None
    evidence: list[EvidenceOut]
    message: str | None


class RunOut(BaseModel):
    id: str
    company_id: int
    as_of: datetime
    kind: str
    status: str
    steps: list[dict[str, object]]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class PerformanceRow(BaseModel):
    subject: str
    decile: int
    horizon_days: int
    n: int
    low_sample: bool
    stats: dict[str, object]


class PerformanceOut(BaseModel):
    backtest_run_id: int | None
    as_of: datetime | None
    config_version: str | None
    rows: list[PerformanceRow]


class DataQualityRow(BaseModel):
    company_id: int | None
    ticker: str | None
    source: str
    last_fetch_at: datetime | None
    last_success_at: datetime | None
    latest_public_at: datetime | None
    fetch_failure_count: int
    parse_failure_count: int
    last_error: str | None


# ------------------------------------------------------------------- the desk
class ReadinessCheckOut(BaseModel):
    key: str
    label: str
    passed: bool
    detail: str
    to_resolve: str
    critical: bool


class ReadinessOut(BaseModel):
    status: str
    headline: str
    checks: list[ReadinessCheckOut]


class DecisionOut(BaseModel):
    id: int
    company_id: int
    ticker: str
    name: str
    as_of: datetime
    verdict: str
    conviction: str | None
    reason: str
    review_trigger: str | None
    review_by: datetime | None
    created_at: datetime
    snapshot: dict[str, object]


class DecisionIn(BaseModel):
    verdict: str = Field(pattern="^(shortlist|track|needs_evidence|pass)$")
    reason: str = Field(min_length=3, max_length=2000)
    conviction: str | None = Field(default=None, pattern="^(low|medium|high)$")
    review_trigger: str | None = Field(default=None, max_length=500)
    review_by: date | None = None
    as_of: date | None = None


class DeskRow(BaseModel):
    company_id: int
    ticker: str
    name: str
    sector: str
    market_cap_cr: float | None
    change: str
    """One plain sentence: what changed, in the detector's own numbers."""
    change_at: datetime | None
    for_case: str
    against_case: str
    readiness: ReadinessOut
    scores: ScoreBrief
    base_rate: dict[str, object] | None
    signal_types: list[str]
    decision: DecisionOut | None


class BaseRateOut(BaseModel):
    signal_type: str
    horizon_days: int
    n: int
    low_sample: bool
    hit_rate: float | None
    mean_excess: float | None
    median_excess: float | None
    ci_low: float | None
    ci_high: float | None


class BreakCondition(BaseModel):
    text: str
    source: str


class BriefOut(BaseModel):
    company: CompanyProfile
    change: str
    change_at: datetime | None
    narrated_signals: list[dict[str, object]]
    readiness: ReadinessOut
    scores: list[ScoreOut]
    base_rates: list[BaseRateOut]
    liquidity: dict[str, object]
    valuation: ValuationOut | None
    thesis: ThesisOut
    forensic_flags: list[dict[str, object]]
    break_conditions: list[BreakCondition]
    evidence: list[EvidenceOut]
    decisions: list[DecisionOut]
    suggested_review_by: datetime


class AlertOut(BaseModel):
    decision: DecisionOut
    kind: str
    text: str
    at: datetime
