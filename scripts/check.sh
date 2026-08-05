#!/usr/bin/env bash
# scripts/check.sh — the one gate command (MISSION.md §6/§8b/§11).
#
# Runs every quality gate for a change in one shot, suppresses passing
# output, and prints only failures plus a one-line PASS/FAIL/SKIP per tool.
# Never invoke ruff/mypy/pytest/tsc/oxlint/etc individually — run this.
#
# Backend and web gates always run. The live-stack UI gates (Playwright E2E,
# the Puppeteer audit runner, and the axe/Lighthouse threshold check) need
# the local Supabase stack (`supabase start`) plus a reachable backend they
# boot themselves; when the stack isn't up they SKIP (not FAIL) with an
# explanation, mirroring the existing pytest DB-integration-test skip
# pattern, rather than blocking gates that don't need it.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="$HOME/.local/bin:$PATH"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILED=()
SKIPPED=()

run() {
  local name="$1"
  shift
  local log="$TMP/$name.log"
  if ( "$@" ) >"$log" 2>&1; then
    echo "PASS   $name"
  else
    echo "FAIL   $name"
    sed -n '1,60p' "$log" | sed 's/^/       /'
    FAILED+=("$name")
  fi
}

skip() {
  echo "SKIP   $1 — $2"
  SKIPPED+=("$1")
}

echo "== Backend =="
run "ruff-check" ruff check .
run "ruff-format" ruff format --check .
run "mypy" mypy lemely
run "import-linter" lint-imports
run "pytest" pytest -q --tb=short

echo
echo "== Web =="
run "web-typecheck" bash -c 'cd web && npm run -s typecheck'
run "web-lint" bash -c 'cd web && npm run -s lint'
run "web-build" bash -c 'cd web && npm run -s build'
run "impeccable-detect" bash -c 'cd web && npx --yes impeccable detect src/'

STACK_UP=0
if supabase status -o json >/dev/null 2>&1; then
  STACK_UP=1
fi

echo
echo "== Live-stack UI gates (Supabase local stack) =="
if [ "$STACK_UP" -eq 1 ]; then
  run "playwright-e2e" bash -c 'cd web && npm run -s test:e2e'
  run "puppeteer-audit" bash -c 'cd web && npm run -s audit'
  run "ui-thresholds" .venv/bin/python scripts/check_ui_gates.py
else
  skip "playwright-e2e" "local Supabase stack not running (supabase status failed)"
  skip "puppeteer-audit" "local Supabase stack not running"
  skip "ui-thresholds" "no fresh audit output (stack down, puppeteer-audit skipped)"
fi

echo
echo "── Summary ───────────────────────────────────────────"
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "All gates passed (${#SKIPPED[@]} skipped)."
else
  echo "FAILED (${#FAILED[@]}): ${FAILED[*]}"
fi

[ "${#FAILED[@]}" -eq 0 ]
