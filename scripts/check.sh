#!/usr/bin/env bash
# scripts/check.sh — the one gate command (MISSION.md §6/§8b/§11).
#
# Runs every quality gate for a change in one shot, suppresses passing
# output, and prints only failures plus a one-line PASS/FAIL/SKIP per tool.
# Never invoke ruff/mypy/pytest/tsc/oxlint/etc individually — run this.
#
# Backend and web build/test gates always run. The live-stack UI gates
# (Playwright E2E, the Puppeteer audit runner, and the axe/Lighthouse threshold
# check) need the local Supabase stack (`supabase start`) plus a reachable
# backend they boot themselves; when the stack isn't up they SKIP (not FAIL)
# with an explanation, mirroring the existing pytest DB-integration-test skip
# pattern, rather than blocking gates that don't need it.
#
# Those three plus `impeccable-detect` are additionally SCOPED TO THE DIFF: they
# read only web/, so a change touching no web/ file skips them with that as the
# stated reason. The scope is computed from the diff and never chosen by the
# caller — `--all-gates` forces them on, nothing forces them off, and an
# uncomputable diff runs them. See the long comment at the scoping block.
#
# Every gate's full output is written to reports/.scratch/sweep/<gate>.log and
# left there. Failures print the first 60 lines and always name the log path.
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
ALL_GATES=0
PYTEST_PATHS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --fast) FAST=1; shift ;;
    --all-gates) ALL_GATES=1; shift ;;
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

# Per-gate logs are PERSISTED, not scratched. They used to go to a `mktemp -d`
# removed by an EXIT trap, and only the first 60 lines were ever echoed — then
# the supervisor truncated check.sh's *combined* output to 60 lines again on the
# way to the next run's prompt. Two truncations and a delete: `impeccable-detect`
# was recorded as "unknown, no evidence" across six consecutive sweeps
# (BUILD/BLOCKERS.md, "The gap underneath all three") when in fact it had been
# printing three specific findings the whole time. A gate whose evidence does
# not outlive the process is a gate nobody can act on.
LOG_DIR="reports/.scratch/sweep"
rm -rf "$LOG_DIR"
mkdir -p "$LOG_DIR"

# ── Gate scoping: the design and live-stack UI gates read only web/ ─────────
#
# `impeccable-detect`, `playwright-e2e`, `puppeteer-audit` and `ui-thresholds`
# scan `web/src` or drive the built frontend. A change that touches no file
# under `web/` cannot move any of them, so running them on such a change yields
# a verdict about somebody else's code. When that verdict is red for an
# unrelated reason — which it has been since the live gates first became
# runnable (BUILD/BLOCKERS.md, "the same three web gates, six sweeps running") —
# every backend run opens with a FAIL header, and a permanently-red gate trains
# its reader to skim. That has already nearly cost something real: when a
# genuine pytest regression joined the standing list, the only thing separating
# it from the noise was reading the failure list item by item.
#
# This is NOT a weaker gate, and the distinction is the whole point:
#
#   * The scope is computed from the DIFF, not chosen by the caller. There is
#     no flag that switches a gate off for a change it covers.
#   * Any change touching web/ runs all four, exactly as before.
#   * `--all-gates` forces them on; nothing forces them off.
#   * If the diff cannot be computed, the gates RUN. Failing safe means
#     running the gate, never skipping it.
#
# What this does not fix: these four now run only when someone edits web/, so a
# standing red there can sit unnoticed for longer. They still have no CI home
# (`ci.yml`'s web job stops at `npm run build`), which BLOCKERS.md already flags
# as "a gate that only ever runs on one machine is a gate nobody is accountable
# to". Scoping makes the backend signal readable; it does not give these an
# owner. That is still open.
web_touched() {
  [ "$ALL_GATES" -eq 1 ] && return 0
  local base
  base="$(git merge-base HEAD origin/develop 2>/dev/null \
       || git merge-base HEAD develop 2>/dev/null)" || return 0
  [ -n "$base" ] || return 0
  # `git diff <base>` (one commit, no --cached) compares base against the
  # WORKING TREE, so committed and uncommitted edits are both covered in one
  # call — check.sh gates the working tree, not HEAD. Untracked files are not
  # in a diff at all, hence the second command.
  {
    git diff --name-only "$base" -- web/ 2>/dev/null
    git ls-files --others --exclude-standard -- web/ 2>/dev/null
  } | grep -q .
}

WEB_SCOPE_REASON=""
if web_touched; then
  WEB_GATES=1
else
  WEB_GATES=0
  WEB_SCOPE_REASON="diff touches no web/ file (--all-gates overrides)"
fi

FAILED=()
SKIPPED=()

run() {
  local name="$1"
  shift
  local log="$LOG_DIR/$name.log"
  if ( "$@" ) >"$log" 2>&1; then
    echo "PASS   $name"
  else
    echo "FAIL   $name"
    sed -n '1,60p' "$log" | sed 's/^/       /'
    local lines
    lines=$(wc -l <"$log")
    if [ "$lines" -gt 60 ]; then
      echo "       … $((lines - 60)) more lines"
    fi
    # Named on every failure, so a truncated hand-off still says where the
    # evidence is rather than losing it.
    echo "       full log: $LOG_DIR/$name.log"
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
elif [ "$WEB_GATES" -eq 0 ]; then
  skip "impeccable-detect" "$WEB_SCOPE_REASON"
else
  run "impeccable-detect" bash -c 'cd web && npx --yes impeccable detect src/'
fi

STACK_UP=0
if [ "$FAST" -eq 0 ] && [ "$WEB_GATES" -eq 1 ] && supabase status -o json >/dev/null 2>&1; then
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
elif [ "$WEB_GATES" -eq 0 ]; then
  skip "playwright-e2e" "$WEB_SCOPE_REASON"
  skip "puppeteer-audit" "$WEB_SCOPE_REASON"
  skip "ui-thresholds" "$WEB_SCOPE_REASON"
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
  echo "Full per-gate logs: $LOG_DIR/<gate>.log"
fi

[ "${#FAILED[@]}" -eq 0 ]
