# Marking Accuracy Fixes (#272, #270, #271, #264, #201) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close #272, #270, #271, #264 and the cost-per-paper half of #201 on branch `fix/marking-accuracy` without moving a single awarded mark, per the approved spec `docs/superpowers/specs/2026-10-01-marking-accuracy-design.md`.

**Architecture:** Four independent lanes start at once. Lane 1 unifies the legacy coherence check on the grouped interval that the award path already uses (one diff in `correction_ai.py`) and then re-baselines the review rate from cached marker output. Lane 2 is serial inside itself: bound the parse worker's lock wait by the caller's deadline, then add a function-application pre-pass, a `)digit` refusal, a narrow `x`-as-times rule and one micro code point to `_normalize_text` (deleting the generation gate's duplicate `x 10^n` rule), then split `equivalence.py` into `equivalence_tables.py`, `equivalence_worker.py` and a facade that re-exports what the tests reference. Lane 3 moves the duplicated difflib agreement function into `lemely/core/text_agreement.py`. Lane 4 snapshots `process_token_totals_by_task()` around each harness case and records USD per paper on `AccuracyResult`, then takes one `--cache-mode bypass` measurement.

**Tech Stack:** Python 3.12-3.14, pydantic v2, SymPy (`parse_expr` with `implicit_multiplication_application`), `multiprocessing` spawn worker, `difflib`, structlog, pytest + unittest, ruff, mypy (strict), pyright, import-linter, pre-commit.

## Global Constraints

Copied verbatim from the spec (section "Global constraints"):

- No mark moves. Only #272 changes outputs, and it changes `needs_teacher_review` and `review_reason`, never `awarded_marks`.
- The harness fingerprint pin `af7fa9cd0e2a` (`tests/test_accuracy_harness.py::test_flag_off_fingerprint_is_unchanged`) reads unchanged after every commit. No change to `_params_fingerprint`, prompt `VERSION`s or wire schemas.
- `equivalence_gate` stays off. The review-rate ratchet stays unarmed, and its targets in `lemely/runtime/config.py` are not touched.
- TDD: each behaviour change lands with a test that is red before it and green after. Pure refactors carry a behaviour-preservation test that is green before and after.
- Signed conventional commits, each naming only its own paths (`git commit -S -- <paths>`). Synthetic fixtures only. Never the full test suite locally: run the touched test files. `tests/test_equivalence.py` runs on its own, not alongside another lane's suite, because its computed-exponent test is load-sensitive.
- Every command pins `PYTHONPATH` to this worktree (the shared venv's editable `.pth` can point at another worktree).

Owner decisions, verbatim from the spec:

| # | Issue | Decision |
|---|---|---|
| D1 | #270 | `sin2x` is read as `sin(2x)` (CAIE convention), pinned both ways by tests. |
| D2 | #271 | The parse worker keeps its 512 MiB `RLIMIT_AS`. Cloud Run moves to `--memory=2Gi` (made in the scan-safety branch, decision S1 there), so the sum of worker caps fits the instance. |
| D3 | #272 | Unify the legacy coherence rule on the grouped interval and refresh `BUILD/review-rate-baseline.json` in the same PR, disclosed as a review-flag re-baseline. |
| D4 | #264 | Deduplicate into one shared function (difflib, 0.8 thresholds unchanged), then close #264. No follow-up issue for the threshold. |
| D5 | #201 | Build cost per paper only. File paper-type detection accuracy, handwriting error rate (CER), rationale and ECF adherence, and mark-scheme parser fidelity as separate issues. Decline the weighted overall score. Close #201. |

Correction to the verbatim constraint above (kept verbatim because the spec governs): the literal `af7fa9cd0e2a` lives in `tests/test_accuracy_harness.py::RunManifestTests::test_params_fingerprint_for_no_arm_override_is_unchanged` (`:1605`, assertion at `:1647`); `test_flag_off_fingerprint_is_unchanged` (`:1692`) asserts that a flags-off `GradingSettings` leaves the hash equal and holds no literal. Every "fingerprint pin" check in this plan runs both (`-k fingerprint`).

Plan-level rules (from the plan brief and the project's CLAUDE.md):

- Worktree: `/home/sico/Code/Lemely/.claude/worktrees/fix-marking-accuracy`, branch `fix/marking-accuracy`, starting at `a1563b4f`. Every command below runs from that directory. `file:line` anchors are against `a1563b4f` (identical to `d66685b1` for every file this plan names; `a1563b4f` only added the spec). Where an earlier task in the same lane shifts a line, search for the quoted code.
- Test command shape: `PYTHONPATH=$PWD .venv/bin/python -m pytest <files> -q --no-cov`. Pre-commit shape: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files <paths>`. The ruff hook autofixes, so after pre-commit re-run `git status --short` and re-run the touched tests on what you are about to commit.
- Commits: `git commit -S -m "<msg>" -- <paths>`. Never `git add -A`, `git add .`, `git stash`, `git reset`. Do not push. Do not open a PR (the controller asks the owner).
- Scratch for probes, logs and measurement outputs: `/home/sico/.claude/jobs/33cebc31/tmp/plans/` (make a per-task subdirectory). Never `/tmp`, never `tests/golden/results/` (a fresh file there is preferred over the committed baseline by `scripts/check_review_rate_gate.py:63-72` and would silently change what the gate sweep reads).
- No `TODO`, `test.skip`, stub tests or unimplemented branches. No new dependencies. Layering (`pyproject.toml` `[tool.importlinter]`): `lemely.app` > `lemely.io` > `lemely.core`; `lemely.core` never imports `io`; `lemely.eval` never imports `io` or `app`.
- Reviews: every task is reviewed at its commit SHA (`git diff <sha>^ <sha>`, never the working tree, which carries other lanes' uncommitted edits). Lanes 1 and 4 (Tasks 1, 4, 5, 7) use the `accuracy-reviewer` agent type; lanes 2 and 3 (Tasks 2, 3, 6, 8) use the `reviewer` agent type. The `accuracy-measurer` agent type runs Tasks 5 and 7.
- The fingerprint pin is computed by `lemely/accuracy/harness.py::_build_run_manifest` (`:874-1050`) from settings, flags and prompt versions, never from code or run outcomes, so no task here can move it; every lane that touches marking or the harness still runs the pinning tests to prove it.

## Task map and waves

| Wave | Tasks (run in parallel within a wave) | Agent | Files owned (disjoint within the wave) |
|---|---|---|---|
| 1 | Task 1 (#272 fix) | accuracy-implementer | `lemely/io/correction_ai.py`, `tests/test_correction_ai.py` |
| 1 | Task 2 (#271 lock deadline) | accuracy-implementer | `lemely/core/equivalence.py`, `tests/test_equivalence.py` |
| 1 | Task 3 (#264 dedupe) | accuracy-implementer | `lemely/core/text_agreement.py` (new), `lemely/io/reread.py`, `lemely/io/second_read.py`, `tests/test_text_agreement.py` (new) |
| 1 | Task 4 (#201 cost fields) | accuracy-implementer | `lemely/accuracy/harness.py`, `tests/test_accuracy_harness.py` |
| 2 | Task 5 (#272 measurement + re-baseline; after Task 1 is committed and reviewed) | accuracy-measurer | `BUILD/review-rate-baseline.json`, `BUILD/accuracy-runs/coherence-272-2026-10-01/` (new) |
| 2 | Task 6 (#270 rewrites + gate dedupe; after Task 2) | accuracy-implementer | `lemely/core/equivalence.py`, `tests/test_equivalence.py`, `lemely/io/question_gates.py`, `tests/test_question_generation.py` |
| 2 | Task 7 (#201 cost measurement; after Task 4) | accuracy-measurer | `BUILD/accuracy-runs/cost-201-2026-10-01/` (new) |
| 3 | Task 8 (#271 split; after Task 6) | accuracy-implementer | `lemely/core/equivalence.py`, `lemely/core/equivalence_tables.py` (new), `lemely/core/equivalence_worker.py` (new), `tests/test_equivalence.py` |
| 4 | Task 9 (gate sweep; after every commit above) | verifier | none (read-only; a fixup commit only if autofix changed something) |
| 5 | Task 10 (whole-branch review) | accuracy-reviewer (opus) | none |
| 6 | Task 11 (issue housekeeping; after the owner opens the PR) | controller / accuracy-scribe | GitHub only |

Lane 2 is strictly serial: Task 2, then Task 6, then Task 8. Splitting before #270 would land behaviour changes inside modules reviewed as a pure move. Tasks 2, 6 and 8 all run `tests/test_equivalence.py` alone (about 94 s); no other lane runs it, and each of those runs is controller-scheduled: it happens only when the controller confirms no other lane's pytest is running (the implementer reports `NEEDS_CONTEXT` if unsure, and the controller sequences it).

---

### Task 1: #272 — check legacy-path coherence on the grouped interval

**Files:**
- Modify: `lemely/io/correction_ai.py` — `_check_coherence` `:769-918` (signature `:775`, docstring `:814-836`, interval block `:878-912`), legacy call site in `_build_ai_corrected` `:1476-1480`.
- Test: `tests/test_correction_ai.py` — new class `LegacyPathGroupedCoherenceTests` inserted after `CoherenceGateTests` (ends `:3678`), the one direct caller at `:3184` updated to pass `groups`, and the import at `:6311` (`from lemely.io.reread import _text_agreement`, inside `test_text_agreement_is_case_and_whitespace_insensitive`) repointed to `from lemely.io.second_read import text_agreement` with the call at `:6313` renamed to match. That test is green before and after (both functions exist today with the same body) and it stops breaking when Task 3 deletes `reread._text_agreement`; Task 1 owns this file, so the repoint lands here, not in Task 3.

**Interfaces:**
- Consumes: `_scheme_groups(question) -> tuple[list[AnswerPoint], list[tuple[str | None, int | None]]]` (`:1054`), `correct_paper(mark_scheme, extracted_answers, *, gemini_client, ...)` with the default `MarkingOptions()` (gate off), `_client_with_seq(tmp, responses)` and `_mock_marker_response(awarded, matched)` test helpers (`tests/test_correction_ai.py:93`, `:78`; note `_mock_marker_response` hard-codes `confidence=0.9`, which equals `REVIEW_CONFIDENCE_THRESHOLD` and does not flag because the check at `:1499` is `<`, so no confidence flag interferes).
- Produces: `_check_coherence(question, matched_point_ids, awarded_marks, *, point_verdicts=None, groups)` where `groups: Sequence[tuple[str | None, int | None]]` is a **required** keyword (no default). The `groups is None` branch (`:907-912`) is gone; one interval computation remains, including the `question.marks` clamp at `:905-906`. `_build_ai_corrected` computes `_, groups = _scheme_groups(question)` and calls `_check_coherence(question, list(mark.matched_point_ids), clamped, groups=groups)`. The out-of-range check at `:1476-1477` is unchanged. `COHERENCE_TRIGGER_MARKER` and every message string are unchanged (the harness trigger wiring depends on them).

- [ ] **Step 1: Write the failing tests**

Append `class LegacyPathGroupedCoherenceTests(unittest.TestCase)` to `tests/test_correction_ai.py` after `CoherenceGateTests`. Each test builds a one-question `MarkScheme` dict (copy the shape of `_hybrid_paper_mark_scheme` at `:33-62`, `scheme_format: "point_based"`, one `explanation` question unless stated), an `ExtractedAnswers` with one answer for that question, a client from `_client_with_seq(self.tmp, [_mock_marker_response(awarded, matched)])`, and calls `correct_paper(scheme, extracted, gemini_client=client)` with **no** `options` argument (default `MarkingOptions`, the legacy path). Assert on the `CorrectedQuestion` for that question id.

1. `test_either_or_pair_matched_both_ways_is_not_flagged`: 1-mark question, points `p1` (1 mark) and `p2` (1 mark, `is_alternative: true`); marker awards 1 with `matched_point_ids=["p1", "p2"]`. Assert `needs_teacher_review is False` and `review_reason is None`. Red today: `needs_teacher_review` is `True` and `review_reason` contains `"implies between 2 and 2"`.
2. `test_det_shaped_scheme_fully_matched_is_not_flagged`: 4-mark question whose `answer_points` are five independent 1-mark points `p1..p5`. `MarkScheme.model_validate` may reject a point sum above the tariff; if it does, build the question as `ClampedCoherenceIntervalTests` does at `:2955-2961` (construct with one point, then assign the five) and the scheme via `MarkScheme.model_construct`, exactly as `io/det/reconcile.py` bypasses the validator. Marker awards 4 with all five matched. Assert no review. Red today: `"implies between 5 and 5"`.
3. `test_over_award_on_a_stated_pool_is_now_flagged`: 4-mark `list` question with `select_count: 2` and four `is_optional` 1-mark points; marker matches three and awards 3. Assert `needs_teacher_review is True` and `COHERENCE_TRIGGER_MARKER in review_reason`. Red today: no flag (the legacy rule allows `[1, 3]`). This pins the disclosed new true flag that Task 5 must count.
4. `test_second_member_only_of_an_either_or_pair_is_not_flagged` (guard, green before and after): the pair from test 1, matched `["p2"]`, awarded 1, no review.

Also update `test_duplicate_point_id_does_not_trigger_review_on_legacy_path` (`:3176-3185`): compute `_, groups = _scheme_groups(q)` and pass `groups=groups` to the direct call; its assertion (`None`) is unchanged and stays green under the grouped rule (two occurrences of an independent 1-mark point give `[2, 2]` either way). This is the only direct `_check_coherence` caller in the tests besides `:2998`, which already passes `groups` (verify: `grep -n "_check_coherence(" tests/test_correction_ai.py` shows exactly those two).

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_correction_ai.py -k "LegacyPathGroupedCoherence" -q --no-cov`
Expected: tests 1-3 FAIL (1 and 2 with `needs_teacher_review` True and the "between N and N" reasons quoted above; 3 with `needs_teacher_review` False), test 4 passes. Save the output to `/home/sico/.claude/jobs/33cebc31/tmp/plans/t1/red.txt` and quote the three assertion lines in the task report.

- [ ] **Step 3: Implement**

In `_check_coherence`: make `groups` a required keyword; delete the `else:` branch at `:907-912`; keep the grouped block at `:879-906` as the single computation (drop the `if groups is not None:` guard, keep the body). Rewrite the paragraph of the docstring at `:814-836` so it describes one rule (grouped interval, both ends clamped at `question.marks`) and states that the legacy path now passes groups too, reversing the 2026-09-26 spec's §1 statement (name it). In `_build_ai_corrected`: before `:1479`, `_, groups = _scheme_groups(question)`; pass `groups=groups`. Update the `_build_ai_corrected` docstring reason 4 (`:1466-1469`) if it mentions the global rule. Do not touch `_verify_calculated_answers`, `_awarded_after_backstop`, the out-of-range check, or any message text.

- [ ] **Step 4: Run the touched test file and the harness pins**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_correction_ai.py -q --no-cov`
Expected: all pass, including `test_any_3_from_5_optional_award_is_coherent`, `test_award_outside_the_implied_range_still_flags`, `ClampedCoherenceIntervalTests`, `CoherenceGateTests` and the four new tests.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py -k "fingerprint or CoherenceTriggerWiring" -q --no-cov`
Expected: all pass, including `test_params_fingerprint_for_no_arm_override_is_unchanged` (`:1605`, which holds the literal `af7fa9cd0e2a` at `:1647`) and `test_flag_off_fingerprint_is_unchanged` (`:1692`, flags-off hash equality); `grep -c af7fa9cd0e2a tests/test_accuracy_harness.py` prints `1`.

- [ ] **Step 5: Pre-commit and commit**

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/io/correction_ai.py tests/test_correction_ai.py`, then `git status --short` (only those two paths may be modified), re-run Step 4's first command if ruff changed anything.

Commit: `git commit -S -m "fix(correction_ai): check legacy-path coherence on the grouped interval (#272)" -- lemely/io/correction_ai.py tests/test_correction_ai.py`

Report: the commit SHA, the three red assertion lines, the green counts, and the statement "fingerprint pin unchanged (settings-only hash; tests green)". Review by `accuracy-reviewer` at that SHA before Task 5 starts.

---

### Task 2: #271 — bound the parse worker's lock wait by the caller's timeout

**Files:**
- Modify: `lemely/core/equivalence.py` — `_ParseWorker.parse` `:1107-1141`; class docstring sentence at `:995-997` ("Calls are serialised by a lock ... waits at most one timeout plus one respawn"); the `last_outcome` comment at `:1019-1024` (add `"busy"`).
- Test: `tests/test_equivalence.py` — two tests inserted after `test_a_caller_queued_behind_a_timeout_gets_its_own_result` (`:2818-2848`).

**Interfaces:**
- Consumes: `threading.Lock.acquire(timeout=...)`, `time.monotonic()`, `_ParseWorker._ready()` (`:1097`), `Connection.poll(timeout)`.
- Produces: `parse(self, text: str, timeout: float, *, vet: bool = True) -> sympy.Expr | None` with the same signature and these semantics: `deadline = time.monotonic() + timeout` at entry; the lock is taken with `self._lock.acquire(timeout=max(0.0, deadline - time.monotonic()))`; on `False` the method sets `self.last_outcome = "busy"` and returns `None` without touching the child; otherwise everything that used to run under `with self._lock:` runs under a `try/finally: self._lock.release()`. The child start inside `_ready()` stays outside the budget, as the class docstring already promises: measure the time `_ready()` takes and add it to `deadline` before polling (`started = time.monotonic(); ready = self._ready(); deadline += time.monotonic() - started`). The poll uses `conn.poll(max(0.0, deadline - time.monotonic()))`. All other outcomes (`"unavailable"`, `"timeout"`, `"crash"`, `"interrupted"`, the reply kinds) are unchanged. No pool, no second worker.

- [ ] **Step 1: Write the failing tests**

1. `test_a_caller_that_cannot_take_the_worker_lock_returns_busy_within_its_timeout`: `worker = eq._ParseWorker()` (a private instance, never the singleton); `worker._lock.acquire()`; start a thread that stores `worker.parse("1+1", timeout=0.2)` and its elapsed time; `thread.join(1.0)`; record `finished_in_time = not thread.is_alive()`; then release the lock, `thread.join(30)`, and `worker.shutdown()`. Assert `finished_in_time is True`, `result is None`, `elapsed < 0.5`, `worker.last_outcome == "busy"`. Red today: the thread blocks until the lock is released, so `finished_in_time` is `False`, and after the release the old code parses successfully (`result == 2`, `last_outcome == "ok"`).
2. `test_the_worker_parses_normally_once_the_lock_is_free` (guard, green before and after): a fresh `eq._ParseWorker()`, `worker.parse("1+1", timeout=5.0) == sympy.Integer(2)`, `worker.last_outcome == "ok"`, then `worker.shutdown()`.

- [ ] **Step 2: Run them to verify the first fails**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -k "cannot_take_the_worker_lock or parses_normally_once_the_lock_is_free" -q --no-cov`
Expected: test 1 FAILS on `assert finished_in_time is True` (quote it); test 2 passes. Save to `/home/sico/.claude/jobs/33cebc31/tmp/plans/t2/red.txt`.

- [ ] **Step 3: Implement** the semantics in Interfaces. Keep `shutdown()`'s `with self._lock:` as is.

- [ ] **Step 4: Run the whole equivalence suite alone** (controller-scheduled: run only when the controller confirms other lanes are idle; if unsure, end the report with status `NEEDS_CONTEXT` and let the controller sequence it)

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q --no-cov`
Expected: all pass (about 94 s; no other lane's pytest running). `test_a_caller_queued_behind_a_timeout_gets_its_own_result` must still pass: its ordinary caller has a 5.0 s budget, and the runaway is killed at 1.0 s plus a respawn, so the lock frees well inside it.

- [ ] **Step 5: Pre-commit and commit**

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/core/equivalence.py tests/test_equivalence.py`; `git status --short`; re-run Step 4 if ruff changed anything.

Commit: `git commit -S -m "fix(core): bound the parse worker's lock wait by the caller's timeout (#271)" -- lemely/core/equivalence.py tests/test_equivalence.py`

Report the SHA and the red line. Review by `reviewer` at that SHA; Task 6 starts after the review passes.

---

### Task 3: #264 — one text-agreement function

**Files:**
- Create: `lemely/core/text_agreement.py`
- Modify: `lemely/io/reread.py` (`:16` `import difflib`, `:70` comment, `:165-180` `_text_agreement`, `:221` call), `lemely/io/second_read.py` (`:34-49` module docstring paragraph, `:54` `import difflib`, `:93-101` `text_agreement`, `:228` call).
- Create: `tests/test_text_agreement.py`
- Untouched and must stay green: `tests/test_reread.py`, `tests/test_second_read.py` (it imports `text_agreement` from `lemely.io.second_read` at `:27` and pins the 0.8 threshold at `:248`), `lemely/io/answer_extraction.py` (imports `REREAD_AGREEMENT_THRESHOLD` from `second_read`).

**Interfaces:**
- Produces: `lemely.core.text_agreement.text_agreement(a: str, b: str) -> float` whose body is exactly today's: `difflib.SequenceMatcher(None, a.strip().casefold(), b.strip().casefold()).ratio()`. Module docstring: the difflib stand-in for rapidfuzz, `.strip().casefold()` only (not the I2 normaliser), and that I2 will plug in here. `lemely.io.reread` and `lemely.io.second_read` both do `from lemely.core.text_agreement import text_agreement` (so `second_read.text_agreement` is the same object and `tests/test_second_read.py:27` keeps working); `reread._text_agreement` is deleted and its call at `:221` becomes `text_agreement(...)`. `REREAD_REVIEW_AGREEMENT_THRESHOLD = 0.8` (`reread.py:72`) and `REREAD_AGREEMENT_THRESHOLD = 0.8` (`second_read.py:85`) stay where they are and stay 0.8. Both `import difflib` lines go.

- [ ] **Step 1: Write the tests** in `tests/test_text_agreement.py` (pytest style):

1. `test_module_imports`: `from lemely.core.text_agreement import text_agreement`; assert it is callable. Red: `ModuleNotFoundError`.
2. `test_reread_and_second_read_share_one_function`: `from lemely.io import reread, second_read`; assert `reread.text_agreement is second_read.text_agreement` and both are the core function. Red: `AttributeError: module 'lemely.io.reread' has no attribute 'text_agreement'`.
3. `test_ratio_table_is_unchanged`, parametrised over `(a, b, expected)` with `expected == pytest.approx(value, abs=5e-7)` (six decimals), computed through `lemely.io.second_read.text_agreement` so the table is green **before** the refactor and still green after: `("A", " a ", 1.0)`, `("42 m/s", "42 m/s", 1.0)`, `("  42 M/S ", "42 m/s", 1.0)`, `("B", "D", 0.0)`, `("0.5", "1/2", 0.0)`, `("gravity acts on it", "gravity acts", 0.8)`, `("42 m/s", "42 ms", 0.909091)`, `("2.4 x 10^4 J", "2.4x10^4J", 0.857143)`. The last two were worked by hand (`2*M/T` with `M=5, T=11` and `M=9, T=21`); run the table against the pre-refactor tree first (Step 2) and if a hand value is off, correct the table to the measured ratio before touching any source. Never adjust the function to the table.

- [ ] **Step 2: Run to verify red/green as expected**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_text_agreement.py -q --no-cov`
Expected: tests 1 and 2 FAIL as quoted; every table row passes. Save to `/home/sico/.claude/jobs/33cebc31/tmp/plans/t3/red.txt`.

- [ ] **Step 3: Implement** the Interfaces block. Update the `second_read.py` docstring paragraph (`:34-49`) to name `lemely.core.text_agreement` as the one implementation, and the `reread.py:70` comment to name `text_agreement` instead of `_text_agreement`.

- [ ] **Step 4: Run the touched and dependent test files**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_text_agreement.py tests/test_reread.py tests/test_second_read.py tests/test_correction_ai.py tests/architecture -q --no-cov`
Expected: all pass (import-linter: `io -> core` is allowed; `tests/architecture/test_no_print_in_core.py` sees no print). `tests/test_correction_ai.py` is run read-only (Task 1 owns it): its `:6311` import of `reread._text_agreement` is repointed by Task 1 in the same wave, so if Task 1's commit is not yet in the tree the one expected failure is that `ImportError`; report it as `NEEDS_CONTEXT` rather than editing the file, and re-run once Task 1 has landed.

- [ ] **Step 5: Pre-commit and commit**

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/core/text_agreement.py lemely/io/reread.py lemely/io/second_read.py tests/test_text_agreement.py`; `git status --short`; re-run Step 4 if anything was autofixed.

Commit: `git commit -S -m "refactor(io): share one text_agreement function between reread and second_read (#264)" -- lemely/core/text_agreement.py lemely/io/reread.py lemely/io/second_read.py tests/test_text_agreement.py`

Review by `reviewer` at the SHA.

---

### Task 4: #201 — cost per paper on `AccuracyResult`

**Files:**
- Modify: `lemely/accuracy/harness.py` — `AccuracyResult` `:424-438`, `measure_accuracy` signature `:1081-1092` and loop `:1178-1351`, return `:1365-1383`, `format_report` `:1391-1503`, `save_result` `:1506-1560` (its `data` dict at `:1524-1559`).
- Test: `tests/test_accuracy_harness.py` — new class `CostPerPaperTests` placed after `RunManifestTests` (which ends before `SaveResultRoundTripTests` at `:2040`), reusing that class's `_mark_scheme`/`_case` shape (`:1389-1397`: an MCQ case marked deterministically, so `gemini_client=None` works).
- Not touched: `lemely/app/cli.py`, `lemely/eval/manifest.py`, `_build_run_manifest`.

**Interfaces:**
- Consumes: `lemely.io.gemini.process_token_totals_by_task() -> dict[str, float]` (`gemini.py:313`, task tag to accumulated USD, read under `_SPEND_LOCK`); `lemely.eval.analyses._percentile(sorted_values, p)` (nearest rank, `analyses.py:955`; `harness.py` already imports from `analyses`); `result.manifest.cache_mode`; `GoldenCase.paper_id` / `GoldenCase.fixture_variant`.
- Produces:
  - `measure_accuracy(..., n_unparseable: int = 0, cost_probe: Callable[[], dict[str, float]] | None = None)`. `None` resolves inside the function to `process_token_totals_by_task` (imported lazily next to the other `lemely.io` imports at `:1163-1168`; `Callable` comes from `collections.abc` under `TYPE_CHECKING`).
  - `AccuracyResult.cost_usd_by_paper: dict[str, dict[str, float]] = field(default_factory=dict)` and `AccuracyResult.cost_usd_total: float = 0.0`, both with defaults so the three test constructors in `tests/test_cli_review_rate_gate.py:73`, `tests/test_cli_coherence_trigger_rate.py:69` and `tests/test_cli_new_commands.py:638` keep working.
  - Per case: `before = cost_probe()` at the top of the loop body (before extraction or correction), `after = cost_probe()` right after `correct_paper` returns; `delta = {tag: after[tag] - before.get(tag, 0.0) for tag in after if after[tag] - before.get(tag, 0.0) > 0.0}`. Key: `case.paper_id` when `case.fixture_variant is None`, else `f"{case.paper_id}/{case.fixture_variant}"` (sibling variants share a `paper_id`, `harness.py:51-65`; summing them would report a four-variant paper as four times its cost). An empty delta is still stored, so a fully cached run shows `{}` per case. `cost_usd_total` is the sum of every value in every delta.
  - `format_report` appends, after the funnel block and before the re-read warning: `Cost per paper (cache_mode=<manifest.cache_mode>): mean=$<m:.4f> p95=$<p:.4f> total=$<t:.4f> over <n> case(s)` where the per-case figure is the sum of that case's tags, mean over cases (0.0 when there are none), and `p = _percentile(sorted(per_case_totals), 0.95)` (nearest rank; 0.0 when empty); and, when `cache_mode != "bypass"`, a second line `  (cached calls record no spend; this is a real cost only at --cache-mode bypass)`.
  - `save_result` adds `"cost_usd_by_paper": result.cost_usd_by_paper` and `"cost_usd_total": result.cost_usd_total` to the JSON.
  - Nothing is added to `RunManifest` or `_build_run_manifest`: cost is an outcome of the run, not a parameter; the pin does not move.

- [ ] **Step 1: Write the failing tests** (`CostPerPaperTests`; cases `p1` and `p2` built like `_case()` with distinct `paper_id`s and `fixture_variant=None`):

1. `test_cost_probe_deltas_are_attributed_per_case_and_summed`: a probe returning, call by call, `{"correction": 0.10}`, `{"correction": 0.25}`, `{"correction": 0.25, "extraction": 0.05}`, `{"correction": 0.40, "extraction": 0.05}`; `measure_accuracy([p1, p2], gemini_client=None, settings=None, cost_probe=probe)`. Assert the probe was called exactly 4 times, `cost_usd_by_paper == {"p1": {"correction": approx 0.15}, "p2": {"correction": approx 0.15}}` (no `extraction` key for `p2`: its delta is 0), `cost_usd_total == approx 0.30`. Red: `TypeError: measure_accuracy() got an unexpected keyword argument 'cost_probe'`.
2. `test_a_variant_case_is_keyed_by_paper_and_variant`: one case with `fixture_variant="partial"`, probe deltas as above for one case; assert the key is `"p1/partial"`. Red: `TypeError`.
3. `test_a_probe_that_reports_no_spend_yields_empty_cost`: probe always `{}`; assert `cost_usd_by_paper == {"p1": {}}` and `cost_usd_total == 0.0`. Red: `TypeError`.
4. `test_format_report_prints_cost_beside_the_cache_mode`: on test 1's result, `format_report(result, Settings().accuracy_eval)` (the stub the existing tests use at `:1177`) contains `"Cost per paper (cache_mode=read_write)"`, `"total=$0.3000"` and `"real cost only at --cache-mode bypass"`. Red: `TypeError` (no result to format) or missing line.
5. `test_save_result_writes_both_cost_fields`: `save_result(result, Path(tmp))`, load the JSON, assert `data["cost_usd_total"] == approx 0.30` and `data["cost_usd_by_paper"]["p1"]["correction"] == approx 0.15`. Red: `KeyError`.

- [ ] **Step 2: Run to verify red**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py -k CostPerPaper -q --no-cov`
Expected: all five FAIL with the errors above. Save to `/home/sico/.claude/jobs/33cebc31/tmp/plans/t4/red.txt`.

- [ ] **Step 3: Implement** the Interfaces block. mypy is strict with `disallow_any_explicit`; type the probe as `Callable[[], dict[str, float]]`.

- [ ] **Step 4: Run the harness test file and the CLI result consumers**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py tests/test_cli_review_rate_gate.py tests/test_cli_coherence_trigger_rate.py tests/test_cli_new_commands.py -q --no-cov`
Expected: all pass, including `test_params_fingerprint_for_no_arm_override_is_unchanged` (`:1605`, the literal `af7fa9cd0e2a` at `:1647`) and `test_flag_off_fingerprint_is_unchanged` (`:1692`).

- [ ] **Step 5: Pre-commit and commit**

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/accuracy/harness.py tests/test_accuracy_harness.py`; `git status --short`; re-run Step 4 if autofixed.

Commit: `git commit -S -m "feat(accuracy): record cost per paper on AccuracyResult (#201)" -- lemely/accuracy/harness.py tests/test_accuracy_harness.py`

Report the SHA and the five red lines. Review by `accuracy-reviewer` at that SHA before Task 7.

---

### Task 5: #272 — review-rate measurement and re-baseline (accuracy-measurer)

Runs only after Task 1's commit (`T1_SHA`) has passed review. Coherence is deterministic Python downstream of the marker's reply, so both runs replay cached marker output and the comparison is code-only.

**Files:**
- Modify: `BUILD/review-rate-baseline.json`
- Create: `BUILD/accuracy-runs/coherence-272-2026-10-01/` containing `compare.py`, `report.json`, `after-results.json` (the after-run's saved result, copied from scratch so the baseline's `source_run` points at a committed file).
- Scratch: `/home/sico/.claude/jobs/33cebc31/tmp/plans/m272/` (two detached scratch worktrees, a cache copy, a `lemely.toml`, two results dirs, logs). Nothing under `tests/golden/results/`.

**Interfaces:**
- Consumes: `lemely measure-accuracy --config <toml> --golden <dir> --results-dir <dir> --cache-mode read_write` (`lemely/app/cli.py:1147-1363`; `--config` is a group option at `:146`); `lemely.eval.analyses.review_rate`, `coherence_trigger_rate`, and its leaf helpers `_question_level`, `_scored`, `_group_by_leaf` (`analyses.py:29-115`); `EvalRecord.model_validate` over `data["eval_records"]`; `scripts/check_review_rate_gate.py`.
- Produces: the numbers listed in Step 6 and the refreshed baseline artifact.

- [ ] **Step 1: Pin the SHAs and build two isolated trees**

`T1_SHA=$(git log --format=%H -1 --grep='#272' -- lemely/io/correction_ai.py)`; `BASE_SHA=$(git rev-parse "$T1_SHA^")`. Then `git worktree add --detach /home/sico/.claude/jobs/33cebc31/tmp/plans/m272/before $BASE_SHA` and `git worktree add --detach /home/sico/.claude/jobs/33cebc31/tmp/plans/m272/after $T1_SHA`. Confirm `git -C .../after diff $BASE_SHA --stat` lists only `lemely/io/correction_ai.py` and `tests/test_correction_ai.py`.

- [ ] **Step 2: Config and cache**

The warm cache lives in the main checkout (`/home/sico/Code/Lemely/.lemely-cache`, 134 files); this worktree has none. `mkdir -p .../m272/cache && cp -r /home/sico/Code/Lemely/.lemely-cache/. .../m272/cache/`. Copy `/home/sico/Code/Lemely/lemely.toml` to `.../m272/lemely.toml` and, under `[paths]`, set `cache_dir = "/home/sico/.claude/jobs/33cebc31/tmp/plans/m272/cache"` and `output_dir = "/home/sico/.claude/jobs/33cebc31/tmp/plans/m272/outputs"` (both absolute; `output_dir` holds `gemini_spend.json`, and Task 7's process must not share it). `GEMINI_API_KEY` must be in the environment (never written anywhere). Run `PYTHONPATH=.../m272/before .venv/bin/lemely --config .../m272/lemely.toml doctor` and confirm it reports that toml and that cache dir. Note `per_run_token_ceiling = 200000` in that toml: a sweep is about 115k tokens only when calls go live, so one cold run fits and two do not; see Step 4's rule.

- [ ] **Step 3: The before run**

`N0=$(find .../m272/cache -type f | wc -l)`; `PYTHONPATH=.../m272/before .venv/bin/lemely --config .../m272/lemely.toml measure-accuracy --golden .../m272/before/tests/golden --results-dir .../m272/results-before --cache-mode read_write 2>&1 | tee .../m272/before.log`; `N1=$(find .../m272/cache -type f | wc -l)`. The CLI exits 1 when any target is missed (expected on this corpus); record the exit code, do not treat it as a failure. Record `N1 - N0` as "cache files added by the before run". `save_result` names the file after `git rev-parse --short HEAD` of the **cwd** (this worktree's HEAD, not `BASE_SHA`); the tree actually measured is the one on `PYTHONPATH`, which `report.json` records explicitly.

- [ ] **Step 4: The after run**

Same command with `PYTHONPATH=.../m272/after`, `--golden .../m272/after/tests/golden`, `--results-dir .../m272/results-after`, log `after.log`; count `N2`. Decision rule: `N2 - N1` must be 0 (every marker reply replayed). If it is not, the comparison is contaminated by fresh model output: run the after command once more (it must then add 0) and use that run; report every count. If the before run itself added files, state the live spend from `before.log` (the client logs per-call cost); the comparison still holds because the after run replayed those same replies.

- [ ] **Step 5: Compare** with `BUILD/accuracy-runs/coherence-272-2026-10-01/compare.py` (committed, like `run_whitespace_58.py` in the sibling run dir). It loads the two results JSON files, validates `eval_records` into `EvalRecord`s, and reports:
  - `review_rate(records)` and `coherence_trigger_rate(records)` for each run: `n`, `review_rate_signal`, `review_rate_total`, `per_paper_p95`, `coherence_trigger_rate`;
  - per-leaf flags by the same union rule the gate uses: over `_group_by_leaf(_scored(_question_level(records)))`, a leaf is flagged when `any(r.triggers for r in group)` and coherence-flagged when `any("coherence_mismatch" in r.triggers for r in group)`; count leaves flagged before and not after (**disappeared**) and not before but after (**appeared**), for both the generic and the coherence flag, listing each leaf's `(paper_id, question_id)`;
  - `metrics.mark_accuracy`, `metrics.mark_accuracy_theory` and the per-`parse_path` correct rate for each run, asserted equal; and the strongest check: for every `(paper_id, fixture_variant, question_id)` present in both runs, `predicted_marks` and `outcome` are identical. A single difference means a mark moved: **stop, do not refresh the baseline, report the records**.
  - the out-of-range residual: `save_result` does not write `review_reason`, so `compare.py` has a second mode, `--count-out-of-range`, run as `PYTHONPATH=.../m272/after .venv/bin/python compare.py --count-out-of-range --config .../m272/lemely.toml --golden .../m272/after/tests/golden`: it builds settings with `load_settings(toml_path=...)`, a `GeminiClient(settings, default_cache_mode="read_write")`, loads the cases with `load_golden_cases`, calls `measure_accuracy(cases, client, settings)` in-process (a replay; count cache files before and after, must add 0), and counts `QuestionResult`s in `result.question_results` whose `review_reason` starts with `marker returned` (the reason-2 out-of-range text at `correction_ai.py:1503-1506`), listing their `(question_id, review_reason)`;
  - the committed baseline, printed next to the before run so the PR separates corpus drift from the #272 effect: `BUILD/review-rate-baseline.json` at `a1563b4f` reads `git_sha f7be062`, `computed_at 2026-08-22`, `n 31`, `corpus_digest e982c884f7f30cd7`, `review_rate_signal 0.2903`, `review_rate_total 0.2903`, `per_paper_p95 0.8333`; report whether the before run's `n` and `corpus_digest` match it (a mismatch is corpus drift since f7be062, not #272, and the PR says so).
  Write `report.json` with every number above, `T1_SHA`, `BASE_SHA`, both `run_id`s, `corpus_digest`, `cache_mode`, the cache-file counts for every run (before, after, in-process count) and the spend statement. Copy `.../m272/results-after/*.json` to the run dir as `after-results.json`.

- [ ] **Step 6: Refresh the baseline**

Edit `BUILD/review-rate-baseline.json`: keep the `_comment`; set `computed_at` to `2026-10-01`, `git_sha` to the short `T1_SHA`, `source_run` to `BUILD/accuracy-runs/coherence-272-2026-10-01/after-results.json`, `run_id` and `corpus_digest` from the after run's manifest, `split` `"dev"`, and `review_rate` to the after run's `{n, review_rate_signal, review_rate_total, per_paper_p95}`. Then run `PYTHONPATH=$PWD .venv/bin/python scripts/check_review_rate_gate.py` and confirm it prints `source=BUILD/review-rate-baseline.json` with the new numbers (confirm `tests/golden/results/` does not exist in this worktree, otherwise it would be preferred). It still exits 0 while the ratchet is unarmed; breaches are printed, not blocking. `lemely/runtime/config.py` is not touched.

Decision rule on direction: the PR ships whichever way the net moves. Report **both** counts (disappeared, appeared) and the net; never only the net.

- [ ] **Step 7: Clean up and commit**

`git worktree remove --force .../m272/before` and `.../m272/after`. Run `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files BUILD/review-rate-baseline.json BUILD/accuracy-runs/coherence-272-2026-10-01/compare.py BUILD/accuracy-runs/coherence-272-2026-10-01/report.json BUILD/accuracy-runs/coherence-272-2026-10-01/after-results.json`; `git status --short`.

Commit: `git commit -S -m "test(accuracy): re-baseline review rate after the coherence unification (#272)" -- BUILD/review-rate-baseline.json BUILD/accuracy-runs/coherence-272-2026-10-01`

Report to the controller: before/after `review_rate_signal`, `review_rate_total`, `per_paper_p95`, `coherence_trigger_rate` and `n`; disappeared and appeared counts (generic and coherence) with leaf ids; "mark metrics identical: yes/no" and "predicted_marks identical on every leaf: yes/no"; cache files added per run; spend; the gate script's printed block; the committed-baseline comparison (n and digest match or drift); the out-of-range residual count from the in-process run, for the PR body. Review by `accuracy-reviewer` at the SHA.

---

### Task 6: #270 — four equivalence misreads, one `x 10^n` rule

Runs after Task 2 is committed and reviewed. Line anchors below are at `a1563b4f`; Task 2 shifted only lines inside `_ParseWorker.parse`.

**Files:**
- Modify: `lemely/core/equivalence.py` — `_SI_PREFIXES` `:269`, `_SUBSCRIPTABLE_LETTERS` `:286`, the regex block near `:375-416` (new regexes), `_looks_like_prose_or_unsafe` `:502-517`, `_normalize_text` `:846-865` (new passes and docstring), `parse_expr_safe` docstring `:1180-1185` (mention the `)digit` refusal).
- Modify: `lemely/io/question_gates.py` — delete `_SCI_X_NOTATION_RE` `:88-99` and `_expand_sci_x_notation` `:149-164`, the call at `:189`, and fix the prose that names them at `:130-131`, `:170-172`, `:208` and `:248-250`.
- Test: `tests/test_equivalence.py` (new parametrised block plus guards), `tests/test_question_generation.py` (`:520-566` the two direct `_expand_sci_x_notation` tests are repointed; rows `:320`, `:352-353`, `:603-605` stay as they are).

**Interfaces:**
- Consumes: `_ALLOWED_FUNCTIONS` `:344-361`, `_SUBSCRIPTABLE_LETTERS`, `_unfold_superscripts` `:494`, `_rewrite_digit_suffixes` `:748-828`, `equivalent`, `parse_expr_safe`, `VerdictKind`; the `_kind_matches` helper in `tests/test_equivalence.py:129`.
- Produces, all private to `equivalence.py`:
  - `_MICRO_SIGN = "µ"`, `_GREEK_MU = "μ"`. `_normalize_text` starts with `text = text.replace(_MICRO_SIGN, _GREEK_MU)`. `_SI_PREFIXES` spells its micro entry as U+03BC; `_SUBSCRIPTABLE_LETTERS` drops the U+00B5 literal (U+03BC is already inside `α-ω`). `u` stays in `_SI_PREFIXES` as the ASCII alias. One micro in the module.
  - `_DIGIT_AFTER_PAREN_RE = re.compile(r"\)\d")`, checked in `_looks_like_prose_or_unsafe` on the raw text, so `parse_expr_safe("(x+1)2")` is `None`. `)x`, `)(`, `)^2`, `)*` and `)²` (a superscript is not an ASCII digit) are unaffected.
  - `_TIMES_X_RE = re.compile(r"(?<=[\d.])\s*[xX]\s*(?=10\s*(?:\^|\*\*))")`, substituted with `"*"` in `_normalize_text` after `_unfold_superscripts` and the `_MULT_CHARS` replacement, before the new function pass. `2x`, `5x3`, `x10`, `2x10` (no exponent marker) stay symbols.
  - `_apply_function_names(text: str) -> str`, the pre-pass driven by `_ALLOWED_FUNCTIONS` (names tried longest first, so `sinh`/`asin` win over `sin`; a name is not matched when a letter precedes it unless the whole preceding letter run is the coefficient case below), run in `_normalize_text` immediately before `_rewrite_digit_suffixes`. Rules, in the spec's words: (1) a name followed by `(` is left alone; (2) `log10(` becomes `(1/log(10))*log(` (a base-10 log built only from allowed calls); (3) a letter run that ends in a name and is followed by `(` or an argument (`Asin(`) becomes `A*sin(`; (4) a name followed directly by an argument is bracketed, where the argument is a number `\d+(?:\.\d+)?` (`ln6` -> `ln(6)`, `3ln2` -> `3ln(2)`, `sqrt2` -> `sqrt(2)`; the implicit-multiplication transformation supplies the `*`), one letter of `_SUBSCRIPTABLE_LETTERS` with optional trailing digits (`sinx` -> `sin(x)`, `cost` -> `cos(t)`, `cosθ1` -> `cos(θ1)`, `sinx2` -> `sin(x2)`; the suffix rule then makes the digits a subscript, so the existing `sinx2 -> sin(x_2)` rows are unchanged), or a number then one such letter (`sin2x` -> `sin(2*x)`, D1). Controller decision extending D1 (the CAIE convention): the number-then-letter form applies to the trig functions (`sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sinh`, `cosh`, `tanh`), `ln` and `log` (`ln2x` -> `ln(2*x)`, `log3x` -> `log(3*x)`); for `sqrt` it is ambiguous, so `sqrt2x` makes `parse_expr_safe` return `None` while `sqrt2` is `sqrt(2)`. (5) A letter run that is a function name plus one trailing letter is that function applied to the letter (`cost` -> `cos(t)`, `sinx` -> `sin(x)`), and concatenated applications split (`sinxcosx` -> `sin(x)*cos(x)`): the pass re-scans after each application rather than consuming the rest of the run. Anything else after a name is left for the existing rules.
  - Order inside `_normalize_text`: micro fold, `_unfold_superscripts`, unicode minus, `_MULT_CHARS`, `÷`, `_UNIT_ALIASES`, `_TIMES_X_RE`, `_apply_function_names`, `_rewrite_digit_suffixes`, `_collapse_thousands_separators`. Update the docstring's "Order matters" paragraph.
  - `question_gates._strip_trailing_unit` no longer expands `x 10^n`; the shape reaches `equivalent` unchanged and `_TIMES_X_RE` handles it there. `_UNIT_TAIL_RE` is unchanged (it already searches from the end and strips `J` off `2.4 x 10^4 J`, leaving `2.4 x 10^4` for the recursive comparison).

- [ ] **Step 1: Record the micro-sign probe** (before any edit)

Run: `PYTHONPATH=$PWD .venv/bin/python -c "from lemely.core.equivalence import parse_expr_safe as p, equivalent as e; print(repr(p('4.5 µg')), repr(p('4.5 μg')), repr(p('µg')), repr(p('μg'))); print(e('4.5 µg', '4.5 μg').kind, e('4.5 µg', '4.5 mg').kind)"` and save the output to `/home/sico/.claude/jobs/33cebc31/tmp/plans/t6/micro-probe.txt`. Quote it in the task report: it is the evidence for which spelling fails today and why (the spec's mechanism is inferred). If the probe shows a different cause than the tokenizer's NFKC fold, the one-code-point fix still holds; add a second spelling row only if the probe shows a third spelling in play.

- [ ] **Step 2: Write the failing tests**

In `tests/test_equivalence.py`, a parametrised block `_ISSUE_270_TABLE` (ids from the row's note) asserting `_kind_matches(equivalent(a, b).kind, expected)`:

| a | b | expected |
|---|---|---|
| `ln6` | `3ln2` | not_equal |
| `ln6` | `ln(6)` | equal |
| `3ln2` | `ln(8)` | equal |
| `sin2x` | `2sinx` | not_equal |
| `sin2x` | `sin(2x)` | equal |
| `2sinx` | `2*sin(x)` | equal |
| `log10(100)` | `2` | equal |
| `Asin(ωt1)` | `A*sin(ω*t_1)` | equal |
| `(x+1)2` | `x^2+2x+1` | unparseable |
| `(x+1)^2` | `x^2+2x+1` | equal |
| `3.0x10^8` | `3.0×10^8` | equal |
| `3.0x10^8` | `3.0*10**8` | equal |
| `2x` | `2*x` | equal |
| `4.5 µg` (U+00B5) | `4.5 μg` (U+03BC) | equal |
| `4.5 µg` | `4.5 mg` | not_equal |

Spell the two micro rows with `"µ"` / `"μ"` escapes so the distinction survives editors. Both rows are red today (measured: both `UNPARSEABLE`, because `parse_expr_safe("4.5 µg")` is `None` while `"4.5 μg"` splits into `4.5*g*μ`); Step 1's probe records the mechanism. Add a direct pin as well, red under either spelling: `test_both_micro_spellings_parse_to_one_unit_symbol`, asserting `parse_expr_safe("4.5 µg") == 4.5 * sympy.Symbol("μg")` and `parse_expr_safe("4.5 μg") == 4.5 * sympy.Symbol("μg")` (today the first is either `Symbol("µg")` or the product `μ*g`, never the U+03BC unit symbol). Rows for the controller's function-application decision, in a second parametrised block `_FUNCTION_APPLICATION_TABLE`, each labelled by what it is today (measured at `a1563b4f` with `/home/sico/.claude/jobs/33cebc31/tmp/plans/t6/probe_today.py`): `cost` vs `cos(t)` equal (red: `not_equal`, parses as `c*o*s*t`); `sinx` vs `sin(x)` equal (red: `not_equal`); `sinxcosx` vs `sin(x)*cos(x)` equal (red: `not_equal`, parses as `c*i*n*o*s**2*x**2`); `sqrt2` vs `sqrt(2)` equal (red: `not_equal`, parses as `2*q*r*s*t`); `ln2x` vs `ln(2*x)` equal (red: `not_equal`, parses as `2*l*n*x`); `log3x` vs `log(3*x)` equal (red); `tan2x` vs `tan(2*x)` equal (red); and a direct pin `parse_expr_safe("sqrt2x") is None` (red: parses as `2*q*r*s*t*x`).

Guard tests, green today and after: `parse_expr_safe("(x+1)2") is None` is **not** a guard (today it parses as `2*x + 2`; it is a red pin and belongs with the red list); the unaffected bracket shapes `equivalent("(x+1)x", "x^2+x")` and `equivalent("(x+1)(x-1)", "x^2-1")` equal (both `EQUAL_PROVEN` today); for the narrow times rule, `equivalent("5x3", "5*x_3")` equal (`EQUAL_PROVEN` today), `equivalent("x10", "x*10")` not equal and `equivalent("2x10", "20")` not equal (both `NOT_EQUAL` today; no exponent marker, `x` stays a symbol).

In `tests/test_question_generation.py`, replace the two direct tests at `:520-566` with the same two assertions made through `parse_expr_safe("2 x 10^400 J")` and `parse_expr_safe("2 x 10^-400 J")` (expected `2 * 10**400 * J` and `2 * J / 10**400`, with `J = parse_expr_safe("J")`), renamed `test_x_times_ten_magnitude_is_read_by_equivalence_without_overflow` / `..._underflow`, docstrings saying the rule moved from the gate to `lemely.core.equivalence` under #270. Drop the `_expand_sci_x_notation` imports.

- [ ] **Step 3: Run to verify red**

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -k "ISSUE_270 or issue_270 or unaffected_bracket or narrow_times" -q --no-cov` (use whatever ids you gave the block)
Expected, as measured at `a1563b4f` (controller's correction: the spec's line "the equal twins are guards" is wrong; a row is a guard only if it is green today, and only `(x+1)^2` vs `x^2+2x+1` and `2x` vs `2*x` are):
- red, `EQUAL_PROVEN` today where `not_equal` is expected: `ln6` vs `3ln2`, `sin2x` vs `2sinx`;
- red, `NOT_EQUAL` today where `equal` is expected: `ln6` vs `ln(6)`, `3ln2` vs `ln(8)`, `sin2x` vs `sin(2x)`, `2sinx` vs `2*sin(x)`, `log10(100)` vs `2`, `Asin(ωt1)` vs `A*sin(ω*t_1)`, `3.0x10^8` vs `3.0×10^8`, `3.0x10^8` vs `3.0*10**8`;
- red, `NOT_EQUAL` today where `unparseable` is expected: `(x+1)2` vs `x^2+2x+1` (`parse_expr_safe("(x+1)2")` returns `2*x + 2`);
- red, `UNPARSEABLE` today for both micro rows: `4.5 µg` vs `4.5 μg` (expected equal) and `4.5 µg` vs `4.5 mg` (expected not_equal); `parse_expr_safe("4.5 µg")` is `None` and `parse_expr_safe("4.5 μg")` is `4.5*g*μ`, so `test_both_micro_spellings_parse_to_one_unit_symbol` is red on both assertions;
- red: every `_FUNCTION_APPLICATION_TABLE` row and the `sqrt2x` pin, as labelled in Step 2;
- green (guards): `(x+1)^2` vs `x^2+2x+1`, `2x` vs `2*x`, the two bracket shapes, `5x3`, `x10`, `2x10`.
Save to `/home/sico/.claude/jobs/33cebc31/tmp/plans/t6/red.txt` and quote one line per red row. A row whose colour differs from this list means the tree moved; stop and report before implementing.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_question_generation.py -k "magnitude_is_read_by_equivalence" -q --no-cov`
Expected: both FAIL today (`parse_expr_safe("2 x 10^400 J")` returns `2*10**400*J*x`, not the expected product).

- [ ] **Step 4: Implement the equivalence changes**, then the gate deletion (both in this task; the gate's rule is dead once equivalence handles the shape).

- [ ] **Step 5: Run the equivalence suite alone, then the gate suite** (the equivalence run is controller-scheduled: run only when the controller confirms other lanes are idle; if unsure, end the report with status `NEEDS_CONTEXT`)

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q --no-cov`
Expected: all pass, in particular `test_a_function_name_head_still_calls_its_subscripted_argument` (the `sinx2` rows at `:3069-3120`), `test_greek_subscripts_are_one_symbol_each`, the 40-pair table, and the Task 2 tests.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_question_generation.py tests/test_correction_ai.py -q --no-cov`
Expected: all pass (rows `("24000", "2.4 x 10^4 J")`, `("2.4", "2.4 x 10^4 J")`, `("3", "3.0 x 10^8 m/s")`, `("2", "2 x 10^400")`, `("2", "2 x 10^308")` go through `_compare_stated` and now rely on `_TIMES_X_RE`; `test_correction_ai.py` is the marking-path guard with the gate off).

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_accuracy_harness.py -k fingerprint -q --no-cov`
Expected: pass; `af7fa9cd0e2a` unchanged (equivalence is not a fingerprint input).

- [ ] **Step 6: Pre-commit and commit**

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/core/equivalence.py lemely/io/question_gates.py tests/test_equivalence.py tests/test_question_generation.py`; `git status --short`; re-run Step 5 if autofixed. `grep -rn "_expand_sci_x_notation\|_SCI_X_NOTATION_RE" lemely tests` must print nothing.

Commit: `git commit -S -m "fix(core): read function names, a digit after a bracket, x as times and one micro sign in equivalence (#270)" -- lemely/core/equivalence.py lemely/io/question_gates.py tests/test_equivalence.py tests/test_question_generation.py`

Report the SHA, the probe output, and the red lines. State for the PR body: no marking change with the gate off; which generated questions the generation gate accepts changes on the default path and no harness metric measures that. Review by `reviewer` at the SHA; Task 8 starts after it passes.

---

### Task 7: #201 — first cost-per-paper measurement (accuracy-measurer)

Runs after Task 4 is committed and reviewed. One live dev-split run, about $1.25.

**Files:**
- Create: `BUILD/accuracy-runs/cost-201-2026-10-01/report.json`
- Scratch: `/home/sico/.claude/jobs/33cebc31/tmp/plans/cost201/` (results dir, log, a detached worktree at Task 4's SHA so other lanes' uncommitted edits cannot leak into the run).

**Interfaces:**
- Consumes: `lemely measure-accuracy --config <toml> --golden <dir> --results-dir <dir> --cache-mode bypass`; the cost block `format_report` now prints; `cost_usd_by_paper`/`cost_usd_total` in the saved JSON.

- [ ] **Step 1: Isolate the tree.** `T4_SHA=$(git log --format=%H -1 --grep='#201' -- lemely/accuracy/harness.py)`; `git worktree add --detach .../cost201/tree $T4_SHA`. Make `.../cost201/lemely.toml` as in Task 5 Step 2 but with its own absolute `output_dir = "/home/sico/.claude/jobs/33cebc31/tmp/plans/cost201/outputs"` and `cache_dir = "/home/sico/.claude/jobs/33cebc31/tmp/plans/cost201/cache"` (bypass never reads the cache, but the run still writes to it; never share Task 5's `output_dir`, which holds its `gemini_spend.json`). Its `per_run_token_ceiling = 200000` covers one ~115k-token sweep; do not raise it. `GEMINI_API_KEY` in the environment.

- [ ] **Step 2: Run once.** `PYTHONPATH=.../cost201/tree .venv/bin/lemely --config <toml> measure-accuracy --golden .../cost201/tree/tests/golden --results-dir .../cost201/results --cache-mode bypass 2>&1 | tee .../cost201/run.log`. Record the exit code (1 on a missed target is expected). Decision rule: this is one run; if it aborts on the token ceiling (`CostCeilingError`), report the partial cost and the ceiling and stop; do not rerun without the controller's say-so. Budget stop: if the printed total exceeds $3.00, report and stop.

- [ ] **Step 3: Record.** `report.json` with: `T4_SHA`, `run_id`, `corpus_digest`, `cache_mode: "bypass"`, `n` cases, the per-case `cost_usd_by_paper` table, per-case totals, mean, p95, `cost_usd_total`, the printed `Cost per paper` lines verbatim, and the mark/review numbers the CLI printed (for context only). Copy the saved results JSON into the run dir as `results.json`. `git worktree remove --force .../cost201/tree`.

- [ ] **Step 4: Commit.** `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files BUILD/accuracy-runs/cost-201-2026-10-01/report.json BUILD/accuracy-runs/cost-201-2026-10-01/results.json`; then `git commit -S -m "test(accuracy): record the first cost-per-paper measurement (#201)" -- BUILD/accuracy-runs/cost-201-2026-10-01`.

Report: mean, p95, total, `n`, the most and least expensive case, and the spend by task tag summed over cases. Review by `accuracy-reviewer` at the SHA.

---

### Task 8: #271 — split `equivalence.py` into tables, worker and facade (pure move)

Runs after Task 6 is committed and reviewed. A pure move: no behaviour edit, no test edit beyond one added import test.

**Files:**
- Create: `lemely/core/equivalence_tables.py`, `lemely/core/equivalence_worker.py`
- Modify: `lemely/core/equivalence.py`; `pyproject.toml` — the ruff per-file ignores at `:184` (`"lemely/core/equivalence.py" = ["RUF001", "RUF002", "RUF003", "S311"]`) and the pyright `executionEnvironments` entry at `:506-508` (`root = "lemely/core/equivalence.py"`, `reportAttributeAccessIssue`/`reportArgumentType = "none"`) are keyed to the one file; add matching entries for `lemely/core/equivalence_tables.py` (RUF001-3: the unit tables carry `×`, `µ`, `Ω`) and `lemely/core/equivalence_worker.py` (RUF001-3 for moved comments, S311 only if the sampler moved there, which it does not; a second pyright environment with the same two suppressions, since `_pow_would_explode`/`_coefficient_height` touch sympy `Basic` attributes). Keep each entry's "NOT A DEFECT" comment. The import-linter contract needs no change (`lemely.core` is one layer, `exhaustive = false`).
- Test: `tests/test_equivalence.py` (one new test), `tests/architecture/` (run, not edited).

**Interfaces:**
- `lemely/core/equivalence_tables.py` (imports only `re`, `sympy` and the SymPy parser transformations): `_TRANSFORMATIONS`, `_BASE_UNIT_SYMBOLS`, `_SI_PREFIXES`, `_UNIT_SYMBOLS`, `_SINGLE_LETTER_UNITS`, `_SUBSCRIPTABLE_LETTERS`, `_LETTER_DIGITS_RE`, `_UNIT_ALIASES`, `_RESERVED_NAME_OVERRIDES`, `_UNIT_LOCAL_DICT`, `_ALLOWED_FUNCTIONS`, `_FUNCTION_CALL_RE`, `_is_disallowed_sympy_call`, with their comments moved verbatim.
- `lemely/core/equivalence_worker.py` (imports `equivalence_tables`, never `equivalence`): `_PARSE_WORKER_MEMORY_BYTES` (still `512 * 1024 * 1024`, D2), `_PARSE_WORKER_START_TIMEOUT`, `_PARSE_WORKER_START_COOLDOWN`, `_ParseRequest`, `_ParseReply`, the explosion bounds `_MAX_EXPONENT_VALUE`, `_MAX_RESULT_DIGITS`, `_MAX_RESULT_INT_BITS`, `_MAX_POW_RESULT_BITS`, `_magnitude_bits`, `_pow_would_explode`, `_is_singular`, `_parse_normalized`, `_coefficient_height`, `_evaluated_would_explode`, `_vetted_parse`, `_vet_and_parse`, `_parse_worker_main`, `_ParseWorker`, `_PARSE_WORKER`, and the `os.register_at_fork` hook. Its logger is `logging.getLogger("lemely.core.equivalence")` spelled explicitly (today `_logger = logging.getLogger(__name__)` at `:75`; the worker's "parse worker not started" warnings must keep the old logger name so log filters and `caplog.at_level(..., logger=eq.__name__)` at `tests/test_equivalence.py:2806` keep matching). `vet=False` stays (its five test uses at `:2546-2830` send inputs the walk would refuse straight to the child to prove the kill paths; replacing it would need a test-only pipe message, a larger seam).
- `lemely/core/equivalence.py` keeps all normalisation: `parse_expr_safe`, `_looks_like_prose_or_unsafe` and its regexes (including Task 6's `_DIGIT_AFTER_PAREN_RE`), `_has_unsafe_exponent`, `_has_unsafe_factorial`, `_unfold_superscripts`, Task 6's `_MICRO_SIGN`, `_GREEK_MU`, `_TIMES_X_RE` and `_apply_function_names`, `_rewrite_digit_suffixes`, `_collapse_thousands_separators`, `_normalize_text`, `_run_bounded`, the tolerance machinery, `Verdict`, `VerdictKind`, `EquivalenceMethod`, `equivalent`. It imports what it uses from the two new modules, and additionally re-exports, in one clearly commented block with `# noqa: F401` per line naming `tests/test_equivalence.py`, every name that file reaches through `eq.`: `_PARSE_WORKER`, `_ParseWorker`, `_PARSE_WORKER_START_COOLDOWN`, `_parse_normalized`, `_evaluated_would_explode`, `_UNIT_LOCAL_DICT` (for the new import test) and `multiprocessing` (the tests monkeypatch `eq.multiprocessing.get_context`, which patches the shared module object, so the worker module sees it). The header import list at `tests/test_equivalence.py:46-65` must keep resolving: `_ABS_TOLERANCE_DISCARD_MULTIPLE`, `_ABS_TOLERANCE_SANITY_FRACTION`, `_DEFAULT_ABS_TOL`, `_DEFAULT_REL_TOL`, `_MAX_PLAUSIBLE_RELATIVE_TOLERANCE`, `EquivalenceMethod`, `Verdict`, `VerdictKind`, `_diff_within_tolerance`, `_numeric_fallback`, `_parse_tolerance`, `_plausible_or_discard_absolute_candidate`, `_round_to_sig_figs`, `_rounds_agree_at_stated_precision`, `_sampler_seed`, `_ToleranceSpec`, `equivalent`, `parse_expr_safe`. `parse_expr_safe` must read the module global `_PARSE_WORKER` of `equivalence.py` (not an attribute of the worker module), so `monkeypatch.setattr(eq, "_PARSE_WORKER", worker)` at `:2805` and `:3202` keeps steering it. `lemely/io/correction_ai.py:13` and `lemely/io/question_gates.py:55` import only public names from `lemely.core.equivalence` and are untouched.
- Where a constant is used on both sides, it lives with its heaviest user and the facade imports it (never the other way round). The spawned child re-imports `lemely.core.equivalence_worker`, which does not import the facade, so nothing changes at runtime.

- [ ] **Step 1: Write the import test** (red: `ModuleNotFoundError`), appended to `tests/test_equivalence.py`:

`test_the_worker_and_tables_modules_import_and_back_the_facade`: `import lemely.core.equivalence_tables as tables; import lemely.core.equivalence_worker as worker`; assert `worker._PARSE_WORKER is eq._PARSE_WORKER` and `tables._UNIT_LOCAL_DICT is` the dict `eq` uses (expose it as `eq._UNIT_LOCAL_DICT` via the same re-export block).

- [ ] **Step 2: Run it to verify red**: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -k "worker_and_tables_modules" -q --no-cov` -> `ModuleNotFoundError: No module named 'lemely.core.equivalence_tables'`.

- [ ] **Step 3: Move the code.** Cut and paste; do not reword bodies. Fix import order; keep each moved comment with its symbol. Then prove the worker module stands alone: `PYTHONPATH=$PWD .venv/bin/python -c "import sys, lemely.core.equivalence_worker; assert 'lemely.core.equivalence' not in sys.modules; print('no facade import')"`.

- [ ] **Step 4: Run the equivalence suite alone, then the architecture tests** (the equivalence run is controller-scheduled: run only when the controller confirms other lanes are idle; if unsure, end the report with status `NEEDS_CONTEXT`)

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_equivalence.py -q --no-cov`
Expected: the same pass count as after Task 6 plus one (report both numbers). Every `eq._PARSE_WORKER` reference, the fork/cool-down tests, the memory test (`2**999999999` under the unchanged 512 MiB cap, outcome `"memory"`, same pid) and the shutdown test pass unchanged.

Run: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/architecture tests/test_question_generation.py tests/test_correction_ai.py -q --no-cov`
Expected: all pass (`lint-imports` contracts included).

Record `wc -l lemely/core/equivalence.py lemely/core/equivalence_tables.py lemely/core/equivalence_worker.py` for the report.

- [ ] **Step 5: Pre-commit and commit**

Run: `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pre-commit run --files lemely/core/equivalence.py lemely/core/equivalence_tables.py lemely/core/equivalence_worker.py tests/test_equivalence.py pyproject.toml`; `git status --short`; re-run Step 4's first command if autofixed (mypy strict and pyright run in pre-commit; a moved symbol that lost an import, or a missing per-file ignore for the new modules, shows here).

Commit: `git commit -S -m "refactor(core): split equivalence into tables, worker and facade modules (#271)" -- lemely/core/equivalence.py lemely/core/equivalence_tables.py lemely/core/equivalence_worker.py tests/test_equivalence.py pyproject.toml`

Review by `reviewer` at the SHA: the diff must read as a move (`git diff --color-moved=dimmed-zebra <sha>^ <sha>`), with the only non-moved lines being imports, the re-export block, the explicit logger name, the two `pyproject.toml` entries, and the new test.

---

### Task 9: Gate sweep on the final tree (verifier)

Runs after Tasks 1-8 are committed. A sweep certifies only the tree it ran on; if anything below produces a fixup commit, run the whole task again on that commit.

**Files:** none edited (a fixup commit only if autofix or a gate forces one).

The list below is derived from `.github/workflows/ci.yml` at `a1563b4f` (jobs `test`, `pre-commit`, `web`), not hand-assembled. Every backend command is prefixed `PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH"`. Log each to `/home/sico/.claude/jobs/33cebc31/tmp/plans/sweep/<gate>.log` and report PASS/FAIL/SKIP with the reason.

- [ ] **Step 1: Confirm the tree.** `git status --short --branch` shows no modified files; record `git rev-parse HEAD`; `git log --oneline a1563b4f..HEAD` lists exactly the eight commits of Tasks 1-8 (plus any reviewed fixups).
- [ ] **Step 2 (`test` job, in order):** `ruff check .`; `ruff format --check .`; `mypy lemely`; `pyright lemely` (local findings of the exact form `"X" is not assignable to "X"` are the known shared-venv artefact; everything else is real); `lint-imports`; `alembic upgrade head` only if `pg_isready -h 127.0.0.1 -p 54322` succeeds, else SKIP "no local Postgres; this branch adds no migration"; the `pytest` step is CI's full suite and is **not** run locally: run instead `.venv/bin/python -m pytest tests/test_correction_ai.py tests/test_text_agreement.py tests/test_reread.py tests/test_second_read.py tests/test_accuracy_harness.py tests/test_question_generation.py tests/test_cli_review_rate_gate.py tests/test_cli_coherence_trigger_rate.py tests/test_cli_new_commands.py tests/architecture -q --no-cov`, then separately and alone `.venv/bin/python -m pytest tests/test_equivalence.py -q --no-cov`; then `python scripts/check_review_rate_gate.py` (must print `source=BUILD/review-rate-baseline.json`, the Task 5 numbers, `armed=False`, exit 0).
- [ ] **Step 3 (`pre-commit` job):** `pre-commit run --all-files --show-diff-on-failure`, then `git status --short` must be empty. If the ruff hook changed a file, that is a FAIL of this gate: commit the autofix with `git commit -S -m "style: apply ruff autofix from the gate sweep" -- <paths>` and restart from Step 1.
- [ ] **Step 4 (`web` job):** the branch touches no `web/` file (`git diff --stat a1563b4f..HEAD -- web/` is empty; record it). If `web/node_modules` exists, run from `web/`: `npm run typecheck`, `npm test`, `npm run lint`, `npm run check:copy`, `npm run build`, `npm run check:installable`; a failure there is pre-existing and is reported as such, not fixed on this branch. If `node_modules` is absent, SKIP with "web untouched; node_modules not installed".
- [ ] **Step 5: Invariants.** `grep -c af7fa9cd0e2a tests/test_accuracy_harness.py` is `1` (the literal at `:1647` inside `test_params_fingerprint_for_no_arm_override_is_unchanged`) and `-k fingerprint` passed in Step 2; `git diff --stat a1563b4f..HEAD -- lemely/app/cli.py lemely/runtime/config.py lemely/io/prompts lemely/eval/manifest.py` is empty; `grep -n "_PARSE_WORKER_MEMORY_BYTES = " lemely/core/equivalence_worker.py` shows `512 * 1024 * 1024`; `grep -n "AGREEMENT_THRESHOLD = 0.8" lemely/io/reread.py lemely/io/second_read.py` shows both.

Report the PASS/FAIL/SKIP table with the HEAD SHA it certifies.

---

### Task 10: Whole-branch review (accuracy-reviewer, opus)

Runs on the SHA Task 9 certified. Read `git diff a1563b4f..<sha>` whole, against the spec. Reject on any of: an `awarded_marks` path changed anywhere; the fingerprint pin or its inputs touched; `equivalence_gate` default or the ratchet targets touched; a `)digit`, times-`x` or function rule wider than the spec's narrow statements (`2x`, `5x3`, `x10` must still be symbols; `)x`, `)(`, `)^2` must still parse); the `sinx2` rows changed; `vet=False` removed; the split carrying a behaviour edit; a cost figure placed in the manifest; the re-baseline netting the two directions; the measurement reports lacking the counts Task 5 Step 6 requires; a threshold moved from 0.8; `lemely/app/cli.py` edited. Confirm the PR-body disclosures exist in the task reports: the 2026-09-26 §1 reversal, the review-flag re-baseline with both counts, the generation-gate acceptance change with no harness metric, the `vet=False` reasoning, the budget table reference for #271's memory item. Output a findings list with severity; anything above Minor goes back to the owning lane as a fixup, followed by a Task 9 rerun.

---

### Task 11: Issue housekeeping (after the owner opens the PR; nothing here pushes)

- [ ] #272 and #270 close through the PR body (`Closes #272`, `Closes #270`). The PR body states: the legacy coherence path now uses the grouped interval, reversing the 2026-09-26 spec's §1; the review-rate re-baseline with Task 5's before/after numbers, disappeared and appeared counts, and the note that CI's `check_review_rate_gate.py` output changes on purpose; #270's generation-gate acceptance change is unmeasured; the residual out-of-range count on overfull det schemes from Task 5 (a follow-up is filed only if it is material).
- [ ] #271 closing comment: the deadline semantics (`"busy"` outcome, start outside the budget), the module split, that the 512 MiB cap stays and the memory concern is closed by the 2 GiB instance (cite the budget table in `docs/superpowers/specs/2026-10-01-scan-render-safety-design.md`, decision S1), and why `vet=False` stays (the test-only pipe message would be a larger seam). `Closes #271` in the PR body.
- [ ] #264 closing comment (D4): the difflib vs normalised-Levenshtein comparison from the design session (`/home/sico/.claude/jobs/33cebc31/tmp/triage/draft-M.md` §#264); that both 0.8 thresholds remain unvalidated and gate different decisions; that the planned I2 normaliser plugs into `lemely.core.text_agreement.text_agreement`. No follow-up issue. `Closes #264`.
- [ ] #201: comment listing what is already measured (mark accuracy and per-path, flag precision and recall, calibration and risk-coverage, review rate and its gate, `agreement_wilson`, `id_match_rate`, `coherence_trigger_rate`, `paper_grade_confidence`) and that cost per paper now ships with Task 7's first number; file four issues: (1) paper-type detection accuracy against the golden fixtures' metadata, scoring `ScanMetadataExtractor` in `lemely/io/scan_metadata.py`; (2) handwriting CER (plan item I2: gold transcriptions, jiwer, normaliser); (3) rationale and ECF adherence, needing pass-2 labels; (4) mark-scheme parser fidelity, with the det-vs-Gemini disagreement rate as a proxy; record the weighted overall score as declined (a composite hides which component moved; the programme's gates are per-metric non-regression); close #201 with `state_reason: completed`.
