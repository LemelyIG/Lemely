#!/usr/bin/env bash
# GATE-DB: Alembic and psql against the throwaway database `lemely_tutoring_gate`.
#
# The migration gates of the tutoring build (fresh upgrade, single head,
# downgrade and upgrade again) run on this one database so they never touch the
# shared `postgres` database. The script refuses any other database name: the
# name may only be overridden by TUTORING_GATE_DB for the test of this refusal,
# and anything but `lemely_tutoring_gate` stops the script before psql or
# Alembic is reached.
#
# Usage: bash scripts/tutoring/gate_db.sh <command>
#   reset              drop and create lemely_tutoring_gate (via the postgres maintenance db)
#   upgrade            alembic upgrade head
#   downgrade <rev>    alembic downgrade <rev>
#   heads              alembic heads; fails unless there is exactly one head
#   current            alembic current
#   check              alembic check, informational: always exits 0 (SPEC section a.4 F20 says
#                      it cannot see exclusion constraints, computed columns or partial predicates)
#
# Alembic runs as `python -m alembic` with PYTHONPATH pinned to this tree.
# TUTORING_PY overrides the interpreter (a test seam for the head-count logic).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

refuse() {
  echo "gate_db.sh: refusing: $*" >&2
  exit 2
}

GATE_DB="lemely_tutoring_gate"
DB="${TUTORING_GATE_DB-$GATE_DB}"
[ "$DB" = "$GATE_DB" ] || refuse "database name '$DB' is not $GATE_DB; this wrapper only ever touches $GATE_DB"

MAINTENANCE_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
ALEMBIC_URL="postgresql+psycopg://postgres:postgres@127.0.0.1:54322/$GATE_DB"
PY="${TUTORING_PY:-$ROOT/.venv/bin/python}"

alembic() {
  env LEMELY_DATABASE__URL="$ALEMBIC_URL" PYTHONPATH="$ROOT" "$PY" -m alembic "$@"
}

[ "$#" -ge 1 ] || refuse "usage: gate_db.sh reset | upgrade | downgrade <rev> | heads | current | check"
command="$1"
shift

case "$command" in
  reset)
    [ "$#" -eq 0 ] || refuse "reset takes no arguments"
    psql "$MAINTENANCE_URL" -v ON_ERROR_STOP=1 \
      -c "DROP DATABASE IF EXISTS $GATE_DB WITH (FORCE)" \
      -c "CREATE DATABASE $GATE_DB"
    echo "gate_db.sh: $GATE_DB recreated empty"
    ;;
  upgrade)
    [ "$#" -eq 0 ] || refuse "upgrade takes no arguments"
    alembic upgrade head
    ;;
  downgrade)
    [ "$#" -eq 1 ] || refuse "downgrade needs exactly one revision"
    [[ "$1" =~ ^[A-Za-z0-9_@+.-]+$ ]] || refuse "revision '$1' has characters outside A-Z a-z 0-9 _ @ + . -"
    alembic downgrade "$1"
    ;;
  heads)
    [ "$#" -eq 0 ] || refuse "heads takes no arguments"
    out="$(alembic heads)"
    echo "$out"
    count="$(printf '%s\n' "$out" | grep -c '(head)' || true)"
    if [ "$count" -ne 1 ]; then
      echo "gate_db.sh: expected exactly one head, found $count" >&2
      exit 1
    fi
    ;;
  current)
    [ "$#" -eq 0 ] || refuse "current takes no arguments"
    alembic current
    ;;
  check)
    [ "$#" -eq 0 ] || refuse "check takes no arguments"
    rc=0
    alembic check || rc=$?
    echo "gate_db.sh: alembic check is informational (exit $rc); it never blocks"
    ;;
  *)
    refuse "unknown command '$command' (reset | upgrade | downgrade <rev> | heads | current | check)"
    ;;
esac
