// Server-side API client. The API key never reaches the browser: client components go
// through the /api proxy route, which adds it.
import "server-only";

const RAW_BASE = process.env.SIGNALALPHA_API_BASE ?? "http://localhost:8000";
const BASE = /^https?:\/\//.test(RAW_BASE) ? RAW_BASE : `http://${RAW_BASE}`;
const KEY = process.env.SIGNALALPHA_API_KEY ?? "";
export const DATASET = process.env.SIGNALALPHA_DATASET ?? "mock";

export type Envelope<T> = {
  as_of: string;
  dataset: string;
  data_quality: { sources: SourceQuality[]; total_failures: number; latest_public_at: string | null } | null;
  data: T;
};

export type SourceQuality = {
  source: string;
  last_success_at: string | null;
  latest_public_at: string | null;
  fetch_failure_count: number;
  parse_failure_count: number;
};

export type ScoreBrief = {
  opportunity: number | null;
  inflection: number | null;
  quality: number | null;
  valuation: number | null;
  risk: number | null;
  attention_gap: number | null;
  scores_as_of: string | null;
};

export type CompanyRow = {
  id: number;
  name: string;
  ticker: string;
  sector: string;
  industry: string | null;
  market_cap_cr: number | null;
  listing_status: string;
  is_illiquid: boolean;
  in_universe: boolean;
  gsm_stage: number | null;
  asm_stage: number | null;
  scores: ScoreBrief;
  key_change: string | null;
  strongest_positive: string | null;
  strongest_negative: string | null;
  new_signal_types: string[];
  data_quality_failures: number;
};

export type CompanyProfile = CompanyRow & {
  isin: string | null;
  exchange: string;
  price: number | null;
  price_date: string | null;
  median_traded_value_30d: number | null;
  delisted_on: string | null;
};

export type Page<T> = { items: T[]; page: number; page_size: number; total: number };

export type FinancialRow = {
  id: number;
  filing_id: number;
  raw_document_id: number;
  period_end: string;
  period_months: number;
  consolidated: boolean;
  public_at: string;
  values: Record<string, string | null>;
  ratios: Record<string, number | null>;
  audit_opinion: string | null;
};

export type Ownership = {
  shareholdings: {
    id: number; period_end: string; promoter_pct: string; promoter_pledged_pct: string; fii_pct: string; dii_pct: string;
    public_pct: string; total_shareholders: number; retail_shareholders: number; holders: { name: string; category: string; pct: string }[];
  }[];
  pledge_events: EventOut[];
  insider_trades: EventOut[];
  bulk_deals: EventOut[];
};
export type EventOut = { id: number; table: string; public_at: string; raw_document_id: number; fields: Record<string, string | number | null> };

export type PriceRow = { trade_date: string; close: number; adjusted_close: number; traded_value: number; delivery_pct: number | null };

export type SignalOut = {
  id: number; signal_type: string; family: string; direction: number; magnitude: number; public_at: string;
  source_records: Record<string, unknown>[]; evidence_ids: number[]; parameters: Record<string, unknown>; active: boolean;
  performance: { backtest_run_id: number; horizons: Record<string, Record<string, unknown>> } | null;
};

export type Component = { raw: number | null; percentile: number | null; weight: number; higher_is_better: boolean; contribution: number | null };
export type ScoreOut = { score_type: string; value: number | null; as_of: string; config_version: string; components: { components: Record<string, Component>; intermediates: Record<string, unknown> }; signal_ids: number[] };

export type Valuation = {
  inputs: Record<string, number | null>;
  scenarios: { name: string; assumptions: Record<string, number | string>; value_per_share: number; implied_change_vs_price: number; forward_revenue: number; forward_ebitda: number; enterprise_value: number; equity_value: number }[];
  source: string;
  spec: { steps: Record<string, string>[] };
};

export type Claim = { text: string; evidence_ids: number[]; quotes: { document_id: number; quote: string }[] };
export type AgentOutput = { agent_run_id: number; agent_name: string; as_of: string; model_id: string; prompt_version: string; validated: boolean; output: Record<string, unknown> | null };
export type Evidence = { id: number; raw_document_id: number; extracted_text: string; char_start: number; char_end: number; page_number: number | null; source: string; public_at: string; document_url: string; created_by: string };
export type Thesis = { thesis: AgentOutput | null; contradiction: AgentOutput | null; evidence: Evidence[]; message: string | null };
export type DocumentOut = { raw_document_id: number; title: string | null; source: string; public_at: string; text: string; page_offsets: number[]; highlight: { evidence_id: number; char_start: number; char_end: number; page_number: number | null } | null };
export type PerformanceRow = { subject: string; decile: number; horizon_days: number; n: number; low_sample: boolean; stats: Record<string, unknown> };
export type Performance = { backtest_run_id: number | null; as_of: string | null; config_version: string | null; rows: PerformanceRow[] };
export type DataQualityRow = { company_id: number | null; ticker: string | null; source: string; last_success_at: string | null; latest_public_at: string | null; fetch_failure_count: number; parse_failure_count: number; last_error: string | null };

export async function api<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<Envelope<T>> {
  const url = new URL(`/api/v1${path}`, BASE);
  url.searchParams.set("dataset", DATASET);
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  const res = await fetch(url, { headers: KEY ? { "X-API-Key": KEY } : {}, cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status} for ${url.pathname}: ${await res.text()}`);
  return (await res.json()) as Envelope<T>;
}

export async function apiOrNull<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<Envelope<T> | null> {
  try {
    return await api<T>(path, params);
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ the desk
export type ReadinessCheck = { key: string; label: string; passed: boolean; detail: string; to_resolve: string; critical: boolean };
export type Readiness = { status: "ready" | "partial" | "not_ready"; headline: string; checks: ReadinessCheck[] };
export type Decision = {
  id: number; company_id: number; ticker: string; name: string; as_of: string; verdict: string;
  conviction: string | null; reason: string; review_trigger: string | null; review_by: string | null;
  created_at: string; snapshot: Record<string, unknown>;
};
export type DeskRow = {
  company_id: number; ticker: string; name: string; sector: string; market_cap_cr: number | null;
  change: string; change_at: string | null; for_case: string; against_case: string;
  readiness: Readiness; scores: ScoreBrief; base_rate: Record<string, unknown> | null;
  signal_types: string[]; decision: Decision | null;
  opportunity_partial: boolean; opportunity_missing: string[];
};
export type DeskCoverage = {
  covered_companies: number; companies_with_signals: number; latest_signal_at: string | null;
  latest_fundamental_period_end: string | null; window_days: number; suggested_window_days: number | null;
  fundamentals_stale_days: number | null; suggested_as_of: string | null;
};
export type DeskResponse = { rows: DeskRow[]; coverage: DeskCoverage };
export type BaseRate = {
  signal_type: string; horizon_days: number; n: number; low_sample: boolean;
  hit_rate: number | null; mean_excess: number | null; median_excess: number | null; ci_low: number | null; ci_high: number | null;
};
export type NarratedSignal = {
  signal_id: number; signal_type: string; family: string; direction: number; magnitude: number;
  public_at: string; sentence: string; evidence_ids: number[]; document_ids: number[];
};
export type Liquidity = {
  adv_inr: number | null; participation_pct: number; comfortable_position_inr: number | null;
  days_to_exit: Record<string, number>; round_trip_cost_pct: number | null; illiquid: boolean;
};
export type Brief = {
  company: CompanyProfile; change: string; change_at: string | null; narrated_signals: NarratedSignal[];
  readiness: Readiness; scores: ScoreOut[]; base_rates: BaseRate[]; liquidity: Liquidity;
  valuation: Valuation | null; thesis: Thesis; forensic_flags: { signal_type: string; severity: string; mechanism: string; claims: Claim[] }[];
  break_conditions: { text: string; source: string }[]; evidence: Evidence[]; decisions: Decision[];
  suggested_review_by: string;
};
export type Alert = { decision: Decision; kind: string; text: string; at: string };
