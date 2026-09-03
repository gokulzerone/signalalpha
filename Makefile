PY=.venv/bin

.PHONY: setup lint typecheck test check migrate

setup:
	uv venv -p 3.12 && uv pip install -e '.[dev]'

lint:
	$(PY)/ruff check . && $(PY)/ruff format --check .

typecheck:
	$(PY)/mypy

test:
	$(PY)/pytest

check: lint typecheck test

migrate:
	$(PY)/alembic -c database/alembic.ini upgrade head
