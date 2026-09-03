-- SignalAlpha point-in-time SQL functions, version 1.
--
-- Every consumer (API, signals, scores, agents, backtester) reads historical state through
-- these functions or through database/pit.py, which wraps them. A row with
-- public_at > p_as_of is never returned (PRD §2.5, §11).

-- Latest non-superseded financial row per (period_end, period_months, consolidated) whose
-- filing was public at p_as_of. Restated periods therefore resolve to the latest restatement
-- that was public at the time (PRD §5.2). p_consolidated NULL returns both bases.
CREATE OR REPLACE FUNCTION sa_financials_as_of(
    p_company_id bigint,
    p_as_of timestamptz,
    p_consolidated boolean,
    p_is_mock boolean
) RETURNS SETOF financials
LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (f.period_end, f.period_months, f.consolidated) f.*
    FROM financials f
    WHERE f.company_id = p_company_id
      AND f.public_at <= p_as_of
      AND f.is_mock = p_is_mock
      AND NOT f.is_superseded
      AND (p_consolidated IS NULL OR f.consolidated = p_consolidated)
    ORDER BY f.period_end, f.period_months, f.consolidated,
             f.public_at DESC, f.filing_id DESC, f.id DESC;
$$;

-- Latest non-superseded shareholding pattern per period_end public at p_as_of.
CREATE OR REPLACE FUNCTION sa_shareholdings_as_of(
    p_company_id bigint,
    p_as_of timestamptz,
    p_is_mock boolean
) RETURNS SETOF shareholdings
LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (s.period_end) s.*
    FROM shareholdings s
    WHERE s.company_id = p_company_id
      AND s.public_at <= p_as_of
      AND s.is_mock = p_is_mock
      AND NOT s.is_superseded
    ORDER BY s.period_end, s.public_at DESC, s.filing_id DESC, s.id DESC;
$$;

-- The versioned universe on p_date: each company's latest snapshot dated on or before
-- p_date. Delisted, suspended and merged companies are included with their status so that
-- the historical universe carries no survivorship bias (PRD §4, §11).
CREATE OR REPLACE FUNCTION sa_universe_as_of(
    p_date date,
    p_is_mock boolean
) RETURNS SETOF universe_snapshots
LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (u.company_id) u.*
    FROM universe_snapshots u
    WHERE u.snapshot_date <= p_date
      AND u.is_mock = p_is_mock
    ORDER BY u.company_id, u.snapshot_date DESC, u.id DESC;
$$;

-- Latest price row per trade_date (across parser versions) in [p_from, p_to], public at p_as_of.
CREATE OR REPLACE FUNCTION sa_prices_as_of(
    p_company_id bigint,
    p_from date,
    p_to date,
    p_as_of timestamptz,
    p_is_mock boolean
) RETURNS SETOF prices
LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (p.trade_date) p.*
    FROM prices p
    WHERE p.company_id = p_company_id
      AND p.trade_date BETWEEN p_from AND p_to
      AND p.public_at <= p_as_of
      AND p.is_mock = p_is_mock
    ORDER BY p.trade_date, p.parser_version DESC, p.id DESC;
$$;
