#!/usr/bin/env bash
# scripts/up.sh — MISSION.md §3's "one command" for the packaged product.
#
# Starts Supabase-local (if not already running) then `docker compose up`
# for the backend + web images, and prints the URL to open. Mirrors the
# scripts/check.sh idiom of exporting $HOME/.local/bin onto PATH so the
# `supabase` CLI is found in a non-interactive shell (it is not on PATH by
# default in this environment).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export PATH="$HOME/.local/bin:$PATH"

if ! command -v supabase >/dev/null 2>&1; then
    echo "error: the supabase CLI is not on PATH (looked in \$HOME/.local/bin and \$PATH)." >&2
    echo "Install it first: https://supabase.com/docs/guides/cli" >&2
    exit 1
fi

echo "==> Checking local Supabase stack..."
if supabase status >/dev/null 2>&1; then
    echo "    already running."
else
    echo "    starting (supabase start)..."
    supabase start
fi

echo "==> Building and starting backend + web (docker compose)..."
docker compose up --build -d

echo "==> Waiting for both services to report healthy..."
# `docker compose up -d` returns as soon as containers start, not once their
# healthchecks pass — poll so "up.sh finished" reliably means "usable",
# matching the request for a single command that actually brings the product
# up rather than one that races the caller's first curl.
for _ in $(seq 1 60); do
    backend_status="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q backend)" 2>/dev/null || echo "starting")"
    web_status="$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q web)" 2>/dev/null || echo "starting")"
    if [ "$backend_status" = "healthy" ] && [ "$web_status" = "healthy" ]; then
        echo ""
        echo "Lemely is up: http://localhost:8080"
        echo "(backend directly, for debugging: http://localhost:8000/api/health)"
        exit 0
    fi
    sleep 2
done

echo "error: services did not become healthy within 120s — check 'docker compose logs'." >&2
exit 1
