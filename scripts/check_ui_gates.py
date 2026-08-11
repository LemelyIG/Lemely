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
  - Lighthouse performance score >= 80, **student routes only**
  - zero console errors, across the whole run
  - zero horizontal-scroll violations, across the whole run

The performance gate arrived in P6.1, closing D4.25. From Phase 2.5 to Phase 5
this script had no performance check at all, while MISSION §11 and four phase
reports described "performance >= 80 on the student routes" as a standing
automated check — so a green ``ui-thresholds`` was cited as a performance pass
it never measured. By Phase 5 eight routes sat below 80 and the gate stayed
green.

Scoped to the student portal because that is exactly how MISSION §11 words the
floor ("performance >= 80 on the student routes"); it has never claimed one for
teacher or parent routes. Their scores are reported in the phase report and
DELIVERY.md rather than gated, which is the honest reading — inventing a floor
MISSION does not state would be as wrong as ignoring the one it does. A route
counts as a student route by ``path`` (the ``/student`` subtree), not by slug
prefix, so a future student screen slugged off-convention cannot escape it.
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
PERFORMANCE_FLOOR = 80
STUDENT_PATH_PREFIX = "/student"


def is_student_route(route: dict) -> bool:
    """True for rows in the ``/student`` portal subtree.

    ``path`` is written by ``web/scripts/audit.mjs`` from P6.1 onward. Report
    dirs baselined before that (phases 2.5-5) have no ``path`` key, so the slug
    prefix is the documented fallback rather than a silent "not a student
    route" — which would make the gate pass by omission on an old corpus, the
    exact failure mode this gate exists to end.
    """
    path = route.get("path")
    if path is not None:
        return path == STUDENT_PATH_PREFIX or path.startswith(STUDENT_PATH_PREFIX + "/")
    return route["slug"].startswith("student-")


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
        if not is_student_route(route):
            continue
        performance = route["scores"].get("performance")
        if performance is None or performance < PERFORMANCE_FLOOR:
            failures.append(
                f"lighthouse: {route['slug']} performance score {performance} < "
                f"{PERFORMANCE_FLOOR} (MISSION §11 floor, student routes) — "
                f"see {REPORT_DIR}/lighthouse/{route['slug']}.json"
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

    student_routes = [r for r in lighthouse if is_student_route(r)]
    print(
        f"UI gates clean: {len(axe)} route(s) zero serious/critical axe, "
        f"Lighthouse accessibility >= {ACCESSIBILITY_FLOOR} on all "
        f"({len(lighthouse)} route report(s)), performance >= {PERFORMANCE_FLOOR} on "
        f"{len(student_routes)} student route(s), zero console errors, "
        f"zero horizontal-scroll violations."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
