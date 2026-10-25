#!/usr/bin/env bash
# SCAN-PY: run every source-scanning test file (PLAN section 0.7).
#
# The list is computed here, not typed: every tests/**/test_*.py that contains
# `rglob(`, the `LEMELY_SRC` marker or `ast.parse`, i.e. the tests that read the
# lemely/ source tree and so can be broken by a file added far from them. The
# script prints the list, fails if it finds fewer than the minimum (default 10;
# `TUTORING_SCAN_MIN` overrides it, for the test of this refusal), then runs the
# list, plus any extra arguments, through pytest.sh.
#
# Usage: bash scripts/tutoring/scan_py.sh [--list] [extra pytest.sh arguments]
#   --list   print the list and exit without running anything
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

refuse() {
  echo "scan_py.sh: refusing: $*" >&2
  exit 2
}

min="${TUTORING_SCAN_MIN:-10}"
case "$min" in
  '' | *[!0-9]*) refuse "TUTORING_SCAN_MIN must be a number, got '$min'" ;;
esac

list_only=0
if [ "${1:-}" = "--list" ]; then
  list_only=1
  shift
fi

files=()
while IFS= read -r line; do
  [ -n "$line" ] && files+=("$line")
done < <(grep -rlE --include='test_*.py' 'rglob\(|LEMELY_SRC|ast\.parse' tests | LC_ALL=C sort || true)

echo "scan_py.sh: ${#files[@]} source-scanning test files in $ROOT"
for f in "${files[@]+"${files[@]}"}"; do
  echo "$f"
done

if [ "${#files[@]}" -lt "$min" ]; then
  refuse "found ${#files[@]} source-scanning test files, fewer than the minimum $min; the scan is not covering what it should"
fi

[ "$list_only" -eq 1 ] && exit 0

exec bash "$ROOT/scripts/tutoring/pytest.sh" "${files[@]}" "$@"
