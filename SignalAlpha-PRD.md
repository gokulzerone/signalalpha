# SignalAlpha — Product Requirements Document

**Version:** 2.0 (revised)
**Status:** Draft for build
**Scope:** Indian listed small-cap and micro-cap companies (NSE and BSE)

---

## 1. What SignalAlpha is

SignalAlpha is a research terminal that surfaces **fundamental inflections** in Indian small-cap and micro-cap companies using only publicly available information, and presents each one as an evidence-backed thesis together with the strongest case against it.

It answers one question for the user: *"Which companies' businesses are changing in ways the market may not yet have priced, and what is the evidence for and against that?"*

It is **not** a stock-price prediction system, a recommendation engine, or a trading bot. Every output is a research aid for a human decision.

## 2. Non-negotiable principles

These apply to every module and every agent. A build that violates any of them is a failed build.

1. **Public information only.** The system must never obtain, solicit, infer from privileged access, or act on unpublished price-sensitive information (UPSI) as defined under SEBI (Prohibition of Insider Trading) Regulations, 2015. All inputs must be traceable to a public source with a publication timestamp.
2. **Evidence or nothing.** Every factual claim made by an AI component must reference at least one evidence record. Claims without evidence IDs are rejected at the schema level, not the prompt level (see §8).
3. **Deterministic arithmetic.** All financial calculations, ratios, growth rates, valuation math, and scores are computed in Python from structured data. LLMs never perform arithmetic. LLMs interpret documents, extract qualitative facts, identify relationships, generate hypotheses, and challenge them.
4. **No fabrication.** The system never generates synthetic market data, filings, or financial figures and presents them as real. Mock data used in development is clearly labelled as such in the database (`is_mock = true`) and is never mixed with live data.
5. **Point-in-time correctness.** Every data record carries the timestamp at which it became public. Any computation for a historical date uses only records public before that date. This governs both backtesting and the "as-of" views in the UI.
6. **Contradiction is mandatory.** No thesis is published without a completed contradiction analysis rendered alongside it.
7. **Explainability.** Every score exposes its inputs, weights, and intermediate values via the API. A score without a breakdown is a bug.

## 3. Users and use cases

**Primary user:** an individual or small-team fundamental investor who covers Indian small caps and currently reads filings manually.

**Core jobs to be done:**

- Each morning, see which companies in the universe had a material fundamental change disclosed in the last 1–7 days, ranked by opportunity and filtered by risk.
- For one company, get a complete picture in five minutes: trajectory of financials, promoter behaviour, order book, valuation scenarios, the thesis, the anti-thesis, and the evidence for both.
- Trust but verify: click any claim and land on the exact passage in the source document.
- Know whether the signals the system produces have historically meant anything (backtest results per signal type).

**Explicitly out of scope for v1:** portfolio management, order execution, brokerage integration, real-time tick data, derivatives, large caps, non-Indian markets, multi-tenant SaaS billing.

## 4. Universe definition

- **Exchanges:** NSE main board, BSE main board. SME platforms (NSE Emerge, BSE SME) are excluded in v1 due to data quality and liquidity.
- **Market cap band:** ₹100 crore to ₹5,000 crore, evaluated at the point-in-time date. Bounds are configuration, not code.
- **Liquidity floor:** 30-day median traded value ≥ ₹25 lakh/day. Companies below the floor remain in the database and are visible but flagged `illiquid` and excluded from backtests by default.
- **Survivorship:** the universe table is versioned by date. Companies that were later delisted, suspended, merged, or fell to zero remain in the historical universe for the dates they were listed. This is mandatory for backtesting (§11).
- **Exclusions:** companies under SEBI trading suspension, companies in the GSM/ASM surveillance frameworks are flagged, not removed, because entering or exiting those frameworks is itself a signal.

## 5. Data sources and ingestion contract

This is the hardest part of the system and is specified first. Each source has a contract: what it provides, how it is fetched, how records are versioned, and what the point-in-time timestamp is.

### 5.1 Source registry

| Source | Provides | Fetch method | Cadence | Point-in-time timestamp |
|---|---|---|---|---|
| NSE corporate announcements | Announcement PDFs and metadata (results, order wins, pledges, board meetings, credit ratings, resignations, fund raises) | Official announcement feed / archive endpoint | Every 15 min during market hours, hourly otherwise | Exchange dissemination timestamp |
| BSE corporate announcements | Same as above for BSE-only companies and cross-check | Official announcement archive | Same | Exchange dissemination timestamp |
| Quarterly / annual financial results | Standalone and consolidated P&L, balance sheet, cash flow (XBRL where available, PDF otherwise) | Announcement attachment | Per filing | Announcement timestamp |
| Shareholding pattern (Reg. 31) | Promoter / FII / DII / public holdings, promoter pledge, number of shareholders by category | Exchange filing | Quarterly | Filing timestamp |
| Promoter pledge / encumbrance (Reg. 31(1)/(2)) | Pledge creation, release, invocation | Exchange filing | Event-driven | Filing timestamp |
| Insider trading disclosures (Reg. 7 PIT) | Promoter and insider buys/sells | Exchange filing | Event-driven | Filing timestamp |
| Bulk and block deals | Large trades, counterparties | Exchange daily file | Daily | Publication timestamp (end of day) |
| Annual reports | MD&A, notes to accounts, related-party transactions, auditor report, contingent liabilities | Announcement attachment / company website | Annual | Announcement timestamp |
| Credit rating rationales | Rating actions and rationale documents (CRISIL, ICRA, CARE, India Ratings) | Rating agency public pages, referenced from exchange announcements | Event-driven | Rationale publication date |
| End-of-day prices and volumes | OHLCV, adjusted for corporate actions, delivery percentage | Exchange bhavcopy | Daily | Trading date end |
| Corporate actions | Splits, bonuses, rights, buybacks, dividends, name changes | Exchange | Event-driven | Ex-date and announcement date both stored |
| Surveillance lists | GSM / ASM stage entries and exits | Exchange daily list | Daily | Publication date |
| Index constituents | For benchmark (Nifty Smallcap 250, Nifty Microcap 250) with historical membership | Index provider public files | Monthly / on change | Effective date |

Sources not in this table (news, social media, third-party screeners) are **not** used in v1. They may be added later behind the same contract.

### 5.2 Ingestion rules

- **Raw first.** Every fetched document is stored verbatim in object storage before any parsing. Key: `raw/{source}/{company_id}/{yyyy}/{mm}/{sha256}.{ext}`. The SHA-256 is the document's identity; identical re-fetches are deduplicated.
- **Parsing is idempotent and versioned.** Each parser has a `parser_version`. Re-running a parser on the same raw document with the same version is a no-op. A new parser version produces new derived records linked to the same raw document; old ones are retained and marked superseded.
- **Restatements.** Financial figures are keyed by `(company_id, period, statement_type, consolidated_flag, filing_id)`. A later filing that restates a period creates a new row; it does not overwrite. Point-in-time queries return the latest filing whose `public_at` ≤ the as-of date.
- **PDF handling.** Text-layer PDFs are parsed directly. Scanned PDFs go through OCR; OCR output carries `extraction_method = 'ocr'` and lower default confidence. Tables in results filings are extracted to structured rows; the extraction stores the page number and bounding box for evidence linking.
- **Legal and ToS compliance.** Fetchers respect robots.txt and rate limits, identify themselves with a User-Agent, and cache aggressively. No credential-gated or paywalled sources in v1. If an exchange endpoint changes, the fetcher fails loudly and raises an alert rather than silently returning nothing.
- **Provenance on every row.** Every derived table row carries `raw_document_id`, `parser_version`, `public_at`, and `ingested_at`.
- **Failure modes are visible.** A `data_quality` table records per-company, per-source freshness and parse-failure counts, surfaced in the UI (§10) so users know when a company's picture is incomplete.

### 5.3 Mock data

- A mock data generator produces a fictional universe of ~40 companies, each with 12 quarters of internally consistent financials, shareholding patterns, announcements, prices, and a handful of designed inflection stories (an order-book surge, a promoter pledge unwind, a margin turnaround, a forensic red flag, a deceptive "growth" story driven by related-party revenue).
- Mock companies use obviously fictional names and ticker symbols prefixed `MOCK-`. Mock documents are generated text, stored through the same raw-document path so the evidence pipeline is exercised end to end.
- All mock rows carry `is_mock = true`. The API refuses to return mock and live data in the same response.

## 6. Signals

A signal is a **deterministic, timestamped, typed event** derived from structured data. Signals are the atomic unit the scores consume and the backtester evaluates. LLM agents may *propose* signals, but a proposed signal becomes real only after a deterministic validator confirms it against structured data or an evidence record.

### 6.1 Signal schema

```
signal_id, company_id, signal_type, direction (+1 / -1 / 0),
magnitude (normalised 0–1), public_at, detected_at,
source_records[] (FK to financials / holdings / announcements / prices),
evidence_ids[], parameters (JSON), validator_version
```

### 6.2 Signal catalogue (v1)

**Financial**

- `revenue_acceleration`: YoY revenue growth in the latest quarter exceeds the trailing-4-quarter average by ≥ X pp, on consolidated figures where available.
- `margin_inflection`: operating margin (EBITDA/revenue) changes by ≥ X bp vs the trailing-4-quarter average, sustained for 2 consecutive quarters.
- `operating_leverage`: EBITDA growth exceeds revenue growth by a configurable ratio for 2 consecutive quarters.
- `cash_conversion_improvement`: CFO / EBITDA (trailing 12 months) rises above a threshold after being below it.
- `working_capital_release`: receivable or inventory days fall by ≥ X days YoY.
- `deleveraging`: net debt / EBITDA falls below a threshold or net debt turns to net cash.
- `capex_cycle_start`: capex / depreciation exceeds a threshold for the first time in N quarters (interpreted with the Industry agent's context).

**Ownership**

- `promoter_stake_increase` / `promoter_stake_decrease`: change in promoter holding ≥ X pp quarter on quarter, or open-market insider purchases above a rupee threshold.
- `pledge_reduction` / `pledge_increase` / `pledge_invocation`.
- `institutional_entry`: first appearance of an FII/DII holding ≥ 1%, or a named institution in a bulk deal.
- `shareholder_count_spike`: retail shareholder count rising ≥ X% in a quarter (usually a negative signal — late retail entry).

**Business**

- `order_win`: announcement of an order or contract with a disclosed value ≥ X% of trailing-12-month revenue. Extracted by the Business agent, validated against the announcement text.
- `capacity_expansion`: announcement of new capacity with disclosed quantum.
- `credit_rating_upgrade` / `credit_rating_downgrade`.
- `key_person_exit`: resignation of CFO, auditor, or independent director (negative).
- `auditor_change`: (negative unless routine rotation).

**Market**

- `delivery_volume_shift`: 20-day average delivery percentage and traded value both rising above trailing 90-day levels.
- `surveillance_entry` / `surveillance_exit`: GSM/ASM framework changes.
- `price_lagging_fundamentals`: price change over 90 days below sector median while `revenue_acceleration` or `margin_inflection` is active.

**Forensic (all negative)**

- `related_party_revenue`: related-party sales ≥ X% of revenue (from annual report notes).
- `receivables_outrunning_revenue`: receivables growth exceeds revenue growth by a configurable margin for 2 consecutive years.
- `cash_vs_debt_anomaly`: large gross cash alongside rising short-term borrowings.
- `audit_qualification`: qualified opinion, emphasis of matter, or going-concern note.
- `contingent_liability_spike`.
- `frequent_fund_raise`: preferential issues or warrants to promoters at a discount, more than once in 2 years.

Every signal type has: a precise definition, thresholds in configuration, a unit test with a positive and negative example, and an entry in the signal performance table (§11).

## 7. Agents

Agents are LLM-driven workers with a fixed input contract, a strict JSON output schema, and a deterministic post-validator. Eight agents, down from nine: "Hidden Signal" is removed as undefined (anything it would have found is either a defined signal or a fabrication), and "Order Book" is renamed to the Business agent with a wider remit (see note below).

**Note on "order book":** in this product, order book means a company's *contractual order book* (orders won, backlog, execution timelines), which is a fundamental signal for capital goods, infrastructure, defence, EPC, and IT services small caps. It does **not** mean the exchange's bid/ask depth, which is not fundamental information and is not reliably available without paid feeds.

| Agent | Input | Output (JSON schema) | Validator |
|---|---|---|---|
| **Financial** | Structured financials (12 quarters), pre-computed ratios, results filing text | Narrative of trajectory; list of `proposed_signals`; list of `claims` each with `evidence_ids` | Every proposed signal must match a deterministic signal already computed, or be rejected; every numeric figure in narrative must match a structured value within rounding |
| **Promoter** | Shareholding history, pledge history, insider disclosures, bulk deals | Ownership narrative; `promoter_behaviour` classification (accumulating / stable / distributing / distressed); claims with evidence | Classification must be consistent with signal directions; no claims about intent without a disclosure citation |
| **Business** | Announcements (order wins, capacity, contracts), MD&A text, credit rating rationales | Order-book estimate with per-order evidence; capacity story; customer/segment concentration; claims with evidence | Every order value must be a verbatim span in an announcement; sum of orders must be arithmetically reproduced by Python from the extracted rows |
| **Industry** | Company's segment disclosures, peer financials (from the same database), rating rationales | Sector context; where the company sits vs peers on growth/margin/valuation; identified tailwinds and headwinds with evidence | Peer comparisons must reference peer `company_id`s in the database; no external market-size numbers without an evidence record |
| **Forensic** | Annual report notes, auditor report, related-party disclosures, cash-flow vs P&L | List of red flags each with severity, evidence, and the specific accounting mechanism suspected | Every flag must map to a forensic signal type or be labelled `unclassified` and shown separately |
| **Valuation** | Structured financials, price history, peer multiples, Business agent output | Three scenarios (bear / base / bull) with explicit assumptions; **no numbers computed by the LLM** — the agent outputs assumption *parameters* (growth, margin, exit multiple) and Python computes the scenario values | Scenario values are recomputed server-side; the LLM's assumption parameters must fall within configurable sanity bounds |
| **Contradiction** | All other agents' outputs, all negative signals, forensic flags | The strongest case against the thesis; specific claims it disputes; what evidence would resolve each dispute; `thesis_survives` (yes / weakened / no) | Must cite at least one negative signal or forensic flag if any exist; cannot be skipped |
| **Thesis** | All agent outputs including Contradiction | Structured thesis: `key_change`, `why_now`, `what_market_may_be_missing`, `strongest_positive`, `strongest_negative`, `what_would_break_this`, `time_horizon`, `confidence` (low / medium / high) | Cannot run until Contradiction has completed for this run; `strongest_negative` must reference the Contradiction output |

### 7.1 Agent runtime rules

- All agent calls use structured output (JSON schema enforced by the model API). Free-text responses are rejected.
- Every agent output is stored with `model_id`, `prompt_version`, `input_snapshot_hash`, and `run_id`. Re-running with identical inputs and versions returns the cached result.
- Agents receive point-in-time inputs. An agent run for as-of date D sees nothing with `public_at > D`.
- Agent prompts live in `/agents/prompts/` as versioned files, not inline strings.
- Token and cost per run are recorded. A per-company daily budget cap prevents runaway loops.
- Agents may not call external tools or the internet. All context comes from the database and object storage.

## 8. Evidence architecture

### 8.1 Evidence record

```
evidence_id, raw_document_id, company_id, source, url,
publication_date, filing_id (nullable),
extracted_text, char_start, char_end, page_number (nullable),
extraction_method (text | table | ocr | structured),
confidence (0–1), created_by (parser | agent:<name>), created_at
```

### 8.2 Validation rules (enforced in code, not prompts)

1. `extracted_text` **must be a verbatim substring** of the stored raw document's extracted text at `[char_start, char_end)`. The validator checks this on write. An LLM cannot create an evidence record by generating text; it can only *select* spans from documents it was given, and the span is verified.
2. Any agent claim whose `evidence_ids` array is empty is rejected. Any claim referencing an evidence ID that belongs to a different company or a document with `public_at` after the run's as-of date is rejected.
3. Evidence records are immutable. Corrections create new records.
4. The UI must be able to render any evidence record as a highlighted span in the original document (PDF viewer with page and highlight, or text viewer with offset).
5. Confidence is set by the parser for structured extractions (1.0 for XBRL, lower for OCR) and is never set by the LLM.

## 9. Scores

Five scores, down from nine. Each score is computed by a pure Python function with a signature `score(inputs: ScoreInputs, config: ScoreConfig, as_of: date) -> ScoreResult`, where `ScoreResult` contains the value, every component, every weight, and every intermediate value.

All scores are **cross-sectional percentiles (0–100) within the universe on the as-of date**, unless noted. This is a deliberate choice: it makes scores comparable over time and makes backtesting meaningful.

| Score | What it measures | Components (each a percentile before weighting) |
|---|---|---|
| **Inflection** | How much and how recently fundamentals are changing for the better | Sum of positive financial and business signal magnitudes in the last 2 quarters; recency-weighted (half-life 90 days); consistency bonus if ≥ 2 signal families agree |
| **Quality** | Whether the business and its accounting can be trusted | Trailing-3-year ROCE, CFO/EBITDA, receivable days trend, promoter holding level, absence of forensic flags (each forensic flag applies a multiplicative penalty defined in config) |
| **Valuation** | How cheap the company is relative to peers and its own history, given the inflection | EV/EBITDA and P/E vs sector median (point-in-time); vs own 3-year median; PEG-style adjustment using trailing growth only (no forecasts) |
| **Risk** | Probability that the thesis is wrong or the position is unsafe (higher = worse) | Forensic flag count and severity; pledge percentage; liquidity (traded value); surveillance status; negative ownership signals; audit qualification; key-person exits; volatility |
| **Attention gap** (replaces "Information Asymmetry") | How under-followed the company is, i.e., how plausible it is that a real change is unpriced | Absence of institutional holders; low delivery volume relative to market cap; days since last significant price move on a fundamental signal; filing complexity (length of notes relative to peers); price lag vs fundamentals (`price_lagging_fundamentals` signal) |

**Opportunity Score** is a derived composite: `Inflection × Quality × Valuation × AttentionGap`, geometrically combined, then multiplied by `(1 − Risk_penalty)` where `Risk_penalty` is a configured function of the Risk score. The multiplicative form is intentional: a company with a great inflection but a zero Quality score gets a zero Opportunity score. The weights and functional form are in `/scoring/config.yaml`, not in code, and the config version is stored with every score.

Every score run stores: `score_id, company_id, as_of, score_type, value, components (JSON), config_version, signal_ids[]`.

## 10. API

All endpoints are versioned under `/api/v1`. All responses include `as_of` and `data_quality` summary. All list endpoints paginate and support `as_of` to view any historical date.

**Companies**

- `GET /companies` — filter by market cap band, sector, liquidity, score ranges, surveillance flag
- `GET /companies/{id}` — profile, current price, market cap, data-quality status
- `GET /companies/{id}/financials?consolidated=true&periods=12` — structured statements and ratios with `filing_id` per row
- `GET /companies/{id}/ownership` — shareholding, pledge, insider trade history
- `GET /companies/{id}/prices?from=&to=` — adjusted OHLCV and delivery %
- `GET /companies/{id}/signals?as_of=` — active and historical signals
- `GET /companies/{id}/scores?as_of=` — all five scores plus Opportunity, with component breakdown
- `GET /companies/{id}/valuation` — scenarios with the assumption parameters and the Python-computed outputs
- `GET /companies/{id}/thesis` — latest thesis, its contradiction analysis, and both agents' evidence
- `GET /companies/{id}/evidence?ids=` — evidence records with document links and offsets
- `GET /companies/{id}/documents/{raw_document_id}?highlight=evidence_id` — serves the original document with a highlight target

**Discovery**

- `GET /discoveries/inflections?since=7d` — companies with new positive signals, ranked by Opportunity
- `GET /discoveries/attention-gap` — high Attention-gap × high Inflection
- `GET /discoveries/red-flags?since=7d` — new forensic or negative ownership signals (users need the bad news as much as the good)

**Research jobs** (all async; return a `run_id`, poll `GET /runs/{run_id}`)

- `POST /research/{company_id}` — full pipeline: refresh data → signals → all agents in dependency order → scores → thesis
- `POST /agents/{agent_name}/{company_id}?as_of=` — run one agent (Contradiction and Thesis enforce their prerequisites)

**System**

- `GET /data-quality` — per-source freshness and failure counts
- `GET /signals/performance` — backtest statistics per signal type (§11)
- `GET /health`

Authentication is a single API key in v1. Rate limiting per key.

## 11. Backtesting

The backtester exists to answer: *"Do these signals and scores carry information about forward fundamentals and returns, or not?"* It runs before the UI is built, because there is no point rendering scores that don't work.

**Rules**

- **No look-ahead.** For every historical date D, the backtester reconstructs signals and scores using only rows with `public_at ≤ D`. This is enforced by the point-in-time query layer, not by the backtester's discipline. A test asserts that querying with `as_of = D` never returns a row with `public_at > D`.
- **No survivorship bias.** The universe on date D is the versioned universe table for D, including companies later delisted or suspended. Delisted companies are assigned a configurable terminal return (default −100% for compulsory delisting, last traded price for voluntary).
- **Realistic execution.** Entry at next-day open after the signal's `public_at`; transaction cost and slippage model calibrated to traded value (illiquid names get wider assumed spreads); position size capped at a percentage of average daily traded value.
- **Reporting lag realism.** Signals derived from quarterly filings become active on the filing's `public_at`, not the period end.

**Outputs, per signal type and per score decile**

- Forward returns at 30 / 90 / 180 / 365 days, absolute and relative to Nifty Smallcap 250 and Nifty Microcap 250 (historical constituents)
- Hit rate (fraction beating benchmark), median and mean excess return, information coefficient
- Volatility, Sharpe, Sortino, maximum drawdown of an equal-weight portfolio rebalanced on signal events
- Turnover and cost drag
- Decay curve: how excess return evolves with holding period
- Sample size and confidence interval; results with n < 30 are shown greyed with a warning

All results are stored in `signal_performance` and `score_performance` tables keyed by `(signal_type | score_type, decile, horizon, backtest_run_id, config_version)` and served in the UI next to the signal they describe.

## 12. UI

Research-terminal style: dense, keyboard-navigable, dark theme default, tabular where possible, charts where trajectory matters.

### 12.1 Dashboard (`/`)

- **Today's inflections:** companies with new positive signals in the selected window (default 7 days), one row each: name, sector, market cap, Opportunity, Attention gap, Risk, key change (one line from the thesis), strongest positive, strongest negative, data-quality indicator.
- **Red flags:** new negative signals in the same window, same row format.
- Filters: market cap band, sector, Opportunity range, Risk range, Attention-gap range, liquidity floor, signal type, surveillance status.
- Sort by any column. Row click opens the company page. Column hover on any score shows the component breakdown.

### 12.2 Company page (`/companies/{id}`)

Sections, in order:

1. **Header:** price, market cap, sector, liquidity, surveillance flags, data-quality status, as-of date selector (view the page as it would have looked on any past date).
2. **Scores strip:** the five scores and Opportunity, each expandable to its component table.
3. **Financial trajectory:** 12-quarter revenue, EBITDA, margin, CFO charts; ratio table; each figure links to its filing.
4. **Ownership trajectory:** promoter holding and pledge over time; insider trades; institutional entries; bulk deals.
5. **Business:** order book table with per-order evidence links; capacity timeline; rating history.
6. **Signals:** active signals with direction, magnitude, date, and each one's historical performance stats.
7. **Valuation scenarios:** bear / base / bull with assumption parameters visible and editable (client-side recomputation using the same formulas, served as a JSON spec so the frontend cannot drift from the backend).
8. **Thesis and contradiction:** side by side, never one without the other. Every claim is a link to its evidence.
9. **Forensic flags:** each with mechanism, severity, evidence.
10. **Evidence viewer:** document list; clicking any evidence link opens the source document scrolled to and highlighting the cited span.

### 12.3 Signal performance page (`/signals`)

Table of every signal type with its backtest statistics, sample size, and decay chart.

### 12.4 Data quality page (`/data`)

Per-source freshness, failure counts, and per-company coverage gaps.

## 13. Architecture

**Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, Recharts. Server components for data-heavy pages; client components for filters and the scenario editor.

**Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2. Strict typing (`mypy --strict`), `ruff` for lint.

**Database:** PostgreSQL 16 with `pgvector` for document-chunk embeddings used in agent context retrieval. Point-in-time queries are implemented as SQL views/functions that take `as_of` so every consumer shares one implementation.

**Workers:** Celery on Redis. Queues: `ingest`, `parse`, `signals`, `agents`, `scores`, `backtest`. Agent tasks are idempotent by `(agent, company_id, as_of, prompt_version, input_hash)`.

**Storage:** S3-compatible object storage (MinIO locally) for raw documents and parsed text.

**LLM layer:** a thin provider-agnostic client with structured-output enforcement, retries, cost accounting, and prompt versioning. No agent framework dependency that hides the prompt or the schema.

**Repository layout**

```
/apps/web            Next.js frontend
/apps/api            FastAPI application, routers, schemas
/database            SQLAlchemy models, Alembic migrations, point-in-time SQL
/data                Source fetchers, parsers, mock data generator
/pipelines           Celery tasks and orchestration (ingest → parse → signals → agents → scores)
/signals             Signal definitions, validators, catalogue config
/agents              Agent implementations, JSON schemas, versioned prompts, post-validators
/scoring             Score functions and config.yaml
/backtesting         Point-in-time simulator, execution model, performance tables
/evidence            Evidence record creation and span validation
/tests               Unit, property-based, and integration tests
/docs                Architecture, data contracts, signal definitions, runbooks
/infra               docker-compose for local (Postgres, Redis, MinIO), CI config
```

## 14. Testing requirements

- **Every financial calculation and score function** has unit tests with hand-verified expected values, including edge cases (negative EBITDA, zero revenue, missing quarters, restated periods).
- **Property-based tests** for scores: percentile outputs are in [0, 100]; monotonicity where it should hold (more positive signals never lower Inflection); Opportunity is zero whenever any multiplicative component is zero.
- **Point-in-time tests:** for randomly sampled `as_of` dates, no query returns a row with `public_at > as_of`.
- **Evidence tests:** an evidence record whose text is not a verbatim span of its document is rejected; an agent claim without evidence is rejected; an agent claim citing another company's evidence is rejected.
- **Signal tests:** each signal type has at least one positive and one negative fixture built from mock data.
- **Backtest tests:** a synthetic universe with a known planted effect recovers that effect; a universe with no effect produces statistics consistent with zero.
- **Agent contract tests:** each agent's output is validated against its JSON schema and post-validator using recorded fixtures, without calling a live model in CI.
- **Parser tests:** golden files for each filing format handled in v1.
- CI runs the full suite against the mock universe. The application must boot and render the dashboard end-to-end with mock data and no network access.

## 15. Build order

1. **Database and point-in-time layer.** Models, migrations, versioned universe, the `as_of` query functions, and their tests.
2. **Mock data generator.** Fictional universe with planted stories, flowing through the raw-document path.
3. **Evidence module.** Record schema, span validation, document viewer endpoint.
4. **Signals.** Catalogue, deterministic detectors, validators, tests against mock data.
5. **Scores.** Five scores plus Opportunity, config-driven, fully tested.
6. **Backtesting.** Simulator and performance tables, verified against the planted mock effects.
7. **API.** All read endpoints over the above.
8. **Agents.** Financial → Promoter → Business → Industry → Forensic → Valuation → Contradiction → Thesis, each with schema, validator, fixtures.
9. **UI.** Dashboard, company page, signal performance, data quality.
10. **Live ingestion.** One source at a time, starting with EOD prices and NSE announcements, each behind a feature flag, with the data-quality page reporting coverage as it grows.

Rationale for the change from the original order: signals, scores, and backtesting come before the API and UI so that what gets rendered has already been shown to carry information. Live ingestion is last because it is the slowest and least predictable work, and everything else can be built and validated against the mock universe.

## 16. Compliance and disclosure

- The product presents **research**, not recommendations. Nothing in the UI or API uses the words "buy", "sell", "target price", or "recommendation". Scores are labelled as research rankings.
- A persistent disclaimer states that the system uses public information only, that outputs may contain errors, that past signal performance is not indicative of future returns, and that nothing constitutes investment advice.
- If the product is ever offered to third parties in India, it must be reviewed against SEBI (Research Analysts) Regulations, 2014 and SEBI (Investment Advisers) Regulations, 2013 before launch. This is a legal decision, not an engineering one, and is flagged here so it is not discovered late.
- Ingestion respects each source's terms of use. A `SOURCES.md` in `/docs` records, per source, the URL, the access method, the terms relied on, and the date last reviewed.
- No user trading data, portfolio data, or brokerage credentials are stored in v1.

## 17. Definition of done for v1

- `docker compose up` boots the whole stack with mock data and no external network.
- Dashboard shows the planted inflection stories ranked sensibly; the planted deceptive-growth story has a high Risk score and low Opportunity score; the forensic story shows its flags.
- Every claim on every mock company page links to a highlighted span in a stored document.
- Backtest on the mock universe recovers the planted effects and reports zero-effect statistics for the control group.
- Test suite passes in CI; coverage on `/scoring`, `/signals`, `/evidence`, `/backtesting` ≥ 90%.
- At least two live sources (EOD prices, NSE announcements) run behind feature flags against a small real universe, with the data-quality page reporting their status.

## 18. Open questions

- Which market-cap and liquidity bounds define the initial live universe (§4 defaults are placeholders).
- Whether to include SME platforms in a later version; their data quality is materially worse.
- Which LLM provider(s) to support first; the abstraction should make this swappable.
- Whether Industry agent peer sets are hand-curated or derived from segment disclosures; v1 should start hand-curated for the pilot universe.
