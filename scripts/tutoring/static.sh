#!/usr/bin/env bash
# STATIC: the non-pytest Python steps of the CI `test` job, against this tree.
#
# ruff check, ruff format --check, mypy, pyright, lint-imports and the review
# rate gate (PLAN section 0.7 and the gate table in section 4). Runs every step,
# prints PASS or FAIL per tool, and exits 1 if any failed.
#
# PYTHONPATH is pinned to this tree and pyright gets a generated config whose
# `extraPaths` is this tree (pyright_config.py), because the shared venv's
# editable install points at the MAIN checkout: without both, mypy, pyright and
# import-linter could judge another tree's code and certify it for this one.
#
# Usage: bash scripts/tutoring/static.sh [--only <step>]
#   steps: ruff-check ruff-format mypy pyright import-linter review-rate-gate
#
# TUTORING_DRY_RUN=1 prints `STEP <name><TAB><command>` per selected step and
# runs nothing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
VENV_BIN="$ROOT/.venv/bin"
PY="$VENV_BIN/python"
PYRIGHT="${TUTORING_PYRIGHT:-$VENV_BIN/pyright}" # TUTORING_PYRIGHT: a test seam for the zero-files guard
PYRIGHT_CONFIG="$ROOT/.omc/pyright-tutoring.json"
LOG_DIR="$ROOT/.omc/static-logs"

refuse() {
  echo "static.sh: refusing: $*" >&2
  exit 2
}

STEPS=(ruff-check ruff-format mypy pyright import-linter review-rate-gate)

only=""
if [ "$#" -gt 0 ]; then
  [ "$1" = "--only" ] || refuse "unknown argument '$1' (usage: static.sh [--only <step>])"
  [ "$#" -eq 2 ] || refuse "--only needs a step name (one of: ${STEPS[*]})"
  only="$2"
  found=0
  for s in "${STEPS[@]}"; do
    [ "$s" = "$only" ] && found=1
  done
  [ "$found" -eq 1 ] || refuse "unknown step '$only' (one of: ${STEPS[*]})"
fi

step_text() {
  case "$1" in
    ruff-check) echo "$VENV_BIN/ruff check ." ;;
    ruff-format) echo "$VENV_BIN/ruff format --check ." ;;
    mypy) echo "$VENV_BIN/mypy lemely" ;;
    pyright) echo "$PY $ROOT/scripts/tutoring/pyright_config.py --root $ROOT && $PYRIGHT -p $PYRIGHT_CONFIG --stats" ;;
    import-linter) echo "$VENV_BIN/lint-imports" ;;
    review-rate-gate) echo "$PY scripts/check_review_rate_gate.py" ;;
  esac
}

step_run() {
  case "$1" in
    ruff-check) "$VENV_BIN/ruff" check . ;;
    ruff-format) "$VENV_BIN/ruff" format --check . ;;
    mypy) "$VENV_BIN/mypy" lemely ;;
    pyright)
      "$PY" "$ROOT/scripts/tutoring/pyright_config.py" --root "$ROOT"
      local out checked rc=0
      out="$("$PYRIGHT" -p "$PYRIGHT_CONFIG" --stats)" || rc=$?
      printf '%s\n' "$out"
      # A config pyright cannot apply (for example an absolute `include`) makes
      # it check no file and report "0 errors", which must not read as a pass.
      checked="$(sed -n 's/^Total files checked: *//p' <<<"$out")"
      if [ -z "$checked" ] || [ "$checked" -eq 0 ]; then
        echo "static.sh: pyright checked no files; a pass would prove nothing" >&2
        return 1
      fi
      return "$rc"
      ;;
    import-linter) "$VENV_BIN/lint-imports" ;;
    review-rate-gate) "$PY" scripts/check_review_rate_gate.py ;;
  esac
}

selected=()
for s in "${STEPS[@]}"; do
  if [ -z "$only" ] || [ "$only" = "$s" ]; then
    selected+=("$s")
  fi
done

if [ "${TUTORING_DRY_RUN:-}" = "1" ]; then
  for s in "${selected[@]}"; do
    printf 'STEP %s\t%s\n' "$s" "$(step_text "$s")"
  done
  exit 0
fi

export PATH="$VENV_BIN:$PATH"
export PYTHONPATH="$ROOT"
export MYPY_CACHE_DIR="$ROOT/.mypy_cache"
mkdir -p "$LOG_DIR"

echo "static.sh: tree $ROOT"
failed=()
summary=()
for s in "${selected[@]}"; do
  log="$LOG_DIR/$s.log"
  echo "== $s: $(step_text "$s")"
  if step_run "$s" >"$log" 2>&1; then
    echo "PASS $s"
    summary+=("$s=PASS")
  else
    echo "FAIL $s (log: $log)"
    head -n 80 "$log" | sed 's/^/    /'
    lines="$(wc -l <"$log")"
    if [ "$lines" -gt 80 ]; then
      echo "    ... $((lines - 80)) more lines in $log"
    fi
    failed+=("$s")
    summary+=("$s=FAIL")
  fi
done

echo "STATIC: ${summary[*]}"
if [ "${#failed[@]}" -gt 0 ]; then
  echo "static.sh: FAILED: ${failed[*]}" >&2
  exit 1
fi
