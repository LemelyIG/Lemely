#!/usr/bin/env bash
# LIVE runner: Playwright specs or the Puppeteer audit against the local stack.
#
# Implements PLAN section 0.9 steps 2-7 (step 1, the lock, is live_lock.sh; the
# caller acquires it before and releases it after). In order, and stopping at the
# first refusal:
#   lock      the lock exists and was taken from this worktree
#   ports     nothing listens on 8000 or 5173 (Playwright's reuseExistingServer
#             would silently test another session's server)
#   tree      `git status --short` is empty (the run tests the committed tree)
#   specs     every spec exists under web/
#   database  dedicated: recreate lemely_tutoring_e2e and point
#                        LEMELY_DATABASE__URL at it, so global setup's
#                        `alembic upgrade head` and seed_e2e.py never touch
#                        the shared `postgres` database
#             shared:    run on `postgres`, then downgrade it to the revision
#                        recorded before the run and verify
#   run       PYTHONPATH pinned to this tree, npm run from web/
#   verify    `postgres`'s alembic_version equals the recorded value
#   summary   a block the caller persists to BUILD/tutoring/handoffs/live-<row>.md
#
# Usage: bash scripts/tutoring/live_e2e.sh <dedicated|shared> <e2e/x.spec.ts>...
#        bash scripts/tutoring/live_e2e.sh --audit <dedicated|shared>
#   (live_audit.sh is the second form: `npm run audit`, then check_ui_gates.py)
#
# TUTORING_LIVE_LOCK overrides the lock path, as in live_lock.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
LOCK="${TUTORING_LIVE_LOCK:-/home/sico/Code/Lemely/.omc/state/tutoring-live.lock}"

PG_BASE="127.0.0.1:54322"
MAINTENANCE_URL="postgresql://postgres:postgres@$PG_BASE/postgres"
E2E_DB="lemely_tutoring_e2e"

refuse() {
  echo "live_e2e.sh: refusing: $*" >&2
  exit 2
}

kind="e2e"
if [ "${1:-}" = "--audit" ]; then
  kind="audit"
  shift
fi

[ "$#" -ge 1 ] || refuse "usage: live_e2e.sh <dedicated|shared> <specs...> | live_e2e.sh --audit <dedicated|shared>"
mode="$1"
shift
case "$mode" in
  dedicated | shared) ;;
  *) refuse "unknown database mode '$mode' (dedicated | shared)" ;;
esac
if [ "$kind" = "audit" ]; then
  [ "$#" -eq 0 ] || refuse "the audit takes no spec arguments"
else
  [ "$#" -ge 1 ] || refuse "name at least one spec, for example e2e/tutoring-smoke.spec.ts"
fi
specs=("$@")

# lock
[ -d "$LOCK" ] || refuse "no live-stack lock at $LOCK; run live_lock.sh acquire <owner> first"
lock_tree="$(cat "$LOCK/worktree" 2>/dev/null || true)"
[ "$lock_tree" = "$(pwd -P)" ] ||
  refuse "the live-stack lock is held for worktree '$lock_tree', not '$(pwd -P)'"
lock_owner="$(cat "$LOCK/owner" 2>/dev/null || echo unknown)"

# ports
listening="$(ss -ltn)" || refuse "could not list listening ports with ss"
local_addresses="$(printf '%s\n' "$listening" | awk '{print $4}')"
for port in 8000 5173; do
  # A here-string, not a pipe into `grep -q`: under pipefail a pipe could report
  # SIGPIPE from the writer and read as "not listening".
  if grep -Eq ":$port\$" <<<"$local_addresses"; then
    refuse "port $port is already listening; Playwright and the audit would reuse that server"
  fi
done

# tree
[ -z "$(git status --short)" ] || refuse "the working tree is not clean; commit first (git status --short must be empty)"

# specs
if [ "$kind" = "e2e" ]; then
  for spec in "${specs[@]}"; do
    case "$spec" in
      e2e/*.spec.ts) ;;
      *) refuse "spec '$spec' must look like e2e/<name>.spec.ts, relative to web/" ;;
    esac
    [ -f "$ROOT/web/$spec" ] || refuse "spec web/$spec does not exist in this tree"
  done
fi

postgres_version() {
  psql "$MAINTENANCE_URL" -tAc "SELECT version_num FROM alembic_version"
}

before="$(postgres_version)" || refuse "could not read alembic_version from the shared postgres database"
[ -n "$before" ] || refuse "the shared postgres database has no recorded alembic_version"

export PYTHONPATH="$ROOT"
database="postgres (shared)"
if [ "$mode" = "dedicated" ]; then
  psql "$MAINTENANCE_URL" -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS $E2E_DB WITH (FORCE)" \
    -c "CREATE DATABASE $E2E_DB"
  export LEMELY_DATABASE__URL="postgresql+psycopg://postgres:postgres@$PG_BASE/$E2E_DB"
  database="$E2E_DB"
  # seed_e2e.py refuses to grade without verified grade thresholds, and they are
  # ingested from the network (scripts/ingest_thresholds.py), not seeded. Migrate
  # the dedicated database, then copy those reference rows from the dev database.
  "$PY" -m alembic upgrade head
  pg_dump --data-only --table=component_thresholds --table=option_thresholds \
    "$MAINTENANCE_URL" | psql "postgresql://postgres:postgres@$PG_BASE/$E2E_DB" -v ON_ERROR_STOP=1 -q
fi

echo "live_e2e.sh: kind=$kind mode=$mode database=$database tree=$ROOT lock-owner=$lock_owner"
echo "live_e2e.sh: shared postgres alembic_version before: $before"

run_rc=0
if [ "$kind" = "audit" ]; then
  npm --prefix "$ROOT/web" run audit || run_rc=$?
  if [ "$run_rc" -eq 0 ]; then
    "$PY" scripts/check_ui_gates.py || run_rc=$?
  fi
  subject="audit + check_ui_gates"
else
  npm --prefix "$ROOT/web" run test:e2e -- "${specs[@]}" || run_rc=$?
  subject="${specs[*]}"
fi

after="$(postgres_version || true)"
verify="ok"
if [ "$after" != "$before" ]; then
  if [ "$mode" = "shared" ]; then
    echo "live_e2e.sh: shared postgres moved $before -> $after; downgrading back to $before"
    env LEMELY_DATABASE__URL="postgresql+psycopg://postgres:postgres@$PG_BASE/postgres" \
      PYTHONPATH="$ROOT" "$PY" -m alembic downgrade "$before" || true
    after="$(postgres_version || true)"
  fi
  if [ "$after" != "$before" ]; then
    verify="FAILED"
  fi
fi

result="PASS"
[ "$run_rc" -eq 0 ] || result="FAIL"

echo "===== live run summary ====="
echo "kind: $kind"
echo "mode: $mode"
echo "database: $database"
echo "worktree: $ROOT"
echo "lock owner: $lock_owner"
echo "run: $subject"
echo "alembic_version before: $before"
echo "alembic_version after: $after"
echo "alembic_version verify: $verify"
echo "result: $result (exit $run_rc)"
echo "============================"

if [ "$verify" != "ok" ]; then
  echo "live_e2e.sh: VERIFY FAILED: the shared postgres database is at '$after', recorded '$before'. Stop the build and tell the user." >&2
  exit 1
fi
exit "$run_rc"
