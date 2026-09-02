#!/bin/sh
# Applies the Alembic schema (idempotent — a no-op if already at head) before
# starting the API, so "one command" really does produce a working backend
# against a freshly-started Supabase-local Postgres, not just a process that
# 500s on first query. Uses the same Settings precedence as everywhere else
# (LEMELY_DATABASE__URL overrides the local-dev default baked into
# lemely/runtime/config.py) — see docker-compose.yml for the value it's set to.
#
# LEMELY_RUN_MIGRATIONS=0 skips this (default: run). docs/deployment.md §3.4
# flags running migrations on every container start as wrong for a real
# deploy — a rollout becomes an unreviewed schema change, and N Cloud Run
# instances could race the same upgrade. The CI/CD pipeline (docs/ci-cd.md)
# runs `alembic upgrade head` as its own gated job before the image deploys,
# then deploys with this var set to 0 so the container never re-runs it.
set -eu

if [ "${LEMELY_RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "[entrypoint] applying database migrations (alembic upgrade head)..."
    alembic upgrade head
else
    echo "[entrypoint] LEMELY_RUN_MIGRATIONS=0 — skipping migrations (already applied by CI/CD)."
fi

echo "[entrypoint] starting API server..."
exec python -m lemely.web
