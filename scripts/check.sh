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
#
# Those UI gates write screenshots and axe/Lighthouse JSON to the gitignored
# scratch dir reports/.scratch (LEMELY_REPORT_DIR's default). They deliberately
# do NOT write into reports/phase-N/: those are the committed baselines the
# "no unintended visual regression" gate compares against, and a gate run that
# overwrites its own reference cannot detect a regression. To re-baseline a
# phase — an explicit, reviewable act — name it:
#
#   cd web && LEMELY_REPORT_DIR=reports/phase-3 npm run test:e2e
#   cd web && LEMELY_REPORT_DIR=reports/phase-3 npm run audit
#
# then commit the diff with a note in the phase report (MISSION §11).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# .venv/bin first so the backend gates run against the project's pinned tools
# even from a shell that never sourced the venv. Without it every backend gate
# reports "command not found" and FAILS — loud, but only if you read the log;
# the far worse variant is a *different* ruff/mypy on PATH silently gating the
# build against the wrong versions. $HOME/.local/bin carries `supabase`, which
# this sandbox's non-interactive shells otherwise lack (P3.7).
export PATH="$PWD/.venv/bin:$HOME/.local/bin:$PATH"

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
run "design-tokens" bash -c 'cd web && node scripts/check-design-tokens.mjs'
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
