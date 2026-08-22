# Improving extraction and marking accuracy — strategy list

Research and diagnosis pass over the extraction → marking → grading pipeline.
Every claim below marked **measured** was reproduced in-container against the real
artefacts in this repo; claims marked **hypothesis** were not, and say so.

Scope note: the $8 ceiling is treated as lifted for this exercise (per the
directive), so techniques D4.1 rejected purely on budget are evaluated on merit.
Per-question hand-labelling is assumed available.

---

## 0. Summary

**If one thing ships: the oracle-transcription ablation.** Today a wrong mark
cannot be attributed to the extractor or the marker, so every downstream decision
about where to spend effort is a guess. `measure_accuracy` already contains both
arms of the experiment — the `scan_path is not None` branch runs real extraction,
the `else` branch synthesises answers from ground truth — but all ten golden
fixtures ship a `scan.pdf`, so the second arm is **dead code** (measured). Running
both splits the recorded 83.8% into extraction-attributable error,
marking-attributable error, and the masked cell (wrong transcription, right mark by
luck), with no hand-labelling and no new fixtures. It reprioritises everything after
it.

**If three:** add (2) the determinism substrate — explicit temperature and seed,
generation params folded into the cache key, a cache-bypass seam, and a published
A/A churn floor; without it every A/B comparison in this programme is uninterpretable
and the response cache guarantees a false zero. And (3) one combined confidence
change: propagate extraction confidence into per-question confidence, rebuild
`_calibrate_confidence`, make a missing MCQ key abstain instead of silently scoring
zero, and un-exclude MCQ from the calibration curve. Each piece alone is either
invisible or a regression; together they are the recorded D3.21 fix.

**The single most important constraint on everything else:** the marker's
confidence signal is *degenerate*, so no threshold change can work. Across the 21
theory questions in the calibration batch it takes six distinct values — 0.65×1,
0.85×4, 0.90×1, 0.95×1, 0.96×1, **0.98×13** — and two of the three disagreements
sit at 0.98, inside the mode. D2.3 already says it: *"confidence and correctness are
close to independent."* Only a **new, independent** signal can move `flag_recall`
off 27.3% (historical; the honest post-D18 baseline is **14.29%**, n=71 —
the argument is unchanged, and the honest figure is worse, not better).

---

## 1. Where accuracy actually stands

| metric | measured | target | source |
|---|---|---|---|
| `mark_accuracy` (synthetic golden set) | **83.8%** — historical, superseded (see below) | ≥95% | D2.5 |
| `mark_accuracy` (post-D18-fix honest baseline) | **90.1%** raw (n=71 rows) / **77.4%** DA6-collapsed (n=31 leaves) | ≥95% | BUILD/DECISIONS.md DA7 |
| `flag_recall` (synthetic golden set) | **27.3%** — historical, superseded (see below) | 100% | D2.5 |
| `flag_recall` (post-D18-fix honest baseline) | **14.29%** (n=71 rows) | 100% | BUILD/DECISIONS.md DA7 |
| `flag_precision_high` (synthetic golden set) | 91.7% — historical, superseded (see below) | — | D2.2 |
| `flag_precision_high` (post-D18-fix honest baseline) | **89.8%** (n=71 rows) | — | BUILD/DECISIONS.md DA7 |
| real paper 22 (MCQ, 40) | 37 vs 34 → **+3**, **zero flags** | — | D3.21 |
| real paper 41 (theory, 80) | 63 vs 66 → **−3**, 20/80 flagged | — | D3.21 |
| mark-scheme parse coverage (0625) | **32/72** | — | D4.1 |

**M0.5/#29 update (BUILD/DECISIONS.md DA7):** the 83.8% row above predates the D18 fix
(`measure_accuracy` silently dropped any ground-truth leaf the extractor never returned
an answer for, shrinking the denominator instead of scoring it as wrong or excluding it
honestly) and predates two rounds of corpus growth (10 → 11 fixtures, 68 → 71 rows,
28 → 31 distinct leaves, DA6b). It is retained here as the historical figure only. The
honest baseline going forward is the pair recorded in the row above and in DA7: no code
path in this repo presents 83.8% as the current measurement. The n=219 paired-McNemar
floor in §6/DA1 is quoted on the legacy 83.8%→88.8% comparison and is **not**
recomputed against the new baseline by this change.

### Three reasons these numbers are weaker than they look

**(a) The 83.8% was measured on a much easier task than the real one.** Rendering
both fixtures for the same paper (`0625_s20_qp_31`) and looking at them:

| | synthetic fixture | real solved script |
|---|---|---|
| pages | 1 | 16 |
| extractable text | rendered | **0 chars** — pure image scan |
| question id | **printed beside every answer** (`Q1a_i`, `Q1b`) | absent; position is the only cue |
| handwriting | uniform TTF, no drift | red-pen cursive, baseline drift, true subscripts |
| furniture | none | question text, figures, answer lines, watermark |

The corpus **hands the extractor the question id in machine-readable type**, so
`id_match_rate` is trivially satisfiable there and mis-attribution is *structurally
impossible to observe*. Two of the fixture's own answers are also corrupted by
rendering bugs (an equation truncated off the right edge; `3.93 N` overprinted on
`clockwise`). More synthetic fixtures cannot fix this. **(measured)**

**(b) The golden corpus is flat, so whole features have never been exercised.**
All 10 fixtures have `parent_id is None` on 100% of leaves, and 6–8 leaves each.
`correct_paper` only builds `sibling_prior` when `q.parent_id is not None`, so the
**PRIOR PART RESULTS block has never been emitted in any measured accuracy run** —
the ECF feature is entirely untested. **(measured)**

**(c) On the deterministic path only one integrity check can actually fail.**
`validate_mark_scheme` checks two trivia and is warnings-only.
`Question.validate_mark_point_sum` raises only when `sum(points) > q.marks`, but
`rows.py::flush()` *assigns* `q.marks = primary_total`, making the comparison
`primary_total > primary_total` — **tautologically false**. Only the paper-level
checksum can fire, and it is the weakest at localising. **(measured)**

---

## 2. Diagnosis — verified defects

Anchored to files, reproduced in-container.

### Mark scheme (the named bottleneck: 32/72)

| # | defect |
|---|---|
| D1 | **Phantom mark points.** `0625_s19_ms_43` parses to 82 vs stated 80. Localised to three **question-number rows** whose answer cell holds an embedded data grid (a logic truth table, a D/E table, `241Am →4α +237Np`) and whose **marks cell is empty**; `rows.py:200` defaults these to `marks=1`. That is +3 phantom against a +2 total — **so a real mark is lost simultaneously. Two defects partially cancelling**, exactly the case a paper-level checksum cannot see. |
| D2 | **No mark provenance.** The parser never records whether a mark was parsed or defaulted, which is why `escalate_on_defaulted_marks` is a no-op its own docstring admits to. |
| D3 | **Operators destroyed, while arithmetic passes.** 21 of 69 answer points in the committed `0625_s20_ms_31.json` have the operator replaced by a newline: `'(p =) 148 \n 16.6'`, `'(moment =) force \n distance'`, `'(s =) d \n t in any form'`, `'density = mass \n volume'`. **The marker cannot tell multiply from divide.** These are fraction bars linearised away. Nothing catches it: `_leaf_marks` sums `q.marks`, not answer points — leaf total 78, answer-point total 68, and nothing compares them. |
| D4 | **Flattened exponents, live in the mark scheme:** `3.0 × 108 m/s` (the speed of light), `1.6 × 105 N`, `6 .0 10–3 m`, `1/2 mv2`, `g/cm3`. 18/270 lines in `s19_ms_43`. The signal is clean and bimodal — body text **11.0pt**, exponents **7.0pt**, no overlap, minus sign included. |
| D5 | **Every det-parsed theory question is typed `RECALL`** (22/22 and 41/41). So the extractor is never told to capture working on calculations — where M-mark evidence lives. The Gemini parse of the same paper gets it right: `{calculation: 9, explanation: 12, diagram: 7, …}`. |
| D6 | **The chain's safety property is inverted.** det is held to an exact checksum and rejected on a discrepancy of 1; the Gemini fallback that replaces it is checked by **nothing**. The committed AI scheme for `s20_ms_31` declares `maximum_mark: 80` while its leaves sum to **78**. |
| D7 | **A single non-canonical marks cell disqualifies a whole column.** 17 of 24 realistic CAIE notations fail `parse_marks_cell` (`"B1 dep"`, `"M1 A1"`, `"3 max"`, `"[1]"`…), and one bad cell flips `is_marks_column` to False so `_find_marks_col` returns a different column. *Mechanism proven at unit level; **hypothesis** as a cause of the 40 real failures — needs the full corpus.* |

### Marking judgment

| # | defect |
|---|---|
| D8 | **ECF fails in opposite directions on the two paths, and neither is ever correct.** det populates `parent_id`, so scoping to the immediate parent drops **10 of 29** eligible chains on `s20_ms_31` (34%) — every `(a)(i)→(b)` transition, the commonest CAIE structure; `8d_i` loses `8a`,`8b`,`8c`. Gemini leaves `parent_id` **None on 41/41 leaves**, so `None == None` is true for every leaf and the marker receives *every previously-marked question in the paper* (40 by `12c`) under the header "PRIOR PART RESULTS (same parent question)". |
| D9 | **ECF's payload is the wrong thing.** `prior_results` is `{question_id: marks_awarded}` — "1a_i: 2 mark(s) awarded". Follow-through requires the student's **incorrect value**, not their score. Even correctly scoped, the marker cannot apply ECF from what it is given. |
| D10 | **The D2.3 numeric backstop is inert on det-parsed papers.** det populates `calculated_answer` on **0/76, 0/82, 0/39** points; Gemini populates 11/69 on the same paper. Review trigger #3 is unreachable there — one of three "independent" triggers does not exist on the majority path. |
| D11 | **Consequence: raising det coverage as built would degrade marking safety.** Every paper migrated from the Gemini path to the det path loses its numeric backstop, its question types and its guidance notes. D4.1 names det coverage the highest-leverage work; done alone it improves a coverage statistic while worsening the product. |
| D12 | **Drawing and graph answers have no rubric at all.** 10 of 40 marks on `0625_m21_ms_62` are graph/drawing points, and `drawing_criteria` is populated on **zero of 149** parsed questions. A quarter of a practical paper is marked by handing a prose description of a hand-drawn graph to a model against an empty rubric, and the result carries ordinary confidence. |

### Extraction and confidence

| # | defect |
|---|---|
| D13 | **MCQ confidence is inflated, then discarded.** `_calibrate_confidence` adds +0.1 to any single-letter answer (raw 0.90 → **1.00**); the extractor prompt's own "circled both B and C" example, authored at 0.38 to represent an ambiguous read, calibrates **up to 0.51**. Then `_build_mcq_corrected` discards it and emits `1.0 / HIGH / needs_review=False`, so `attempt_repo` never queues it. Paper 22 produced zero review items **by construction**. |
| D14 | **The caps in that function are not caps.** `min(conf,0.2)` and `min(conf,0.3)` are applied *before* an unconditional `+0.03 for source_region`, so they leak to 0.23/0.33 — and the prompt instructs the model to fill `source_region` on exactly the ambiguous cases the cap protects. |
| D15 | **A missing MCQ key silently scores zero at full confidence.** `'B' == None → False` → `awarded_marks=0, confidence_score=1.0, HIGH, no flag`. A missing key is an error state, not a wrong answer. |
| D16 | **D3.21's headline attribution has an unstated premise.** `BLOCKERS.md:140` records `0625_s23_ms_22` — paper 22 itself — as *"fail — computed 12 vs max 40"* on det, rescued by the Gemini fallback. So the answer key came from the unchecked, lossy path. If one letter of 40 is wrong, that is ±1 mark with **zero vision error**. The "confidently wrong" conclusion stands; the attribution of all 3 marks to vision does not. Verifying it costs 40 characters. |
| D17 | **The positional fallback silently reassigns answers** to leftover manifest ids in order. It logs a warning but does not lower confidence, flag review, or surface anywhere. One missing answer shifts every subsequent one. |
| D18 | **`mark_accuracy` cannot see extraction failures** — `measure_accuracy` skips questions the extractor never returned, so a worse extractor returning fewer, easier questions scores *higher*. |
| D19 | **The calibration curve excludes MCQ by construction** (`if r.question_type == "theory"`), so it is structurally blind to the exact D3.21 defect. |
| D20 | **No temperature, top_p, seed or logprobs are set anywhere** in the Gemini path; extraction and marking run at the API default sampling temperature. **Thinking is disabled** for both (`thinking_budget_for` defaults to `{"mark_scheme": 8000}` only). **No image preprocessing at all** — raw PDF, one call for a 16-page script, no DPI control, page split, deskew or orientation check. |
| D21 | **The cache will silently defeat naive voting** — keyed on (model, prompt+version, file bytes), so k identical calls return k identical cached replies. Any consensus design must vary `extra_cache_key`, as the escalation ladder already does. |

---

## 3. Strategies

Ordered by tier. Effort is XS (<½ day) → XL (weeks).

### Tier 0 — measurement foundation

Nothing below Tier 0 can be validated without these. Ship first.

| # | strategy | effort | how you know it worked |
|---|---|---|---|
| **T0.1** | **Oracle-transcription ablation.** Run both existing arms of `measure_accuracy` on every golden case: arm A real extraction, arm B ground-truth answers injected. Report the 2×2 — extraction-attributable, marking-attributable, and the masked cell. | S | 83.8% splits into named components. Report as a **lower bound** on extraction share: `synth.py` cannot render a superscript or a crossing-out, so it understates. |
| **T0.2** | **Determinism substrate.** Set explicit `temperature`/`seed`, fold generation params into `_cache_key`, add a cache-bypass seam, then publish an **A/A churn floor** with its n. | S | Two identical runs differ by a stated amount. Until this exists, every A/B is uninterpretable and the cache returns a false zero. |
| **T0.3** | **Two-layer labelling protocol on real scripts.** Label (i) verbatim transcription and (ii) marks earned **per mark point** — separately, so extraction and marking error are independently attributable. Blind: the labeller must not see pipeline output (D3.21's no-back-deriving rule, enforced structurally, not by policy). | M | ~300 labelled leaves ≈ 7–8 papers (a 0625 theory paper has ~41 leaves). See §5. |
| **T0.4** | **Paired McNemar as the release gate**, replacing comparison of two headline percentages. Plus Wilson intervals, n-floors and an exclusion funnel in the report. | S | 3–5× more statistical power for the same labels (§5). |
| **T0.5** | **Frozen train/dev/test split with a test-touch ledger.** | XS | Prevents prompt-overfitting to a ~20-item eval set — the standard trap. |
| **T0.6** | **Normalise golden fixtures to carry `parent_id`, and add a nested multi-part fixture.** | S | **Blocks T1.5.** Today ECF never fires on the corpus, so a correct ECF fix measures as zero effect and gets discarded. |
| **T0.7** | **Failure-reason census over all 40 failing schemes** — count causes rather than guessing. Requires restoring the paperscraper corpus. | XS | Turns D7 from hypothesis into a ranked work-list. |
| **T0.8** | **Make "we could not read this" a first-class outcome** with an honest denominator, rather than a silent zero or a guess. | M | Abstention rate becomes a reported number instead of hiding in the accuracy figure. |

### Tier 1 — high leverage

| # | strategy | effort | why |
|---|---|---|---|
| **T1.1** | **The combined confidence change, shipped as one unit:** propagate extraction confidence into per-question confidence; rebuild `_calibrate_confidence` (delete the +0.1 MCQ bonus, fix the cap ordering); make `mcq_answer is None` abstain; un-exclude MCQ from calibration. | S | D13–D15, D19. Each piece alone is invisible or a regression — see §4. |
| **T1.2** | **Delete the positional fallback.** Emit `UNMATCHED` and carry an `id_match` provenance field into review. | S | D17. Production-standard in document AI; a silent realignment is worse than a gap. |
| **T1.3** | **Glyph-level superscript/subscript reconstruction** from `page.chars` (modal font size; smaller runs directly following a base-size char are exponents). Place beside `desymbolize()` in `det/symbols.py` so every consumer benefits. | M | D4. Signal is bimodal 11.0/7.0pt with no overlap. **Blocks any unit or sig-fig enforcement** — enforcing units against `'g/cm\n'` revokes marks from correct students. |
| **T1.4** | **Operator/fidelity gate on the fallback**, plus an answer-point sum check. Count embedded newlines in answer points; compare `sum(answer_points)` against `q.marks`. | S | D3, D6. The current reconciliation is an *arithmetic* check being mistaken for a *fidelity* check. |
| **T1.5** | **Fix ECF: scope to the top-level question, and pass the student's value, not their mark count.** | S | D8, D9. Gated on **T0.6**. |
| **T1.6** | **Make the defaulted-mark hook real.** Add `marks_defaulted` provenance at `make_point`; stop creating 1-mark points from rows with an empty marks cell; implement `escalate_on_defaulted_marks`. | S | D1, D2. Turns a documented no-op into a working check. |
| **T1.7** | **Per-mark-point binary verdicts with quoted evidence, summed in Python** — replace the holistic `awarded_marks` with one judgment per point, each carrying the span of student work that satisfied it. | M | The rubric-decomposition result from the ASAG literature, and it makes marking auditable. Also enables point-level F1 and chance-corrected agreement (QWK). |
| **T1.8** | **Coherence gate:** `awarded_marks` must reconcile with `matched_point_ids`, and those ids must exist in the scheme. | XS | A structural inconsistency signal independent of stated confidence — which is the property D2.2 proved confidence lacks. |
| **T1.9** | **Two structurally different reads, disagreement as the review trigger.** A field-guided pass and a document-guided pass have opposite failure modes, so disagreement is informative in a way self-consistency is not. | M–L | The only proposal here that manufactures a genuinely independent uncertainty signal. Mind D21. |
| **T1.10** | **Unconditional random audit sample** that no confidence signal can suppress. | S | The only trigger that can catch *confidently wrong* — by construction, every confidence-gated trigger cannot. |
| **T1.11** | **Populate `calculated_answer`, question types and guidance notes on the det path.** | M | D5, D10, D11. Precondition for det-coverage work being a net gain rather than a net loss. |
| **T1.12** | **Route review by marks-to-boundary, and optimise for grade stability rather than mark error.** | XS | The product output is a grade. A 3-mark error matters enormously 1 mark from a boundary and not at all mid-band. Nobody is using this signal. |
| **T1.13** | **Verify the MCQ answer keys.** Cross-check the rows det recovered against the fallback key; re-parse twice. | XS | D16. Forty characters converts D3.21's central inference into a measurement. |
| **T1.14** | **Inject the CAIE Generic Marking Principles the parser already extracts** into the marker prompt, and fix the A-mark dependency rule. | XS | The scheme's own published rules are parsed and then not used. |

### Tier 2 — solid

- **T2.1 Per-question / per-region cropping** instead of one call per whole script. Evidence is strong that whole-document input is the worst configuration and degrades past ~3 pages; a narrow crop is also *cheaper* in vision tokens. Now affordable with the ceiling lifted.
- **T2.2 Document anchoring** — feed the deterministic pdfplumber text and coordinates *alongside* the page image. Lemely already extracts this; close to free.
- **T2.3 Grounding** — require a verbatim quoted span plus page and bounding box per extracted answer, so an answer can be spatially verified against its question's location.
- **T2.4 Verbatim-vs-normalised dual transcription** with an explicit anti-correction contract, so the model records what is written *and* its reading, instead of silently normalising.
- **T2.5 Explicit DPI / media-resolution control** on the vision call.
- **T2.6 Scan hygiene gate** — orientation, page count against the paper, ink presence. A phone photo is the realistic input; nothing currently checks it is the right way up.
- **T2.7 Context caching** of the shared marking prefix (cached input bills at ~0.1×), making per-question and multi-pass designs cheap.
- **T2.8 Enable a thinking budget for correction**, and put the mark *after* the evidence in the response schema so reasoning precedes scoring.
- **T2.9 QP↔mark-scheme tariff join** as a per-question failure localiser — the question paper prints `[4]` and `[Total: 10]`, giving the per-question checksum the paper-level reconciler lacks.
- **T2.10 Risk-coverage curves** replacing bucketed calibration, with per-trigger breakdown and MCQ included.
- **T2.11 Label-free metamorphic tests** for the marker (e.g. reordering mark points must not change the mark).
- **T2.12 Measure the synthetic-to-real transfer gap** with a paired same-content experiment.

### Tier 3 — speculative, or later

Step-level verification for method marks (process-reward-model shaped, and the honest answer to D2.5's "free-form algebraic method verification" gap); multi-hypothesis parse with a selector; consensus entropy across models; test-time augmentation ensembles with alignment-based per-character confidence; a dedicated HTR engine alongside the VLM; fine-tuning on labelled CAIE questions; conformal/selective-risk thresholds with distribution-free guarantees; automated prompt optimisation (DSPy/GEPA); continuous seeded-gold monitoring in production; MCQ mark detection as a classical-CV problem rather than a VLM one.

---

## 4. Sequencing — what must ship together, and what must not

**Must ship as one change:**
- Extraction-confidence propagation **+** the `_calibrate_confidence` rebuild. The rebuild alone is a literal no-op (the value is discarded at the marking boundary); the propagation alone floods the queue with a signal still poisoned by the +0.1 bonus.
- Propagation **+** the paper-level grade-confidence rule. Ship the first without the second and every paper reads LOW, destroying the signal where it is consumed.

**Strict orderings:**
- Cache-bypass seam → A/A floor → *any* A/B claim.
- Golden fixtures carry `parent_id` (T0.6) → ECF fix (T1.5). **Reversed, a correct fix measures zero and gets thrown away.**
- Superscript reconstruction (T1.3) → any unit or sig-fig enforcement.
- Tariff join (T2.9) → narrow LLM repair (it produces the address the repair consumes).
- Positional-fallback removal (T1.2) → the harness change that renames and explains `id_match_rate`. Otherwise the metric drops below its target, CI fails, and someone restores the guess.

**Must NOT land together:**
- Mark-raising fixes (A-mark rule) with mark-lowering fixes (unit rule, list rule, alternative clipping). **They cancel** — D2.4's own history records two iterations netting exactly zero this way. Build the signed over-award/under-award split first.
- Multiple prompt `VERSION` bumps — each invalidates the whole cached golden corpus, so batch them or you cannot attribute the delta to any one change.
- Random audit with confidence propagation — both raise review volume; landed together neither contribution is recoverable.

---

## 5. How much to hand-label

95% Wilson interval on the measured 83.8%:

| n | 95% CI | ± |
|---|---|---|
| 100 | 75.4–89.7% | 7.2pp |
| **300** | **79.2–87.5%** | **4.2pp** |
| 1000 | 81.4–86.0% | 2.3pp |

At n=100, 83.8% and 90% are statistically indistinguishable.

Power to *prove* an improvement (80% power, α=0.05):

| target | unpaired, n/arm | **paired (McNemar), n** |
|---|---|---|
| 86.8% | 2186 | **482** |
| 88.8% | 741 | **219** |
| 91.8% | 262 | **95** |

**Target ~300 labelled leaf questions ≈ 7–8 real papers.** Stratify across MCQ /
calculation / explanation / diagram and across variants — not 8 papers of one type.
Always re-run the *same* set through both pipelines and test paired.

Start with `Sources/Physics/Solved/` — four committed real scripts, one a 40-item
MCQ paper whose scheme is already parsed. Forty letters is under an hour and it
converts D3.21's "3 marks of vision error" from an inference into a measurement.

---

## 6. How this programme could fail

**The dominant risk: building the instrument for the wrong half of the corpus.**
Every judgment strategy needs `calculated_answer`, real question types, guidance
notes and M/A/B codes. Exactly one path produces those — the Gemini fallback. So
labelling will naturally happen on Gemini-parsed schemes, the marker will be tuned
against them, and the golden corpus already *is* them — while the deterministic
path (32 of 72 papers; all-`RECALL`, zero `calculated_answer`, nested) receives a
marker fitted to a distribution it never sees. **Every number goes up and the
product does not improve for the papers that parse deterministically.** T1.11 is
the mitigation; a stratified labelling plan that deliberately covers both parse
paths is the other half.

**The secondary risk: the review queue eats the product.** Count what is proposed
to route a question to a human — sub-threshold extraction confidence on every MCQ,
cross-read disagreement, unmatched ids, structural failures, revoked values,
boundary proximity, a random audit. **No strategy here carries "total review rate
stays under X" as an acceptance criterion.** A teacher asked to check 60% of a
paper has been sold a slower way to mark by hand, and will stop — at which point
every confidence improvement is worthless because nobody consumes the signal. Set
a review budget before shipping any of T1.1/T1.9/T1.10.

**Two smaller stalls.** A third of this plan needs the paperscraper corpus (72
schemes, blank question papers, examiner reports), which is **not in this
checkout** — corpus restoration is item zero for T0.7, T2.9 and the layout work.
And `total_usd_ceiling` defaults to 8.0, is enforced against a persistent
cross-run ledger, and several proposals multiply call volume; raise it deliberately
and in advance rather than discovering it mid-campaign as an `ExternalServiceError`.

---

## Appendix — method and provenance

Diagnosis was produced by reading and **running** this repo: parsing the four real
mark schemes in `Sources/Physics/MarkingSchemes/`, comparing det against Gemini
output on the same paper, rendering and visually inspecting both a synthetic and a
real scan of `0625_s20_qp_31`, unit-testing `parse_marks_cell` against 24 CAIE
notations, executing `_calibrate_confidence`, simulating `correct_paper`'s ECF
scoping on both parse paths, and computing the power arithmetic in §5.

Strategy generation drew on a parallel research sweep (8 lanes, ~200 catalogued
techniques with sources, spanning handwriting OCR, VLM extraction engineering, PDF
table parsing, ASAG/AES and LLM-as-judge, calibration and selective prediction,
evaluation methodology, exam-board practice, and current model/API capabilities),
followed by six ideation lanes, an adversarial grounding pass per lane, and a
completeness critic. Claims from that process were re-verified against the repo
before being included here; several did not survive and were dropped or corrected.
