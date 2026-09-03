# SignalAlpha

Research terminal that surfaces fundamental inflections in Indian small-cap and micro-cap
companies from public data only. `SignalAlpha-PRD.md` is the specification.

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
5. Scores — pending
