# Extraction and Marking Accuracy Programme — Design Spec

**Date:** 2026-08-17
**Author:** Yassin Diab (lemelyig@gmail.com)
**Status:** Approved — ready for implementation planning (M0 and M1)
**Revision:** v2 — rewritten after an adversarial review pass (13 blockers, 31 majors).
Changes from v1 are listed in §12.
**Source:** `docs/ACCURACY-STRATEGIES.md` (commit `72d3127`)

---

## Summary

`docs/ACCURACY-STRATEGIES.md` diagnoses 21 defects across the extraction → marking →
grading pipeline and proposes ~35 strategies across four tiers. This spec turns that
list into an executable programme: a decomposition into six milestones, an
architectural decision about where the evaluation instrument lives, the sequencing
constraints that must hold, and the acceptance gates each milestone must pass.

The programme is a **measurement programme first and an engineering programme
second**. The source document's central argument is that a wrong mark cannot
currently be attributed to the extractor or the marker, so every decision about
where to spend effort is a guess. Nothing in Tier 1 or above can be *validated*
until that changes.

Three findings from the verification pass (§2) reshape the brief:

1. **The system already spends 19.1% of a teacher's attention on review** — 13 of 68
   records, 95% Wilson [11.5%, 30.0%] — and catches 3 of 11 wrong marks. The agreed
   review budget is ≤10%. The programme is therefore a *net-reduction* brief: roughly
   double flag recall (3/11 → ≥6/11) while cutting signal-driven volume from 19.1% to
   ≤8%. It is not an additive one.
2. **The measurement corpus is corrupt, and in a direction that inverts M0.4's
   headline.** The synthetic renderer overprints and clips long answers, and the
   handwriting font has no glyph for `θ` or `π` — both render as `.notdef`. Ground
   truth the scan does not contain would be booked as extraction error. Repairing the
   renderer is now the first item in the programme (M0.0), before the ablation whose
   whole purpose is attribution.
3. **The "wrong half of the corpus" risk in §6 of the source document is not a risk;
   it is the present state, at 100%.** Every deterministically parsed mark scheme is
   typed `mcq` or `recall`, carries zero `calculated_answer` values, and carries zero
   `drawing_criteria`.

## Goals

1. **Attribution** — split the honest baseline `mark_accuracy` into
   extraction-attributable error, marking-attributable error, and the masked cell
   (wrong transcription, right mark by luck).
2. **Interpretability** — no A/B claim without a published A/A churn floor and a
   paired test. Today the response cache guarantees a false zero.
3. **Honest denominators** — a question the extractor never returned must not
   silently improve the score. Abstention becomes a reported outcome that counts
   against accuracy.
4. **Ground truth on real scripts** — ~300 blind-labelled leaf questions covering
   both parse paths, so the instrument measures the product rather than a synthetic
   proxy of it.
5. **Repair what is provably broken** — a set of defects that need no experiment to
   justify, each shipped with a regression test.
6. **Stay inside the review budget** — `review_rate_signal ≤ 8%` and
   `review_rate_total ≤ 10%`, enforced in CI, without letting flag recall fall below
   the M0 baseline.

## Non-Goals

- Tier 3 speculative work (fine-tuning, dedicated HTR engines, conformal
  prediction, DSPy/GEPA prompt optimisation).
- Detailed planning of M3 and M4. Their content is conditioned on measurements that
  do not yet exist. They are scoped here and re-planned when M0 and M2 produce
  numbers.
- Raising deterministic mark-scheme coverage (the 32/72 → higher work). Per D11,
  done before M3 this actively degrades the product; it is gated behind parse-path
  parity.
- **D12 (drawing/graph rubrics) beyond parsing.** M3 populates `drawing_criteria`
  on the det path; making the marker *consume* it is M4 work and is not specified
  here.

---

## 1. Terminology

| term | meaning |
|---|---|
| **arm** | Which pipeline configuration produced a record. `extract+mark` runs real vision extraction; `oracle+mark` injects ground-truth answer text and runs marking only. |
| **leaf** | A question with `marks > 0` and no sub-parts — the unit the marker operates on. |
| **distinct leaf** | A leaf counted once per paper, not once per fixture variant. The golden set has **28 distinct leaves** replayed across `correct`/`partial`/`wrong` into **68 records**. Interval and power arithmetic uses distinct leaves; the two must never be conflated (§2.3(b)). |
| **parse path** | `det` (deterministic pdfplumber parser) or `gemini` (AI fallback). The two produce structurally different mark schemes. |
| **review rate** | Fraction of **question-level** `EvalRecord` rows (`mark_point_id is None`) whose `triggers` list is non-empty. Reported pooled over the frozen dev split *and* as a per-paper distribution. `review_rate_signal` excludes the random audit; `review_rate_total` includes it. |
| **A/A churn** | Disagreement rate between two identical runs with the cache bypassed. The noise floor below which any A/B delta is meaningless. |
| **honest baseline** | `mark_accuracy` after M0.0 (corpus repair) and M0.5 (abstentions in the denominator). Supersedes the historical 83.8% as the comparison point for every later milestone. |

---

## 2. Verification pass

Every claim below was reproduced against the working tree at commit `2403442`, then
independently re-checked by six adversarial reviewers. This section exists because
the programme's sequencing depends on these facts being true *now*.

### 2.1 Confirmed as described

| ref | claim | anchor |
|---|---|---|
| D13 | `+0.1` confidence bonus for any single-letter answer; then discarded — `_build_mcq_corrected` emits `1.0 / HIGH / needs_review=False` unconditionally | `answer_extraction.py:99`, `correction_ai.py:155` |
| D14 | `min(conf, 0.2)` / `min(conf, 0.3)` caps are applied *before* an unconditional `+0.03` for `source_region`, so they leak to 0.23 / 0.33 | `answer_extraction.py:99–111` |
| D17 | The positional fallback logs a warning and does nothing else — no confidence reduction, no flag, no provenance | `answer_extraction.py:69–77` |
| D18 | `measure_accuracy` skips any question the extractor never returned, so a worse extractor returning fewer, easier questions scores higher | `harness.py:275` |
| D19 | The calibration curve is built from `question_type == "theory"` only, so it is structurally blind to MCQ defects | `harness.py:202` |
| D20 | No `temperature`, `top_p`, `seed` or `logprobs` are set anywhere; `thinking_budget_for` defaults to `{"mark_scheme": 8000}`, so extraction and marking run with thinking disabled; no image preprocessing of any kind | `gemini.py:376`, `:386–396` |
| D21 | `_cache_key` is `sha256(model + prompt + version + extra_key)` plus a file-bytes hash. Generation parameters are absent and there is no bypass seam, so *k* identical calls return *k* identical cached replies | `gemini.py:158–178` |
| D2 | `escalate_on_defaulted_marks` is a no-op its own docstring admits to: *"Not yet implemented — kept as a hook for a future improvement"* | `det/reconcile.py:60–64` |
| D1 | An unparseable marks cell silently mints a 1-mark point | `det/rows.py:194–205` |
| D5 | Every deterministically parsed theory question is typed `RECALL` — hardcoded, not inferred | `det/rows.py:184` |
| §1(b) | All 10 golden fixtures have `parent_id` on **0** of their leaves, so `correct_paper`'s ECF block has never executed in a measured run | `tests/golden/*/mark_scheme.json` |
| §0 | All 10 golden fixtures ship a `scan.pdf`, so the `else` branch of `measure_accuracy` is dead code | `tests/golden/*/scan.pdf` |
| §1(a) | The corpus hands the extractor the question id in clean machine-readable type beside every answer (`Q1a_i`, `Q4a`, …), so `id_match_rate` is trivially satisfiable at 1.0 | verified by rendering `tests/golden/0625_s20_qp_31_theory_partial/scan.pdf` |

### 2.2 Corrected

**(i) D8's second half is wrong.** The source document states that because the Gemini
path leaves `parent_id` as `None` on every leaf, `None == None` holds and the marker
receives every previously-marked question. It does not — `correct_paper` guards the
block (`correction_ai.py:463–469`), so `sibling_prior` stays empty and no PRIOR PART
RESULTS block is emitted at all. The defect is *silent absence* on the Gemini path,
not over-inclusion. ECF is dead on one path and mis-scoped on the other.

**(ii) D15 is latent, not live.** `_build_mcq_corrected` (`correction_ai.py:125`,
`:154–166`) *would* score a missing MCQ key as `awarded_marks=0,
confidence_score=1.0, HIGH, no flag`. But `Question.validate_type_constraints`
(`loose_schemas.py:815–829`) is a live `model_validator(mode="after")` that rejects
`type=mcq` with `mcq_answer=None` at both construction and `model_validate` —
verified: both paths raise. The branch is defensive only, contributes nothing to the
measured baseline, and 0 of 528 MCQ leaves on disk carry a null key.
**Consequence:** M1.1's abstain change cannot have a fail-then-pass regression test
through normal construction; it is re-scoped to hardening a defensive branch (§4).

**(iii) D3's "nothing compares them" is wrong.** A per-question comparison exists:
`Question.validate_mark_point_sum` (`loose_schemas.py:900–922`) is a live validator
that raises when primary points *exceed* `q.marks`. It is **one-sided** (never checks
under-sum) and exempts `LEVELS_BASED`, `INDICATIVE_CONTENT` and `MCQ`. Worse, on the
det path the two numbers are equal *by construction* — `det/rows.py:146–159` assigns
`q.marks = primary_total` — so the check is tautological there.

**The invariant must carry the filter, or it is not an invariant.** Measured across
the 575 det questions that have answer points:

| formulation | mismatches |
|---|---|
| `sum(p.marks for p in q.answer_points)` — raw | **67 of 575**, across 6 schemes |
| `sum(p.marks for p in q.answer_points if not p.is_alternative and not p.is_optional)` | **0 of 575** |

The raw sum is *not* the invariant: alternative and optional points are supposed to
exceed the tariff, because only some of them are credited. A gate written against the
raw sum produces 67 false positives on a well-formed corpus.

The real gap is the under-sum direction and the Gemini path. **Consequence:** M1.4 is
corrected in §4 — the filtered sum gate is a guaranteed no-op on the deterministic
corpus, and its regression fixture cannot be the one v1 named (see §2.3(d)).

**(iv) D6 is imprecise.** The deterministic path is held to an exact *paper-level*
checksum (`det/reconcile.check`, tolerance 0, escalate on by default). The Gemini
fallback has no paper-level counterpart — but it is not checked by *nothing*: every
Gemini-parsed scheme passes through `validate_mark_point_sum` at `model_validate`.
What is missing is the paper-level reconciliation, which is why
`0625_s20_ms_31.json` can declare `maximum_mark: 80` with leaves summing to 78.

**(v) One metric discrepancy.** The source document cites `flag_precision_high` at
91.7% (D2.2). The most recent saved golden run records **85.5%**. Both are
superseded by the M0 honest baseline.

### 2.3 Newly found

**(a) The current review rate is 19.1%, with a wide interval.** From
`tests/golden/results/2026-08-04-9a7f4c8.json`: 68 records, 13 flagged — 19.1%, 95%
Wilson [11.5%, 30.0%] — and 11 wrong marks of which **3** flagged (recall 27.3%,
[9.7%, 56.6%]). Against a ≤10% budget this is the most consequential number in the
programme (§5).

**(b) The golden set is 28 distinct leaves, not 68 records.** The `correct`,
`partial` and `wrong` variants of each paper replay the same questions: 0580 (7),
0606 (6), 0625 MCQ (8), 0625 s20 (7) = **28 distinct leaves**, expanded to 68 by
variant. Observations within a family are not independent, so **every interval and
power calculation quoted on n=68 is invalid**. This is why M1's acceptance gate is
non-regression rather than improvement (§4).

**(c) Confidence degeneracy quantified.** The 68 records take 8 distinct confidence
values: `0.65×5, 0.85×6, 0.90×5, 0.95×14, 0.96×5, 0.98×24, 0.99×1, 1.00×8`. The eight
`1.00` values are the MCQs, which by construction cannot be anything else.

**(d) The det path produces no judgment substrate whatsoever.** Across the 33
deterministically parsed schemes in `outputs/schemes/`:

| measure | value |
|---|---|
| leaves | 1,095 (`mcq` 520, `recall` 575 — **no other type exists**) |
| answer points | 1,000 |
| points with `calculated_answer` | **0** |
| questions with `drawing_criteria` | **0** |
| schemes where leaf sum ≠ `maximum_mark` | **0 of 33** |

The last row is the reconciler working as designed — only papers that balance survive
as det output — which is precisely why D1's phantom-and-lost cancellation is
invisible to it.

By contrast, the **two** Gemini-parsed schemes in `Sources/` both fail the checksum
the det path enforces. `0625_s20_ms_31.json` has six question types (`calculation` 9,
`explanation` 12, `recall` 11, `diagram` 7, `list` 1, `multi_step` 1) and 11
calculated answers, and declares `maximum_mark: 80` while its leaves sum to **78**.
`0606_s23_ms_12.json` declares 80 and parses to a leaf total of **20** — a quarter of
the paper. Both are identifiable as Gemini output because the det parser cannot emit
any type other than `mcq` or `recall`.

**A correction to v1 and to the first revision of v2.** Both cited 0606's answer
points "summing to 27 against a leaf total of 20" as a second, independent fidelity
defect. It is not a defect. `3b` carries 4 alternative points (raw 8, filtered 4) and
`4b` carries 3 (raw 6, filtered 3); 27 − 20 = 7 is exactly those alternatives. That is
well-formed CAIE alternative-method marking. **0606's only defect is the 80 → 20
truncation**, which a point-sum check cannot see and only a
leaf-sum-versus-`maximum_mark` check catches.

**And that check cannot be applied to the golden corpus as-is.** Six of the ten
fixtures are deliberate excerpts:

| fixture family | declared `maximum_mark` | leaf sum |
|---|---|---|
| `0580_s23_qp_22_theory_*` (×3) | 70 | **13** |
| `0606_s23_qp_12_theory_*` (×3) | 80 | **20** |
| `0625_m20_qp_12_mcq` | 8 | 8 |
| `0625_s20_qp_31_theory_*` (×3) | 19 | 19 |

`escalate_on_mark_mismatch` defaults to `True` at tolerance 0, so a paper-level gate
ported symmetrically to the AI path is a hard reject of 6 of the 10 fixtures that M0
and M1 both run on. The fixtures are excerpts by design and must not have their
`maximum_mark` rewritten — that would decouple them from their source PDFs. The golden
case contract needs an explicit `is_excerpt` marker instead (M0.8).

**(e) Denominators differ between surveys — stated explicitly.** 1,000 answer points
across the 33 det schemes in `outputs/schemes/`; **1,132** points across all 37
surveyed schemes (33 det + 4 in `Sources/`). Rates below are quoted against 1,132
unless stated.

**(f) T1.4's proposed detector needs refining, and splitting by path.** 272 of 1,000
det answer points (27%) contain an embedded newline — the same rate D3 found on a
single paper (21/69, 30%), so the signal is corpus-wide rather than paper-specific.
But many are *legitimately* multi-line: coordinate lists, stem-and-leaf tables,
matrices. A raw newline count false-positives at scale. Two signals are unambiguous:

- the **fraction-bar shape** — expression, newline, expression, with no operator
  between them (`'(p =) 148 \n 16.6'`);
- **Symbol-font private-use codepoints** surviving into the text (`U+F0B8` = ÷,
  `U+F0E6`/`U+F0F6` = bracket pieces, `U+F02D` = minus). Present in 6 of 1,132 points
  (0.5%) — **all of them in the det-parsed `0580_s23_ms_22.json`, none in either
  Gemini scheme**. Rare, but 100% corrupt when present, so a zero-false-positive
  detector.

A crude flattened-exponent signature matches 56 of 1,132 points (4.9%), consistent
with D4's 18/270 (6.7%).

**(g) The golden corpus is corrupt in two independent ways.** Both were reproduced.

1. **Overprint and clipping.** `_wrap_answer_text` measures wrapping with a base-size
   font while `_draw_handwritten_line` renders with a jittered size, and the
   continuation line is emitted at the *same* y-cursor. Rendering
   `0625_s20_qp_31_theory_partial/scan.pdf` at 150 dpi shows Q5b with `3.93 N`
   overprinted on `clockwise` and the line running off the right edge after
   `F = 200 / 60 =`. That answer carries **2 expected marks** and is unreadable. The
   same 5b appears in all three `0625_s20_qp_31` variants.
2. **Missing glyphs.** The handwriting font renders `θ`, `π` and `Ω` identically to
   `.notdef` (verified by pixel comparison against an unmapped private-use
   codepoint); `×`, `÷`, `²`, `−`, `°` are present. The `0606` ground truth contains
   `θ` 8 times across 4 leaves and `π` once — so the rendered scan does not contain
   what `answers.json` says it contains.

Between them these touch roughly 5 of 28 distinct leaves (~18%). **M0.4 would book
all of it as extraction-attributable error**, which is the exact opposite of the
"lower bound" framing. Hence M0.0.

**(h) Every capability the programme needs is accepted by the SDK — but acceptance is
not endpoint support.** `google-genai` 2.10.0 `GenerateContentConfig` accepts
`temperature`, `top_p`, `top_k`, `seed`, `candidate_count`, `response_logprobs`,
`logprobs`, `media_resolution` and `thinking_config`. T0.2 and T2.5 are mechanically
available. **`response_logprobs`/`logprobs` are reported to be rejected by the
Developer API for `gemini-2.5-flash`** — the Tier-3 logprob ideas must be probed
against the live endpoint before being planned on, and are out of scope here anyway.

**(i) The corpus is not as absent as the source document assumes — but most of it is
untracked.** PaperScraper is present at `/home/sico/PaperScraper`.
`tests/fixtures/real-papers/` holds two real scripts with ground-truth totals in
their filenames (`0625_s23_qp_22-(34..40).pdf`, `0625_w24_qp_41-(66..80).pdf`) — but
these are **gitignored (`.gitignore:89`) and exist only in this working tree**. The
four solved scripts in `Sources/Physics/Solved/` are tracked but carry **no** recorded
totals and are unusable as scored fixtures until supplied.

**(j) Budget state — all of it working-tree, none of it tracked.** `lemely.toml`
(`.gitignore:47`), `outputs/` (`:46`) and `.lemely-cache/` (`:22`) are untracked, so
the following describe this machine, not the repository:

- `total_usd_ceiling = 4.99` (the code default is 8.0)
- `per_run_token_ceiling = 200000` (the code default is `None`)
- ledger at **$0.4026**; cache at 138 entries / 620 KB

**(k) The pricing table is stale, so the ledger and both ceilings are in understated
units.** `_DEFAULT_PRICING` (`gemini.py:29–33`) carries the *preview* price sheet —
its own comment names `gemini-2.5-flash-preview-05-20` — while the configured model
is GA `gemini-2.5-flash`. Table: $0.150/$0.600 per 1M. Current GA: **$0.30/$2.50** —
2.0× and 4.17×. Flash-Lite and Pro output are likewise understated. Because
`gemini.py:418` computes the ledger from the same table, the recorded $0.4026 and the
enforced `total_usd_ceiling` are both understated by roughly 2–4×.

**(l) Thinking tokens are billed but never ledgered.** `_call_once` counts only
`prompt_token_count` and `candidates_token_count` (`gemini.py:412–413`).
`thoughts_token_count` is omitted entirely, and mark-scheme parsing runs with a
`thinking_budget` of 8000 by default.

**(m) A second hard ceiling that M0 arms.** `_check_cost_ceiling` raises on
`per_run_token_ceiling` against module-level globals (`gemini.py:43–46`) that are
reset only by a test helper — so they accumulate for the whole process. Today it never
fires because a cache hit returns at `:237–245`, *before* the ceiling check at `:247`.
M0.2's `cache_mode=bypass` is precisely what makes every call live: a full golden
sweep is ~70 calls / ~115k tokens, so M0.3 and M0.4 trip the 200k ceiling on the
second sweep in a single process.

---

## 3. Architecture — where the instrument lives

### 3.1 The decision

Introduce a new `lemely/eval/` package owning the evaluation record model and the
statistical analyses. `lemely/accuracy/harness.py` keeps its public API and becomes
one runner that emits records.

**Label *data* does not live there.** Labels are written to repository-root
`eval/labels/…`, deliberately outside the `lemely/eval/` Python package, so labels
are never importable and the labeller process cannot reach pipeline code (§6).

### 3.2 Why

Three M0 items — the ablation arms, abstention as an outcome, honest denominators —
are changes to *what is recorded*, not to what is reported. The current
`QuestionResult` carries six fields and cannot express an arm label, an abstention,
id provenance, a parse path, or anything below the question level. Two later items
need sub-question rows regardless: T0.3's per-mark-point labels and T1.7's
per-mark-point verdicts. Getting the record right once avoids migrating results twice.

### 3.3 The record model

```
EvalRecord
  run_id            str            # joins to RunManifest
  arm               "extract+mark" | "oracle+mark"
  paper_id          str
  fixture_variant   str | None     # correct | partial | wrong — for distinct-leaf collapsing
  question_id       str
  mark_point_id     str | None     # None ⇒ question-level row
  parse_path        "det" | "gemini"
  predicted_marks   int | None     # None when abstained
  truth_marks       int | None     # None when unlabelled
  outcome           correct | over | under | abstain | unmatched | excluded
  extraction_conf   float | None
  marker_conf       float | None
  id_match          "exact" | "fuzzy" | "unmatched"
  triggers          list[str]      # which review triggers fired
```

```
RunManifest
  run_id, git_sha, timestamp
  prompt_versions   {extraction, correction, mark_scheme}
  params_fingerprint  # model, temperature, top_p, seed, thinking_budget,
                      # max_output_tokens, response-schema hash
  models_by_task    dict[str, str]
  cache_mode        "read_write" | "bypass" | "refresh"
  split             "train" | "dev" | "test"
  corpus_digest     str
```

**Outcome semantics, and their place in the funnel:**

| outcome | funnel stage | in `mark_accuracy` denominator? | counts as correct? |
|---|---|---|---|
| `correct` | scored | yes | yes |
| `over` / `under` | scored | yes | no |
| `abstain` | marked, no confident answer | **yes** | no |
| `unmatched` | extracted but no id match | **yes** | no |
| `excluded` | never attempted (non-leaf, no scan region) | **no** | n/a |

**Analyses are pure functions over `list[EvalRecord]`** — no I/O, no Gemini, no
filesystem: `ablation_2x2`, `mcnemar`, `wilson`, `risk_coverage`, `exclusion_funnel`,
`review_rate`. Every analysis filters to question-level rows (`mark_point_id is
None`) unless explicitly a point-level analysis, and every interval or power
calculation collapses to **distinct leaves** first.

### 3.4 Alternatives rejected

**Grow `harness.py` in place.** Cheaper this milestone. Rejected because the
instrument and the product then share fate — and a measurement blindness caused by
exactly that coupling (D18) is one of the defects being fixed.

**Analysis scripts over the saved result JSON.** Zero risk to product code. Rejected
because it cannot add the arms: the ablation, cache bypass and abstention change what
the run *does*, not merely what is reported afterwards.

---

## 4. Milestones

### M0 — Instrument

Code only. No labels required. Estimated API cost ≈ $3 at corrected rates.

| # | item | source |
|---|---|---|
| **M0.0** | **Repair the fixture renderer and regenerate all fixtures.** Fix the wrap/draw font mismatch and the same-y continuation bug; substitute or embed a font covering the symbols the ground truth uses. Assert, at generation time, that every answer round-trips: no glyph renders as `.notdef`, no ink past the text box, no overprint. Fixture generation fails otherwise. | §2.3(g), source §1(a) |
| M0.1 | `lemely/eval/` — record model, run manifest, pure analyses; `harness.py` emits records; `AccuracyMetrics` derived | §3 |
| M0.2 | **Determinism substrate** — explicit `temperature`/`top_p`/`seed`; `params_fingerprint` in `_cache_key`; `cache_mode` seam. **Plus three corrections it depends on:** fix `_DEFAULT_PRICING` to GA rates, count `thoughts_token_count` as output, and raise `per_run_token_ceiling` | T0.2, §2.3(k)(l)(m) |
| M0.3 | **A/A churn floor** — N repeats of the golden set with the cache bypassed; publish per-question disagreement rate with its n | T0.2 |
| M0.4 | **Oracle-transcription ablation** — both arms over all fixtures; report the 2×2 | T0.1 |
| M0.5 | **Honest denominators** — fix D18; publish the exclusion funnel; abstention enters the denominator; publish both the legacy and honest baselines | T0.8, D18 |
| M0.6 | **Paired statistics** — McNemar, Wilson intervals, n-floors, all computed over distinct leaves | T0.4 |
| M0.7a | **Split mechanism** — the `split` field, the test-touch ledger, and a CI assertion that no run reads `test` without an authorisation token | T0.5 |
| M0.8 | **Fixtures carry `parent_id`**, plus an 11th genuinely nested multi-part fixture | T0.6 |
| M0.9 | **`review_rate` as a CI gate** — two-part, and a ratchet | §5 |

**Ordering inside M0:** M0.0 → M0.1/M0.2 → M0.8 → *baseline run* → M0.3/M0.4/M0.5.
The corpus must be final before it is measured; a fixture added after the baseline
invalidates it.

**Per-item acceptance:**

- **M0.0** — every fixture regenerates; the round-trip assertion is part of
  generation, not a separate test; the Q5b overprint and the `θ`/`π` losses are gone.
- **M0.1** — the saved 2026-08-04 `AccuracyMetrics` is reproduced bit-identically from
  `list[EvalRecord]`; all six analyses have unit tests and touch no network.
- **M0.2** — two runs with identical `params_fingerprint` hit cache, two with
  differing fingerprints do not; a bypassed multi-sweep run completes without an
  `ExternalServiceError`; a call with a thinking budget ledgers more than
  `candidates_token_count`.
- **M0.3** — floor published with its n, in the report and in `BUILD/DECISIONS.md`;
  documented rule that any A/B delta below the floor is *within noise*.
- **M0.4** — `ablation_2x2` cross-tabulates `oracle+mark` outcome against
  `extract+mark` outcome per question: both-correct; extraction-attributable (oracle
  correct, extract wrong); marking-attributable (both wrong); masked (oracle wrong,
  extract correct). Reported as a lower bound on extraction share **only because**
  M0.0 has asserted render fidelity.
- **M0.5** — an extractor returning fewer questions cannot score higher; the funnel is
  printed; **two figures published** — the legacy 83.8% and the honest baseline. The
  honest baseline is the sole comparison point thereafter; every later reference to
  83.8% is historical.
- **M0.6** — intervals and n-floors computed on 28 distinct leaves, not 68 records; a
  metric below its n-floor prints as underpowered rather than as a number.
- **M0.7a** — no run can read the test split without a token; every read appends to
  the ledger.
- **M0.8** — `parent_id` on every leaf of all 10 fixtures plus an 11th nested fixture;
  a test proves the PRIOR PART RESULTS block is emitted; **the golden case contract
  gains `is_excerpt`**, set on the six fixtures whose declared `maximum_mark` exceeds
  their leaf sum by design (§2.3(d)), without altering any fixture's `maximum_mark`.
- **M0.9** — see §5.

### M1 — Fixes that need no measurement to justify

Each ships with a regression test that fails before and passes after. Estimated API
cost ≈ $4 at corrected rates.

| # | item | direction | source |
|---|---|---|---|
| M1.1 | **The confidence unit, as one commit** | mixed (self-contained) | T1.1, D13, D14, D19 |
| M1.2 | **Delete the positional fallback**; emit `UNMATCHED` with `id_match` provenance, and re-derive the metric's CI target in the same commit | neutral | T1.2, D17 |
| M1.3 | **Defaulted-mark provenance**; stop minting 1-mark points from empty cells; implement `escalate_on_defaulted_marks` | lowering | T1.6, D1, D2 |
| M1.4 | **Fidelity gate** — the **under-sum** direction of the *filtered* point sum, plus an excerpt-scoped paper-level aggregate for the Gemini path; fraction-bar detector on both paths; PUA-glyph detector on the det path | lowering | T1.4, D3, D6 |
| M1.5 | **Coherence gate** — `awarded_marks` reconciles with `matched_point_ids`, and those ids exist | neutral | T1.8 |
| M1.6 | **Inject the CAIE Generic Marking Principles**; fix the A-mark dependency rule | raising | T1.14 |
| M1.7 | **Verify the 40 MCQ answer keys** for `0625_s23_ms_22` | neutral | T1.13, D16 |
| M1.8 | **Label-free metamorphic tests** — reordering mark points, renaming point ids, and normalising answer whitespace must not change `awarded_marks` | neutral | T2.11 |

**Commit rule (§7):** no commit may contain items of both `raising` and `lowering`
direction. M1.1 is exempt because its own components are internally coupled and it
reports its own signed split.

**Corrections carried into M1 from §2.2:**

- **M1.1's MCQ-abstain component is re-scoped.** `mcq_answer is None` is unreachable
  through normal construction, so this is hardening a defensive branch — it ships with
  a `model_construct` unit test, not an end-to-end regression, and the spec says so
  rather than claiming a live defect fixed.
- **M1.1 specifies the paper-level rule.** Paper-level grade confidence is the
  **marks-weighted mean** of per-question confidence, banded HIGH ≥ 0.85 /
  MEDIUM ≥ 0.65 / LOW below. It is explicitly **not** a min over questions — a min
  propagates any single LOW question to the whole paper, which is the failure §7
  forbids. Acceptance: on the M0 baseline set the paper-level band distribution is not
  degenerate.
- **M1.4 is corrected twice over.** (a) The invariant is the **filtered** sum —
  excluding `is_alternative` and `is_optional` points — not the raw sum, which
  mismatches on 67 of 575 det questions by design. (b) So stated it is tautological on
  the det path (575/575, because `rows.py:154–158` derives `q.marks` from that same
  filtered sum) and the over-sum direction is already enforced by
  `validate_mark_point_sum`. The new work is the **under-sum** direction plus a
  paper-level aggregate. (c) The paper-level aggregate must be **scoped to
  non-excerpt schemes** or it rejects 6 of the 10 golden fixtures (§2.3(d)) — which
  requires the `is_excerpt` marker from M0.8. (d) The regression fixture cannot be
  `0606_s23_ms_12`'s point sum, which is well-formed; it must target the 80 → 20
  truncation, or be a synthetic scheme built for the purpose.

**M1 acceptance.** The population is the golden dev split — a subset of **28 distinct
leaves**, an order of magnitude below the n-floor for detecting improvement. So:

- McNemar is **reported, not gated for improvement**.
- The blocking condition is **non-regression**: the signed over/under-award split
  shows no significant increase in wrong marks (α = 0.05).
- **Flag recall must not fall below the M0 baseline.**
- `review_rate_signal ≤ 8%`.
- Improvement claims are deferred to M2.4's labels. The heading "needs no measurement
  to justify" refers to the *justification* for fixing these defects, not to the
  existence of an acceptance gate.

### M2 — Ground Truth (runs in parallel from day one)

The critical path: human-bound, longest lead time. It does **not** wait for M0 —
except for **M0.7a**, which must land in M0 week one because the labeller cannot write
a valid record before the `split` field exists.

| # | item | source |
|---|---|---|
| M2.1 | **Corpus restoration** via PaperScraper — dry-run scope approved before any fetch | source §6 |
| M2.2 | **Failure-reason census** over the failing schemes | T0.7, D7 |
| M2.3 | **The labeller** — see §6 | T0.3 |
| M2.4 | **~300 labelled leaves** | T0.3 |
| M2.5 | **Synthetic-to-real transfer gap** — run the extraction arm over the synthetic and real scans of the same paper and publish the delta | T2.12 |
| M0.7b | **Split membership frozen** over the restored corpus; human-approved | T0.5 |

**Stratification (corrected).** `calculation`, `explanation` and `diagram` do not
exist on the det path and will not until M3, so a naive 4×2 type-by-path matrix has
four structurally empty cells. Stratification therefore uses the **labeller's own type
judgement**, never the pipeline-emitted `question_type`, which on the det path is
hardcoded to `recall`. The resulting table shows a det-path type distribution the det
parser cannot itself represent; that gap is M3's input.

**Per-item acceptance:** M2.1 — the catalogue diff covers the approved scope and the
ledger shows no unapproved fetches. M2.2 — every failing scheme classified, counts
published, D7 ranked. M2.3 — the labeller writes a valid hash-chained JSONL for a
smoke paper and imports zero pipeline modules (asserted by test). M2.4 — ≥300 leaves,
stratification table published, self-agreement published. M2.5 — delta published with
its interval.

**Statistical unit.** The leaf. A leaf is correct iff `sum(awarded points) ==
sum(truth points)`; per-mark-point verdicts are inputs to that derivation and are
analysed separately without interval claims.

### M3 — Parse-Path Parity and Mark-Scheme Fidelity (scoped, re-planned later)

T1.11 (`calculated_answer`, real question types, guidance notes **and
`drawing_criteria`** on the det path), T1.3 (glyph-level superscript/subscript
reconstruction), T1.5 (the ECF fix, gated on M0.8), T2.9 (QP↔mark-scheme tariff join),
and the D7 repairs ranked by M2.2's census.

**Why a milestone rather than scattered Tier-1 items:** §2.3(d) shows the judgment
substrate is entirely absent on the majority parse path. Every judgment strategy in M4
needs it. Until M3 lands, tuning the marker measures the Gemini path and ships to the
det path.

### M4 — Judgment and Vision (scoped, re-planned later)

T1.7 (per-mark-point verdicts with quoted evidence), T1.9 (dual-read disagreement),
T1.10 (unconditional random audit), T1.12 (marks-to-boundary routing), T2.1–T2.8
(cropping, anchoring, grounding, dual transcription, DPI, scan hygiene, context
caching, thinking budget), and making the marker consume `drawing_criteria` (D12).

---

## 5. The review budget

**Two-part gate, enforced in CI from M0.9:**

```
review_rate_signal ≤ 8%      # everything except the random audit
review_rate_total  ≤ 10%     # including it
per-paper p95      ≤ 15%     # a pooled 9% must not hide a paper at 30%
```

Until T1.10 ships in M4, `review_rate_total == review_rate_signal` and the 2pp
reservation is enforced as **unused headroom, not slack**. Without this, an M1 landing
at 9.9% signal-driven review would pass every gate and make T1.10 mathematically
unmergeable.

**The gate is a ratchet, not an absolute.** CI fails if
`review_rate > min(10%, last_merged_review_rate)`. The absolute condition becomes
blocking at M1 acceptance. M0 records 19.1% as the ratchet's starting value and
**passes with a recorded-but-non-blocking breach** — otherwise CI is red for all of
M1 and even the fix cannot merge.

**The gate compares point estimates deliberately;** interval reporting is advisory.
On 28 distinct leaves the metric moves in coarse steps, and a gate that waits for a
significant result never fires.

**Starting position: 19.1%, catching 3 of 11 wrong marks.** Any proposal that adds a
trigger must state which existing trigger it displaces, or show the displaced volume
was noise.

---

## 6. Labelling protocol

**Mechanism.** `lemely label <paper_id>` serves a single-purpose page on localhost. A
terminal cannot display handwriting, so the interface is a browser tab driven by a CLI
command — not a web feature, and not part of the product surface.

**Two passes, in separate sessions:**

1. **Transcription.** Shows the scan region only. The mark scheme is not loaded.
2. **Marking.** Shows the mark scheme and *the labeller's own* transcription from
   pass 1. Output: a binary verdict per mark point, plus the labeller's own judgement
   of the question's true type (used for stratification).

**Blindness is structural.** The labeller process never imports the correction
pipeline — asserted by a test. Labels are append-only JSONL with a hash chain, so an
edit made after seeing results is detectable rather than merely forbidden.

**Storage.** Repository-root `eval/labels/<paper_id>/{transcription,marking}.jsonl`
plus a manifest recording split assignment and labeller identity — deliberately
outside the `lemely/eval/` package (§3.1).

**Volume.** ~300 **distinct** leaves ≈ 7–8 real papers. At n=300 the 95% Wilson
interval on 83.8% is ±4.2pp, and paired McNemar can prove an improvement to 88.8% with
n=219 where unpaired needs 741 per arm.

**Self-agreement.** A 10% sample is re-labelled after a delay. Without it there is no
ceiling on how good the pipeline can honestly be said to be.

---

## 7. Sequencing constraints

**§7 is the complete set of ordering constraints. Anything not listed here is
unordered.**

### Must ship as one commit

- Extraction-confidence propagation **+** the `_calibrate_confidence` rebuild. The
  rebuild alone is a literal no-op — the value is discarded at the marking boundary
  (`correction_ai.py:43` carries confidence into the tuple; nothing reads index 2).
  The propagation alone floods the queue with a signal still poisoned by the `+0.1`
  bonus.
- Propagation **+** the paper-level grade-confidence rule (specified in §4).
- Positional-fallback removal **+** the metric's CI-target re-derivation (M1.2). Split
  across commits, the metric drops below its 0.99 target, CI fails, and someone
  restores the guess to make the build green.

### Strict orderings

| first | then | why |
|---|---|---|
| fixture repair (M0.0) | any baseline run | Otherwise fixture corruption is booked as extraction error |
| fixtures final (M0.8) | A/A floor (M0.3), ablation (M0.4) | A fixture added after the baseline invalidates it |
| cache-bypass seam (M0.2) | A/A floor (M0.3) | The cache returns a false zero |
| pricing + token-ceiling fix (M0.2) | any multi-sweep run | The 200k process ceiling trips on sweep two |
| A/A floor (M0.3) | any A/B claim | A delta below the floor is noise |
| M0.9 | M1.1 | The confidence unit needs the baseline and the live ratchet |
| split mechanism (M0.7a) | any labelling (M2.3, M2.4) | The labeller cannot write a record without the `split` field |
| corpus restore (M2.1) | split membership (M0.7b) | Membership is frozen over the real corpus |
| census (M2.2) | the D7 repairs in M3 | The census produces the work order |
| fixtures carry `parent_id` (M0.8) | ECF fix (M3/T1.5) | Reversed, a correct fix measures zero and is discarded |
| superscript reconstruction (M3/T1.3) | any unit or sig-fig enforcement | Enforcing units against `'g/cm\n'` revokes marks from correct students |
| tariff join (M3/T2.9) | narrow LLM repair | It produces the address the repair consumes |
| M3 parity | M4 judgment tuning | Otherwise the marker is fitted to a distribution the majority parse path never produces |

### Must NOT land together

- **Mark-raising with mark-lowering fixes** — see the `direction` column in §4's M1
  table. They cancel; the project's own history records two iterations netting exactly
  zero this way.
- **Multiple prompt `VERSION` bumps.** Each invalidates the cached corpus. Batch them
  or the delta cannot be attributed.
- **Random audit (M4/T1.10) with the confidence unit (M1.1).** Both raise review
  volume; landed together neither contribution is recoverable.

---

## 8. Cost and budget

**The pricing table must be corrected before any of this arithmetic is meaningful**
(§2.3(k)). `_DEFAULT_PRICING` carries preview rates; the configured model is GA
`gemini-2.5-flash` at **$0.30/1M in, $2.50/1M out**. Flash-Lite is $0.10/$0.40 and Pro
output is $10.00/1M. Fixing the table is part of M0.2.

At corrected rates a full 41-leaf theory paper costs roughly **$0.035** end to end
(~73k input tokens across 42 calls, ~6.2k output); the golden set costs ~$0.06 per full
sweep.

| milestone | estimate (corrected rates) |
|---|---|
| M0 — including an A/A floor at n=10, the ablation, and one full cache rebuild | ≈ $3 |
| M1 — regression sweeps plus one prompt-batch invalidation | ≈ $4 |
| headroom for Pro escalation and re-runs | ≈ $8 |

**Two ceilings must be raised, not one:**

- `total_usd_ceiling` 4.99 → **25.00**. Note that the recorded $0.4026 was accumulated
  under the stale table and understates real spend by 2–4×, and thinking tokens were
  never counted at all — so 25 ledger-dollars is not 25 real dollars until M0.2 lands.
- `per_run_token_ceiling` 200000 → **2000000** or `null`. One cache-bypassed golden
  sweep is ~115k tokens across ~70 calls (10 extraction + 60 correction; the 8 MCQ
  leaves are marked deterministically) against a module-global counter, so M0.3 and
  M0.4 trip it on the second sweep in a single process.

**Both ceilings are pre-flight, not hard stops.** `_check_cost_ceiling`
(`gemini.py:193–199`) runs *before* the call is issued, so a single request can
overshoot the ceiling rather than be refused at it. The ceiling bounds when spending
stops, not how much is spent.

---

## 9. Execution mechanics

- Work happens in a git worktree **outside** the repository, with its own virtual
  environment (the main `.venv` editable-installs `lemely` from `/home/sico/Lemely`,
  so imports would otherwise silently resolve to the wrong branch).
- Signed commits (`git commit -S`), conventional messages with scopes.
- `pre-commit run --all-files` passes before any commit is created.
- Decision records appended to `BUILD/DECISIONS.md`.
- No commits and no pushes without an explicit request.
- **Untracked state is a hazard.** `lemely.toml`, `outputs/`, `.lemely-cache/` and
  `tests/fixtures/real-papers/` are gitignored. A worktree gets none of them; the two
  real-paper fixtures exist in exactly one place on one machine (§11 task 10).

---

## 10. How this programme could still fail

**The instrument gets built for the wrong half of the corpus.** §2.3(d) shows this is
the present state, not a risk. Mitigations are M3 (parity) and M2.4's requirement that
labelling cover both parse paths by *labeller-assigned* type. If only one lands, every
number improves and the product does not.

**The review queue eats the product.** Mitigated by the two-part ratchet gate from
M0.9, before any strategy that raises volume can merge, and by reserving the audit
allocation as headroom rather than slack.

**The synthetic corpus keeps flattering the extractor — and also lies in the other
direction.** The fixtures print the question id in clean type beside every answer, so
`id_match_rate` is trivially 1.0 and mis-attribution is unobservable; that inflates
apparent extraction quality. Simultaneously the renderer *loses* ground truth (§2.3(g)),
which deflates it. M0.0 removes the second; only M2.4's real labels remove the first.

**The golden set is too small to prove anything.** 28 distinct leaves. M1's gate is
non-regression precisely because improvement cannot be demonstrated there. If M2 slips,
the programme has fixes it cannot validate.

**Labelling stalls.** ~6–8 hours of one person's attention, gating M2, M3 and M4.
Starting it on day one in parallel with M0 is the mitigation.

---

## 11. Human tasks

| # | task | needed by | estimate |
|---|---|---|---|
| 1 | Raise **both** ceilings in `lemely.toml`: `total_usd_ceiling` 4.99 → 25.00 **and** `per_run_token_ceiling` 200000 → 2000000 (or null); confirm `GEMINI_API_KEY` is live | M0.3 | 5 min |
| 2 | Approve the PaperScraper dry-run scope | M2.1 | 15 min |
| 3 | Verify the 40 MCQ answer keys for `0625_s23_ms_22` (M1.7) | M1 | 20 min |
| 4 | Approve the frozen split membership (M0.7b) | M2.4 | 15 min |
| 5 | Supply ground-truth totals for the four solved scripts in `Sources/Physics/Solved/`, or confirm they are unknown | M2.4 | varies |
| 6 | **Label ~300 distinct leaves** across two passes | M2.4 | **6–8 h**, splittable |
| 7 | Re-label a 10% sample after a delay, for self-agreement | M2.4 | +45 min |
| 8 | Adjudicate CAIE judgment questions raised during labelling | ongoing | ~30 min |
| 9 | Authorise the single run of the frozen test split | release | 10 min |
| 10 | **Decide what to do about untracked corpus state** — the two real-paper fixtures with known totals, `outputs/schemes/`'s 33 parsed schemes and `lemely.toml` exist only in this working tree and are gitignored. Either commit them, back them up, or accept that a worktree and a fresh clone both start without them | M0 (worktree setup) | 20 min |

---

## 12. Changes in v2

### v2.1 — corrections to v2 itself

The review's synthesis pass landed after v2 was written and found two errors **in the
corrections**, both verified before being accepted here:

- **The point-sum invariant must carry the `is_alternative`/`is_optional` filter.**
  Raw sums mismatch on 67 of 575 det questions *by design*; filtered, 0 of 575. A gate
  written against the raw sum false-positives on well-formed schemes.
- **`0606_s23_ms_12`'s "27 points against 20 marks" is not a defect.** It is exactly
  the 7 alternative points on `3b` and `4b`. v1 and the first draft of v2 both cited it
  as evidence. Its only real defect is the 80 → 20 truncation.
- **A paper-level gate would reject 6 of the 10 golden fixtures**, which are deliberate
  excerpts (0580: 70 declared / 13 parsed; 0606: 80 / 20). M0.8 now adds an
  `is_excerpt` marker; M1.4's paper-level aggregate is scoped to non-excerpt schemes.
- **Both cost ceilings are pre-flight**, so a single call can overshoot.

### v2 — changes from v1

Rewritten after an adversarial review by six independent reviewers (four fact
verifiers, three critics) producing 13 blockers and 31 majors. Substantive changes:

- **New milestone item M0.0** — the fixture corpus is corrupt (overprint, clipping,
  `.notdef` glyphs); repairing it must precede the ablation (§2.3(g)).
- **D15 reclassified** as latent/unreachable; M1.1's abstain component re-scoped.
- **D3 corrected** — `validate_mark_point_sum` exists, is one-sided, and is
  tautological on the det path; M1.4 redirected to the under-sum direction and the
  Gemini path.
- **D6 corrected** — the Gemini path is not unchecked, it lacks a *paper-level* check.
- **Distinct leaves (28) separated from records (68)**; every interval and power claim
  requalified; M1's gate changed from improvement to non-regression.
- **The review-budget gate made two-part and a ratchet**, so CI is not red for all of
  M1 and T1.10 remains mergeable.
- **Pricing table, thinking tokens and the second token ceiling** added to M0.2 and
  §8; both ceilings now appear in human task 1.
- **`review_rate` given a precise definition** (§1) — denominator, corpus,
  aggregation, per-paper p95.
- **M0.7 split** into mechanism (M0.7a, in M0) and membership (M0.7b, in M2).
- **The paper-level grade-confidence rule specified** (marks-weighted mean, banded,
  explicitly not a min).
- **Per-item acceptance criteria** added throughout, replacing milestone-level prose.
- **M1.8 (metamorphic tests, T2.11) and M2.5 (transfer gap, T2.12)** added — both were
  silently dropped in v1.
- **Stratification corrected** to use labeller-assigned types.
- **Untracked working-tree state** flagged throughout, and human task 10 added.
- **§7 declared exhaustive**; a `direction` column added to the M1 table.

---

## Appendix — provenance

Every number in §2 was reproduced against the working tree at commit `2403442`, then
independently re-verified. Method: reading the named source locations; parsing the 33
schemes in `outputs/schemes/` and the 4 in `Sources/`; inventorying the golden
fixtures; rendering `0625_s20_qp_31_theory_partial/scan.pdf` at 150 dpi and inspecting
it; pixel-comparing font glyphs against an unmapped private-use codepoint;
constructing `Question` objects to test validator reachability; reading the most recent
saved accuracy result; and introspecting the installed `google-genai` 2.10.0
configuration model.

Claims that could not be reproduced are marked corrected in §2.2. Claims requiring
artefacts absent from this checkout remain unverified and are addressed by M2.1 and
M2.2 rather than assumed: **D7** (the 24-notation `parse_marks_cell` failure as the
cause of the real failures), **D11**, **D16**, and the **32/72** coverage figure.
**D9, D10 and D12** are diagnosed but not routed to an M0/M1 item — D9 and D10 are
M3 work (they depend on parse-path parity), D12 is split between M3 (parse) and M4
(consume), as stated in Non-Goals.
