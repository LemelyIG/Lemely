r"""MISSION §13 clause 5 — Gemini marking accuracy in its own terms. ZERO SPEND.

Clause 5 requires **both paths measured in their own terms**: det **parse
coverage** (now 331 of 479, DA34/DA39/DA41) and **Gemini marking accuracy**.
The det half is measured; this computes the Gemini half from data already on
disk — `aa-floor-2026-08-23-a`'s per-repeat records carry `parse_path`.

**Method validated before use.** The leaf collapse here — a leaf counts correct
iff every one of its fixture-variant rows is correct — reproduces the published
`wilson_mark_accuracy_per_repeat` successes **exactly on all 10 repeats**. Only
then is it split by path.

**The n that matters is 23, not 230.** The 10 repeats re-mark the SAME 31 leaves
under an identical fingerprint, so pooling them does not create independent
observations. Both numbers are reported so the difference is visible rather than
assumed away.
"""

from __future__ import annotations

import glob
import json
import math
from collections import defaultdict
from pathlib import Path

Z = 1.959963984540054
OUT = Path("BUILD/accuracy-runs/path-accuracy-2026-08-29")
SRC = "BUILD/accuracy-runs/aa-floor-2026-08-23-a"


def wilson(k: int, n: int) -> tuple[float, float, float]:
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = k / n
    d = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / d
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


per_repeat: dict[str, dict] = {}
for f in sorted(glob.glob(f"{SRC}/records-repeat-*.jsonl")):
    rid = f.split("repeat-")[1][:2]
    leaves: dict[tuple[str, str], list[str]] = defaultdict(list)
    path: dict[tuple[str, str], str] = {}
    for line in open(f):
        r = json.loads(line)
        key = (r["paper_id"], r["question_id"])
        leaves[key].append(r["outcome"])
        path[key] = r["parse_path"]
    coll = {k: all(o == "correct" for o in v) for k, v in leaves.items()}
    per_repeat[rid] = {
        "n": len(coll),
        "correct": sum(coll.values()),
        "by_path": {
            p: {
                "correct": sum(1 for k, v in coll.items() if path[k] == p and v),
                "n": sum(1 for k in coll if path[k] == p),
            }
            for p in ("det", "gemini")
        },
    }

# --- validation gate: the collapse must reproduce the published successes ---
pub = json.load(open(f"{SRC}/analysis-aa-churn-floor.json"))["wilson_mark_accuracy_per_repeat"]
mismatches = [
    rid for rid in per_repeat if per_repeat[rid]["correct"] != pub[f"repeat-{rid}"]["successes"]
]
assert not mismatches, f"collapse does not reproduce published successes: {mismatches}"

result: dict[str, object] = {
    "purpose": "MISSION §13 clause 5 — Gemini marking accuracy in its own terms",
    "spend_usd": 0.0,
    "source_run": "aa-floor-2026-08-23-a",
    "collapse_validated_against_published_successes": True,
    "per_repeat": per_repeat,
}

for p in ("det", "gemini"):
    ks = [per_repeat[r]["by_path"][p]["correct"] for r in sorted(per_repeat)]
    n_leaves = per_repeat["01"]["by_path"][p]["n"]
    # honest n: one repeat's distinct leaves, at the mean success count
    k_mean = round(sum(ks) / len(ks))
    pt_h, lo_h, hi_h = wilson(k_mean, n_leaves)
    # naive n: pooling repeats as if independent (reported to be refused, not used)
    pt_p, lo_p, hi_p = wilson(sum(ks), n_leaves * len(ks))
    result[p] = {
        "distinct_leaves": n_leaves,
        "per_repeat_correct": ks,
        "mean_correct": round(sum(ks) / len(ks), 2),
        "accuracy_point": round(pt_h, 4),
        "wilson_at_honest_n": [round(lo_h, 4), round(hi_h, 4)],
        "half_width_pp_honest": round((hi_h - lo_h) / 2 * 100, 2),
        "wilson_if_repeats_pooled_NAIVE": [round(lo_p, 4), round(hi_p, 4)],
        "half_width_pp_naive": round((hi_p - lo_p) / 2 * 100, 2),
    }

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "path-accuracy.json").write_text(json.dumps(result, indent=2) + "\n")
for p in ("det", "gemini"):
    d = result[p]
    print(
        f"{p:7s} {d['mean_correct']}/{d['distinct_leaves']} = {d['accuracy_point']:.3f}  "
        f"honest 95% [{d['wilson_at_honest_n'][0]:.3f}, {d['wilson_at_honest_n'][1]:.3f}] "
        f"(±{d['half_width_pp_honest']}pp)   naive-pooled ±{d['half_width_pp_naive']}pp"
    )
