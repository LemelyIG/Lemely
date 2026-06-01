# Accuracy Optimization Design

**Date:** 2026-06-02
**Branch:** phase-2-multi-paper-extraction
**Target:** >95% correction accuracy, ~99% confidence flagging precision

---

## Context

The Lemely pipeline has three stages: **parse** (PDF → JSON mark scheme, Pro model), **extract** (scan → answers, Flash), **correct** (answers + scheme → marks, Flash + optional Pro escalation). Currently there is no systematic way to measure accuracy at any stage — all AI-touching tests use mocked responses and test plumbing, not correctness. Without measurement, any improvement is a guess.

The approach is: build a measurement harness first, establish a baseline, then fix culprits in priority order, re-measuring after each change.

---

## 1. Golden Dataset Structure

Ground truth is stored under `tests/golden/`, one subdirectory per paper.

```
tests/golden/
  0625_m20_qp_12/
    mark_scheme.json          ← already-parsed JSON mark scheme
    answers.json              ← ground truth per leaf question
    scan.pdf                  ← optional; only needed for extraction tests
```

### `answers.json` format

```json
{
  "1":     { "student_answer": "A",            "awarded_marks": 1 },
  "1(a)":  { "student_answer": "20 m/s",       "awarded_marks": 2 },
  "1(b)":  { "student_answer": "uses v = d/t", "awarded_marks": 1, "notes": "owtte accepted" }
}
```

Every leaf question in the mark scheme must have an entry. The optional `notes` field is human annotation for reviewer reference — not used by the harness.

---

## 2. Metrics

A new CLI command `lemely eval-accuracy --golden tests/golden/` runs all cases and prints:

```
Stage       Metric                  Score    Target   Description
────────────────────────────────────────────────────────────────────────────────────────────────
Correction  mark_accuracy           –        >95%     % of questions where awarded_marks == ground truth
Correction  mark_accuracy (theory)  –        >95%     Same, theory-only questions (MCQ excluded)
Extraction  id_match_rate           –        >99%     % of leaf questions successfully matched to an extracted answer
Confidence  flag_precision (HIGH)   –        >99%     Of HIGH-confidence decisions, % that were actually correct
Confidence  flag_recall             –        >85%     Of incorrectly-marked questions, % that were flagged for review
```

### Metric definitions

**`mark_accuracy`** — Per question: `awarded_marks == ground_truth_awarded_marks`. MCQ questions are always deterministic and correct; the interesting number is `mark_accuracy (theory)` on non-MCQ questions only.

**`id_match_rate`** — After extraction, every leaf question in the mark scheme manifest should appear in `ExtractedAnswers`. A question absent from the extracted output counts as a miss. This catches silent extraction failures where a question is skipped rather than misread.

**`answer_transcription_accuracy`** — Not an exact-string match. An extracted answer is correct if running it through the corrector produces the right `awarded_marks`. This is tested implicitly via `mark_accuracy` on end-to-end cases (cases with `scan.pdf`).

**`flag_precision (HIGH)`** — Of all questions where `needs_teacher_review=False` (system is confident), what fraction were actually correct? This is the user-facing guarantee: "when the system says it's confident, it must be right 99% of the time."

**`flag_recall`** — Of all questions where `awarded_marks != ground_truth`, what fraction had `needs_teacher_review=True`? A missed flag means a wrong mark slips through undetected.

### Calibration curve

In addition to the summary table, the harness emits a calibration table grouping predictions into five confidence buckets:

```
Confidence bucket   Predictions   Actual accuracy   Calibration gap (actual − stated)
0.90 – 1.00         –             –                 –
0.80 – 0.90         –             –                 –
0.70 – 0.80         –             –                 –
0.60 – 0.70         –             –                 –
< 0.60              –             –                 –
```

A negative calibration gap (actual accuracy < stated confidence) means the model is overconfident in that bucket. A large negative gap identifies where the escalation threshold must be set. The threshold is derived from calibration data — it is the lowest bucket where actual accuracy exceeds 99%.

### Configurable targets

Targets are set in `lemely.toml` under a new `[eval]` section:

```toml
[eval]
mark_accuracy_target        = 0.95
id_match_rate_target        = 0.99
flag_precision_target       = 0.99
flag_recall_target          = 0.85
```

The harness exits non-zero if any metric falls below its target.

---

## 3. Accuracy Fixes

Ordered by expected impact. Each fix is independently measurable via the harness.

### Fix 1 — ECF cross-part context

**Problem:** Each question is corrected in isolation. The corrector for `1(b)` has no knowledge of what the student scored in `1(a)`, so ECF/follow-through marks are frequently wrong on multi-step calculation questions.

**Fix:** In `correct_paper`, accumulate a running `prior_results` dict `{question_id → awarded_marks}` as questions are corrected in order. When correcting a question, inject the results of same-parent sibling questions (those sharing the same parent in the question tree, answered before the current one) into the marking prompt as a "Prior part results" block.

**Scope:** `lemely/io/correction_ai.py`, `lemely/io/prompts/correction_ai.py`.

---

### Fix 2 — Confidence rubric in both prompts

**Problem:** The current instruction "set below 0.7 when uncertain" is too vague. LLMs are systematically overconfident; Flash reports ≥0.75 even on genuinely borderline marks, making the escalation threshold nearly useless.

**Fix:** Replace the vague instruction with explicit calibrated bands in both the extraction and correction system prompts:

- `0.95–1.00` — exact match to a listed mark point or accepted variant; no judgment required
- `0.80–0.95` — clear owtte match / minor wording difference; confident but applied judgment
- `0.60–0.80` — borderline; could go either way, or phrasing genuinely ambiguous
- `0.00–0.60` — handwriting unclear (extraction) or mark scheme interpretation uncertain (correction)

**Scope:** `lemely/io/prompts/answer_extraction.py`, `lemely/io/prompts/correction_ai.py`. Bump VERSION in both files.

---

### Fix 3 — Raise escalation threshold to 0.80

**Problem:** `escalation_confidence_threshold = 0.6` in config almost never fires because Flash rarely reports below 0.70. The Pro fallback is effectively dead.

**Fix:** Change the default to `0.80`. Questions in the borderline band (0.60–0.80) get re-marked by Pro before being returned. The exact value is tuned empirically using the calibration curve: find the lowest confidence bucket where actual accuracy exceeds 99%.

**Scope:** `lemely.toml.example`, `lemely/runtime/example_toml.py`.

---

### Fix 4 — Raise `needs_teacher_review` threshold to 0.80

**Problem:** Currently `needs_teacher_review = confidence < 0.70`, misaligned with the escalation threshold.

**Fix:** Change to `confidence < 0.80` so teacher-review flagging and Pro escalation fire on the same population.

**Scope:** `lemely/io/correction_ai.py` (`_build_ai_corrected`).

---

### Fix 5 — Few-shot examples in both prompts

**Problem:** Without worked examples, the model applies boundary-case rules inconsistently — especially owtte acceptance, M/B mark distinction, and ambiguous MCQ letters.

**Fix:** Add 2–3 worked examples directly in each system prompt:

- **Extraction examples:** one unambiguous MCQ letter, one handwritten calculation with working, one ambiguous case (partially circled letter) with low confidence and description.
- **Correction examples:** one exact mark-point match (HIGH confidence), one owtte acceptance (MEDIUM), one borderline rejection with feedback citing the mark code.

**Scope:** `lemely/io/prompts/answer_extraction.py`, `lemely/io/prompts/correction_ai.py`. Bump VERSION.

---

### Fix 6 — Enable thinking budget for borderline correction

**Problem:** Questions where Flash returns confidence < 0.80 go straight to Pro escalation, which is expensive. Flash 2.5 with a thinking budget handles many borderline cases correctly at a fraction of Pro cost.

**Fix:** For questions where first-pass Flash confidence falls below the escalation threshold, retry with `thinking_budget > 0` before promoting to Pro. If thinking Flash still returns confidence below the threshold, escalate to Pro as normal. Add `correction_borderline` to the `[gemini.thinking_budget_for]` config section with a sensible default (e.g. 2000 tokens).

**Scope:** `lemely/io/correction_ai.py`, `lemely/runtime/config.py`, `lemely.toml.example`.

---

### Fix 7 — Correction prompt: explicit mark-point reasoning chain

**Problem:** The model pattern-matches on the overall answer rather than checking each mark point explicitly. Multi-point questions (e.g. 3-mark recall with three distinct B marks) frequently miss one or two points.

**Fix:** Add an instruction before `Return:` in the marker system prompt: "Before writing `awarded_marks`, go through each mark point in the scheme one by one and state whether the student satisfied it and why. Then sum only the satisfied marks."

**Scope:** `lemely/io/prompts/correction_ai.py`. Bump VERSION.

---

### Fix 8 — Extraction prompt: per-type failure mode guidance

**Problem:** The extraction prompt handles ambiguous cases generically. The hardest real-world cases — partially circled MCQ letters, multi-line numerical answers, crossed-out attempts — get inconsistent treatment.

**Fix:** Add type-specific handling:
- **MCQ ambiguous:** "If the circled letter is unclear, set confidence < 0.50 and describe what you see in `source_region`."
- **Calculation:** "Preserve the student's exact units and standard form. If the answer spans multiple lines, concatenate."
- **Crossed-out:** "Transcribe the final (non-crossed-out) attempt as `answer`. Record crossed-out legible attempts in `working_out`."

**Scope:** `lemely/io/prompts/answer_extraction.py`. Bump VERSION.

---

### Fix 9 — Question ID normalization

**Problem:** Extracted question IDs are matched to the mark scheme manifest by exact string. Any OCR drift (`1 a i` vs `1(a)(i)`, `1a` vs `1(a)`) produces a silent miss — the question is treated as unanswered rather than as an extraction error.

**Fix:** After extraction, canonicalize all extracted IDs using a normalization function: strip spaces, standardize brackets. Fall back to fuzzy positional matching (by question order in the manifest) if canonical match fails. Log a warning when positional fallback is used.

**Scope:** `lemely/io/answer_extraction.py` (post-extraction normalization step).

---

### Fix 10 — Mark scheme validation gate

**Problem:** If the parser miscaptures a mark point (wrong text, missing alternative, wrong mark type), every correction for that question is corrupted with no visible warning.

**Fix:** After parsing, assert structural invariants: every leaf question has ≥1 mark point or a valid MCQ answer (A–D), no leaf has `marks == 0`, mark totals sum to declared `maximum_mark`. Emit structured warnings (not crashes) for violations. Warnings surface in CLI output and in the event bus so the UI can display them.

**Scope:** `lemely/io/subject.py` or a new `lemely/io/validation.py`.

---

## 4. Confidence Calibration

Calibration converts the model's raw confidence score into an empirically-grounded threshold.

**Process:**
1. Run `lemely eval-accuracy` on the full golden set.
2. Read the calibration curve — identify the lowest bucket where actual accuracy ≥ 99%.
3. Set `escalation_confidence_threshold` to the lower bound of that bucket.
4. Re-run to verify `flag_precision (HIGH)` meets target.

**Staleness:** Calibration data is keyed on the VERSION strings of all three prompt files. If any VERSION changes, the harness discards cached calibration and forces a fresh run.

**Stored results:** Each eval run writes to `tests/golden/results/YYYY-MM-DD-<git-sha>.json`, providing a history of accuracy over time and enabling regression detection across model upgrades.

---

## 5. CI Integration

The eval harness is not wired to CI by default — it calls the live Gemini API and has non-trivial cost. It runs in two situations:

**Mandatory — on prompt VERSION changes**
A `make eval` target detects changes to any of the three prompt files and must be run and pass before merging. VERSION mismatches in cached calibration data force a fresh run automatically.

**On demand**
Run manually when:
- Adding new golden cases
- Upgrading model versions (e.g. Flash preview → stable)
- Tuning `escalation_confidence_threshold`
- Investigating a reported accuracy regression

**What is never in CI**
The harness never runs on PRs that touch only non-prompt code (schemas, IO wiring, CLI). Those are covered by the existing fast unit test suite. The split keeps CI cheap.

---

## Implementation Order

1. Golden dataset + `lemely eval-accuracy` harness (prerequisite; measure baseline first)
2. Fix 10 — Mark scheme validation gate (catch upstream corruption before fixing downstream)
3. Fix 9 — Question ID normalization (reduce silent misses before measuring correction)
4. Fix 2 — Confidence rubric + Fix 7 — Mark-point reasoning chain (prompts; re-measure)
5. Fix 5 — Few-shot examples (prompts; re-measure)
6. Fix 8 — Extraction per-type guidance (prompts; re-measure)
7. Fix 1 — ECF cross-part context (code change; re-measure)
8. Fix 3 + Fix 4 — Escalation and review thresholds (tune from calibration data)
9. Fix 6 — Thinking budget for borderline correction (cost-accuracy tradeoff; tune last)
