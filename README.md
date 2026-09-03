# SignalAlpha

Research terminal that surfaces fundamental inflections in Indian small-cap and micro-cap
companies from public data only. `SignalAlpha-PRD.md` is the specification.

## Run the whole stack

```bash
docker compose -f infra/docker-compose.yml up   # Postgres, Redis, MinIO, bootstrap (mock data), API, worker, beat, web
```

Then open http://localhost:3000. Without Docker: `make bootstrap`, then `make api` and `make web`.

## Development

```bash
make setup      # Python 3.12 venv via uv
make check      # ruff + mypy --strict + pytest
```

Tests run against an embedded PostgreSQL 16 + pgvector (no Docker needed). Set
`SIGNALALPHA_DATABASE_URL` to a real PostgreSQL URL to use `infra/docker-compose.yml`.

## Build status (PRD §15)

1. Database and point-in-time layer — done
2. Mock data generator — done (`python -m data.mock generate`, see `docs/mock-universe.md`)
3. Evidence module — done (span validation in Python and in a DB trigger; viewer endpoint)
4. Signals — done (30 catalogue types, point-in-time runner, proposal validator)
5. Scores — done (five percentile scores + Opportunity, all components exposed)
6. Backtesting — done (point-in-time simulator, execution model, signal and score-decile performance tables)
7. API — done (all PRD §10 endpoints; research jobs inline or via Celery)
8. Agents — done (eight agents with validators; Claude, recorded-fixture and offline template clients)
9. UI — done (dashboard, company page, signals, data; see `docs/ui.md`)
10. Live ingestion — done (NSE EOD prices and announcements behind feature flags; see `docs/SOURCES.md`)
