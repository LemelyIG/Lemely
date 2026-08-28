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
Split is `dev (pre-M0.7a)`; membership is **not frozen**. #57 is blocked — not on #44, which is CLOSED, but on #88's empty Gemini strata and on #151, which may collapse DA1's parse-path stratum axis entirely.

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
**DA9a**; the constant is #161's to fix, not a measurement issue's (this line used to cite #36, which is CLOSED and is M1.1, the confidence unit).

Both limbs are breached in every repeat (ceiling `min(10%, 29.03%)` = 10%
against ~32.6%; p95 target 15% against ~82%). The breach is not in doubt and
stays **recorded-not-blocking** while the ratchet is unarmed at M0.

**The 19.1% figure** quoted in older material is stale and was retracted by
`DA-M0.9`. Do not cite it.

---

## The oracle-transcription ablation (M0.4 / #28) — the 2×2 DOES NOT EXIST

**Published because it was attempted and did not produce a result.** A section
missing from this file would read as "not tried"; the honest record is that it
was tried, one arm is empty by construction, and the human then ruled it waits.

**The 2×2 verdict is `NOT_APPLICABLE`.** The `oracle+mark` arm produced **zero
records**, so `mcnemar()` and `ablation_2x2()` return `b = c = n_pairs = 0` and
an all-zero table. Those are **degenerate outputs reflecting missing data, not a
paired comparison**. No paired McNemar, no cross-arm Wilson comparison and no
minimum-detectable-effect figure are reportable from this run, and none should
be quoted from it.

**Ruling, 2026-08-25:** #28 stays **CLOSED with every acceptance box unticked**,
is **not** reopened, and the 2×2 **waits for #57's corpus expansion to ~300
leaves**. The 2026-08-24 spend authorisation **lapsed when the issue closed** —
and that generalises: *a spend authorisation does not survive its issue being
closed*. PR #87's arm mechanism made the 2×2 *possible*, never *authorised*.

### What the run DID measure — the `extract+mark` arm alone

| figure | value | n |
|---|---|---|
| Leaf accuracy, all | **77.4%**, Wilson [60.2%, 88.6%] | 24 / 31 |
| Leaf accuracy, `det` | **100%**, Wilson [67.6%, 100%] | 8 / 8 |
| Leaf accuracy, `gemini` | **69.6%**, Wilson [49.1%, 84.4%] | 16 / 23 |
| `review_rate_total`, all | **29.03%** | 31 |
| `review_rate_total`, `det` | **0.00%** | 8 |
| `review_rate_total`, `gemini` | **39.13%** | 23 |
| Per-paper p95 | 66.7% | 5 papers — **UNDERPOWERED** |
| Coherence trigger rate | 6.45% | 31 |
| Exclusion funnel | `total` 31, `scored` 31, **`excluded` 0** | correct 24, under 6, unmatched 1 |

**`det` at 8/8 is not evidence that det marks perfectly.** n=8 gives a Wilson
lower bound of **67.6%** — the interval is consistent with the det path being
worse than the gemini path. Quote the interval, never the point.

**The per-paper p95 rests on 5 papers.** It is printed because omitting it would
be selective, not because it resolves anything.

Run `ablation-2026-08-24-a` · sha `1435cebf` · split `dev` (**not frozen**) ·
evidence in `BUILD/accuracy-runs/ablation-2026-08-24-a/` · analyses computed by
`lemely.eval.analyses` over the committed records with **no Gemini calls and no
reruns**.

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

## Det-path defect rates (M1 / #38, #136) — measured 2026-08-27

Published because they change how every det-path figure above should be read.

| figure | value | n |
|---|---|---|
| Papers with ≥1 **defaulted** mark | **44.4%** | 24 / 54 parsed, from a 60-PDF random sample |
| Papers where *every* point is defaulted | 9.3% | 5 / 54 |
| **All answer points defaulted** | **21.6%** | 596 / 2,754 |

A *defaulted* mark is one the parser minted rather than read: `rows.py:200`
falls back to `marks=1` when `parse_marks_cell` finds nothing. Countable only
because #38 shipped the `marks_defaulted` flag first.

**Most of that 21.6% is correct — by luck.** The default of 1 is right for
`B1`/`M1`/`A1`/`C1` and wrong for every multi-mark code. So **"defaulted" is not
by itself evidence of a wrong mark**, and a bare defaulted-count is the wrong
escalation trigger: arming it as written would route ~44% of the det corpus to
the paid path on a signal that is mostly right.

**Cause, named at source with the arithmetic closing exactly (DA21):**
`rows.py:311` drops a continuation row carrying marks but no answer text;
`rows.py:200` defaults where the marks column merged into the answer cell.

**Consequence for reading the ablation above:** the det arm's 8/8 sits on a path
where a fifth of all answer points carry a minted mark. A paper can be
**under-sum because of the parser**, not because of a marking defect.

---

## Metamorphic properties (M1.8 / #58) — live, cache bypassed

Label-free properties that must hold regardless of ground truth.

| property | result | n |
|---|---|---|
| Renaming mark-point ids | **57 held / 0 violated / 14 skipped** | live, `bypass` |
| Normalising answer whitespace | **7 held / 0 violated / 0 skipped** | live, `bypass`, 2026-08-27 |
| Reordering mark points | **30 held / 1 VIOLATED / 40 skipped** | live, `bypass` |

**The reorder property is violated and is NOT ticked.** `0625_s20_qp_31` q11b
awards 1 → 2 on reorder. It **reproduces**: 2/10 fresh perturbed repeats against
**0/14** unperturbed markings of the same leaf.

**And it is not established.** Pre-committed Fisher exact, two-sided:
**p = 0.4737** at n=10/arm. The post-hoc pooled p = 0.0717 is secondary and is
never the finding. **It has not been re-run at higher n, and must not be** —
MISSION §12.9 forbids chasing significance.

So the honest statement is: *a property a live run falsifies is not ticked, and
a violation this corpus cannot establish is not a claim.* Both halves hold.

**The whitespace figure is 7 live outcomes, not 78.** Only 1 of 12 golden cases
carries collapsible whitespace; the other 71 leaves are no-ops under the
transform, determined offline by string comparison with **no marking call**, and
flagged `determined_offline` in the artifact.

---

## Parse-path composition (#151 / ruling C6) — counted 2026-08-27

Not a model. Counted over the 289 committed schemes at `parser_sha 8758dba`,
and it reconciles exactly with #41's independent 10,314-point census.

| paper_type | schemes | answer points |
|---|---|---|
| theory_extended | 87 | 4,692 (45.5%) |
| **mcq** | **79** | **0 (0.0%)** |
| theory_core | 73 | 3,649 (35.4%) |
| practical | 26 | 1,031 (10.0%) |
| alternative_practical | 24 | 942 (9.1%) |

**MCQ schemes carry zero `answer_points`** — MCQ answers live in the separate
`mcq_answer` field. Published because it is load-bearing for an open decision:
restricting deterministic parsing to MCQ would retire **210 of 289 schemes
(72.7%)** and **10,314 of 10,314 answer points (100%)** from the det path.

**That routing is NOT happening — ruling C11 (2026-08-27) superseded C6**
(DA27). det parses all mark schemes and marks MCQ; Gemini does all extraction
and marks non-MCQ, which is the architecture already in place. The costs once
published here — one-off $11.92–$14.71, recurring $25.23–$28.02 — **priced a
migration that never occurs**. Struck rather than deleted, so the correction
stays legible.

**The composition figures above stand on their own**, independent of any ruling:
they are a **count over the committed corpus**, not a projection. They are
published because they made the C6 reading's blast radius visible, and because
the det/Gemini split they describe is **DA1's stratum axis** — which survives
C11 and which #57's split depends on.

**The gap this table does not show:** 289 schemes parse, but **190 of 479 fail
the det parser outright** and have no parsed output at all. Closing that is #88.

**Measured 2026-08-27 under ruling C20, and the answer is worse than the cost
question it was asked about.** A budget-bounded sweep (hard cap $3.00, the live
ledger re-read before every scheme) attempted 24 of them: **12 parsed, 12 failed
— 50%**, and the failure is **systematic by size**, not random.

| syllabus | parsed / attempted |
|---|---|
| 0580 | 9 / 11 (82%) |
| 0625 | 3 / 9 (33%) |
| **0606** | **0 / 4 (0%)** |

Failures average **10.0 pages / 11,637 chars** against **7.3 / 8,608** for
successes. **Not output truncation** — the limit is 65,536 tokens and the largest
success used 26,571. **Not fully deterministic** — the n=1 probe failed, then
succeeded unchanged.

**So the Gemini parse path closes roughly half of the 190-scheme gap, not the
gap.** The sweep is **NOT REPORTABLE** for its stated purpose: four DA1 strata
(`0606/p1`, `0606/p2`, `0625/p4`, `0625/p5`) got **zero** successes, so the
stratum coverage the spend was justified by was not delivered. The 12 parsed
schemes are kept and **must not be presented as coverage**. Cost per *success*
was **$0.2372**, 3.39× the projection, extrapolating to **$45.08** for all 190.

**This was invisible until now because the 2026-08-26 run aborted at 6 of 190 on
cost — and all 6 happened to succeed.** An abort is not a pilot. Open as **#166**
(DA31); the remaining decision is whether to spend ~$0.15 of the $2.01 headroom
diagnosing it.

---

## Spend

Re-summed across all four worktree ledgers at 2026-08-28, **never carried
forward from a header** (that rule exists because carrying it forward had
reproduced the previous run's arithmetic error every run).

| | |
|---|---|
| **Cumulative, programme-wide** | **$5.993470** |
| **Committed hard ceiling** | **$8.00** — `lemely/runtime/config.py:111` |
| Headroom | **$2.006530** |
| ~~Local override~~ | ~~$25.00 in `lemely.toml`~~ — **REMOVED 2026-08-27 by ruling C12 (DA28)** |
| ~~Token ceiling~~ | ~~5,000,000 `per_run_token_ceiling`~~ — **REMOVED 2026-08-27 by ruling C21 (DA32)**; the dollar ceiling is now the sole guard |

The programme-wide figure is the sum of four files:

| worktree ledger | USD |
|---|---|
| `Lemely-worktrees/accuracy` | 5.588999 |
| `Lemely` | 0.402869 |
| `Lemely-worktrees/subject-name-primary-identifier` | 0.000961 |
| `Lemely-worktrees/research-accuracy-tuning` | 0.000640 |

**The enforcing guard does not see that sum.** `GeminiClient` builds its ledger
path from `settings.paths.output_dir` (`gemini.py:162`), so the ceiling check at
`gemini.py:298` reads only the **local** worktree's file — it would allow $2.411
here against a programme headroom of $2.007. Recorded in DA32; publish the sum,
never the local file.

**$2.847 of the total is C20's sweep**, which held its own $3.00 cap exactly.

**The ceiling published here used to read $25.00, and that was wrong.** The
$25.00 lives in `lemely.toml`, which is gitignored: it does not survive worktree
deletion and **CI cannot see it**. The only durable ceiling is the committed
**$8.00** default, and every headroom figure must be sized against that. This is
DA13's hazard class, and publishing the local value made this file assert
headroom the programme does not durably have.

**`cumulative_usd` is a conservative UPPER BOUND on money spent, not money
spent** (DA17, amending DA11). Some tests resolve `paths.output_dir` to the real
repo and write mock-derived costs into the authoritative ledger (#114). The
contamination is **one-directional**, so every ceiling check stays conservative;
the contaminated portion cannot be reconstructed, because the file keeps one
running total with no history.

Pre-M0.2 ledger figures understate real spend by 2–4×; figures from #26 onward
use corrected GA pricing. **`output_tokens` already includes `thoughts_tokens`**
— pricing input + output alone reproduces the ledger to the cent, and adding
thoughts on top overshoots. Anyone re-deriving spend must not add them.
