#!/usr/bin/env bash
# Run pytest on NAMED test files only, against the tree this script lives in.
#
# This is the only way the tutoring build runs pytest locally (PLAN section 0.7,
# PYT). It refuses zero arguments, any directory, `tests`, and any path that is
# not an existing tests/**/*.py file (a `file::test` node id is allowed), so a
# lane can never start the whole suite by accident. It always passes --no-cov
# (the 70 percent coverage floor is CI's gate, not a local one) and
# `-p no:cacheprovider`, pins PYTHONPATH to this tree, and prints
# `lemely.__file__` first so the evidence shows which tree was imported.
#
# Usage: bash scripts/tutoring/pytest.sh [-x] [-v] [-s] [-k EXPR] [-m EXPR]
#            [--tb=MODE] [--maxfail=N] [--durations=N] [--collect-only]
#            <tests/...py[::test]>...
#
# TUTORING_DRY_RUN=1 validates the arguments and prints the command that would
# run, as `DRY-RUN <argv>`, without starting Python.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

refuse() {
  echo "pytest.sh: refusing: $*" >&2
  exit 2
}

[ "$#" -gt 0 ] || refuse "no arguments. Name test files under tests/; the whole suite is CI's job, never a local run"

args=()
files=0
while [ "$#" -gt 0 ]; do
  arg="$1"
  shift
  case "$arg" in
    -x | -v | -vv | -s | -l | --showlocals | --collect-only | --co)
      args+=("$arg")
      ;;
    --tb=* | --maxfail=* | --durations=*)
      args+=("$arg")
      ;;
    -k | -m)
      [ "$#" -gt 0 ] || refuse "option $arg needs an expression"
      args+=("$arg" "$1")
      shift
      ;;
    -*)
      refuse "option '$arg' is not allowed (coverage, config and rootdir overrides are pinned by the wrapper)"
      ;;
    *)
      path="${arg%%::*}"
      suffix="${arg#"$path"}"
      case "$path" in
        /*)
          case "$path" in
            "$ROOT"/*) path="${path#"$ROOT"/}" ;;
            *) refuse "'$arg' is outside this tree ($ROOT)" ;;
          esac
          ;;
        ./*) path="${path#./}" ;;
      esac
      case "$path" in
        '' | tests | tests/) refuse "'$arg' names the whole tests directory, not a file" ;;
        ../* | */../* | */..) refuse "'$arg' contains a '..' segment" ;;
      esac
      [ ! -d "$ROOT/$path" ] || refuse "'$arg' is a directory; name test files"
      case "$path" in
        tests/*.py) ;;
        *) refuse "'$arg' is not a tests/**/*.py file" ;;
      esac
      [ -f "$ROOT/$path" ] || refuse "'$arg' does not exist in this tree"
      args+=("$path$suffix")
      files=$((files + 1))
      ;;
  esac
done

[ "$files" -gt 0 ] || refuse "no test file named; options alone would run nothing useful"

# No `-q` here: pyproject's addopts already carries one, and a second makes
# `-qq`, which drops the final "N passed, M skipped" line the evidence rules
# (PLAN section 0.8, "0 skipped") are read from.
cmd=("$PY" -m pytest --no-cov -rs -p no:cacheprovider "${args[@]}")

if [ "${TUTORING_DRY_RUN:-}" = "1" ]; then
  printf 'DRY-RUN'
  printf ' %q' "${cmd[@]}"
  printf '\n'
  exit 0
fi

export PYTHONPATH="$ROOT"
export PYTEST_ADDOPTS=""
echo "pytest.sh: tree $ROOT"
"$PY" -c 'import lemely; print("lemely.__file__ =", lemely.__file__)'
exec "${cmd[@]}"
