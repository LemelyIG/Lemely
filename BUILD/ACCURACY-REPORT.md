# ACCURACY-REPORT.md — published figures for the accuracy programme

Every number the accuracy programme publishes lives here, with its n, its
denominator, and a pointer to the raw evidence. A figure that is not in this
file has not been published, and a figure here without an n is a bug.

**Reading rule:** no comparison in this programme is interpretable without the
A/A churn floor below. A delta smaller than the floor is noise. Say "within
noise", not "a small improvement".

> ## ⛔ PROGRAMME RETIRED 2026-08-29 (ruling C26, DA51) — and a population warning
>
> These figures are **final**; nothing here will be re-measured. Read them with
> `BUILD/ACCURACY-FINAL-REPORT.md`, which says what they add up to and what they
> do not.
>
> **EVERY mark-scheme figure below that cites a denominator of 479, 289 or 190 is
> AS-OF THE 479-SCHEME POPULATION** — question papers 2019–2025 only. On
> 2026-08-29 the corpus expanded to **1,130 canonical schemes (2010–2025)** and
> corpus-wide det parse coverage is **393 of 1,130 = 34.8%**, not the 69.1% those
> sections imply (DA50). The 2019–2025 sub-population still measures 331 of 477,
> so those analyses are **not wrong — they are narrower than they read**. Each is
> a true statement about the easy decade.
>
> They are deliberately **not rewritten**. Re-deriving them over 1,130 schemes was
> never done, and back-filling a denominator without re-running the analysis would
> manufacture figures rather than restate them. The scope note is the honest fix;
> a recomputed table would not be.
>
> **This banner exists because its absence was a live defect.** DA50 landed in
> `DECISIONS.md`, `JOURNAL.md` and the state header on 2026-08-29 and never
> reached this file, so the clause-5 section went on publishing *"det parse
> coverage MET, now 331 of 479"* after that had been falsified. Fourth instance of
> the DA45/DA46/DA48 stale-claim pattern; first one found in the report itself.

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

## Marking accuracy BY PATH (§13 clause 5) — computed 2026-08-29, zero spend

§13 clause 5 requires **both paths measured in their own terms**. The det half is
**parse coverage**; this section is the other half, computed from
`aa-floor-2026-08-23-a`'s records, which already carry `parse_path`.

**Corrected 2026-08-29 (DA50, retirement walk).** This paragraph read *"now 331
of 479"* and the clause-5 verdict below read *"det parse coverage MET"*. Both
were written against the **479-scheme** population and were **not restated when
the corpus expanded to 1,130 schemes the same day** — #189 landed DA50 in
`DECISIONS.md`, `JOURNAL.md` and the state header but **did not touch this
file**. Corpus-wide det parse coverage is **393 of 1,130 = 34.8%**, not 69.1%:

| population | schemes | exact | rate |
|---|---|---|---|
| 2019–2025 | 477 | 331 | 69.4% |
| 2010–2018 | 299 | 62 | 20.7% |
| **all (canonical)** | **1,130** | **393** | **34.8%** |

The 2019–2025 row **reproduces the earlier 331 exactly**, which is what makes the
two populations comparable rather than merely different. Nothing regressed — the
earlier figure was measured on the easy decade. Evidence:
`BUILD/accuracy-runs/corpus-expanded-2026-08-29/RESULT.md`.

This was the **fourth** instance of the DA45/DA46/DA48 pattern — a claim accurate
when written that rotted in place — and the first found in this file.

| path | leaves | correct (mean of 10 repeats) | accuracy | 95% Wilson at the honest n |
|---|---|---|---|---|
| **det** | 8 | 8.0 / 8 | **100%** | **67.6% – 100%** (±16.2pp) |
| **gemini** | 23 | 15.5 / 23 | **69.6%** | **49.1% – 84.4%** (±17.6pp) |

**Method validated before use:** the leaf collapse reproduces the published
`wilson_mark_accuracy_per_repeat` successes **exactly on all 10 repeats**, and
the script asserts it.

**The headline blends a 100% path with a 70% path — and the weighting is
backwards relative to what matters.** MCQ schemes carry **zero** `answer_points`
(DA23); the Gemini path carries **10,314 of 10,314**. So the path responsible for
every answer point in the corpus measures **69.6%**, while the headline is pulled
upward by a path carrying none of them.

**det's 100% is not evidence the det path is perfect** — 8 MCQ leaves from one
paper, whose own Wilson lower bound is **67.6%**.

**Pooling the 10 repeats would fake the precision.** They re-mark the *same* 31
leaves under an identical fingerprint, so they are not independent observations.
Pooling reports ±6.0pp (gemini) and ±2.3pp (det) instead of ±17.6 and ±16.2. The
naive figures are recorded in the artifact **to be refused, not used**.

**Clause 5 status at retirement: BOTH HALVES SHORT.** det parse coverage is
**measured** — 393 of 1,130, 34.8% — but the clause asks for the det path to be
measured in its own terms, and a coverage figure that fell by half the moment the
population stopped being the easy decade is a measurement of the corpus as much as
of the parser. Gemini marking accuracy is **MEASURED BUT NOT TO SCOPE**: the
clause asks for a figure covering 10,314 answer points; this covers 23 leaves of
one golden corpus. Closing that needed #47's labelled corpus, which does not
exist — `eval/labels/` holds only `.gitkeep`.

Artifacts: `BUILD/accuracy-runs/path-accuracy-2026-08-29/`.

## Review rate (M0.9 / #33) — re-measured live 2026-08-23

| figure | value | n |
|---|---|---|
| `review_rate_total`, mean over 10 repeats | **32.58%** | 31 leaves × 10 |
| Per-repeat range | **29.03% – 41.94%** | 10 repeats |
| `review_rate_signal` | identical to `total` (no `random_audit` fired) | — |
| Per-paper p95, mean | 82.1% (range 66.7% – 85.7%) | 10 repeats |
| Committed constant, **restated 2026-08-28 under C13** | **0.4838** | `config.py`, DA33 |
| ~~Previous constant~~ | ~~29.03%~~ | the **minimum** of the ten — **all 10 of 10** unchanged repeats exceeded it |

**0.4838 is the 95th percentile of the beta-binomial predictive distribution for a
single new run** (Jeffreys prior on the pooled 101/310 leaf-repeats). Predictive,
not a confidence interval on the mean: the gate judges *one* run, and a CI on the
mean narrows with n until it sits inside the spread unchanged code produces.

**The restatement did NOT unblock arming, and DA33 measured why.** All four gate
limbs fail — signal 3.6×, total 2.9×, p95 **5.6×** — and three fail on absolute
targets `review_rate_last_merged` cannot touch. While the measured rate is above
the 10% target the ratchet limb is pinned by `review_rate_total_target`, and **no
value of the constant moves it**. Arming needs the review rate to come down.

**29.03% is the bottom of the observed range** — the value that came up on the
**4** luckiest of 10 identical repeats (02, 03, 06, 09, all at 9/31). It is a best
case, not a central estimate. Arming `min(10%, last_merged_review_rate)` against it
would gate the build on a number **all 10 of 10** unchanged repeats exceed as
stored (the constant was truncated down from 0.29032258…; 6 of 10 exceed the exact
value). See **DA33**.

> **Corrected at retirement (DA51).** This paragraph read *"the 3 luckiest"* and
> *"unchanged code exceeds 7 times in 10"*. Recounted directly from
> `analysis-aa-churn-floor.json`, the per-repeat flagged counts are
> `[11, 9, 9, 10, 10, 9, 11, 13, 9, 10]` — **four** at the minimum, not three; and
> **10 of 10** exceed the stored constant, not 7. The 7-in-10 figure was DA9a's
> *estimate*, superseded by DA33's measurement and never restated here.
>
> **The committed constant is no longer 29.03% either.** Under ruling C13 (#161,
> DA33) `review_rate_last_merged` is **0.4838**, the 95th percentile of the
> beta-binomial predictive for one new run. That restatement did **not** unblock
> arming, which was its finding.

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

**Re-measured 2026-08-29 on the FIXED parser, as ruling C2 required.** The
2026-08-27 figures were contaminated by DA21 mechanism (B); #136 fixed it, so
these are the clean rate. Both arms over the same 397 papers.

| figure | contaminated | **clean** |
|---|---|---|
| Papers with ≥1 **defaulted** mark | 44.58% | **34.26%** (136 / 397) |
| Papers where *every* point is defaulted | 25 papers | **3 papers (0.76%)** |
| **All answer points defaulted** | 22.05% | **8.94%** (2,000 / 22,372) |

**Mechanism (B) was 59% of the signal** — 2,928 of 4,928 defaulted points. Where
the marks column merged into the answer cell the code arrived as trailing text,
`parse_marks_cell` saw nothing, and every such point defaulted. Those codes are
now recovered and are not flagged, because a mark read from the wrong column was
still *read*, not minted.

A *defaulted* mark is one the parser minted rather than read: `rows.py:200`
falls back to `marks=1` when `parse_marks_cell` finds nothing. Countable only
because #38 shipped the `marks_defaulted` flag first.

> **Rates superseded (DA46, PR #184).** The `44.4%` of papers / `21.6%` of points
> in this section are the **pre-#136 figures from a 60-PDF sample (54 parsed)**,
> measured while the mark-total defects were still inflating the defaulted count.
> The clean rates over **397 det-parsed papers** are **34.26% of papers** and
> **8.94% of answer points**. The argument below is unchanged and is if anything
> stronger at the lower rate; only the magnitudes move.

**Most of that 21.6% is correct — by luck.** The default of 1 is right for
`B1`/`M1`/`A1`/`C1` and wrong for every multi-mark code. So **"defaulted" is not
by itself evidence of a wrong mark**, and a bare defaulted-count is the wrong
escalation trigger: arming it as written would route **34%** of the det corpus to
the paid path on a signal that is mostly right — and that path is itself measured
failing on ~50% of the schemes det cannot parse (#166 / DA35).

**What the clean rate makes affordable for the first time:** a trigger on *"every
point in the paper is defaulted"* is now **3 papers of 397**, down from 25. A
paper where **no** mark was read is suspect in a way one minted mark is not.
**Proposed, not armed** — it routes papers to the same fallback as the #110 and
#39 detectors, so all three are one cost-and-coverage decision, and it is the
human's.

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

**The gap this table does not show:** 289 schemes parsed, but **190 of 479
failed the det parser outright** and had no parsed output at all. Closing that is
#88.

**That gap shrank on 2026-08-28, at zero cost.** #136 named and fixed four
mark-total defects in the det parser — two that lose marks (a marks-only
continuation row discarded whole; a mark code leaked into the answer text
defaulting to 1) and two that invent them (numeric data-table rows minting a
mark each; **parenthesised mark cells being summed**, when CAIE brackets an
*alternative* route to the same allocation). Measured over all 479 source
schemes with both arms re-parsing the PDFs:

| | before | now |
|---|---|---|
| reconcile **exactly** with the printed maximum | **289** | **331** |
| still not exact | **190** | **148** |
| corpus-wide overcount | 845 marks | **349** |
| leaves lost to duplicate-id collapse | 57 | **25** |
| schemes carrying duplicate leaf ids | 34 | **15** |
| phantom (contentless) leaves inflating the denominator | 58 | **0** |

*(The intermediate figures were 333 exact / 146 not-exact after #136 alone; #112
then removed double-counted alternative routes from 2 papers that had been
reconciling by cancellation — see DA39, where reconciliation is recorded as a
**confounded** criterion for that fix.)*
| total overcount across over-counting schemes | 845 marks | **349 marks** |

**+47 newly exact, −3 regressed, net +44** — and the three regressions are named
in DA34 rather than folded into the pass. They were previously exact **by
cancellation**, not by correctness, which is the whole reason the two defect
classes had to be fixed together: opposite-sign errors hide each other.

**No awarded mark has moved yet.** The harness reads pre-parsed
`mark_scheme.json` and never invokes the det parser, so the marking effect
appears only when #95 regenerates the fixtures — which this unblocks.

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

**So the Gemini parse path closes roughly half of the gap, not the gap** — and
the gap it is measured against is now **148**, not 190. It fell to 146 after
#136 and rose by 2 when #112 removed double-counted alternative routes from
papers that had been reconciling *by cancellation* — a rise that is the fix
working, not regressing (DA39). The sweep is **NOT REPORTABLE** for its stated purpose: four DA1 strata
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

**FINAL — re-summed across all four worktree ledgers at retirement, 2026-08-29**,
by reading each file rather than carrying a figure forward from a header (that
rule exists because carrying it forward had reproduced the previous run's
arithmetic error every run — and the table this replaces is why it matters).

| | |
|---|---|
| **Cumulative, programme-wide** | **$6.370451** |
| **Committed hard ceiling** | **$8.00** — `lemely/runtime/config.py:111` |
| Headroom, never spent | **$1.629549** |
| ~~Local override~~ | ~~$25.00 in `lemely.toml`~~ — **REMOVED 2026-08-27 by ruling C12 (DA28)** |
| ~~Token ceiling~~ | ~~5,000,000 `per_run_token_ceiling`~~ — **REMOVED 2026-08-27 by ruling C21 (DA32)**; the dollar ceiling is now the sole guard |

The programme-wide figure is the sum of four files, each read at close:

| worktree ledger | USD | last written |
|---|---|---|
| `Lemely-worktrees/accuracy` | 5.965980 | 2026-08-28T20:43:20Z |
| `Lemely` | 0.402869 | 2026-08-17T19:03:37Z |
| `Lemely-worktrees/subject-name-primary-identifier` | 0.000961 | 2026-08-18T11:30:55Z |
| `Lemely-worktrees/research-accuracy-tuning` | 0.000640 | 2026-08-14T21:56:57Z |

> **This table was stale when the retirement walk found it.** It read **$5.993470**
> cumulative with the accuracy ledger at **5.588999** — a re-sum taken earlier on
> 2026-08-28, before that ledger's final write at 20:43:20Z the same day. The
> ceiling was never at risk either way, and no decision turned on the difference.
> Recorded because it is the **second** stale figure this file was found publishing
> at retirement (the first being clause 5's det coverage, DA51), and because the
> paragraph immediately above it is a rule against exactly this. A rule written
> into a document does not enforce itself.

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
