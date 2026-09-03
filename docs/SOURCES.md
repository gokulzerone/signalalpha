# Sources (PRD §16)

Every live source is fetched only when its feature flag is on. Fetchers identify themselves
with a User-Agent (set `SIGNALALPHA_CONTACT`), respect `robots.txt`, rate-limit to the
configured requests per minute, and store every fetched file verbatim before parsing.

| Source | URL / access | Terms relied on | Flag | Last reviewed |
|---|---|---|---|---|
| NSE security-wise bhav data (EOD prices, delivery %) | `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv` (public daily CSV; template in `data/sources.yaml`) | Public archive published by the exchange for general use; no login. Review NSE's terms of use before running against the live endpoint. | `SIGNALALPHA_LIVE_EOD_PRICES` | not yet reviewed against the live endpoint (the format was implemented from the published CSV layout and a golden fixture) |
| NSE corporate announcements | `https://www.nseindia.com/api/corporate-announcements?...` (public JSON behind the exchange website; template in `data/sources.yaml`) | Public disclosure feed; the site may require a warm-up request for cookies and may rate-limit. Review NSE's terms of use before running. | `SIGNALALPHA_LIVE_NSE_ANNOUNCEMENTS` | not yet reviewed against the live endpoint |

Sources listed in PRD §5.1 but not yet implemented (BSE announcements, XBRL results,
shareholding patterns, pledge and insider disclosures, bulk deals, annual reports, rating
rationales, corporate actions, surveillance lists, index constituents) follow the same
contract: a URL template in `data/sources.yaml`, a versioned parser with a golden-file test,
a feature flag, and a row in this table with the terms relied on and the review date.

No credential-gated or paywalled source is used. If an endpoint changes shape, the parser
raises, the failure is written to `data_quality`, and the task fails loudly.
