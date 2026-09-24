# Verdict Path: Switchable and Coherent — Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the I6/I7 per-point verdict feature enableable from `lemely.toml`, make both the teacher and student surfaces correct once it is, and cover the teacher surface behaviourally for the first time.

**Architecture:** Five stories over existing read paths. One deletes a wire-schema field that can never be filled (and must move the marking-cache key to do so safely). One threads an existing config flag into the two call sites that never passed it. Two widen already-widened DTO paths — teacher and student — to carry the marker's reasoning and verdict. The last adds the Playwright spec that `/teacher/review` has never had.

**Tech Stack:** Python 3.13, pydantic v2, SQLAlchemy, FastAPI, pytest/unittest, React + TypeScript, vitest, Playwright.

Spec: `docs/superpowers/specs/2026-09-24-verdict-path-production-readiness-design.md`.
Plan 2 (stories E and F, bounding boxes) is separate and follows this one.

## Global Constraints

- Signed commits only: `git commit -S`. Conventional messages with a scope.
- Never `git commit -a`, `git add -A`, or `git add .`. Name paths explicitly: `git commit -S -- <paths>`. The index is shared with concurrent agents.
- Do NOT push. The user pushes.
- The repo is PUBLIC. No real student scripts, labels, or `GEMINI_API_KEY` in any commit.
- Prefix every Python command with `PATH="$PWD/.venv/bin:$PATH"`, or tools report "Executable not found".
- Add `--no-cov` to any single-file pytest run. The coverage gate is global and fails single-file runs at ~10%; that failure is not yours.
- Report test counts by grepping the `N passed` summary line. Never from `tail`, never by counting dots in a `-q` run.
- Run `pre-commit run --all-files`, **then** bare `ruff check .` and `ruff format --check .` on the resulting commit. The pre-commit ruff hook runs `--fix` and reports on the post-fix tree.
- UI copy passes `npm run check:copy`: no em-dashes, no exclamation marks.
- No acceptance criterion is satisfied by asserting the absence of a string.
- Every new test must be observed FAILING before the implementation, and the failure message recorded in the task's report.

**Baselines on `a5ac66e0`** (hold or exceed): `tests/test_correction_ai.py` 127 · `tests/test_question_points.py` 35 · `tests/test_review_repo.py` 32 · `tests/test_web_review.py` 30 · `tests/test_migration_0041_point_verdict_columns.py` 7 · vitest 197 files / 3415 tests · `pyright lemely` 0 errors · `mypy lemely` 308 files · `lint-imports` 4 contracts · `dup_verdict_probe.py` 0 violations.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `lemely/core/schemas.py` | `PointVerdict` loses `evidence_box` | 1 |
| `tests/test_accuracy_harness.py` | the pinned marking-cache fingerprint | 1 |
| `lemely/web/services/grading.py` | `grade_paper` accepts and forwards `equivalence_gate` | 2 |
| `lemely/app/cli.py`, `lemely/web/routers/student.py`, `lemely/web/routers/teacher.py` | pass `settings.grading.equivalence_gate` | 2 |
| `lemely/db/review_repo.py` | `ReviewItemPoint` carries `rationale` | 3 |
| `lemely/web/schemas_review.py`, `lemely/web/routers/review.py` | teacher wire DTO carries it | 3 |
| `web/src/lib/teacherTypes.ts` | TS mirror | 3, 4 |
| `web/src/portals/teacher/screens/ReviewItem.tsx` | render rationale, suppress the empty section, correct the banner | 4 |
| `lemely/db/self_review_repo.py` | student payload carries verdict/span/ecf | 5 |
| `lemely/web/schemas_student_self_review.py` | revealed DTO only | 5 |
| `web/src/lib/selfReviewTypes.ts`, the student self-review screen | TS mirror and student copy | 6 |
| `web/e2e/self-review.spec.ts` | student behaviour | 6 |
| `web/e2e/teacher-review.spec.ts` (new) | teacher behaviour, first ever | 7 |

---

## Task 1: Delete `evidence_box` and re-pin the marking fingerprint

**Files:**
- Modify: `lemely/core/schemas.py` (the `PointVerdict` class, ~line 249-265)
- Modify: `tests/test_accuracy_harness.py:1586` (the pinned hash)
- Test: `tests/test_correction_ai.py` (new test in `PointVerdictBuildTests`)

**Interfaces:**
- Consumes: nothing.
- Produces: `PointVerdict` with fields `point_id: str`, `verdict: PointVerdictWire`, `evidence_span: str = ""`, `note: str = ""`, `ecf_applied: bool = False`. No `evidence_box`. Later tasks must not reference it.

**Why this is its own task:** it is the only change in either plan that invalidates the marking cache, and it must be attributable to exactly one commit. Three agents produced three incomparable `model_json_schema()` hashes for this one invariant during task #30.

- [ ] **Step 1: Record the current fingerprint before touching anything**

```bash
PATH="$PWD/.venv/bin:$PATH" python -c "
import hashlib, json
from lemely.core.schemas import AIMarkResponse
blob = json.dumps(AIMarkResponse.model_json_schema(), sort_keys=True)
print('before:', hashlib.sha256(blob.encode()).hexdigest()[:12])
print('evidence_box present:', 'evidence_box' in blob)
"
```

Expected: `before: 886c4232e7a7` and `evidence_box present: True`. Record both in your report. If the hash differs from `886c4232e7a7`, stop and report — something landed since this plan was written.

- [ ] **Step 2: Write the failing test that documents the coupling**

Add to `tests/test_correction_ai.py`, inside the existing `PointVerdictBuildTests` class (unittest style, matching that file):

```python
    def test_a_payload_carrying_evidence_box_is_now_rejected(self):
        """`StrictModel` is `extra="forbid"`, so removing a wire-schema field
        makes any cached payload still carrying it unparseable. That is why the
        fingerprint MUST move with this deletion: the key change orphans those
        entries instead of reading them. A future change that pins the key to
        avoid the hash budget would break parsing on every cached hit.
        """
        with self.assertRaises(ValidationError):
            PointVerdict(point_id="p1", verdict="awarded", evidence_box=None)
```

Ensure `ValidationError` is imported in that file: `from pydantic import ValidationError`.

- [ ] **Step 3: Run it and confirm it fails**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_correction_ai.py -k evidence_box_is_now_rejected --no-cov -p no:cacheprovider
```

Expected: FAIL. `evidence_box` is still a declared field, so passing `evidence_box=None` is accepted and no `ValidationError` is raised.

- [ ] **Step 4: Delete the field**

In `lemely/core/schemas.py`, remove the `evidence_box: None = None` line from `PointVerdict`, and remove the comment above the class that explains it (`# ``evidence_box`` is left ``None``-only for now (no OCR bounding-box ...`). Replace that comment with one sentence recording why there is no box field at all:

```python
# `PointVerdict` carries no bounding box. Marking is text-only -- `_mark_question`
# sends the transcription, never the page image -- so the model cannot produce
# one. Question-level boxes come from `ExtractedAnswer.source_box` on the
# extraction side instead (see the 2026-09-24 production-readiness spec).
```

- [ ] **Step 5: Confirm the test now passes**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_correction_ai.py -k evidence_box_is_now_rejected --no-cov -p no:cacheprovider
```

Expected: PASS.

- [ ] **Step 6: Measure the new fingerprint**

```bash
PATH="$PWD/.venv/bin:$PATH" python -c "
import hashlib, json
from lemely.core.schemas import AIMarkResponse
blob = json.dumps(AIMarkResponse.model_json_schema(), sort_keys=True)
print('after:', hashlib.sha256(blob.encode()).hexdigest()[:12])
print('evidence_box present:', 'evidence_box' in blob)
"
```

Expected: a hash different from `886c4232e7a7`, and `evidence_box present: False`. Record it.

- [ ] **Step 7: Watch the pinned harness assertion fail, then re-pin it**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_accuracy_harness.py -k params_fingerprint --no-cov -p no:cacheprovider
```

Expected: `test_params_fingerprint_is_stable_for_identical_settings` FAILS, because the manifest fingerprint incorporates the response schema. **That failure is the evidence the cache moved** — record the expected-vs-actual values from the output.

Then update `tests/test_accuracy_harness.py:1586` to the value the failure reports:

```python
        self.assertEqual(manifest.params_fingerprint, "<the value from the failure>")
```

Re-run: all 11 fingerprint tests pass.

- [ ] **Step 8: Full gate sweep**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_correction_ai.py tests/test_accuracy_harness.py --no-cov -p no:cacheprovider 2>&1 | grep -E "passed|failed"
PATH="$PWD/.venv/bin:$PATH" mypy lemely
PATH="$PWD/.venv/bin:$PATH" pyright lemely
PATH="$PWD/.venv/bin:$PATH" pre-commit run --all-files
PATH="$PWD/.venv/bin:$PATH" ruff check .
PATH="$PWD/.venv/bin:$PATH" ruff format --check .
```

Expected: `test_correction_ai.py` at 128 (127 + 1), `mypy` Success 308 files, `pyright` 0 errors, pre-commit all hooks pass, both ruff commands clean.

- [ ] **Step 9: Commit**

```bash
git commit -S -- lemely/core/schemas.py tests/test_correction_ai.py tests/test_accuracy_harness.py
```

Message body must state: the before and after hashes, and that `extra="forbid"` makes the key change mandatory rather than optional.

---

## Task 2: Thread `equivalence_gate` to both entry points

**Files:**
- Modify: `lemely/web/services/grading.py:56` (`grade_paper` signature) and `:91` (the `correct_paper` call)
- Modify: `lemely/app/cli.py:354`
- Modify: `lemely/web/routers/student.py:1059`
- Modify: `lemely/web/routers/teacher.py:489`
- Test: `tests/test_web_review.py` or the file that already covers `grade_paper` — check with `grep -rln "grade_paper" tests/` and use the existing home rather than creating a new file.

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `grade_paper(..., *, equivalence_gate: bool = False)`. Closes US-040.

**Verified before writing this task:** `settings` is already in scope at all three callers — `cli.py:350` (`settings = _get_settings(ctx)`), `student.py:1059` (uses `settings.integrity` on the adjacent line), and `teacher.py:439-470` (uses `settings.storage.bucket`). **No threading of a settings object is required.** The spec hedged that it might be; it is not.

- [ ] **Step 1: Write the failing tests**

```python
def test_grade_paper_forwards_equivalence_gate_when_enabled(monkeypatch):
    """The flag must reach `correct_paper`, not merely exist in settings.

    US-005b's own criteria tested only the OFF state, which passed happily
    while nothing could turn the flag ON. A test that checks the default
    cannot detect an unreachable flag.
    """
    seen: dict[str, object] = {}

    def _spy(**kwargs):
        seen.update(kwargs)
        raise _StopForTest

    monkeypatch.setattr(grading_module, "correct_paper", _spy)
    with pytest.raises(_StopForTest):
        grade_paper(_scheme(), {}, equivalence_gate=True)
    assert seen["equivalence_gate"] is True


def test_grade_paper_defaults_equivalence_gate_off(monkeypatch):
    seen: dict[str, object] = {}

    def _spy(**kwargs):
        seen.update(kwargs)
        raise _StopForTest

    monkeypatch.setattr(grading_module, "correct_paper", _spy)
    with pytest.raises(_StopForTest):
        grade_paper(_scheme(), {})
    assert seen["equivalence_gate"] is False
```

Define `class _StopForTest(Exception): ...` at module level in the test file — it short-circuits `grade_paper` right after the call under test, so neither test needs a Gemini client or a full report.

Reuse the file's existing mark-scheme fixture for `_scheme()`; do not build a new one.

- [ ] **Step 2: Run them and confirm they fail**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest <that test file> -k equivalence_gate --no-cov -p no:cacheprovider
```

Expected: FAIL with `TypeError: grade_paper() got an unexpected keyword argument 'equivalence_gate'` on the first, and `KeyError: 'equivalence_gate'` on the second.

- [ ] **Step 3: Add the parameter and forward it**

In `lemely/web/services/grading.py`, add to `grade_paper`'s keyword-only block (after `mcq_only`, matching that parameter's shape rather than `integrity_settings`' object shape — one flag does not need a settings object):

```python
    equivalence_gate: bool = False,
```

Document it in the Args block:

```
        equivalence_gate: US-005b's marking gate. Forwarded to `correct_paper`;
            defaults False so this function's behaviour is unchanged unless a
            caller opts in. Enabling it changes how papers are marked and is a
            deliberate act -- see the 2026-09-24 production-readiness spec.
```

Then at the `correct_paper` call (`:91`):

```python
    correction: CorrectionResult = correct_paper(
        mark_scheme=mark_scheme,
        extracted_answers=extracted_answers,
        gemini_client=gemini_client,
        mcq_only=mcq_only,
        equivalence_gate=equivalence_gate,
    )
```

- [ ] **Step 4: Confirm the tests pass**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest <that test file> -k equivalence_gate --no-cov -p no:cacheprovider
```

Expected: 2 passed.

- [ ] **Step 5: Pass the setting at all three callers**

`lemely/app/cli.py:354` — `settings` is defined at `:350`:

```python
    correction = hybrid_correct_paper(
        mark_scheme=ms,
        extracted_answers=extracted,  # type: ignore[arg-type]
        gemini_client=client,
        mcq_only=mcq_only,
        equivalence_gate=settings.grading.equivalence_gate,
    )
```

`lemely/web/routers/student.py:1059`:

```python
                report = grade_paper(
                    mark_scheme,
                    extracted,
                    gemini_client=gemini_client,
                    student_id=None,
                    integrity_settings=settings.integrity,
                    equivalence_gate=settings.grading.equivalence_gate,
                )
```

`lemely/web/routers/teacher.py:489`:

```python
            report = grade_paper(
                scheme,
                extracted,
                gemini_client=gemini_client,
                student_id=None,
                history_store=None,
                equivalence_gate=settings.grading.equivalence_gate,
            )
```

- [ ] **Step 6: Prove the flag is now reachable from config, which is the point of the story**

```bash
PATH="$PWD/.venv/bin:$PATH" grep -c equivalence_gate lemely/app/cli.py lemely/web/services/grading.py lemely/web/routers/student.py lemely/web/routers/teacher.py
```

Expected: every file returns a non-zero count. Before this task, `cli.py` and `grading.py` returned 0 and the other two did not mention it at all — that was US-040's whole finding.

- [ ] **Step 7: Gate sweep and commit**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest <that test file> tests/test_web_review.py --no-cov -p no:cacheprovider 2>&1 | grep -E "passed|failed"
PATH="$PWD/.venv/bin:$PATH" mypy lemely && PATH="$PWD/.venv/bin:$PATH" pyright lemely && PATH="$PWD/.venv/bin:$PATH" lint-imports
PATH="$PWD/.venv/bin:$PATH" pre-commit run --all-files && PATH="$PWD/.venv/bin:$PATH" ruff check . && PATH="$PWD/.venv/bin:$PATH" ruff format --check .
git commit -S -- lemely/web/services/grading.py lemely/app/cli.py lemely/web/routers/student.py lemely/web/routers/teacher.py <that test file>
```

Message: `feat(config): make equivalence_gate reachable from lemely.toml (closes US-040)`. State in the body that the default is unchanged and that enabling it is a separate deliberate act.

---

## Task 3: Carry the marker's `rationale` to the teacher wire

**Files:**
- Modify: `lemely/db/review_repo.py` — the `ReviewItemPoint` dataclass and its builder inside `get_item_detail`
- Modify: `lemely/web/schemas_review.py` — `ReviewItemPointDTO`
- Modify: `lemely/web/routers/review.py:144` — `_point_to_dto`
- Test: `tests/test_review_repo.py`, `tests/test_web_review.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2.
- Produces: `ReviewItemPoint.rationale: str | None` and `ReviewItemPointDTO.rationale: str | None`. Task 4 renders it.

**Why it matters:** `question_result_points.rationale` is written by `derive_point_rows` on **both** the verdict and legacy paths, and read by exactly one consumer — `self_review_repo.py:377`, the student surface. The teacher whose screen US-046 was built for never sees it. This is the only change in Plan 1 that improves the screen before the flag is ever enabled.

- [ ] **Step 1: Write the failing repo test**

In `tests/test_review_repo.py`, matching the file's existing fixture style:

```python
def test_review_item_point_carries_the_markers_rationale(...):
    """`rationale` is populated by `derive_point_rows` on the legacy path too
    (from `point_notes`), so this reaches the teacher screen with the flag off.
    """
    # seed a question_result_points row with rationale="method mark: 2x not shown"
    detail = service.get_item_detail(item_id, caller_id=..., caller_role=...)
    assert detail.points[0].rationale == "method mark: 2x not shown"
```

Follow the seeding helper the neighbouring tests already use; do not write a new one.

- [ ] **Step 2: Run it and confirm it fails**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_review_repo.py -k markers_rationale --no-cov -p no:cacheprovider
```

Expected: FAIL with `AttributeError: 'ReviewItemPoint' object has no attribute 'rationale'`.

- [ ] **Step 3: Add the field to the dataclass**

In `lemely/db/review_repo.py`, in the `ReviewItemPoint` frozen dataclass, after `ecf_applied`:

```python
    rationale: str | None  # the marker's own reasoning for this point, either path
```

And extend the class docstring:

```
    ``rationale`` is the marker's own per-point reasoning. It is populated on
    BOTH paths -- ``PointVerdict.note`` on the verdict path, ``point_notes`` on
    the legacy one, with the precedence rule in
    :func:`lemely.db.question_points.derive_point_rows` -- so unlike ``verdict``
    it is present today with ``equivalence_gate`` off.
```

- [ ] **Step 4: Read it in the builder**

In `get_item_detail`'s `ReviewItemPoint(...)` comprehension — the one inside the open session, beside `verdict=`/`evidence_span=`/`ecf_applied=` — add:

```python
                        rationale=p.rationale,
```

It must go in that same comprehension. `qr` is detached once the `with` block exits, and the surrounding comment already documents why.

- [ ] **Step 5: Confirm the repo test passes, then write the wire test**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_review_repo.py -k markers_rationale --no-cov -p no:cacheprovider
```

Expected: PASS.

Then in `tests/test_web_review.py`:

```python
def test_review_item_detail_exposes_rationale_on_the_wire(...):
    body = client.get(f"/api/teacher/review/{item_id}", headers=...).json()
    assert body["points"][0]["rationale"] == "method mark: 2x not shown"
```

Run it; expect FAIL with a `KeyError: 'rationale'`.

- [ ] **Step 6: Widen the DTO and the converter**

`lemely/web/schemas_review.py`, in `ReviewItemPointDTO` after `ecfApplied`:

```python
    rationale: str | None
```

Extend that class's docstring to say it is present on both paths, unlike `verdict`.

`lemely/web/routers/review.py`, in `_point_to_dto`:

```python
        rationale=point.rationale,
```

- [ ] **Step 7: Confirm both tests pass and revert-probe them**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_review_repo.py tests/test_web_review.py --no-cov -p no:cacheprovider 2>&1 | grep -E "passed|failed"
```

Expected: 34 passed (32 + 30 baseline plus 2 new is 64 across both — report the real number from the summary line, not this estimate).

Then revert-probe: `git stash push -- lemely/db/review_repo.py lemely/web/schemas_review.py lemely/web/routers/review.py`, re-run, confirm both new tests go red, `git stash pop`. Record the failure messages.

- [ ] **Step 8: Gate sweep and commit**

```bash
PATH="$PWD/.venv/bin:$PATH" mypy lemely && PATH="$PWD/.venv/bin:$PATH" pyright lemely && PATH="$PWD/.venv/bin:$PATH" lint-imports
PATH="$PWD/.venv/bin:$PATH" pre-commit run --all-files && PATH="$PWD/.venv/bin:$PATH" ruff check . && PATH="$PWD/.venv/bin:$PATH" ruff format --check .
git commit -S -- lemely/db/review_repo.py lemely/web/schemas_review.py lemely/web/routers/review.py tests/test_review_repo.py tests/test_web_review.py
```

---

## Task 4: Teacher screen — render rationale, suppress the empty section, correct the banner

**Files:**
- Modify: `web/src/lib/teacherTypes.ts` — `ReviewItemPoint`
- Modify: `web/src/portals/teacher/screens/ReviewItem.tsx` — `MarkerVerdicts`, and the banner at `:704`
- Test: `web/tests/unit/reviewItemMarkerVerdicts.test.ts`

**Interfaces:**
- Consumes: `ReviewItemPointDTO.rationale: str | None` from Task 3 — on the wire as `rationale`.
- Produces: nothing later tasks consume. Task 7 verifies it behaviourally.

**Read before editing:** `web/src/components/ui/chip.tsx`'s header defines the tone vocabulary. Do not add tones. This screen's existing verdict tones are `awarded: "ok"`, `withheld: "neutral"`, `unverifiable: "warn"` and stay as they are.

- [ ] **Step 1: Mirror the field in TypeScript**

In `web/src/lib/teacherTypes.ts`, in `ReviewItemPoint` after `ecfApplied: boolean`:

```ts
  /**
   * The marker's own reasoning for this point. Present on BOTH marking paths
   * (`PointVerdict.note` on the verdict path, `point_notes` on the legacy one),
   * so unlike `verdict` this is populated today with `equivalence_gate` off.
   */
  rationale: string | null
```

- [ ] **Step 2: Write the failing assertions**

In `web/tests/unit/reviewItemMarkerVerdicts.test.ts`:

```ts
  it("MarkerVerdicts renders the marker's rationale when present", () => {
    const body = functionBody(reviewItemSource, "MarkerVerdicts", "AwardedMarks")
    expect(body).toContain("point.rationale")
  })

  it("MarkerVerdicts renders nothing when no point carries a verdict", () => {
    // Section-level suppression, NOT per-point: a per-point filter re-creates
    // the invisible-point defect this component exists to fix. Verified
    // behaviourally in web/e2e/teacher-review.spec.ts; this only pins that the
    // guard is on the collection, not on each element.
    const body = functionBody(reviewItemSource, "MarkerVerdicts", "AwardedMarks")
    expect(body).toMatch(/points\.some\(\(p\) => p\.verdict !== null\)/)
    expect(body).toMatch(/\{points\.map\(/)
    expect(body).not.toMatch(/points\.filter\(/)
  })

  it("the evidence banner no longer claims the scan is not stored", () => {
    expect(reviewItemSource).not.toContain("aren't stored anywhere in this product")
  })
```

- [ ] **Step 3: Run and confirm they fail**

```bash
cd web && npx vitest run tests/unit/reviewItemMarkerVerdicts.test.ts
```

Expected: 3 failures — no `point.rationale`, no `points.some(...)` guard, and the banner string still present.

- [ ] **Step 4: Suppress the section when no verdict exists**

In `MarkerVerdicts`, replace the existing early return:

```tsx
  if (points.length === 0) return null
```

with:

```tsx
  // Section-level suppression. With `equivalence_gate` off every `verdict` is
  // null, so without this the screen shows a section whose every row repeats
  // the `awarded` boolean the matched-point chips already implied. A per-point
  // filter would instead re-create the invisible-point defect this component
  // exists to fix -- a reviewer demonstrated that a guard inside the map
  // callback passes every unit assertion with a clean tsc.
  if (points.length === 0 || !points.some((p) => p.verdict !== null)) return null
```

- [ ] **Step 5: Render the rationale**

Inside `MarkerVerdicts`' row, after the `evidenceSpan` block, add:

```tsx
            {point.rationale ? (
              <p className="text-body-sm text-ink-faint leading-[1.5] m-0 text-pretty line-clamp-3">
                {point.rationale}
              </p>
            ) : null}
```

Plain JSX text, never markup — same posture as `studentEvidence`. `line-clamp-3` keeps a long note from dominating the row.

- [ ] **Step 6: Correct the banner**

At `ReviewItem.tsx:704`, replace the false sentence. The scan **is** retained (`Upload.storage_path`, reachable via `upload_id`); the mark-scheme half is true and stays:

```tsx
                    The mark scheme's own wording isn't stored anywhere in this
                    product, and this screen does not display the original scan.
                    What's below is Lemely's own transcription of the student's
                    answer.
```

Plan 2 changes only the "does not display the original scan" clause when crops land. That is a planned clause swap, not a re-litigation.

- [ ] **Step 7: Confirm all three pass, then revert-probe the suppression**

```bash
cd web && npx vitest run tests/unit/reviewItemMarkerVerdicts.test.ts
```

Expected: 15 passed (12 baseline + 3).

Revert-probe: change the guard back to `if (points.length === 0) return null`, re-run, confirm the suppression assertion goes red, restore. Record the failure message.

- [ ] **Step 8: Gate sweep and commit**

```bash
cd web && npx tsc --noEmit && npm run lint && npm run typecheck && npm run check:copy && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "
```

Expected: `tsc` clean, lint clean, `check:copy` clean (the new banner copy has no em-dash and no exclamation mark), vitest 197 files / 3418 tests.

```bash
git commit -S -- web/src/lib/teacherTypes.ts web/src/portals/teacher/screens/ReviewItem.tsx web/tests/unit/reviewItemMarkerVerdicts.test.ts
```

---

## Task 5: Carry verdict, span and ECF to the student wire

**Files:**
- Modify: `lemely/db/self_review_repo.py` — the revealed-point builder at ~`:965-978`
- Modify: `lemely/web/schemas_student_self_review.py:49` — `SelfReviewRevealedPointDTO` only
- Test: the existing self-review repo/web test files (find with `grep -rln "SelfReviewRevealed" tests/`)

**Interfaces:**
- Consumes: nothing from Tasks 1-4.
- Produces: `SelfReviewRevealedPointDTO` gains `verdict: PointVerdictWire | None`, `evidenceSpan: str`, `ecfApplied: bool`. Task 6 renders them.

**The contract decides placement, not preference.** That builder emits `awarded=p.awarded`, so it is the **revealed** shape. `web/src/lib/selfReviewTypes.ts` says of the pending shape: *"If a field named `awarded` ever appears on the pending shape here, the backend contract has been broken, not extended."* A verdict is strictly more informative than `awarded`, so it can only join the revealed DTO. `SelfReviewRevealedPointDTO` already **extends** `SelfReviewPendingPointDTO`, so adding fields to the subclass is structurally correct and keeps the pending shape clean by construction.

Side effect worth keeping: the student therefore sees the verdict only after committing their self-mark, so it cannot inform what they claim.

- [ ] **Step 1: Write the failing tests, both halves of the contract**

```python
def test_revealed_point_carries_verdict_span_and_ecf(...):
    payload = repo.get_self_review(attempt_id, question_result_id, user_id=...)
    point = payload.points[0]
    assert point.verdict == "withheld"
    assert point.evidence_span == "v = 12.5"
    assert point.ecf_applied is True


def test_pending_point_carries_none_of_them(...):
    """The pending shape must stay clean. `selfReviewTypes.ts` documents that
    `awarded` appearing there is a broken contract, and a verdict is strictly
    more informative than `awarded`.
    """
    payload = repo.get_self_review(attempt_id, question_result_id_not_yet_marked, user_id=...)
    assert not hasattr(payload.points[0], "verdict")
```

Seed a `question_result_points` row with `verdict="withheld"`, `evidence_span="v = 12.5"`, `ecf_applied=True` using the helper the neighbouring tests already use.

- [ ] **Step 2: Run and confirm failure**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest <that test file> -k "verdict_span_and_ecf or pending_point_carries" --no-cov -p no:cacheprovider
```

Expected: the first FAILS with `AttributeError`; the second PASSES already (it guards a property that currently holds and must keep holding).

- [ ] **Step 3: Widen the revealed DTO only**

`lemely/web/schemas_student_self_review.py`, in `SelfReviewRevealedPointDTO`:

```python
    verdict: PointVerdictWire | None
    evidenceSpan: str
    ecfApplied: bool
```

Import the alias from its single home: `from lemely.core.schemas import PointVerdictWire as PointVerdictWire`. Do **not** re-declare the literal — `core/schemas.py` is its one definition and two modules already re-export it.

Add to the class docstring:

```
    ``verdict``/``evidenceSpan``/``ecfApplied`` are I6/I7's marker verdict, on
    the REVEALED shape only. They cannot join
    :class:`SelfReviewPendingPointDTO`: a verdict is strictly more informative
    than ``awarded``, which that shape deliberately omits until the student has
    committed their self-mark.
```

- [ ] **Step 4: Read them in the builder**

In `lemely/db/self_review_repo.py`, in the revealed-point comprehension beside `awarded=p.awarded`:

```python
                verdict=_narrow_point_verdict(p.verdict, mark_point_id=p.mark_point_id),
                evidence_span=p.evidence_span,
                ecf_applied=p.ecf_applied,
```

Reuse `lemely.db.review_repo._narrow_point_verdict` rather than writing a second narrowing site — it already logs an unrecognised value and carries `None`, and a second implementation is how two consumers drift apart. If importing it from `review_repo` crosses a `lint-imports` contract, stop and report rather than duplicating it.

- [ ] **Step 5: Confirm both tests pass, revert-probe, gate sweep, commit**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest <that test file> --no-cov -p no:cacheprovider 2>&1 | grep -E "passed|failed"
PATH="$PWD/.venv/bin:$PATH" mypy lemely && PATH="$PWD/.venv/bin:$PATH" pyright lemely && PATH="$PWD/.venv/bin:$PATH" lint-imports
PATH="$PWD/.venv/bin:$PATH" pre-commit run --all-files && PATH="$PWD/.venv/bin:$PATH" ruff check . && PATH="$PWD/.venv/bin:$PATH" ruff format --check .
git commit -S -- lemely/db/self_review_repo.py lemely/web/schemas_student_self_review.py <that test file>
```

---

## Task 6: Student screen — student-specific copy for the three verdicts

**Files:**
- Modify: `web/src/lib/selfReviewTypes.ts` — `SelfReviewRevealedPoint`
- Modify: the student self-review screen (find with `grep -rln "SelfReviewRevealedPoint" web/src/portals/student/`)
- Modify: `web/e2e/self-review.spec.ts`

**Interfaces:**
- Consumes: `verdict`, `evidenceSpan`, `ecfApplied` on the revealed DTO from Task 5.
- Produces: nothing.

**The copy is deliberately different from the teacher's.** "Unverifiable, could not confirm" is institutional hedging to a sixteen-year-old. Student wording says the same thing and implies what to do differently. Two vocabularies for one concept is intended here and recorded in the spec, so it is not drift.

- [ ] **Step 1: Mirror the fields on the revealed shape only**

In `web/src/lib/selfReviewTypes.ts`, in `SelfReviewRevealedPoint` (**not** `SelfReviewPendingPoint`):

```ts
  /** I6: the marker's own verdict. Null on the legacy marking path. */
  verdict: "awarded" | "withheld" | "unverifiable" | null
  /** The marker's verbatim quote from this student's own answer. `""` when none. */
  evidenceSpan: string
  /** I7: this point was re-marked using the student's earlier value, so one slip did not cascade. */
  ecfApplied: boolean
```

- [ ] **Step 2: Write the student copy map**

In the student self-review screen:

```tsx
/*
 * Student-facing wording for I6's three verdicts. Deliberately NOT the teacher
 * screen's labels ("Withheld, judged absent" / "Unverifiable, could not
 * confirm"): that is institutional hedging to a student mid-revision, and this
 * copy says the same thing while implying what to do differently. The two
 * vocabularies are intended -- see the 2026-09-24 production-readiness spec.
 */
const STUDENT_VERDICT_LABEL: Record<"awarded" | "withheld" | "unverifiable", string> = {
  awarded: "Marked correct",
  withheld: "Not shown in your answer",
  unverifiable: "We could not find this in your working",
}
```

No em-dashes, no exclamation marks — `check:copy` enforces both.

- [ ] **Step 3: Render verdict, span and ECF per revealed point**

```tsx
      {point.verdict ? <Chip tone="neutral">{STUDENT_VERDICT_LABEL[point.verdict]}</Chip> : null}
      {point.ecfApplied ? (
        <Chip tone="info">Carried forward, so one earlier slip did not cost you twice</Chip>
      ) : null}
      {point.evidenceSpan ? (
        <p className="text-body-sm text-ink-muted m-0 whitespace-pre-wrap">
          "{point.evidenceSpan}"
        </p>
      ) : null}
```

Match the tones already used on that screen; read it before choosing.

- [ ] **Step 4: Extend the e2e spec**

`web/e2e/self-review.spec.ts` already asserts that nothing about the marker's verdict is in the DOM before submission:

```ts
  await expect(page.getByTestId("self-review-outcome")).toHaveCount(0)
  await expect(page.getByText(/^Marker:/)).toHaveCount(0)
```

**Do not weaken those.** Add, after the existing post-submit reveal assertions, a check that the new copy appears only then:

```ts
  // The three verdicts use student-facing wording, and appear only post-reveal.
  await expect(
    page.getByText(/Marked correct|Not shown in your answer|We could not find this in your working/),
  ).toHaveCount(0)
```

placed **before** the submit click, and after the reveal:

```ts
  await expect(page.getByTestId("self-review-outcome")).toBeVisible()
```

If the seeded `selfReview` student's question has no `verdict` (likely, since `equivalence_gate` is off in the seed), assert the pre-submit absence only and record that the post-reveal half needs a seeded verdict row — then add one to `web/e2e/seed.ts` rather than skipping the assertion.

- [ ] **Step 5: Gate sweep and commit**

```bash
cd web && npx tsc --noEmit && npm run check:copy && npm run lint && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "
npx playwright test e2e/self-review.spec.ts
```

```bash
git commit -S -- web/src/lib/selfReviewTypes.ts <the student screen> web/e2e/self-review.spec.ts
```

---

## Task 7: The first Playwright spec for `/teacher/review`

**Files:**
- Create: `web/e2e/teacher-review.spec.ts`
- Possibly modify: `web/e2e/seed.ts` (a review-queue item with verdict-bearing points)

**Interfaces:**
- Consumes: the rendered surface from Tasks 3, 4.
- Produces: the behavioural coverage that closes the N3 gap.

**Why this exists:** `grep -rlnE 'teacher/review|ReviewItem' web/e2e/` returns nothing across 20 spec files. `web/vitest.config.ts` is `environment: "node"` with no jsdom by deliberate decision, and its comment claims component behaviour is covered by the Playwright suite — true for other screens, false for this one. A reviewer proved the cost: re-introducing the invisible-point defect as a guard **inside** the map callback passes all 12 unit assertions with a clean `tsc`. A source-text test can pin the shape of an iteration but never "every element produces output".

- [ ] **Step 1: Check what the seed already provides**

```bash
PATH="$PWD/.venv/bin:$PATH" grep -n "review\|teacher" web/e2e/seed.ts | head -20
```

Record whether a teacher with a review-queue item exists. If one does, use it. If not, add a seeded item with two points: one `verdict="withheld"`, one `verdict="unverifiable"`, plus a `rationale` on the first.

- [ ] **Step 2: Write the spec**

```ts
import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Teacher review item (T-08), end to end. This screen had NO behavioural
 * coverage before: web/vitest.config.ts is environment:"node" with no jsdom,
 * so its unit tests assert source text, and a reviewer showed that a guard
 * inside MarkerVerdicts' map callback re-creates the invisible-point defect
 * while passing every one of those assertions with a clean tsc. These are the
 * assertions that cannot be satisfied by a string check.
 */

test("a teacher sees every point's marker verdict, with withheld and unverifiable distinguishable", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const teacher = seed.teachers.review

  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()

  await page.goto(`/teacher/review/${seed.reviewItems.withVerdicts.id}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })

  const section = page.getByRole("region", { name: /marker's per-point verdicts/i })
  await expect(section).toBeVisible()

  // Every point renders, not only those the student self-marked. This is the
  // assertion a source-text test cannot make.
  await expect(section.getByTestId("marker-verdict-row")).toHaveCount(2)

  // withheld and unverifiable must be distinguishable from each other.
  await expect(section.getByText("Withheld, judged absent")).toBeVisible()
  await expect(section.getByText("Unverifiable, could not confirm")).toBeVisible()

  expect(errors).toHaveLength(0)
})

test("a legacy item with no verdicts shows no marker-verdict section at all", async ({ page }) => {
  const seed = readSeed()
  const teacher = seed.teachers.review

  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()

  await page.goto(`/teacher/review/${seed.reviewItems.legacyNoVerdicts.id}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })

  // Section-level suppression, verified behaviourally rather than by regex.
  await expect(page.getByRole("region", { name: /marker's per-point verdicts/i })).toHaveCount(0)
})
```

- [ ] **Step 3: Add the hooks the spec needs**

`MarkerVerdicts` must expose a `data-testid="marker-verdict-row"` per row and its section must have an accessible name matching the query. Add them in `ReviewItem.tsx` if absent — a test that cannot select what it asserts is not a test.

- [ ] **Step 4: Run it, and prove it catches the defect it exists for**

```bash
cd web && npx playwright test e2e/teacher-review.spec.ts
```

Expected: 2 passed.

Then the probe that justifies this whole task — change `MarkerVerdicts`' map to
`{points.map((point, index) => point.verdict === null ? null : (` and re-run:

```bash
cd web && npx vitest run tests/unit/reviewItemMarkerVerdicts.test.ts   # still passes: the gap
npx playwright test e2e/teacher-review.spec.ts                          # now FAILS: the gap closed
```

Record both outcomes. That contrast is the deliverable. Restore the code.

- [ ] **Step 5: Gate sweep and commit**

```bash
cd web && npx tsc --noEmit && npm run check:copy && npm run test -- --run 2>&1 | grep -E "Test Files|Tests "
git commit -S -- web/e2e/teacher-review.spec.ts web/e2e/seed.ts web/src/portals/teacher/screens/ReviewItem.tsx
```

---

## Self-review of this plan

**Spec coverage.** Story A → Task 1. Story B → Task 2. Story C → Tasks 3 and 4 (backend wire, then render; a reviewer can reject one and accept the other). Story G → Tasks 5 and 6. Story D → Task 7. Stories E and F are Plan 2 by the approved split. The spec's disclosure gate belongs to Plan 2 and is not referenced here, correctly — Plan 1 adds no new access path to student scans.

**One spec claim this plan corrects.** The spec says story B's risk is that a settings object may need threading into `grade_paper`'s callers. Measured while writing Task 2: `settings` is already in scope at all three (`cli.py:350`, `student.py` beside `settings.integrity`, `teacher.py:439-470`). B is four one-line additions plus a signature, not a threading exercise. Task 2 Step 6 proves reachability by grep rather than asserting it.

**Type consistency.** `PointVerdictWire` has exactly one definition (`lemely/core/schemas.py`) and is re-exported, never re-declared — Task 5 Step 3 states that explicitly. `rationale` is `str | None` at the dataclass (Task 3), the DTO (Task 3) and TS (Task 4). `_narrow_point_verdict` is reused in Task 5, not reimplemented, with an instruction to stop and report if `lint-imports` forbids the direction rather than duplicating it.

**Known gaps an executing agent must resolve, not guess.** Three tasks say "find the existing test file with `grep`" rather than naming one, because the right home depends on fixtures I did not read. Task 6 Step 4 and Task 7 Step 1 may need `web/e2e/seed.ts` extended with a verdict-bearing row; both say to add the seed rather than skip the assertion. These are instructions to check, not placeholders for behaviour.
