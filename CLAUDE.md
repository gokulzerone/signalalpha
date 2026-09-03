# SignalAlpha

Research terminal that surfaces fundamental inflections in Indian small-cap and micro-cap companies from public data only.

## Read first
- `SignalAlpha-PRD.md` is the full specification. Follow it section by section; do not invent modules, agents, or scores that are not in it.

## Hard rules (from PRD §2)
- Public information only. Never fetch, infer, or use unpublished price-sensitive information.
- Every AI factual claim must cite evidence IDs; evidence text must be a verbatim span of a stored document (PRD §8).
- Python does all arithmetic. LLMs never compute financial numbers.
- Never fabricate market data or filings. Mock data is `is_mock = true` and uses `MOCK-` tickers.
- All queries are point-in-time: nothing with `public_at > as_of` is ever returned.
- No thesis without a completed contradiction analysis.
- Every score exposes its components.

## Build order (PRD §15)
1. Database + point-in-time layer  2. Mock data generator  3. Evidence module  4. Signals
5. Scores  6. Backtesting  7. API  8. Agents  9. UI  10. Live ingestion (feature-flagged, last)

Work one step at a time. Each step ends with passing tests before the next begins.

## Stack
Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, PostgreSQL 16 + pgvector, Redis + Celery, MinIO (S3), Next.js App Router + TypeScript + Tailwind + Recharts. `mypy --strict`, `ruff`, `pytest`.

## Repository layout
See PRD §13. Keep `/apps/web`, `/apps/api`, `/database`, `/data`, `/pipelines`, `/signals`, `/agents`, `/scoring`, `/backtesting`, `/evidence`, `/tests`, `/docs`, `/infra`.

## Conventions
- Thresholds and weights live in config files (`/scoring/config.yaml`, `/signals/catalogue.yaml`), never hard-coded.
- Agent prompts are versioned files in `/agents/prompts/`.
- Every derived row carries `raw_document_id`, `parser_version`, `public_at`, `ingested_at`.
- Commit after each completed step with a message naming the PRD step.
