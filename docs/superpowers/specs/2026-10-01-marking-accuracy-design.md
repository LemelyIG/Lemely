# Marking accuracy fixes: #272, #270, #271, #264, #201

Date: 2026-10-01. Status: approved design, owner decisions recorded below.

Branch `fix/marking-accuracy`, stacked on `feat/ai-improvements` at d66685b1 (PR #237, CI green). It opens its own PR into `develop` and is rebased or retargeted once #237 merges. A sibling branch, `fix/scan-render-safety`, is designed in `2026-10-01-scan-render-safety-design.md` and runs in parallel. The two share one decision, the Cloud Run memory budget, recorded in both specs.

Line numbers refer to d66685b1.

## Goal

Close five open issues on the marking path without moving marks:

- **#272:** the default (legacy) coherence check falsely flags either/or pairs and det-shaped schemes, which inflates the review rate.
- **#270:** the equivalence parser misreads function names followed by digits, `(x+1)2`, `x` used as a times sign, and the micro sign.
- **#271:** the equivalence parse worker's lock wait is unbounded, and the 2,526-line module needs splitting.
- **#264:** two identical text-agreement functions.
- **#201:** the accuracy-metrics umbrella, of which cost per paper is built here and the rest is filed or declined.

## Owner decisions

| # | Issue | Decision |
|---|---|---|
| D1 | #270 | `sin2x` is read as `sin(2x)` (CAIE convention), pinned both ways by tests. |
| D2 | #271 | The parse worker keeps its 512 MiB `RLIMIT_AS`. Cloud Run moves to `--memory=2Gi` (made in the scan-safety branch, decision S1 there), so the sum of worker caps fits the instance. |
| D3 | #272 | Unify the legacy coherence rule on the grouped interval and refresh `BUILD/review-rate-baseline.json` in the same PR, disclosed as a review-flag re-baseline. |
| D4 | #264 | Deduplicate into one shared function (difflib, 0.8 thresholds unchanged), then close #264. No follow-up issue for the threshold. |
| D5 | #201 | Build cost per paper only. File paper-type detection accuracy, handwriting error rate (CER), rationale and ECF adherence, and mark-scheme parser fidelity as separate issues. Decline the weighted overall score. Close #201. |

## Global constraints

- No mark moves. Only #272 changes outputs, and it changes `needs_teacher_review` and `review_reason`, never `awarded_marks`.
- The harness fingerprint pin `af7fa9cd0e2a` (`tests/test_accuracy_harness.py::test_flag_off_fingerprint_is_unchanged`) reads unchanged after every commit. No change to `_params_fingerprint`, prompt `VERSION`s or wire schemas.
- `equivalence_gate` stays off. The review-rate ratchet stays unarmed, and its targets in `lemely/runtime/config.py` are not touched.
- TDD: each behaviour change lands with a test that is red before it and green after. Pure refactors carry a behaviour-preservation test that is green before and after.
- Signed conventional commits, each naming only its own paths (`git commit -S -- <paths>`). Synthetic fixtures only. Never the full test suite locally: run the touched test files. `tests/test_equivalence.py` runs on its own, not alongside another lane's suite, because its computed-exponent test is load-sensitive.
- Every command pins `PYTHONPATH` to this worktree (the shared venv's editable `.pth` can point at another worktree).

## 1. #272: one coherence rule

### Problem

`_check_coherence` (`lemely/io/correction_ai.py:769-918`) has two branches:

- **Verdict path:** passes `groups` and gets the group-aware interval, clamped at `question.marks` (`:879-906`).
- **Legacy path:** the default, used while `equivalence_gate` is off. It calls the function without groups (`:1479`) and gets the old global rule (`:908-912`): points flagged `is_alternative` or `is_optional` are non-additive, and everything else is primary and additive.

The global rule is wrong for either/or pairs by construction:

- **Either/or pairs.** Only the second member of a pair carries `is_alternative` (`lemely/core/point_groups.py:34-37`). Take a 1-mark question where the marker matched both routes `[p1, p2]` and awarded 1. The rule computes an implied interval of `[2, 2]`, so the award of 1 is flagged.
- **Det-shaped schemes.** Five 1-mark independent points on a 4-mark question give `[5, 5]`. The award was already clamped to 4 at `:1476`, so a fully correct answer is flagged. The corpus has 4 such schemes out of 479 (`lemely/io/det/reconcile.py:47`).

The legacy path already awards by the group rule: `_awarded_after_backstop` at `:1086` goes through `_group_capped_total`. It checks coherence by a different rule. That mismatch is the defect.

### Design

- `_build_ai_corrected` computes `_, groups = _scheme_groups(question)` and passes `groups=groups` to `_check_coherence`.
- The `groups is None` branch is deleted. One interval computation remains: the grouped branch, including the `question.marks` clamp.
- This reverses the 2026-09-26 spec's §1 statement that the legacy path keeps the global rule. The PR description says so.
- The out-of-range check (`:1476-1477`) is unchanged.

**Disclosed behaviour change.** For an "any N from" pool with a stated `select_count`, the grouped interval tops out at the pool cap. A marker that matched three members of an "any 2 from" pool and awarded 3 is now flagged where the legacy rule let it through. That flag is true (an over-award), but it is new, so the measurement reports both directions.

### Tests (`tests/test_correction_ai.py`, through `correct_paper` with default `MarkingOptions`)

- **Either/or (red today with "between 2 and 2"):** a 1-mark question with p1 and p2 (`is_alternative`), and a fake marker returning `awarded_marks=1`, `matched_point_ids=[p1, p2]`, confidence 0.95. Assert `needs_teacher_review is False` and `review_reason is None`.
- **Det-shaped (red today with "between 5 and 5"):** a 4-mark question whose five independent 1-mark points are all matched, awarded 4. Assert no review.
- **New true flag:** an "any 2 from 4" pool (`select_count` 2) on a 4-mark question, three matched, awarded 3. Assert it is flagged.
- **Guards that stay green:**
  - matched `[p2]` only, awarded 1;
  - `test_any_3_from_5_optional_award_is_coherent`;
  - `test_award_outside_the_implied_range_still_flags`;
  - `CoherenceTriggerWiringTests`;
  - the fingerprint pin.

### Measurement and re-baseline (accuracy-measurer, after the commit)

Coherence is deterministic Python downstream of the marker's response. Both runs therefore replay cached marker outputs (`--cache-mode read_write`) and cost nothing.

On the dev split, before and after, report:
- `review_rate_signal`, `review_rate_total`, `per_paper_p95` and `coherence_trigger_rate`;
- the count of leaves whose flag disappeared;
- the count of leaves whose flag appeared;
- per-path mark metrics, asserted identical (they must be, by construction).

Then:
- Refresh `BUILD/review-rate-baseline.json` with the after-numbers.
- Record the run under `BUILD/accuracy-runs/<run>/`.
- State the re-baseline in the PR. CI prints the committed file (`scripts/check_review_rate_gate.py:84-93`), so its output changes on purpose.

If the net rate goes up, the PR still ships and reports the numbers as measured. The two directions are never netted silently.

## 2. #270: four equivalence misreads

### Problem

`lemely/core/equivalence.py` decides `equivalent`. With the gate off it is not on the marking path, but it is on the default generation path: `lemely/io/question_gates.py:55`, `_safe_equivalent` at `:199`. These misreads are also the stated blockers for turning the gate on.

1. **Function names.** `_rewrite_digit_suffixes` (`:748-828`) leaves a known function name followed by digits untouched (`:812-813`). SymPy's `split_symbols` then breaks the unknown identifier into letters, so `ln6` and `3ln2` both become `6*l*n` and compare `EQUAL_PROVEN`. `Asin(ωt1)` splits the same way.
2. **`(x+1)2`** is read as `(x+1)*2`. The student almost always means a lost superscript.
3. **`3.0x10^8`.** `_normalize_text` (`:846-865`) maps `×·∙` to `*`, but a letter `x` stays a symbol. `question_gates.py:95-99` carries its own `_SCI_X_NOTATION_RE` for this shape.
4. **The micro sign.** The tables use U+00B5, and the module does no Unicode normalisation. The suspected mechanism: Python's tokenizer NFKC-folds identifiers to U+03BC, which misses the `local_dict` keys. This is unverified. The implementer records a probe of both spellings before fixing.

### Design (a new pre-pass in `_normalize_text`, before `_rewrite_digit_suffixes`)

1. **Function application, driven by `_ALLOWED_FUNCTIONS`:**
   - A name followed by `(` is left alone.
   - `log10(` becomes a base-10 log.
   - A letter run that ends in a function name (`Asin`) becomes coefficient times function.
   - A name followed directly by an argument is bracketed. The argument can be:
     - a number: `ln6` becomes `ln(6)`, `3ln2` becomes `3*ln(2)`;
     - one symbol with an optional subscript: `sinx`, `cosθ1`, consistent with the existing `sinx2` rows;
     - a number then one symbol: `sin2x` becomes `sin(2*x)` (D1).
2. **A digit directly after `)`** makes `parse_expr_safe` return `None` (route to review). `)x`, `)(` and `)^2` are unaffected.
3. **Times sign.** `x` or `X` between a number and `10` that is followed by an exponent marker (`^`, `**`, or an unfolded superscript) becomes `*`. Deliberately narrow: `2x`, `5x3` and `x10` stay symbols. `question_gates._expand_sci_x_notation` and its regex are then deleted, so the rule lives in one place.
4. **One micro.** U+00B5 maps to U+03BC at the top of `_normalize_text`, and the tables are spelled with U+03BC. `u` stays an ASCII alias.

### Tests (`tests/test_equivalence.py`, one parametrised block)

Every "not equal" and "unparseable" row is red today. The equal twins are guards.

| Left | Right | Expected |
|---|---|---|
| `ln6` | `3ln2` | not equal |
| `ln6` | `ln(6)` | equal |
| `3ln2` | `ln(8)` | equal |
| `sin2x` | `2sinx` | not equal |
| `sin2x` | `sin(2x)` | equal |
| `2sinx` | `2*sin(x)` | equal |
| `log10(100)` | `2` | equal |
| `Asin(ωt1)` | `A*sin(ω*t_1)` | equal |
| `(x+1)2` | anything | unparseable |
| `(x+1)^2` | `x^2+2x+1` | equal |
| `3.0x10^8` | `3.0×10^8` | equal |
| `3.0x10^8` | `3.0*10**8` | equal |
| `2x` | `2*x` | equal |
| `4.5 µg` (U+00B5) | `4.5 μg` (U+03BC) | equal |
| `4.5 µg` | `4.5 mg` | not equal |

The existing suite stays green, the `sinx2` rows in particular. `tests/test_question_generation.py` stays green after the gate's duplicate rule is removed.

### Accuracy impact

- **Marking:** no marking change with the gate off, so no mark re-baseline. The fingerprint is unchanged.
- **Question generation:** which generated questions the gate accepts changes on the default path. No harness metric measures this, and the PR says so instead of claiming neutrality.

## 3. #271: bounded lock wait and the module split

### Lock deadline

**Problem.** `_ParseWorker.parse` (`:1107-1141`) holds `self._lock` for the whole send, poll and receive. Waiters block with no timeout, and the caller's `timeout` starts only once the lock is held. So the k-th concurrent caller waits about k times the parse timeout, plus a cold start of up to 30 s.

**Design.** `parse` computes `deadline = monotonic() + timeout`:
- It acquires the lock with `acquire(timeout=remaining)`.
- It polls with whatever budget remains.
- On a failed acquire it returns `None` with `last_outcome = "busy"`.

There is no worker pool. A warm call measures 0.3-0.6 ms, so contention is a cold-start and runaway-sibling problem, not a throughput one.

**Tests.**
- **Busy:** the test holds `worker._lock` and calls `worker.parse("1+1", timeout=0.2)` on another thread. Assert it returns `None` within 0.5 s with `last_outcome == "busy"`. Red today: the call blocks until the lock is released.
- **Guard:** once the lock is free, a normal call still parses.

### Memory

`_PARSE_WORKER_MEMORY_BYTES` stays 512 MiB (D2). The issue's memory concern is closed by the 2 GiB instance in the scan-safety branch. The issue's closing comment cites that budget table.

### Split (lands last, pure move)

- **`lemely/core/equivalence_tables.py`:** unit symbols, prefixes, aliases, reserved names, allowed functions, the local dict, the transformations.
- **`lemely/core/equivalence_worker.py`:** the memory and timeout constants, the explosion bounds, `_parse_normalized`, `_vet_and_parse`, `_parse_worker_main`, `_ParseWorker`, the singleton and the fork hook.
- **`lemely/core/equivalence.py`** keeps `parse_expr_safe`, `_normalize_text`, the tolerance machinery and `equivalent`. It re-exports `_PARSE_WORKER`, so the test references `eq._PARSE_WORKER` keep working.
- **Why two modules:** one `equivalence_worker` importing the local dict from `equivalence` would be a circular import.
- **Runtime:** the spawned child re-imports whichever module holds `_parse_worker_main`, so the move changes nothing at runtime.
- **`vet=False` stays.** Its test uses send inputs the vetting walk would refuse straight to the child, to prove the kill paths. Replacing it would need a test-only pipe message, which is a larger seam. The closing comment says so.

**Tests.**
- The whole equivalence suite passes unchanged.
- `tests/architecture` (import-linter) passes.
- One import test for `lemely.core.equivalence_worker`.

### Order within the lane

1. Lock deadline.
2. The #270 rewrites.
3. The split, last.

Splitting first would make the #270 behaviour changes land in modules reviewed as a pure move.

## 4. #264: one text-agreement function

- **New function:** `lemely/core/text_agreement.py` gets `text_agreement(a: str, b: str) -> float` with today's body: `difflib.SequenceMatcher(None, a.strip().casefold(), b.strip().casefold()).ratio()`.
- **Callers:** `lemely/io/reread.py` (its private `_text_agreement` is deleted) and `lemely/io/second_read.py` both import it.
- **Thresholds stay where they are and stay 0.8:**
  - `REREAD_REVIEW_AGREEMENT_THRESHOLD` (`reread.py:72`) gates review.
  - `REREAD_AGREEMENT_THRESHOLD` (`second_read.py:85`) gates re-read eligibility.

  They gate different decisions and may diverge once measured.
- **Tests (`tests/test_text_agreement.py`):**
  - The module imports.
  - `lemely.io.reread` and `lemely.io.second_read` resolve to the same function object (red before the refactor).
  - A table of pairs pins today's ratios to six decimals: `"A"`/`" a "` gives 1.0, plus several MCQ and numeric pairs. This table is green before and after.
- **Closing #264.** The closing comment records:
  - the difflib vs normalised-Levenshtein comparison from the design session;
  - that the 0.8 thresholds remain unvalidated;
  - that the planned I2 normaliser will plug into this function.

## 5. #201: cost per paper

### Design (`lemely/accuracy/harness.py` only)

- **Cost probe.** `measure_accuracy` takes a `cost_probe: Callable[[], dict[str, float]]` parameter, defaulting to `lemely.io.gemini.process_token_totals_by_task`. It snapshots the probe before and after each case.
- **New result fields.** `AccuracyResult` gains:
  - `cost_usd_by_paper: dict[str, dict[str, float]]`: paper id to task tag to USD;
  - `cost_usd_total: float`.
- **Reporting.**
  - `format_report` prints the per-paper mean and p95, with the manifest's `cache_mode` beside them. A cached call records no spend, so the figure is a real cost only at `--cache-mode bypass`.
  - `save_result` writes both fields.
- **Not in the fingerprint.** Cost is an outcome of the run, not a parameter. The pin is unchanged.
- **Out of scope:**
  - `lemely/app/cli.py` is not edited.
  - Per-student and per-session aggregation.
  - Production per-paper attribution (a DB column).

### Tests (`tests/test_accuracy_harness.py`)

- A fake probe returns known increasing totals. Assert the per-paper figures equal the deltas and the total equals their sum. Red before the fields exist.
- `test_flag_off_fingerprint_is_unchanged` stays green.

### Measurement

The measurer takes the first real number from one `--cache-mode bypass` dev run, costing about $1.25, and records it under `BUILD/accuracy-runs/`.

### Issue housekeeping (controller, after the PR opens)

- Comment on #201 with what is already measured: mark accuracy and per-path, flag precision and recall, calibration and risk-coverage, review rate and its gate, `agreement_wilson`, `id_match_rate`, `coherence_trigger_rate`, `paper_grade_confidence`.
- File four issues:
  1. Paper-type detection accuracy against the golden fixtures' metadata, scoring `ScanMetadataExtractor` in `lemely/io/scan_metadata.py`.
  2. Handwriting CER (plan item I2: gold transcriptions, jiwer, normaliser).
  3. Rationale and ECF adherence, needing pass-2 labels.
  4. Mark-scheme parser fidelity, with the det-vs-Gemini disagreement rate as a proxy.
- Record the weighted overall score as declined: a composite hides which component moved, and the programme's gates are per-metric non-regression.
- Close #201.

## Work breakdown

| Lane | Issue | Owns | Commits |
|---|---|---|---|
| 1 | #272 | `lemely/io/correction_ai.py`, `tests/test_correction_ai.py` | `fix(correction_ai): ...`; then the measurer's `BUILD/` artifacts in a separate `test(accuracy): ...` commit |
| 2 | #270, #271 | `lemely/core/equivalence.py`, new `lemely/core/equivalence_tables.py`, new `lemely/core/equivalence_worker.py`, `tests/test_equivalence.py`, `lemely/io/question_gates.py`, `tests/test_question_generation.py` | in order: lock deadline; #270 rewrites; split |
| 3 | #264 | new `lemely/core/text_agreement.py`, `lemely/io/reread.py`, `lemely/io/second_read.py`, new `tests/test_text_agreement.py` | `refactor(io): ...` |
| 4 | #201 cost | `lemely/accuracy/harness.py`, `tests/test_accuracy_harness.py` | `feat(accuracy): ...` |

All four lanes start at once, and lane 2 is serial within itself. Review and verification:
- Each task is reviewed at its SHA, with `accuracy-reviewer` for lanes 1 and 4.
- The gate sweep, using commands derived from `.github/workflows/ci.yml` including `check_review_rate_gate.py`, runs on the final tree.
- A whole-branch opus review runs at the end.

## Risks

- **Review-rate direction.** #272 moves the review rate both ways. Report both counts.
- **Micro sign.** The #270 micro mechanism is inferred, not probed. If the probe shows a different cause, the one-code-point fix still holds, but the test rows may need a second spelling.
- **Load-sensitive suite.** `tests/test_equivalence.py` is slow (about 94 s) and load-sensitive. Run it alone.
- **Ruff autofix.** The ruff hook autofixes, so re-check `git status` after `pre-commit` before committing.

## Out of scope

- Arming the ratchet or changing its targets.
- Turning `equivalence_gate` on.
- rapidfuzz, jiwer and the I2 normaliser.
- Label campaigns.
- Production cost attribution.
- The out-of-range flag on overfull det schemes. Lane 1's measurement reports its size, and a follow-up is filed only if it is material.
