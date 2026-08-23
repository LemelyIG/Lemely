# ACCURACY-REPORT.md — published figures for the accuracy programme

Every number the accuracy programme publishes lives here, with its n, its
denominator, and a pointer to the raw evidence. A figure that is not in this
file has not been published, and a figure here without an n is a bug.

**Reading rule:** no comparison in this programme is interpretable without the
A/A churn floor below. A delta smaller than the floor is noise. Say "within
noise", not "a small improvement".

---

## The A/A churn floor (M0.3 / #27) — published 2026-08-23

Ten repeats of the golden set at byte-identical configuration, cache bypassed.
This is the instrument measuring its own noise: every difference between these
repeats is churn, because nothing changed between them.

| figure | value | n |
|---|---|---|
| **Pairwise leaf-outcome churn** | **11.61%** | 162 / 1395 pair-leaf comparisons (45 pairs × 31 leaves) |
| Per-pair spread | 0.0% – 19.35% | 45 pairs |
| Leaves that ever churned | **9 of 31**, Wilson [16.1%, 46.6%] | 31 leaves |
| Churn, `det` path | **0.00%** | 0 / 360 |
| Churn, `gemini` path | **15.65%** | 162 / 1035 |

**The rule.** Any A/B delta on the **gemini** path below **11.6pp** is *within
noise*. The **det** path floor is **0.0%**, measured at n=360 — an arm touching
only det behaviour is not subject to the pooled figure. Quote the path-specific
floor whenever an arm is path-specific.

**Why no Wilson interval on 162/1395:** the 45 pairs re-use the same 10 runs, so
those comparisons are not independent. The per-pair range is the honest spread.
The Wilson interval is quoted only on 9/31, which is a clean binomial.

**Scope — what this run does not show.** Single-arm, so no A/B effect of any
kind. n=31 leaves against the n=219 paired-McNemar improvement floor (DA7).
Split is `dev (pre-M0.7a)`; membership is not frozen (#57 waits on #44).

Run `aa-floor-2026-08-23-a` · sha `b364bf76` · `gemini-2.5-flash` ·
`cache_mode=bypass`, `cache_hit_detected=false` on all 10 repeats across ~740
real calls · cost $0.958711 · evidence in
`BUILD/accuracy-runs/aa-floor-2026-08-23-a/` · decision record **DA9**.

---

## Leaf accuracy on the golden corpus

| figure | value | n | source |
|---|---|---|---|
| **Pooled over 10 repeats** | **75.8%** | 235 / 310 leaf-repeats | DA9a, this run |
| Per-repeat range | 67.7% – 80.6% (stdev 3.5pp) | 10 repeats | DA9a |
| Single-run honest baseline | 77.4% | 24 / 31 leaves | DA8, `2026-08-22-79f5fa8.json` |
| Raw per-row, no DA6 collapse | 90.1% | 64 / 71 rows | DA8 |

DA8's 77.4% is the **modal** draw (5 of 10 repeats), so it is representative and
stands — but it is one sample from a ~13pp spread. **Prefer the pooled 75.8%**
and cite 24/31 as the single-run draw it is. Per-repeat Wilson intervals at n=31
are ~0.50–0.91 wide: **this corpus cannot resolve anything finer than ~10pp**,
before the churn floor is applied.

The gap between 90.1% raw and 75.8% collapsed is the DA6 unanimity rule, not a
discrepancy: a leaf counts correct only if every fixture variant of it is
correct. Both are published; publishing only the flattering one would be the
denominator shell game D18 existed to create.

---

## Review rate (M0.9 / #33) — re-measured live 2026-08-23

| figure | value | n |
|---|---|---|
| `review_rate_total`, mean over 10 repeats | **32.58%** | 31 leaves × 10 |
| Per-repeat range | **29.03% – 41.94%** | 10 repeats |
| `review_rate_signal` | identical to `total` (no `random_audit` fired) | — |
| Per-paper p95, mean | 82.1% (range 66.7% – 85.7%) | 10 repeats |
| Committed constant | 29.03% | `config.py:168`, `review-rate-baseline.json` |

**The committed 29.03% is the bottom of the observed range** — the value that
came up on the 3 luckiest of 10 identical repeats. It is a best case, not a
central estimate. Arming `min(10%, last_merged_review_rate)` against it would
gate the build on a number that unchanged code exceeds 7 times in 10. See
**DA9a**; the constant is #36's to fix, not a measurement issue's.

Both limbs are breached in every repeat (ceiling `min(10%, 29.03%)` = 10%
against ~32.6%; p95 target 15% against ~82%). The breach is not in doubt and
stays **recorded-not-blocking** while the ratchet is unarmed at M0.

**The 19.1% figure** quoted in older material is stale and was retracted by
`DA-M0.9`. Do not cite it.

---

## Exclusion funnel and abstention discipline

Across all 10 repeats: `scored = total = 31`, **`excluded = 0`**. The 71→31
collapse is a DA6 merge, not a drop.

**0 `abstain` outcomes exist in this corpus** — the observed vocabulary is
`correct` 627, `under` 60, `over` 16, `unmatched` 7 over 710 raw rows.
`unmatched` sits **in** the denominator and is never counted correct (#29/D18).
The abstention machinery is therefore **unexercised by this corpus**, which is a
gap in coverage, not evidence that it works.

---

## Spend

| | |
|---|---|
| This run | $0.958711 |
| Cumulative | **$1.425511** |
| Ceiling | $25.00 (notify at 50% / 80%) |

Pre-M0.2 ledger figures understate real spend by 2–4×; figures from #26 onward
use corrected GA pricing and count `thoughts_token_count` (0 on every call here).
