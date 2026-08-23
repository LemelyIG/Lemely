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
#
# ── Two modes ──────────────────────────────────────────────────────────────
#
#   scripts/check.sh                  the authoritative gate. Serial pytest,
#                                     coverage instrumented, --cov-fail-under=70
#                                     enforced. This is what a merge decision
#                                     is allowed to rest on.
#
#   scripts/check.sh --fast [PATH...] the non-authoritative in-run check, for
#                                     the unattended orchestrator. Identical
#                                     gate list; the only difference is that
#                                     pytest runs under xdist with coverage
#                                     off, optionally narrowed to PATH...
#
# Why --fast exists: the full serial+coverage suite is ~3800 tests on 4 cores
# and cannot finish inside one unattended `claude -p` run. Runs were spending
# their entire lifetime waiting on it, ending their turn, and the next run —
# fresh context, no memory a suite was in flight — started it again. Nothing
# ever landed. --fast gives a run a check it can actually finish.
#
# --fast is deliberately NOT a weaker gate that can be mistaken for the real
# one. It drops coverage measurement only, and it says so on every run and in
# its own exit banner. Coverage and the 70% floor stay enforced by the default
# mode and by CI (.github/workflows/ci.yml runs bare `pytest` on 3.12/3.13/
# 3.14, which picks up the coverage addopts from pyproject.toml). A green
# --fast run is never sufficient to merge; CI green is. See ACCURACY-MISSION
# §9.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

FAST=0
PYTEST_PATHS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --fast) FAST=1; shift ;;
    -h|--help) sed -n '2,60p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    --) shift; PYTEST_PATHS+=("$@"); break ;;
    -*) echo "check.sh: unknown option '$1'" >&2; exit 2 ;;
    *) PYTEST_PATHS+=("$1"); shift ;;
  esac
done

if [ "$FAST" -eq 0 ] && [ "${#PYTEST_PATHS[@]}" -gt 0 ]; then
  echo "check.sh: test paths are only meaningful with --fast; the authoritative" >&2
  echo "          gate always runs the whole suite. Refusing to narrow it." >&2
  exit 2
fi
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

if [ "$FAST" -eq 1 ]; then
  echo "┌──────────────────────────────────────────────────────────────────┐"
  echo "│ FAST MODE — NOT the authoritative gate.                          │"
  echo "│ Coverage is OFF, so the 70% floor is NOT enforced here.          │"
  echo "│ A green run here does not justify a merge. CI does.              │"
  if [ "${#PYTEST_PATHS[@]}" -gt 0 ]; then
  echo "│ pytest narrowed to: ${PYTEST_PATHS[*]}"
  fi
  echo "└──────────────────────────────────────────────────────────────────┘"
  echo
fi

echo "== Backend =="
run "ruff-check" ruff check .
run "ruff-format" ruff format --check .
run "mypy" mypy lemely
run "import-linter" lint-imports
# M0.9 (#33): review-rate two-part ratchet gate. Falls back to the committed
# BUILD/review-rate-baseline.json when no fresh dev-split golden run exists
# under the gitignored tests/golden/results/, so this is always runnable —
# never SKIPped — in both modes.
run "review-rate-gate" python scripts/check_review_rate_gate.py
if [ "$FAST" -eq 1 ]; then
  # -n auto: one worker per core. --no-cov overrides the --cov addopts from
  # pyproject.toml (coverage under xdist needs combining and roughly doubles
  # the wall clock, which is the exact cost --fast exists to avoid).
  run "pytest(fast,no-cov)" pytest -q --tb=short -n auto --no-cov "${PYTEST_PATHS[@]}"
else
  run "pytest" pytest -q --tb=short
fi

echo
echo "== Web =="
run "web-typecheck" bash -c 'cd web && npm run -s typecheck'
run "web-lint" bash -c 'cd web && npm run -s lint'
run "web-build" bash -c 'cd web && npm run -s build'
# Vitest (P3.10 e3, D3.20). Absorbs the former standalone `design-tokens` gate:
# `web/scripts/check-design-tokens.mjs`'s two invariants moved into
# `web/tests/unit/design-tokens.test.ts` verbatim, as that script's own header
# said to do once a runner existed. MISSION §6 gate 3's "frontend unit tests
# green" was vacuous before this — there was no runner to be green.
run "web-test" bash -c 'cd web && npm run -s test'
if [ "$FAST" -eq 1 ]; then
  # `npx --yes` resolves impeccable from the network on every invocation, so
  # this gate's verdict depends on connectivity rather than on the tree. That
  # is tolerable for the authoritative gate and not for a per-run check.
  skip "impeccable-detect" "fast mode (network-dependent npx resolve)"
else
  run "impeccable-detect" bash -c 'cd web && npx --yes impeccable detect src/'
fi

STACK_UP=0
if [ "$FAST" -eq 0 ] && supabase status -o json >/dev/null 2>&1; then
  STACK_UP=1
fi

echo
echo "== Live-stack UI gates (Supabase local stack) =="
if [ "$STACK_UP" -eq 1 ]; then
  run "playwright-e2e" bash -c 'cd web && npm run -s test:e2e'
  run "puppeteer-audit" bash -c 'cd web && npm run -s audit'
  run "ui-thresholds" .venv/bin/python scripts/check_ui_gates.py
elif [ "$FAST" -eq 1 ]; then
  # Not "stack down" — the stack may well be up. These boot a real browser and
  # dominate the wall clock (~5 min observed), which is the whole cost --fast
  # exists to avoid. Backend-only accuracy work does not move these gates; the
  # default mode and CI still run them.
  skip "playwright-e2e" "fast mode (browser E2E — run the full gate before merge)"
  skip "puppeteer-audit" "fast mode (browser audit — run the full gate before merge)"
  skip "ui-thresholds" "fast mode (no fresh audit output — puppeteer-audit skipped)"
else
  skip "playwright-e2e" "local Supabase stack not running (supabase status failed)"
  skip "puppeteer-audit" "local Supabase stack not running"
  skip "ui-thresholds" "no fresh audit output (stack down, puppeteer-audit skipped)"
fi

echo
echo "── Summary ───────────────────────────────────────────"
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "All gates passed (${#SKIPPED[@]} skipped)."
  if [ "$FAST" -eq 1 ]; then
    echo
    echo "⚠  FAST MODE: coverage was not measured and the 70% floor was not"
    echo "   enforced$([ "${#PYTEST_PATHS[@]}" -gt 0 ] && echo ", and pytest ran only: ${PYTEST_PATHS[*]}")."
    echo "   This is NOT a merge signal. Push and let CI decide."
  fi
else
  echo "FAILED (${#FAILED[@]}): ${FAILED[*]}"
fi

[ "${#FAILED[@]}" -eq 0 ]
