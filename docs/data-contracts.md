# Data contracts (build step 1)

This document records the decisions behind the database layer that are not obvious from the
code. The PRD (§5, §8, §11) is the authority; this is the implementation record.

## Point-in-time semantics

* Every point-in-time table carries `public_at` (timestamptz). It is the instant at which the
  record became public (exchange dissemination time, filing time, or end of trading day).
* `as_of` values are timezone-aware instants. A bare **date** `D` passed as `as_of` means
  **23:59:59.999999 IST on D**: everything published on day D is visible, nothing later.
  For a backtest with entry at the next day's open this is the correct boundary (PRD §11).
* All reads go through `database.pit.PointInTimeSession`, which wraps the SQL functions in
  `database/sql/pit_functions_v1.sql`. The functions are versioned; a change to semantics is
  a new file and a new migration, never an edit.
* Prices are published at 18:00 IST on the trade date (bhavcopy publication) in the mock
  universe; live fetchers must record the actual publication time.

## Mock isolation

* Every table (except child tables `document_texts` and `institutional_holdings`, which
  inherit status from their parent) has `is_mock`.
* `PointInTimeSession` is constructed with `is_mock` and filters every query by it.
* A check constraint on `companies` enforces that mock tickers start with `MOCK-` and live
  tickers never do.

## Restatements and re-parses

* `financials` and `shareholdings` are keyed by
  `(company_id, period_end, period_months, consolidated, filing_id, parser_version)`.
  A restating filing is a new `filing_id` and a new row. A re-parse with a new
  `parser_version` is a new row and the old one gets `is_superseded = true`.
* The point-in-time functions return, per period, the row from the latest filing public at
  `as_of` (`ORDER BY public_at DESC, filing_id DESC`), excluding superseded rows.

## Deviations from the PRD wording

* PRD §5.2 keys financial figures by `statement_type`. The implementation stores one **wide**
  row per period holding P&L, balance-sheet, cash-flow and note items together, because
  Indian quarterly filings publish P&L quarterly and balance sheet / cash flow half-yearly,
  and the signal detectors need typed columns rather than a line-item table. The uniqueness
  guarantees are the same.
* PRD §13 puts parsed text in object storage. Extracted text is stored in `document_texts`
  in PostgreSQL (raw bytes stay in object storage) so that evidence-span validation (§8.2) is
  a single indexed lookup. Object storage for raw bytes is introduced in step 2.
* Prices are stored **unadjusted**. Adjustment for splits/bonuses is applied at query time
  from `corporate_actions` rows public at `as_of`, so an adjusted series is itself
  point-in-time correct.

## Universe versioning

`universe_snapshots` holds one row per company per snapshot date with market cap, liquidity,
listing status, surveillance stage and the `in_universe` decision (with `config_version`).
The universe on date D is each company's latest snapshot dated on or before D. Delisting,
suspension and merger create a snapshot with the new status, so the historical universe has
no survivorship bias.

## Evidence (build step 3)

* `evidence` rows are verbatim spans `[char_start, char_end)` of one `document_texts` row
  (`document_text_id` pins the parser version). `public_at` equals the document's
  publication instant (the PRD's `publication_date`).
* A `BEFORE INSERT` trigger re-checks the span against the stored text, the document
  ownership and `public_at`; a `BEFORE UPDATE` trigger makes rows immutable. Deleting is
  allowed only so that a mock dataset can be regenerated.
* `confidence` defaults by extraction method (structured 1.0, table 0.95, text 0.9, OCR 0.6)
  and can only be overridden by `created_by = 'parser'`.
* Claims are validated by `evidence.claims.validate_claims`: non-empty `evidence_ids` is a
  schema rule (Pydantic), and every id must belong to the claim's company, the same dataset,
  and be public at the run's `as_of`.
* `evidence.viewer.document_view` returns the document text with page offsets and the
  highlighted span for the UI; the API serves it at
  `GET /api/v1/companies/{id}/documents/{raw_document_id}?highlight={evidence_id}`.

## Signals (build step 4)

* `signals/catalogue.yaml` holds every threshold and the `config_version` stamped on each
  signal. `signals/detectors/` holds one pure function per catalogue entry, operating on a
  `DetectionContext` (plain dataclasses), so detectors are unit-tested without a database.
* The runner (`signals/runner.py`) evaluates each company at every instant a record became
  public (plus a weekly cadence for price-derived signals). At instant `T` it materialises
  the state visible at `T` (re-resolving restatements with the same rule as the SQL
  functions; a test asserts equivalence) and keeps only candidates whose `public_at == T`.
  A signal therefore never depends on later data, and its timestamp is the filing's.
* Signals are idempotent on `(company, signal_type, dedupe_key)`; re-running the detector
  creates nothing new. `source_records` lists the rows the signal was computed from and
  `parameters` exposes every intermediate value (PRD §2.7).
* Business signals extract order values and capacity quanta from the announcement text with
  deterministic regexes and store the quoted span as parser evidence; the sum-of-orders
  arithmetic for the Business agent (step 8) reuses these rows.
* Agent-proposed signals go through `signals/validators.py`: a proposal is accepted only if a
  deterministic signal of that type already exists for the company (matched by `dedupe_key`
  or by `public_at` within a day). Nothing an agent says can create a signal.

## Scores (build step 5)

* `scoring/config.yaml` carries every weight, window, forensic penalty and the Opportunity
  form; its `version` is stored on every score row.
* `scoring/inputs.py` computes every raw metric in Python from point-in-time data (reusing
  the signal `DetectionContext`), including each company's own 3-year monthly valuation
  history using only data public at each month.
* `scoring/scores.py` ranks metrics as cross-sectional percentiles within the companies
  that are `in_universe` on the as-of date (listed and inside the cap band; illiquid names
  are included and flagged). Missing components are dropped and weights renormalised, and
  every `ScoreResult` exposes raw value, percentile, weight and contribution per component.
* Quality is multiplied by a per-flag penalty for each active forensic signal (365-day
  window). Risk is "higher = worse". Opportunity is the weighted geometric mean of the four
  other scores times `1 - risk_penalty(Risk)`, and is zero when any of the four is zero or
  missing (a loss-making company with no valuation multiple therefore scores zero; this is
  the PRD's multiplicative form applied literally).

## Backtesting (build step 6)

* `backtesting/config.yaml`: horizons, benchmark index per dataset, execution model
  (one-way base cost plus slippage `k / sqrt(ADV in ₹ crore)` clipped to a band, position cap
  as a percentage of ADV, portfolio capital), terminal returns for delistings, minimum
  sample size.
* Entry is the first trading day's open after the event's `public_at` date; exit is the
  close on the first trading day at or after entry plus the horizon. A window that ends
  after the run's `as_of` is discarded (never truncated), so nothing after `as_of` leaks.
* Returns are adjusted for bonuses and splits whose ex-date falls inside the window
  (dividends are not added; documented simplification). A company compulsorily delisted
  inside the window earns the configured terminal return (default −100%); a voluntary
  delisting earns its last traded price.
* Eligibility uses the versioned universe on the event date (listed, in the cap band) and
  excludes illiquid names unless configured otherwise.
* Benchmark return over a window is the equal-weight return of the index's constituents
  as of the entry date (historical membership), each with the same execution convention.
* Per group (signal type, or score type and decile) and horizon: n, hit rate, mean and
  median excess, 95% CI, Spearman information coefficient (signals: magnitude vs excess),
  and an equal-weight event portfolio (weights capped by the liquidity cap, rebalanced daily
  across open positions) giving volatility, Sharpe, Sortino, max drawdown, turnover and
  cost drag. `decay` holds the mean excess at every horizon. Rows with n below the minimum
  sample are flagged `low_sample`.
* Score deciles are recomputed at each rebalance date from data public at that date
  (`compute_universe_inputs` + `score_universe`), never read from stored scores.

## API (build step 7)

* Every endpoint is under `/api/v1`, behind a single `X-API-Key` (disabled when the key is
  unset, development only). Every response is an envelope with `as_of`, `dataset` and a
  `data_quality` summary. `dataset=mock|live` selects one dataset per request; mock and live
  rows are never mixed.
* `as_of` accepts `YYYY-MM-DD` (end of that day IST) or an ISO instant with an offset; naive
  datetimes are rejected. List endpoints paginate (`page`, `page_size`, `total`).
* Company rows for the dashboard carry the six scores, the latest thesis lines when a
  validated thesis exists, and otherwise the strongest positive/negative signal in the window.
* `GET /companies/{id}/valuation` serves three scenarios computed in Python from assumption
  parameters (agent-supplied when a validated Valuation run exists, otherwise defaults around
  trailing values, flagged `source`), plus the formula spec the frontend recomputes with.
* `GET /companies/{id}/thesis` serves a thesis only together with its contradiction analysis;
  until step 8 it returns an explanatory message.
* Research jobs (`POST /research/{id}`, `POST /agents/{name}/{id}`) create a `research_runs`
  row and return 202 with the run id; `GET /runs/{id}` reports status and steps. Jobs run on
  Celery when `SIGNALALPHA_BROKER_URL` is set, otherwise in an in-process worker thread so
  the stack works with no network.
* The API never uses the words "buy", "sell", "target price" or "recommendation" (PRD §16);
  a test asserts this on the valuation payload.

## Agents (build step 8)

* `agents/llm.py` is the provider layer: `AnthropicClient` (Claude API, structured output
  via `messages.parse`), `RecordedClient` (replays fixtures keyed by the input hash for CI)
  and `TemplateClient`, a deterministic stand-in labelled `template-v1` that writes
  schema-valid output from the structured snapshot. The template client is not an LLM; it
  exists so the whole pipeline runs and is tested with no network, and so mock company pages
  carry theses whose every claim links to a verified span. Select with
  `SIGNALALPHA_LLM_PROVIDER=anthropic|recorded|template` (`agents/config.yaml` default).
* Agents never create evidence text. Their claims carry `(document_id, quote)` pairs for
  documents they were given; Python locates each quote and creates the evidence record
  (`created_by = agent:<name>`), then `validate_claims` checks company and time.
* Every narrative figure must match a structured input value (or a number inside one of the
  claim's verified quotes) within `numeric_tolerance`; downstream agents may also reuse
  figures already present in validated upstream outputs.
* Validators per PRD §7: Financial (proposed signals must match computed ones), Promoter
  (classification consistent with ownership signals and pledge level), Business (each order
  value is a verbatim span, Python sums the order book), Industry (peer ids must exist),
  Forensic (flags map to computed forensic signals or are `unclassified`), Valuation
  (parameters only, within bounds; Python computes scenarios), Contradiction (must cite a
  negative signal when one exists), Thesis (needs a validated Contradiction for the same
  as-of and must restate one of its disputes).
* Runs are cached on `(company, agent, as_of, prompt_version, input_hash, model_id)`;
  tokens and cost are stored per run and a per-company daily budget stops runaway loops.
  Prompts are versioned files in `agents/prompts/`.

## Live ingestion (build step 10)

* Every live source is behind a feature flag (`SIGNALALPHA_LIVE_EOD_PRICES`,
  `SIGNALALPHA_LIVE_NSE_ANNOUNCEMENTS`), off by default. URL templates, cadence and parser
  versions live in `data/sources.yaml`; the small real universe lives in
  `data/live_universe.yaml` (shipped empty so that no market data is invented).
* `data/fetchers/transport.py` identifies itself, checks `robots.txt`, rate-limits and
  raises `FetchError` on anything but a 200 with a body. `FakeTransport` serves tests.
* `data/ingest.py` stores every fetched file raw-first through `DocumentWriter` (dedup by
  SHA-256), parses with a versioned parser, writes derived rows with provenance and
  `is_mock = false`, and updates `data_quality` (fetch/parse failure counts, last error,
  latest `public_at`) before re-raising any failure so the Celery task fails loudly.
* Announcement attachments are fetched, kept as raw PDF bytes, and their text layer appended
  to the announcement document; a scanned PDF is recorded as a parse failure (no OCR in v1)
  and the announcement row carries `summary = attachment_unavailable=true`.
* Celery beat schedules follow PRD §5.1 (announcements every 15 minutes in market hours,
  hourly otherwise; prices after the daily publication). `docs/SOURCES.md` records each
  source's URL, access method, terms relied on and review date (PRD §16).
* `infra/docker-compose.yml` boots Postgres+pgvector, Redis, MinIO, a bootstrap job (mock
  universe through agents), the API, a worker, beat and the web app.
