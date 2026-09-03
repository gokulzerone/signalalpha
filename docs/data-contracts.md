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
