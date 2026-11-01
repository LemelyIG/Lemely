#!/usr/bin/env bash
# LIVE audit: the Puppeteer audit and the UI threshold gates (PLAN section 0.7, LIVE).
#
# The same lock, port, clean-tree, database and verification protocol as
# live_e2e.sh, so this is that script's `--audit` form: `npm run audit`, then
# `python scripts/check_ui_gates.py` on its fresh output.
#
# Usage: bash scripts/tutoring/live_audit.sh <dedicated|shared>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

exec bash "$ROOT/scripts/tutoring/live_e2e.sh" --audit "$@"
