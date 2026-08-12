#!/bin/sh
# Applies the Alembic schema (idempotent — a no-op if already at head) before
# starting the API, so "one command" really does produce a working backend
# against a freshly-started Supabase-local Postgres, not just a process that
# 500s on first query. Uses the same Settings precedence as everywhere else
# (LEMELY_DATABASE__URL overrides the local-dev default baked into
# lemely/runtime/config.py) — see docker-compose.yml for the value it's set to.
set -eu

echo "[entrypoint] applying database migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] starting API server..."
exec python -m lemely.web
