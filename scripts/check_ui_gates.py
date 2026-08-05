#!/usr/bin/env python3
"""Enforce the axe/Lighthouse thresholds from BUILD/QUALITY-BAR.md.

Checks the most recent `npm run audit` output (web/scripts/audit.mjs)
so scripts/check.sh fails the build the same way a human reviewer would
reject the diff.

Reads reports/phase-2.5/axe/_summary.json and
reports/phase-2.5/lighthouse/_summary.json — the per-route summaries the audit
runner writes on every run. Does not run the audit itself; scripts/check.sh
runs `npm run audit` first and only calls this on fresh output.

Gates (QUALITY-BAR.md "Accessibility"):
  - zero serious or critical axe violations, per route
  - Lighthouse accessibility score >= 95, per route
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AXE_SUMMARY = REPO_ROOT / "reports/phase-2.5/axe/_summary.json"
LH_SUMMARY = REPO_ROOT / "reports/phase-2.5/lighthouse/_summary.json"
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
                f"minor={counts['minor']}) — see reports/phase-2.5/axe/{route['slug']}.json"
            )

    for route in lighthouse:
        score = route["scores"].get("accessibility")
        if score is None or score < ACCESSIBILITY_FLOOR:
            failures.append(
                f"lighthouse: {route['slug']} accessibility score {score} < "
                f"{ACCESSIBILITY_FLOOR} — see reports/phase-2.5/lighthouse/{route['slug']}.json"
            )

    if failures:
        print(f"{len(failures)} UI gate violation(s):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(
        f"UI gates clean: {len(axe)} route(s) zero serious/critical axe, "
        f"Lighthouse accessibility >= {ACCESSIBILITY_FLOOR} on all."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
