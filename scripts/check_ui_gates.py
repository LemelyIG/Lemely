#!/usr/bin/env python3
"""Enforce the axe/Lighthouse/console/responsive thresholds from BUILD/QUALITY-BAR.md.

Checks the most recent `npm run audit` output (web/scripts/audit.mjs)
so scripts/check.sh fails the build the same way a human reviewer would
reject the diff.

Reads <report-dir>/axe/_summary.json, <report-dir>/lighthouse/_summary.json,
<report-dir>/console-errors.json and <report-dir>/responsive-summary.json —
all four written by the audit runner on every run. Does not run the audit
itself; scripts/check.sh runs `npm run audit` first and only calls this on
fresh output.

``<report-dir>`` comes from ``LEMELY_REPORT_DIR`` (repo-relative or absolute)
and defaults to the gitignored scratch dir ``reports/.scratch``, so a routine
gate run never overwrites a committed phase baseline. Re-baselining is the
explicit act of naming the phase:
``LEMELY_REPORT_DIR=reports/phase-3 npm run audit`` (see web/scripts/audit.mjs).

Gates (QUALITY-BAR.md "Accessibility", MISSION.md §11 "standing automated
checks" — P3.10 chunk b makes the latter two real gates instead of numbers
only ever read by a human):
  - zero serious or critical axe violations, per route
  - Lighthouse accessibility score >= 95, per route
  - zero console errors, across the whole run
  - zero horizontal-scroll violations, across the whole run
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Keep this default byte-identical to audit.mjs's, or the gate reads a
# different directory than the audit runner just wrote.
DEFAULT_REPORT_DIR = "reports/.scratch"
REPORT_DIR = Path(os.environ.get("LEMELY_REPORT_DIR") or DEFAULT_REPORT_DIR)
if not REPORT_DIR.is_absolute():
    REPORT_DIR = REPO_ROOT / REPORT_DIR
AXE_SUMMARY = REPORT_DIR / "axe/_summary.json"
LH_SUMMARY = REPORT_DIR / "lighthouse/_summary.json"
CONSOLE_ERRORS = REPORT_DIR / "console-errors.json"
RESPONSIVE_SUMMARY = REPORT_DIR / "responsive-summary.json"
ACCESSIBILITY_FLOOR = 95


def main() -> int:
    if not AXE_SUMMARY.exists() or not LH_SUMMARY.exists():
        print(f"missing {AXE_SUMMARY} or {LH_SUMMARY} — run `npm run audit` in web/ first")
        return 1

    axe = json.loads(AXE_SUMMARY.read_text())
    lighthouse = json.loads(LH_SUMMARY.read_text())

    failures: list[str] = []

    for route in axe:
        counts = route["counts"]
        bad = counts["critical"] + counts["serious"]
        if bad:
            failures.append(
                f"axe: {route['slug']} has {counts['critical']} critical + "
                f"{counts['serious']} serious violation(s) (moderate={counts['moderate']}, "
                f"minor={counts['minor']}) — see {REPORT_DIR}/axe/{route['slug']}.json"
            )

    for route in lighthouse:
        score = route["scores"].get("accessibility")
        if score is None or score < ACCESSIBILITY_FLOOR:
            failures.append(
                f"lighthouse: {route['slug']} accessibility score {score} < "
                f"{ACCESSIBILITY_FLOOR} — see {REPORT_DIR}/lighthouse/{route['slug']}.json"
            )

    # console-errors.json/responsive-summary.json predate this gate in some
    # older report dirs (a stale re-baseline never regenerated) — missing is
    # "not checked", not "clean", so it's reported rather than silently passed.
    if CONSOLE_ERRORS.exists():
        console_errors = json.loads(CONSOLE_ERRORS.read_text())
        if console_errors:
            failures.append(
                f"console: {len(console_errors)} error(s) collected across the run — "
                f"see {CONSOLE_ERRORS}"
            )
    else:
        failures.append(f"missing {CONSOLE_ERRORS} — run `npm run audit` in web/ first")

    if RESPONSIVE_SUMMARY.exists():
        responsive_violations = json.loads(RESPONSIVE_SUMMARY.read_text())
        for v in responsive_violations:
            failures.append(
                f"responsive: {v['slug']} has horizontal overflow at {v['bpWidth']}px "
                f"(scrollWidth {v['scrollWidth']} > clientWidth {v['clientWidth']}) — "
                f"see {RESPONSIVE_SUMMARY}"
            )
    else:
        failures.append(f"missing {RESPONSIVE_SUMMARY} — run `npm run audit` in web/ first")

    if failures:
        print(f"{len(failures)} UI gate violation(s):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(
        f"UI gates clean: {len(axe)} route(s) zero serious/critical axe, "
        f"Lighthouse accessibility >= {ACCESSIBILITY_FLOOR} on all, zero console errors, "
        f"zero horizontal-scroll violations."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
