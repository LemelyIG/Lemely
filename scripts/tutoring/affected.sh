#!/usr/bin/env bash
# AFFECTED: the test files a change can break, computed from imports (PLAN section 0.7).
#
#   bash scripts/tutoring/affected.sh --paths <changed files...>
#   bash scripts/tutoring/affected.sh --diff <base> <head>
#   add --run to run the list through pytest.sh (and --dry-run to only print that command)
#   bash scripts/tutoring/affected.sh --show-pins    the hub modules and their pin lists
#
# Prints the test files, space-separated on one line, and the count on stderr.
# The work is done by affected_tests.py (stdlib ast); see its docstring.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# The calculator is stdlib-only, so a tree without a .venv (CI, a bare checkout)
# can still run it with the system interpreter.
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi

exec "$PY" "$ROOT/scripts/tutoring/affected_tests.py" "$@"
