r"""#161 / ruling C13 — restate the review rate DISTRIBUTION-AWARE. Zero spend.

Ruling C13: *"the ratchet publishes an UPPER INTERVAL BOUND of the measured
distribution and arms against that — NOT the mean (half of no-op diffs would
fail), NEVER 29.03%."*

The published 0.2903 is ONE DRAW from a range already measured at ~13
percentage points wide. This script re-derives the statistic from the EXISTING
10-repeat A/A floor (`aa-floor-2026-08-23-a`) — no new measurement, per MISSION
12.9, which forbids re-running to chase a tighter number.

**Which upper bound, and why this one.** The gate compares ONE future run
against the ceiling, so the right object is an upper bound on the PREDICTIVE
distribution of a single new run — not a confidence interval on the mean. A CI
on the mean narrows as n grows and would let the ceiling drift below the spread
that unchanged code actually produces; that is the DA9a trap in a new costume.

Primary statistic: the 95th percentile of the beta-binomial predictive for a
new run's flagged-leaf count, with a Jeffreys Beta(1/2,1/2) prior updated on the
pooled 101/310 leaf-repeats. Read as: *unchanged code exceeds this rate about
5% of the time.*

**A conservatism check that matters.** Per-run counts are LESS dispersed than
binomial (observed sd 1.20 against binomial sd 2.61 at the same mean), because
the same 31 leaves recur every repeat and most are deterministic. Under-
dispersion means the binomial-based predictive bound is WIDER than the truth,
which is the safe direction for a gate: it errs toward not failing unchanged
code. Stated rather than hidden, because it also means this bound must not be
sold as tight.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path("/home/sico/Lemely-worktrees/accuracy")
AA = ROOT / "BUILD/accuracy-runs/aa-floor-2026-08-23-a/analysis-aa-churn-floor.json"
OUT = ROOT / "BUILD/accuracy-runs/ratchet-161-2026-08-28"

aa = json.loads(AA.read_text())
per = aa["review_rate_per_repeat"]
n_leaves = aa["n_distinct_leaves"]

rates = [per[k]["review_rate_total"] for k in sorted(per)]
p95s = [per[k]["per_paper_p95"] for k in sorted(per)]
counts = [round(r * n_leaves) for r in rates]
n_rep = len(rates)

# every repeat must be the same denominator, else pooling is invalid
assert {per[k]["n"] for k in per} == {n_leaves}, "repeats do not share a denominator"
# spec 5/7 invariant: total == signal until random_audit exists
assert all(
    per[k]["review_rate_total"] == per[k]["review_rate_signal"] for k in per
), "review_rate_total != review_rate_signal in the source run"

mean = sum(rates) / n_rep
sd = math.sqrt(sum((r - mean) ** 2 for r in rates) / (n_rep - 1))

successes, trials = sum(counts), n_leaves * n_rep
a, b = successes + 0.5, trials - successes + 0.5  # Jeffreys posterior


def beta_binom_pmf(k: int, n: int, a: float, b: float) -> float:
    return math.exp(
        math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
        + math.lgamma(k + a) + math.lgamma(n - k + b) - math.lgamma(n + a + b)
        - (math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b))
    )


pmf = [beta_binom_pmf(k, n_leaves, a, b) for k in range(n_leaves + 1)]
cdf, acc = [], 0.0
for p in pmf:
    acc += p
    cdf.append(acc)

k95 = next(k for k, c in enumerate(cdf) if c >= 0.95)
bound = k95 / n_leaves

# binomial sd at the pooled mean, for the under-dispersion check
p_hat = successes / trials
binom_sd = math.sqrt(n_leaves * p_hat * (1 - p_hat)) / n_leaves

# truncate DOWN at 4dp: a ceiling must only ever tighten when rounded
published = math.floor(bound * 10_000) / 10_000

result = {
    "issue": 161,
    "ruling": "C13 - publish an upper interval bound, arm against that",
    "source_run": aa["run_label"],
    "spend_usd": 0.0,
    "n_repeats": n_rep,
    "n_distinct_leaves": n_leaves,
    "observed_rates": rates,
    "observed_counts": counts,
    "mean": round(mean, 6),
    "sd_between_repeats": round(sd, 6),
    "min": min(rates),
    "max": max(rates),
    "range_width_pp": round((max(rates) - min(rates)) * 100, 2),
    "pooled": {"successes": successes, "trials": trials, "p_hat": round(p_hat, 6)},
    "predictive_upper_bound_95": {
        "k": k95,
        "rate": round(bound, 6),
        "published_truncated_4dp": published,
        "reading": "an unchanged run exceeds this about 5% of the time",
    },
    "dispersion_check": {
        "observed_sd": round(sd, 6),
        "binomial_sd_at_p_hat": round(binom_sd, 6),
        "under_dispersed": sd < binom_sd,
        "note": "under-dispersed, so the binomial-based bound is WIDER than truth - conservative for a gate, and not to be sold as tight",
    },
    "observed_runs_exceeding_bound": sum(1 for r in rates if r > bound),
    "per_paper_p95_distribution": {
        "values": p95s,
        "mean": round(sum(p95s) / len(p95s), 6),
        "max": max(p95s),
    },
    "the_29_03_figure": {
        "value": 0.2903,
        "what_it_actually_is": "the MINIMUM of the 10 observed rates, not a central estimate",
        "runs_at_or_below_it": sum(1 for r in rates if r <= 0.2903),
        "runs_above_it": sum(1 for r in rates if r > 0.2903),
    },
}
(OUT / "restatement.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
