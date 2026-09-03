# Mock universe (build step 2)

`python -m data.mock generate` writes a fictional universe of 40 companies through the real
ingestion path: every figure arrives via a raw document in object storage, a
`document_texts` row, and a provenance-bearing derived row. All rows are `is_mock = true`,
all tickers start with `MOCK-`, and every document says it is fictional.

The blueprint (names, sectors, stories) is `data/mock/universe.yaml`; the synthesis is
deterministic for a given seed (default 20240903).

## Timeline

| Item | Range |
|---|---|
| Quarterly results | 16 quarters, Jun 2022 to Mar 2026 (PRD asks for 12; four extra quarters give the YoY-based signals a warm-up) |
| Results publication | quarter end + 40 days (Q4: + 55 days), 17:30 IST |
| Shareholding pattern | quarter end + 14 days, 16:00 IST |
| Annual report | FY end + 150 days, 15:00 IST. It re-files the annual row with notes (related-party revenue, contingent liabilities, audit opinion) via the restatement path |
| Prices | weekdays 1 Apr 2022 to 31 Aug 2026, bhavcopy public 18:00 IST |
| Universe snapshots | every month end, plus the delisting date |
| Index | `MOCK-SMALLCAP`: monthly membership of companies inside the cap band |

Reporting basis: companies with `id % 5 == 0` file both consolidated and standalone,
`id % 5 in (1, 2)` consolidated only, the rest standalone only, so consumers must handle
the "consolidated where available" rule.

## Planted stories

Inflection quarter index `s = 9` (period ending 30 Sep 2024).

| Story | Companies | What is planted | Expected detection |
|---|---|---|---|
| `order_book_surge` | MOCK-ARGR, MOCK-SHDE | Three order wins of 22–35% of trailing revenue in quarters 8–9, capacity expansion, revenue up ~12% per quarter thereafter, capex/depreciation 2.5× | `order_win`, `capacity_expansion`, `revenue_acceleration`, `capex_cycle_start`; positive forward returns |
| `pledge_unwind` | MOCK-BHSP, MOCK-GHIN | Pledge 65% → 45% → 20% → 0% over quarters 8–10 with release disclosures, promoter market buys, deleveraging | `pledge_reduction`, `promoter_stake_increase`, `deleveraging`; positive forward returns |
| `margin_turnaround` | MOCK-NRSC, MOCK-KRCS | EBITDA margin 8.5% → 17% over quarters 8–11, rating upgrade in quarter 11 | `margin_inflection`, `operating_leverage`, `credit_rating_upgrade`; positive forward returns |
| `forensic_red_flag` | MOCK-GMRD, MOCK-LNFB | Receivable days 70 → 160, short-term borrowings rising with cash still large, contingent liabilities 5×, emphasis of matter then qualified opinion, CFO resignation, downgrade, auditor change | `receivables_outrunning_revenue`, `cash_vs_debt_anomaly`, `contingent_liability_spike`, `audit_qualification`, `key_person_exit`, `auditor_change`, `credit_rating_downgrade`; negative forward returns |
| `deceptive_growth` | MOCK-ZNIT, MOCK-MJFD | 45% revenue growth from quarter 6 with 42% related-party revenue, receivable days 80 → 170, retail shareholder count +60% then +35%, promoter sales, two discounted warrant issues, ASM entry and exit | `related_party_revenue`, `shareholder_count_spike`, `promoter_stake_decrease`, `frequent_fund_raise`, `surveillance_entry`; high Risk, low Opportunity |
| `delisted` | MOCK-HGHT | GSM entry, losses, compulsory delisting on 13 Dec 2024; filings stop after quarter 9 | Survivorship: present in the universe before, `delisted` after, −100% terminal return in backtests |
| `illiquid` | MOCK-BNPR | Traded value ≈ ₹8 lakh/day | Flagged `illiquid`, excluded from backtests by default |
| `control` | 28 companies | Zero-drift prices around a common market factor; occasional small orders, insider trades, dividends; MOCK-TGBR has a 1:1 bonus (unadjusted prices halve on the ex-date) | Zero-effect statistics in backtests |

Price effects are planted as extra daily log-drift over a fixed number of trading days after
the story's first public event (positive stories +0.15–0.16%/day for 180–200 days; negative
stories −0.15–0.22%/day for 200–220 days).
