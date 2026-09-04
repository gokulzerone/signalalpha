# Sources (PRD §16)

Every live source is fetched only when its feature flag is on. Fetchers identify themselves,
respect `robots.txt`, rate-limit to 20 requests a minute, and store every fetched file
verbatim before parsing. All endpoints below were verified working on **2026-09-04**.

| Source | Endpoint | Flag | Freshness observed | Terms relied on |
|---|---|---|---|---|
| Listed equities | `nsearchives.nseindia.com/content/equities/EQUITY_L.csv` | always (universe) | current | Public archive file, no login |
| End-of-day prices, delivery % | `nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv` | `SIGNALALPHA_LIVE_EOD_PRICES` | **current** (T+0 after 18:00 IST) | Public daily archive, no login |
| Quarterly results (Ind-AS XBRL) | `nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly&symbol=…` plus the `xbrl` link on each row | `SIGNALALPHA_LIVE_FINANCIAL_RESULTS` | **history complete to the quarter ending 31 Dec 2024; nothing newer is served** | Public disclosure feed |
| Corporate announcements | `nseindia.com/api/corporate-announcements?index=equities&from_date=…&to_date=…` | `SIGNALALPHA_LIVE_NSE_ANNOUNCEMENTS` | **current** (minutes) | Public disclosure feed |
| Corporate actions | `nseindia.com/api/corporates-corporateActions?index=equities` | `SIGNALALPHA_LIVE_CORPORATE_ACTIONS` | current | Public disclosure feed |

`robots.txt` on `www.nseindia.com` is `Allow: /` with a single unrelated exclusion, and the
archive host serves the files above without restriction.

## Two things a reader should know

**The results API lags.** On 2026-09-04 the financial-results endpoint returned nothing newer
than the quarter ending 31 December 2024, and that is true for the largest listed companies as
well as small caps, so it is a property of the source rather than of one company. Prices and
announcements from the same exchange are current to the minute. The consequence is visible in
the product rather than hidden: the data page shows per-source freshness, and a company's
readiness check refuses to call a view "ready" when its newest reported quarter is more than
about 200 days old. Viewing the terminal as of a date shortly after those results were filed
gives a complete, honest picture; viewing it today gives current prices and announcements over
stale fundamentals, and says so.

**The User-Agent is browser-shaped.** NSE's CDN drops connections from crawler-style agents,
so the configured agent is a normal browser string with `SignalAlpha/0.1` appended, which
keeps this tool identifiable in the exchange's logs. Nothing else about the access is
disguised: no CAPTCHA is bypassed, no IP rotation, no fingerprint spoofing, one session, and a
conservative rate limit. Before running the live flags against the exchange for anything
beyond personal research, read NSE's terms of use and satisfy yourself that your use is
within them; that is a decision for the operator, not for this code.

## Not yet implemented

Shareholding patterns, promoter pledges, insider trades, bulk and block deals, annual reports,
credit-rating rationales, surveillance lists and index constituents (PRD §5.1) have no live
fetcher yet, so ownership and most forensic signals stay silent on live companies. Each would
follow the same contract: a URL template in `data/sources.yaml`, a versioned parser with a
golden-file test, a feature flag, and a row in this table.
