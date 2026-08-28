r"""#47 / C24 — is H7's 10% double-labelled sample big enough to do its job?

ZERO SPEND, pure arithmetic on figures already fixed by the issues.

#47 targets **>=300 distinct leaves**, justified there by a 95% Wilson interval
of +/-4.2pp on 83.8%. #51 (H7) specifies **10% of labelled leaves** independently
marked by labeller B, and states H7's purpose plainly: without inter-annotator
agreement "there is no ceiling on how good the pipeline can honestly be said to
be".

A ceiling is only useful if it is measured at least as precisely as the thing it
bounds. This computes both intervals on the same footing and asks whether that
holds. Nothing here is a recommendation — the sizing decision is the human's.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path("/home/sico/Lemely-worktrees/accuracy/BUILD/accuracy-runs/two-seat-47-2026-08-29")
Z = 1.959963984540054  # 95%


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float, float]:
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


def half_width_pp(k_rate: float, n: int) -> float:
    _, lo, hi = wilson(round(k_rate * n), n)
    return (hi - lo) / 2 * 100


def n_for_half_width(rate: float, target_pp: float, cap: int = 20000) -> int:
    for n in range(10, cap):
        if half_width_pp(rate, n) <= target_pp:
            return n
    return -1


LEAVES = 300
OVERLAP_SHARE = 0.10
overlap = round(LEAVES * OVERLAP_SHARE)

# #47's own justification, restated on the same footing.
acc_rate = 0.838
acc_p, acc_lo, acc_hi = wilson(round(acc_rate * LEAVES), LEAVES)

rows = []
for agree in (0.80, 0.85, 0.90, 0.95, 1.00):
    p, lo, hi = wilson(round(agree * overlap), overlap)
    rows.append({
        "assumed_agreement": agree,
        "n_overlap": overlap,
        "wilson_low": round(lo, 4),
        "wilson_high": round(hi, 4),
        "half_width_pp": round((hi - lo) / 2 * 100, 2),
        "n_needed_for_pm4.2pp": n_for_half_width(agree, 4.2),
        "share_of_300_that_would_require": round(n_for_half_width(agree, 4.2) / LEAVES, 3),
    })

payload = {
    "issues": "47 (C24) / 51 (H7)",
    "spend_usd": 0.0,
    "leaves_target": LEAVES,
    "h7_overlap_share": OVERLAP_SHARE,
    "h7_overlap_leaves": overlap,
    "pipeline_accuracy_interval_at_n300": {
        "point": round(acc_p, 4), "low": round(acc_lo, 4), "high": round(acc_hi, 4),
        "half_width_pp": round((acc_hi - acc_lo) / 2 * 100, 2),
        "note": "#47 cites +/-4.2pp; this recomputes it rather than quoting it",
    },
    "h7_agreement_interval_at_10pct": rows,
}
(OUT / "overlap_power.json").write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload, indent=2))
