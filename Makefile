.PHONY: install dev test lint typecheck imports lock pre-commit fmt clean \
	db-up db-down db-stop db-status db-reset db-migrate db-revision db-downgrade seed

PYTHON ?= python
ALEMBIC ?= alembic

install:
	pip install -e .

dev:
	pip install -e ".[dev,ui,web,db]"
	pre-commit install || true

test:
	pytest

lint:
	ruff check .

fmt:
	ruff check --fix .
	ruff format .

typecheck:
	mypy lemely

imports:
	lint-imports

pre-commit:
	pre-commit run --all-files

lock:
	uv lock

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# ── Local database (Supabase stack + Alembic) ────────────────────────────────
# `db-up` boots the full local Supabase stack (Postgres, Auth, Storage, Studio)
# via Docker, then applies the Alembic schema. See docs/database.md.
db-up:
	supabase start
	$(ALEMBIC) upgrade head

db-down db-stop:
	supabase stop

db-status:
	supabase status

# Reset Postgres to a clean state (drops app data + auth users), then rebuild
# the app schema with Alembic and re-seed demo accounts.
db-reset:
	supabase db reset
	$(ALEMBIC) upgrade head
	$(MAKE) seed

# Apply all pending migrations against the running Postgres.
db-migrate:
	$(ALEMBIC) upgrade head

# Autogenerate a new migration from model changes: make db-revision m="add foo"
db-revision:
	$(ALEMBIC) revision --autogenerate -m "$(m)"

# Roll back one migration.
db-downgrade:
	$(ALEMBIC) downgrade -1

# Seed demo/reference data (idempotent). Requires the schema to be migrated.
seed:
	$(PYTHON) -m lemely.db.seed
