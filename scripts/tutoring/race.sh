#!/usr/bin/env bash
# RACE: run named test files N times in a row and stop at the first red.
#
# Concurrency tests (booking, grants, sweeps) are flaky by nature, so the lead
# runs them several times at the integration rows, serially, with no lane active
# (PLAN section 0.7, RACE). Every iteration goes through pytest.sh, so the same
# refusals apply (named files only, never a directory).
#
# Usage: bash scripts/tutoring/race.sh <n 1..20> <tests/...py>...
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

refuse() {
  echo "race.sh: refusing: $*" >&2
  exit 2
}

[ "$#" -ge 2 ] || refuse "usage: race.sh <n> <test files...>"
n="$1"
shift
case "$n" in
  '' | *[!0-9]*) refuse "iteration count must be a positive integer, got '$n'" ;;
esac
{ [ "$n" -ge 1 ] && [ "$n" -le 20 ]; } || refuse "iteration count must be between 1 and 20, got $n"

for ((i = 1; i <= n; i++)); do
  echo "race iteration $i/$n"
  rc=0
  bash "$ROOT/scripts/tutoring/pytest.sh" "$@" || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "race.sh: red on iteration $i/$n (exit $rc); stopping" >&2
    exit "$rc"
  fi
done
echo "race.sh: $n/$n iterations green"
