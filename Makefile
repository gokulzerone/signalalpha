PY=.venv/bin
export SIGNALALPHA_DATABASE_URL ?= embedded

.PHONY: setup lint typecheck test check migrate bootstrap api web demo

setup:
	uv venv -p 3.12 && uv pip install -e '.[dev]' && npm --prefix apps/web install

lint:
	$(PY)/ruff check . && $(PY)/ruff format --check .

typecheck:
	$(PY)/mypy && npm --prefix apps/web run typecheck

test:
	$(PY)/pytest

check: lint typecheck test

migrate:
	$(PY)/alembic -c database/alembic.ini upgrade head

bootstrap:  ## migrate + mock universe + signals + scores + backtest + agents (offline)
	$(PY)/python scripts/bootstrap_mock.py

api:
	$(PY)/uvicorn apps.api.main:app --factory --port 8000

web:
	SIGNALALPHA_API_BASE=http://localhost:8000 npm --prefix apps/web run dev

demo: bootstrap  ## then run `make api` and `make web` in two terminals
	@echo "database ready; run 'make api' and 'make web'"
