# Verdict Path: Question-Level Boxes — Implementation Plan (Plan 2 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the question-level `source_box` the extractor already produces, serve a cropped image of that region of the student's script, and render it on the teacher review screen where today an honest placeholder apologises for its absence.

**Architecture:** Stories E and F of the approved design. Almost none of this is new machinery: `SourceBox` exists with a validator, `ExtractedAnswer` carries it, `box_plausibility` checks it contains ink, `reread.py` already crops it, `Upload.storage_path` retains the scan, and `get_paper_preview` already renders one page of a stored scan behind the teacher guard. The box is produced at extraction, consumed in-process by the re-read, and then discarded: `source_box` has zero hits in `lemely/db/` and `lemely/web/`. Five tasks close that, in the order carry → persist → expose → serve → render.

**Tech Stack:** Python 3.13, pydantic v2, SQLAlchemy, Alembic, FastAPI, pymupdf, Pillow, pytest/unittest, React + TypeScript, vitest, Playwright.

Spec: `docs/superpowers/specs/2026-09-24-verdict-path-production-readiness-design.md` (stories E and F, plus the Disclosure human gate).
Plan 1 (`2026-09-24-verdict-path-switchable.md`, stories A, B, C, G, D) precedes this one and must be complete first: Task 5 here edits `ReviewItem.tsx`, which Plan 1's Task 4 also edits.

## Global Constraints

- Signed commits only: `git commit -S`. Conventional messages with a scope.
- Never `git commit -a`, `git add -A`, or `git add .`. Name paths explicitly: `git commit -S -- <paths>`. The index is shared with concurrent agents.
- Do NOT push. The user pushes.
- The repo is PUBLIC. No real student scripts, labels, or `GEMINI_API_KEY` in any commit. **This plan serves images of student work: no real scan may enter a fixture, a test, or a screenshot.**
- Prefix every Python command with `PATH="$PWD/.venv/bin:$PATH"`, or tools report "Executable not found".
- Add `--no-cov` to any single-file pytest run. The coverage gate is global and fails single-file runs at ~10%; that failure is not yours.
- Report test counts by grepping the `N passed` summary line. Never from `tail`, never by counting dots in a `-q` run.
- Run `pre-commit run --all-files`, **then** bare `ruff check .` and `ruff format --check .` on the resulting commit. The pre-commit ruff hook runs `--fix` and reports on the post-fix tree.
- **Frontend type checking is `npm run typecheck`, not `tsc --noEmit`.** The gate runs `tsc -b --force --noEmit`, which includes the test project; the bare command does not, and Plan 1 shipped a red gate for an hour because of exactly that difference.
- UI copy passes `npm run check:copy`: no em-dashes, no exclamation marks.
- No acceptance criterion is satisfied by asserting the absence of a string.
- Every new test must be observed FAILING before the implementation, and the failure message recorded in the task's report. A check earns the name only if it evaluates the predicate rather than reading it, over inputs a real producer can emit, and was observed going red (`sdd/probes/README.md`).

**Baselines measured while writing this plan** (hold or exceed; **re-measure at task start**, because Plan 1's tail may move them): `tests/test_correction_ai.py` 128 · `tests/test_question_points.py` 35 · `tests/test_review_repo.py` 33 · `tests/test_web_review.py` 31 · `tests/test_self_review_repo.py` 84 · `tests/test_student_self_review_web.py` 17 · `tests/test_migration_0041_point_verdict_columns.py` 7 · vitest 197 files / 3422 tests · `pyright lemely` 0 errors · `mypy lemely` 308 files · `lint-imports` 4 contracts · `dup_verdict_probe.py` 0 violations.

## Corrections to the spec, measured while writing this plan

The spec's story E was written from a reading of the code. Five of its particulars are wrong, and each one would have cost an implementer real time.

1. **The function is `_flatten_answers`, not `_answers_by_id`,** at `lemely/io/correction_ai.py:49`.
2. **The dedup rule is already explicit and published.** `_flatten_answers`' docstring records NIT-B's policy as **last-wins**, and it emits a `DUPLICATE_QUESTION_ID` bus event counting the extras. The spec worried a second rule might appear; the plan's design makes that structurally impossible rather than merely discouraged, by keying the box off the same dict.
3. **There are nine `CorrectedQuestion(` construction sites in that file, not four.** The spec's "four existing `extraction_confidence=` sites" (`:301`, `:316`, `:331`, `:372`) are all inside the single MCQ helper `_correct_mcq`. The other five (`:1034`, `:1201`, `:1224`, `:1312`, `:1382`) are the AI, verdict-path, blank and dropped builders, and `corrected.append` appears six times. Threading a parameter through all of them would be nine edits and nine chances to miss one. Task 1 sets the field **once**, at the single `CorrectionResult(` assembly at `:2103`.
4. **The savepoint precedent does not apply here.** The spec says hop 3 should follow `_safe_derive_point_rows`, which wraps its write in `session.begin_nested()`. That works for `question_result_points` because those are separate rows added after a flush. `question_results` rows are built by `_to_question_result` and attached to the attempt *before* `session.add(attempt)` (`attempt_repo.py:340`), inside the outer transaction. A savepoint cannot protect a column on the attempt's own dependent row. The guard must therefore be a **pure validation before construction**, which is strictly better anyway: a malformed box never becomes a column value at all.
5. **The web layer renders single pages with pymupdf, not pypdfium2.** `get_paper_preview` (`lemely/web/routers/teacher.py:940-1003`) already does `storage.download` → `pymupdf.open(stream=...)` → `doc.load_page(0).get_pixmap(dpi=...)` → `Response(media_type="image/png")`, with `StorageObjectNotFoundError` → 404, `page_count == 0` → 422, an unrenderable file → 422, and `Cache-Control: private, max-age=3600`. **No new single-page entry point is needed in `rasterise.py`.** Task 4 follows that route's shape and reuses `crop_and_upscale` verbatim.

   Why reusing the box across renderers is safe: `SourceBox.box` is normalised to 0-1000 of the page, so it is independent of both renderer and DPI. The box was captured against a pypdfium2 render at `EXTRACTION_DPI = 200.0`; cropping it out of a pymupdf render at any DPI is correct as long as the arithmetic scales by *that* render's own pixel dimensions, which `crop_and_upscale` does. The one thing that must hold is that page **order** agrees between the two renderers. Both are 0-based document order, and Task 4 pins it with a test rather than assuming it.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `lemely/io/correction_ai.py` | `_flatten_answers` carries the box; one assembly site sets it | 1 |
| `lemely/core/schemas.py` | `CorrectedQuestion.source_box` | 1 |
| `lemely/db/models/attempts.py` | five nullable `source_box_*` columns on `QuestionResult` | 2 |
| `lemely/db/migrations/versions/0042_question_result_source_box.py` (new) | the columns plus CHECK constraints mirroring `SourceBox`'s validator | 2 |
| `lemely/db/attempt_repo.py` | `_to_question_result` persists the box behind a pure guard | 2 |
| `lemely/db/review_repo.py` | `ReviewItemDetail.has_source_box`; a guarded crop-source lookup | 3, 4 |
| `lemely/web/schemas_review.py` | `ReviewItemDetailDTO.hasSourceBox`, and a docstring that stops denying crops exist | 3 |
| `lemely/web/routers/review.py` | `_detail_to_dto` carries it; the crop route | 3, 4 |
| `web/src/lib/teacherTypes.ts` | TS mirror | 3, 5 |
| `web/src/portals/teacher/screens/ReviewItem.tsx` | render the crop, swap the banner's display clause | 5 |
| `web/e2e/teacher-review.spec.ts` | a boxless point shows no crop affordance | 5 |

---

## Task 1: Carry `source_box` from the extractor to `CorrectedQuestion`

**Files:**
- Modify: `lemely/core/schemas.py` — `CorrectedQuestion` gains one field
- Modify: `lemely/io/correction_ai.py:49` (`_flatten_answers`), `:1735` (a 3-tuple unpack), `:2103` (the assembly)
- Test: `tests/test_correction_ai.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CorrectedQuestion.source_box: SourceBox | None = None`, populated for every question whose extracted answer carried a box. Task 2 persists it.

**This task does not move the marking fingerprint.** `CorrectedQuestion` is an *output* record and is not the `response_schema` at any of the twelve `_params_fingerprint` call sites. Only Plan 1's Task 1 touched a hashed schema. If you find yourself needing to re-pin a hash, stop and report: it means this claim is wrong and that is worth knowing before it is papered over.

- [ ] **Step 1: Write the failing test for the real-`ExtractedAnswers` branch**

Add to `tests/test_correction_ai.py`, in the class that already covers `_flatten_answers` (find it with `grep -n "_flatten_answers" tests/test_correction_ai.py`; add a new class beside it only if none exists):

```python
    def test_flatten_answers_carries_the_source_box(self):
        """The extractor's box must survive into marking, not be discarded.

        `source_box` has zero hits in `lemely/db/` and `lemely/web/`: it is
        produced at extraction, used in-process by the crop-and-re-read, and
        then lost. This is the first hop that keeps it.
        """
        extracted = ExtractedAnswers(
            answers=[
                ExtractedAnswer(
                    question_id="1",
                    answer="42",
                    confidence=0.9,
                    source_box=SourceBox(page=0, box=[100, 200, 300, 400]),
                )
            ]
        )
        flat = _flatten_answers(extracted)
        self.assertEqual(flat["1"][3], SourceBox(page=0, box=[100, 200, 300, 400]))
```

Import `SourceBox` and `_flatten_answers` alongside the file's existing imports from `lemely.core.schemas` and `lemely.io.correction_ai`.

- [ ] **Step 2: Write the failing test for the plain-`Mapping` branch**

```python
    def test_flatten_answers_yields_no_box_for_a_plain_mapping(self):
        """A `Mapping[str, str]` is the correction-only/oracle bypass: it never
        went through extraction, so there is no box to carry. It already
        fabricates `None` working_out and `1.0` confidence; the box follows the
        same shape.
        """
        flat = _flatten_answers({"1": "42"})
        self.assertIsNone(flat["1"][3])
```

- [ ] **Step 3: Write the failing test that pins WHICH duplicate supplies the box**

```python
    def test_a_duplicate_question_id_takes_the_box_from_the_surviving_answer(self):
        """NIT-B: two answers can share one `question_id`, and this function's
        documented policy is last-wins. The box must come from the SAME
        survivor, not from a second rule.

        A second dedup rule is the failure this branch already paid for:
        `point_verdicts` had two consumers resolving a duplicate differently,
        and a 1-mark point scored 2.
        """
        first = SourceBox(page=0, box=[10, 10, 20, 20])
        last = SourceBox(page=1, box=[30, 30, 40, 40])
        extracted = ExtractedAnswers(
            answers=[
                ExtractedAnswer(question_id="1", answer="first", confidence=0.5, source_box=first),
                ExtractedAnswer(question_id="1", answer="last", confidence=0.5, source_box=last),
            ]
        )
        flat = _flatten_answers(extracted)
        self.assertEqual(flat["1"][0], "last", "last-wins is the documented policy")
        self.assertEqual(flat["1"][3], last, "the box must come from the surviving answer")
```

- [ ] **Step 4: Run the three tests and confirm they fail**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_correction_ai.py -k "source_box or supplies_the_box" --no-cov -p no:cacheprovider
```

Expected: FAIL with `IndexError: tuple index out of range` — the tuple has three elements, not four. Record the exact message.

- [ ] **Step 5: Widen the tuple**

In `lemely/io/correction_ai.py`, change `_flatten_answers`' signature and both returns:

```python
def _flatten_answers(
    extracted: ExtractedAnswers | Mapping[str, str],
) -> dict[str, tuple[str, str | None, float, SourceBox | None]]:
```

Update the first line of its docstring to `"""Return {question_id: (answer, working_out, confidence, source_box)} for every extracted answer.` and leave the rest of that docstring alone — the NIT-B paragraph is still exactly true, and the box now inherits its policy by construction.

Inside the `ExtractedAnswers` branch, the accumulator and the write:

```python
        flattened: dict[str, tuple[str, str | None, float, SourceBox | None]] = {}
```

```python
            flattened[a.question_id] = (a.answer, a.working_out, a.confidence, a.source_box)
```

The `Mapping` fallback return:

```python
    return {str(k): (str(v), None, 1.0, None) for k, v in extracted.items()}
```

Add a sentence to the fallback's existing comment: `A plain mapping has no box either, for the same reason it has no working_out.`

- [ ] **Step 6: Fix the one unpack site that breaks**

`lemely/io/correction_ai.py:1735` destructures three elements:

```python
        answer, working, _ = answers[leaf_id]
```

becomes

```python
        answer, working, _, _ = answers[leaf_id]
```

The other two consumers are index-based and need no change: `:1696` reads `prereq_answer[0]`, and `:1918` reads `answer_tuple[0]`, `[1]`, `[2]`. Confirm with `grep -n "answers\[\|answers.get(" lemely/io/correction_ai.py` that those three are the only readers, and report the output.

- [ ] **Step 7: Add the field to `CorrectedQuestion`**

In `lemely/core/schemas.py`, inside `class CorrectedQuestion(StrictModel)` (starts `:300`), add after `rationale`'s declaration:

```python
    source_box: SourceBox | None = None
    """Where on the rasterised page this question's answer was read from
    (E, 2026-09-24 production-readiness spec). QUESTION-level, not per mark
    point: marking is text-only -- `lemely/io/correction_ai.py` references no
    `image`, `RasterisedPage` or `media_resolution` -- so the marker never
    sees the page and cannot attribute a region to one point. It answers
    "where did this answer come from", never "which pixels justify this
    mark". `None` is the common case rather than an error: the extractor may
    return no box, and a box it returned may have been dropped as unusable
    (`ExtractedAnswers.source_box_drops`), and those two are deliberately
    indistinguishable here. Absence must render as absence, never as a
    failed crop."""
```

`SourceBox` is declared at `:498` in the same file, above `CorrectedQuestion` at `:300`? Check the order with `grep -n "^class SourceBox\|^class CorrectedQuestion" lemely/core/schemas.py`. If `SourceBox` is declared *below* `CorrectedQuestion`, annotate the field as `"SourceBox | None"` in quotes, or move nothing and rely on `from __future__ import annotations` if that file has it — check, and report which applies rather than guessing.

- [ ] **Step 8: Write the failing test for the assembly**

```python
    def test_correct_paper_puts_the_extractors_box_on_the_corrected_question(self):
        """The box must reach the output record, not stop at the flatten step.

        Set once at the single `CorrectionResult` assembly rather than threaded
        into nine `CorrectedQuestion(` sites: one write is one rule, and it
        keys off the same `answers` dict, so `_flatten_answers`' last-wins
        dedup policy is inherited instead of restated.
        """
        scheme = _mcq_scheme()  # reuse the file's existing MCQ scheme helper
        extracted = ExtractedAnswers(
            answers=[
                ExtractedAnswer(
                    question_id="1",
                    answer="A",
                    confidence=0.9,
                    source_box=SourceBox(page=2, box=[100, 100, 200, 200]),
                )
            ]
        )
        result = correct_paper(mark_scheme=scheme, extracted_answers=extracted, mcq_only=True)
        by_id = {cq.question_id: cq for cq in result.questions}
        self.assertEqual(by_id["1"].source_box, SourceBox(page=2, box=[100, 100, 200, 200]))

    def test_a_question_with_no_extracted_answer_has_no_box(self):
        """A question absent from `answers` must not raise a KeyError on the way
        through, and must come out with `source_box=None`.
        """
        scheme = _mcq_scheme_two_questions()  # find or add a two-question helper
        extracted = ExtractedAnswers(
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.9)]
        )
        result = correct_paper(mark_scheme=scheme, extracted_answers=extracted, mcq_only=True)
        by_id = {cq.question_id: cq for cq in result.questions}
        self.assertIsNone(by_id["1"].source_box)
        self.assertIsNone(by_id["2"].source_box)
```

Use the scheme helpers that already exist in this file — find them with `grep -n "def _mcq\|def _scheme\|mcq_answer" tests/test_correction_ai.py` and use the real ones. Do not invent a helper if one exists; do not build a `MarkScheme` inline if the file has a builder.

- [ ] **Step 9: Run them and confirm they fail**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_correction_ai.py -k "extractors_box or no_extracted_answer_has_no_box" --no-cov -p no:cacheprovider
```

Expected: FAIL — `source_box` is `None` on the assembled question because nothing sets it yet. Record the message.

- [ ] **Step 10: Set the field once, at the assembly**

`lemely/io/correction_ai.py:2103` currently reads:

```python
    return CorrectionResult(metadata=_exam_metadata(scheme), questions=corrected)
```

Replace with:

```python
    # E (2026-09-24 production-readiness spec): attach each question's
    # extraction bounding box here, at the ONE place the list is finished,
    # rather than at the nine `CorrectedQuestion(` construction sites (six of
    # which are reached through `corrected.append`). One write is one rule,
    # and keying off `answers` means the box comes from whichever answer
    # `_flatten_answers`' last-wins policy kept -- a second dedup rule cannot
    # appear here, which is the failure `point_verdicts` already paid for.
    corrected = [
        cq.model_copy(update={"source_box": answers[cq.question_id][3]})
        if cq.question_id in answers
        else cq
        for cq in corrected
    ]
    return CorrectionResult(metadata=_exam_metadata(scheme), questions=corrected)
```

- [ ] **Step 11: Run them and confirm they pass, then the whole file**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_correction_ai.py --no-cov -p no:cacheprovider 2>&1 | tail -3
```

Expected: 133 passed (128 + 5). If the number differs from 128 + 5, say so and explain which count moved rather than adjusting the expectation silently.

- [ ] **Step 12: Confirm the marking fingerprint did NOT move**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_correction_ai.py -k schema_hash --no-cov -p no:cacheprovider 2>&1 | tail -3
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_accuracy_harness.py -k params_fingerprint --no-cov -p no:cacheprovider 2>&1 | tail -3
```

Expected: both pass unchanged. `CorrectedQuestion` is an output record and is not hashed. **If either fails, stop and report** — a moved key here means this task invalidated the marking cache, which is Plan 1 Task 1's job alone and must not happen twice.

- [ ] **Step 13: Full gate sweep**

```bash
PATH="$PWD/.venv/bin:$PATH" mypy lemely
PATH="$PWD/.venv/bin:$PATH" pyright lemely
PATH="$PWD/.venv/bin:$PATH" lint-imports
PATH="$PWD/.venv/bin:$PATH" pre-commit run --all-files
PATH="$PWD/.venv/bin:$PATH" ruff check .
PATH="$PWD/.venv/bin:$PATH" ruff format --check .
```

Expected: mypy Success 308 files, pyright 0 errors, 4 contracts kept, all hooks pass, both ruff commands clean.

- [ ] **Step 14: Commit**

```bash
git commit -S -- lemely/core/schemas.py lemely/io/correction_ai.py tests/test_correction_ai.py
```

Message must state: that the field is set at one assembly site rather than nine construction sites, and that the marking fingerprint is unchanged because `CorrectedQuestion` is not a `response_schema`.

---

## Task 2: Persist the box on `question_results`

**Files:**
- Create: `lemely/db/migrations/versions/0042_question_result_source_box.py`
- Modify: `lemely/db/models/attempts.py` — `QuestionResult` (class at `:161`)
- Modify: `lemely/db/attempt_repo.py:564` (`_to_question_result`)
- Test: `tests/test_migration_0042_question_result_source_box.py` (new, modelled on `tests/test_migration_0041_point_verdict_columns.py`), plus `tests/test_attempt_repo.py` for the guard

**Interfaces:**
- Consumes: `CorrectedQuestion.source_box` from Task 1.
- Produces: five nullable columns on `question_results` — `source_box_page`, `source_box_ymin`, `source_box_xmin`, `source_box_ymax`, `source_box_xmax`, all `Integer` — and `_source_box_columns(cq) -> dict[str, int | None]` in `attempt_repo.py`. Task 3 reads them.

**Five explicit columns, not one jsonb blob.** The spec's reason: `SourceBox`'s validator enforces coordinate range and positive area, and a jsonb blob would let a degenerate box through to render time where nobody can see why it broke. Explicit columns let the database carry the same invariant as a CHECK constraint, so a degenerate box cannot be stored by any writer, including a future one that bypasses pydantic.

**Current Alembic head is `0041_point_verdict_columns`.** Confirm with `ls lemely/db/migrations/versions/` and by checking no other file declares `down_revision = "0041_point_verdict_columns"`. If something else already revises it, stop and report — two heads is a merge conflict, not something to guess at.

- [ ] **Step 1: Write the migration**

Create `lemely/db/migrations/versions/0042_question_result_source_box.py`:

```python
"""Persist the extraction bounding box on `question_results`.

Story E, `docs/superpowers/specs/2026-09-24-verdict-path-production-readiness-design.md`.
`CorrectedQuestion.source_box` is produced by extraction (`ExtractedAnswer.source_box`,
US-006), checked for ink (`io/box_plausibility.py`, US-017), and cropped in-process by
`io/reread.py` -- and then discarded: before this migration `grep -rn "source_box"
lemely/db/ lemely/web/` returns zero hits. The same shape of gap `point_verdicts` had
before `0041`.

**Five explicit integer columns, not one jsonb blob.** `SourceBox.validate_box_coords`
enforces that every coordinate is in [0, 1000] and that the box has positive area. A
jsonb blob would let a degenerate box reach the crop route, where the failure surfaces
as a broken image and nobody can see why. The CHECK constraints below carry the same
invariant in the database, so no writer can store a box that cannot be cropped --
including a future writer that does not go through pydantic.

`source_box_page` is the 0-based index of the rasterised page, matching
`lemely.io.rasterise.RasterisedPage.index` and the `page` Gemini echoes back.
Coordinates are `[ymin, xmin, ymax, xmax]` on a 0-1000 scale, so they are independent
of renderer and DPI.

All five are nullable and all-or-nothing: a partially populated box is meaningless, so
`ck_question_results_source_box_all_or_none` rejects it. `NULL` is the common case, not
an error -- the extractor may return no box, and a returned box may have been dropped as
unusable (`ExtractedAnswers.source_box_drops`), and those are deliberately
indistinguishable downstream.

`downgrade()` drops all five, restoring the pre-migration shape exactly. No backfill
either direction, the same posture as every other lossy migration on this table.

Revision ID: 0042_question_result_source_box
Revises: 0041_point_verdict_columns
Create Date: 2026-09-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0042_question_result_source_box"
down_revision: str | Sequence[str] | None = "0041_point_verdict_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COORD_COLUMNS = ("source_box_ymin", "source_box_xmin", "source_box_ymax", "source_box_xmax")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "question_results",
        sa.Column("source_box_page", sa.Integer(), nullable=True),
    )
    for name in _COORD_COLUMNS:
        op.add_column("question_results", sa.Column(name, sa.Integer(), nullable=True))

    # Mirrors `SourceBox.validate_box_coords`: coordinates in range, positive
    # area. Enforced here as well as in pydantic because the crop route reads
    # these columns, not the model, and a degenerate box is only visible as a
    # broken image at that point.
    op.create_check_constraint(
        "ck_question_results_source_box_page_non_negative",
        "question_results",
        "source_box_page IS NULL OR source_box_page >= 0",
    )
    op.create_check_constraint(
        "ck_question_results_source_box_range",
        "question_results",
        " AND ".join(
            f"({name} IS NULL OR ({name} >= 0 AND {name} <= 1000))" for name in _COORD_COLUMNS
        ),
    )
    op.create_check_constraint(
        "ck_question_results_source_box_positive_area",
        "question_results",
        "source_box_ymax IS NULL OR source_box_xmax IS NULL "
        "OR (source_box_ymax > source_box_ymin AND source_box_xmax > source_box_xmin)",
    )
    # A half-written box is meaningless: either the page and all four
    # coordinates are present, or none of them are.
    op.create_check_constraint(
        "ck_question_results_source_box_all_or_none",
        "question_results",
        "(source_box_page IS NULL AND source_box_ymin IS NULL AND source_box_xmin IS NULL "
        "AND source_box_ymax IS NULL AND source_box_xmax IS NULL) "
        "OR (source_box_page IS NOT NULL AND source_box_ymin IS NOT NULL "
        "AND source_box_xmin IS NOT NULL AND source_box_ymax IS NOT NULL "
        "AND source_box_xmax IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    for name in (
        "ck_question_results_source_box_all_or_none",
        "ck_question_results_source_box_positive_area",
        "ck_question_results_source_box_range",
        "ck_question_results_source_box_page_non_negative",
    ):
        op.drop_constraint(name, "question_results", type_="check")
    for name in ("source_box_xmax", "source_box_ymax", "source_box_xmin", "source_box_ymin"):
        op.drop_column("question_results", name)
    op.drop_column("question_results", "source_box_page")
```

- [ ] **Step 2: Add the columns to the model**

In `lemely/db/models/attempts.py`, in `class QuestionResult` after `rationale`'s declaration:

```python
    source_box_page: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """0-based rasterised-page index for `source_box_*` (migration `0042`).

    Question-level, not per mark point: marking is text-only, so the marker
    never sees the page. See `CorrectedQuestion.source_box`. All five
    `source_box_*` columns are all-or-nothing, enforced by
    `ck_question_results_source_box_all_or_none`.
    """
    source_box_ymin: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_box_xmin: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_box_ymax: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_box_xmax: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
```

Read `QuestionResult`'s class docstring before you finish this step. It states what this table does and does not keep; if it claims no bounding box or scan region is stored, update that sentence in this commit. A docstring that contradicts its own columns is the false-prose defect this branch has paid for repeatedly.

- [ ] **Step 3: Write the failing migration round-trip test**

Create `tests/test_migration_0042_question_result_source_box.py`. **Read `tests/test_migration_0041_point_verdict_columns.py` first and follow its structure exactly** — its fixtures, its real-Postgres guard and skip behaviour, and its habit of asserting types, nullability and defaults rather than column names. Assert:

1. After upgrade, all five columns exist on `question_results` with integer type and `nullable=True`.
2. A **raw non-ORM INSERT** of a valid box round-trips: `source_box_page=2`, `[100, 200, 300, 400]`.
3. A raw INSERT with a coordinate of `1001` is rejected by the database.
4. A raw INSERT with `ymax <= ymin` is rejected.
5. A raw INSERT with `source_box_page` set but the coordinates `NULL` is rejected.
6. `downgrade()` removes all five columns and all four constraints.

Points 3 to 5 are the reason for explicit columns over jsonb. Assert them by catching the database's integrity error, not by inspecting constraint names.

- [ ] **Step 4: Run it and confirm it fails**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_migration_0042_question_result_source_box.py --no-cov -p no:cacheprovider
```

Expected: FAIL — the migration does not run, or the columns do not exist. If the whole file SKIPS because no Postgres is available, say so plainly in your report and state that points 1 to 6 are unverified; do not report a skip as a pass. Check how `0041`'s test is run in CI (`grep -rn "test_migration" .github/workflows/`) and report whether this new file will be picked up by the same job.

- [ ] **Step 5: Run the migration, confirm the test passes**

```bash
PATH="$PWD/.venv/bin:$PATH" alembic upgrade head
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_migration_0042_question_result_source_box.py --no-cov -p no:cacheprovider 2>&1 | tail -3
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_migration_0041_point_verdict_columns.py --no-cov -p no:cacheprovider 2>&1 | tail -3
```

Expected: the new file passes; `0041`'s 7 still pass. Also confirm a single head: `PATH="$PWD/.venv/bin:$PATH" alembic heads` must print exactly one.

- [ ] **Step 6: Write the failing test for the pure guard**

The guard's job: a `CorrectedQuestion` whose `source_box` is somehow unusable must persist as `NULL` and must not cost the student their marked paper. Add to `tests/test_attempt_repo.py`, beside `test_persist_survives_derive_point_rows_raising` (find it with `grep -n "persist_survives" tests/test_attempt_repo.py` and follow its shape):

```python
def test_persist_writes_the_source_box_columns(...):
    """A box on the corrected question reaches the row, not just the object."""
    # ... persist a correction whose question carries
    # SourceBox(page=1, box=[10, 20, 30, 40]), then read the QuestionResult row
    # back and assert all five columns.


def test_persist_survives_an_unusable_source_box(...):
    """A bad box costs the box, never the attempt.

    `_safe_derive_point_rows` can use `session.begin_nested()` because
    `question_result_points` rows are added after a flush. These columns are on
    the `question_results` row itself, attached to the attempt BEFORE
    `session.add(attempt)`, so no savepoint can protect them -- the guard has to
    reject the value before the row is built. This test is what proves it does.
    """
    # ... construct a CorrectedQuestion, then force an unusable box past pydantic
    # with `model_construct` (this is the one legitimate use of it here: a real
    # producer cannot emit this, and the point is that the WRITE path does not
    # trust that). Assert: the attempt persists, every question result exists,
    # and the five columns are NULL.
```

Fill in the bodies using the file's existing persist fixtures. Do not invent a new sessionmaker or factory if the file has one.

- [ ] **Step 7: Run them and confirm they fail**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_attempt_repo.py -k source_box --no-cov -p no:cacheprovider
```

Expected: FAIL — `_to_question_result` sets no such columns, so they are `NULL` in the first test. Record the message.

- [ ] **Step 8: Write the guard and wire it**

In `lemely/db/attempt_repo.py`, above `_to_question_result` (`:564`):

```python
def _source_box_columns(cq: CorrectedQuestion) -> dict[str, int | None]:
    """Map `cq.source_box` onto the five `question_results` columns, or all `None`.

    A pure guard rather than a savepoint, and deliberately so.
    `_safe_derive_point_rows` can wrap its write in `session.begin_nested()`
    because `question_result_points` rows are added separately, after a flush.
    These columns live on the `question_results` row itself, which is attached
    to the attempt before `session.add(attempt)` -- inside the outer
    transaction, with no savepoint available. A value Postgres rejects there
    would abort the whole transaction and take the attempt, every
    `QuestionResult`, every `WeaknessRecord` and every `ReviewQueueItem` with
    it: the student would lose their marked paper over a bounding box. Nothing
    on this path may fail a correction (spec 2026-09-17, "Error handling"), so
    the value is checked before it ever becomes a column.

    `SourceBox`'s own validator already enforces range and positive area, so a
    box that reached here through pydantic is sound. This re-checks anyway,
    because the cost of being wrong is asymmetric and the check is four
    comparisons.
    """
    empty: dict[str, int | None] = {
        "source_box_page": None,
        "source_box_ymin": None,
        "source_box_xmin": None,
        "source_box_ymax": None,
        "source_box_xmax": None,
    }
    box = cq.source_box
    if box is None:
        return empty
    if box.page < 0 or len(box.box) != 4:
        return empty
    ymin, xmin, ymax, xmax = box.box
    if not all(0 <= coord <= 1000 for coord in box.box):
        return empty
    if ymax <= ymin or xmax <= xmin:
        return empty
    return {
        "source_box_page": box.page,
        "source_box_ymin": ymin,
        "source_box_xmin": xmin,
        "source_box_ymax": ymax,
        "source_box_xmax": xmax,
    }
```

Then in `_to_question_result`, after `rationale=cq.rationale,`:

```python
        **_source_box_columns(cq),
```

- [ ] **Step 9: Run them and confirm they pass, then the file and its neighbours**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_attempt_repo.py --no-cov -p no:cacheprovider 2>&1 | tail -3
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_review_repo.py tests/test_question_points.py --no-cov -p no:cacheprovider 2>&1 | tail -3
```

Report both counts against the baselines.

- [ ] **Step 10: Prove the guard discriminates**

Change one comparison in `_source_box_columns` so it stops rejecting — for example `if ymax <= ymin` to `if False` — and re-run `-k source_box`. The unusable-box test must FAIL. Record the failure, then revert. A guard never observed rejecting is not a guard.

- [ ] **Step 11: Full gate sweep, then commit**

Run the Task 1 Step 13 sweep. Then:

```bash
git commit -S -- lemely/db/migrations/versions/0042_question_result_source_box.py lemely/db/models/attempts.py lemely/db/attempt_repo.py tests/test_migration_0042_question_result_source_box.py tests/test_attempt_repo.py
```

Message must state: five explicit columns with CHECK constraints rather than jsonb and why, and that the guard is pure rather than a savepoint because these columns are on the attempt's own dependent row.

---

## Task 3: Expose whether a box exists on the review-item wire

**Files:**
- Modify: `lemely/db/review_repo.py` — `ReviewItemDetail`, and `get_item` (`:494`)
- Modify: `lemely/web/schemas_review.py` — `ReviewItemDetailDTO` (`:129`), including its docstring
- Modify: `lemely/web/routers/review.py:158` (`_detail_to_dto`)
- Modify: `web/src/lib/teacherTypes.ts`
- Test: `tests/test_review_repo.py`, `tests/test_web_review.py`

**Interfaces:**
- Consumes: Task 2's columns.
- Produces: `ReviewItemDetail.has_source_box: bool` and `ReviewItemDetailDTO.hasSourceBox: bool`, plus the TS mirror. Task 4's route is only called when this is `true`; Task 5 renders against it.

**Why a flag and not the box itself.** The client never needs the coordinates: it asks the route for an image. What it does need is to know whether to draw the affordance at all, *before* issuing a request. `source_box = NULL` is the common case, and a client that has to probe for absence shows a broken affordance first and corrects itself second. Send the one bit that decides the render, and nothing more: coordinates on the wire would be student-derived data with no consumer.

- [ ] **Step 1: Write the failing repo test**

Add to `tests/test_review_repo.py`, following the shape of the tests added for `rationale` (find them with `grep -n "rationale" tests/test_review_repo.py`):

```python
def test_get_item_reports_a_source_box_when_one_was_persisted(...):
    """The teacher screen must know whether a crop exists before asking for it."""
    # ... seed an attempt whose question result carries the five source_box
    # columns, then assert detail.has_source_box is True.


def test_get_item_reports_no_source_box_when_the_columns_are_null(...):
    """The common case. `source_box=NULL` is normal, not an error: the extractor
    may return no box, and a box it returned may have been dropped as unusable.
    """
    # ... seed without the columns, assert detail.has_source_box is False.
```

- [ ] **Step 2: Run them and confirm they fail**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_review_repo.py -k source_box --no-cov -p no:cacheprovider
```

Expected: FAIL with `AttributeError: 'ReviewItemDetail' object has no attribute 'has_source_box'`. Record it.

- [ ] **Step 3: Add the field to `ReviewItemDetail` and populate it**

Add to the `ReviewItemDetail` dataclass:

```python
    has_source_box: bool = False
    """True when this question result has all five `source_box_*` columns set,
    so `GET /api/teacher/review/{item_id}/crop` will return an image.

    A flag rather than the coordinates: the client asks the route for an
    image and never does the arithmetic, and coordinates on the wire would be
    student-derived data with no consumer. False is the common case.
    """
```

In `get_item` (`:494`), populate it from `qr`. **It must be read inside the open session**, next to the other scalar reads, for the reason the existing comment in that method already gives about `qr.points` and `DetachedInstanceError`. Scalar columns are populated by the query, so reading them after the block would work — but put it with the others anyway, and do not move the existing `points` read.

```python
            has_source_box=qr is not None and qr.source_box_page is not None,
```

One column suffices as the test, because `ck_question_results_source_box_all_or_none` makes the five all-or-nothing. Say so in a comment, citing the constraint by name, so the next reader does not "fix" it into a five-way `and`.

- [ ] **Step 4: Run the repo tests, confirm they pass**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_review_repo.py --no-cov -p no:cacheprovider 2>&1 | tail -3
```

- [ ] **Step 5: Write the failing wire test**

Add to `tests/test_web_review.py`, beside the `rationale` wire test:

```python
def test_review_item_detail_reports_whether_a_crop_exists(...):
    """`hasSourceBox` must reach the HTTP response, not stop at the dataclass."""
    # ... GET /api/teacher/review/{item_id} for a boxed question,
    # assert body["hasSourceBox"] is True; and for a boxless one, False.
```

- [ ] **Step 6: Run it, confirm it fails with `KeyError: 'hasSourceBox'`, then wire the DTO**

Add to `ReviewItemDetailDTO`:

```python
    hasSourceBox: bool = False
```

and in `_detail_to_dto` (`lemely/web/routers/review.py:158`):

```python
        hasSourceBox=detail.has_source_box,
```

- [ ] **Step 7: Correct `ReviewItemDetailDTO`'s docstring**

Its docstring currently states:

> There is still no persisted mark-scheme extract or scan-crop image on `QuestionResult` (see its docstring) — that part of the gap is real and stays real, so a future screen must not invent scan-crop or scheme-prose precision this backend cannot provide.

Half of that is now false: the scan-crop half is exactly what this plan delivers. Rewrite the sentence so it is true, keeping the mark-scheme half intact — there is still no persisted mark-scheme extract, and that remains a real gap a screen must not invent. State that a scan crop is available when `hasSourceBox` is true, served by the crop route, and that it is **question-level**, covering where the answer was read from rather than which pixels justify a mark point.

This step is not cosmetic. A docstring that denies a feature the same file exposes is the false-prose defect this branch has paid for repeatedly, and it is the kind a reviewer finds after merge.

- [ ] **Step 8: Mirror the field in TypeScript**

In `web/src/lib/teacherTypes.ts`, add `hasSourceBox: boolean;` to the review-item detail interface, next to the fields Plan 1's Task 3 and 4 added. Match the file's existing comment convention.

- [ ] **Step 9: Run the web tests, vitest and both typecheckers**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_web_review.py --no-cov -p no:cacheprovider 2>&1 | tail -3
cd web && npm run typecheck && npm test 2>&1 | tail -5
```

`npm run typecheck`, not `tsc --noEmit`. Report the vitest summary line.

- [ ] **Step 10: Full gate sweep, then commit**

```bash
git commit -S -- lemely/db/review_repo.py lemely/web/schemas_review.py lemely/web/routers/review.py web/src/lib/teacherTypes.ts tests/test_review_repo.py tests/test_web_review.py
```

Message must state: a flag rather than coordinates and why, and that `ReviewItemDetailDTO`'s docstring no longer denies that crops exist.

---

## HUMAN GATE — disclosure, before Task 4: CLEARED 2026-09-24

**Ruling: the existing public disclosure already covers this. All five tasks proceed. No page edit is required, and none is to be made.**

The gate existed because Task 4 serves a teacher a cropped region of a student's uploaded script, and `Upload`'s class docstring (`lemely/db/models/attempts.py:34-42`) states: *"The public 'How Lemely handles your data' page cites this model for what an upload row keeps, so a change to that list is a change to a disclosure."*

The page is `web/src/portals/marketing/dataHandling.ts`. Two of its panels bear on this, quoted as they stand:

- **"The papers you upload"** — *"A scan is kept as a file in Google Cloud Storage, along with its original filename, its type, its size and how many pages it has."* So retention is disclosed.
- **"Who else can see your work"** — *"A teacher can see the work of students in their own classes. When Lemely is unsure about a paper it marked, that paper is put in a queue for a teacher to look at."* So class-scoped teacher access to the work, and the review queue by name, are both disclosed.

The user ruled that wording sufficient: a crop of the scan is the student's work, the viewer is a class-scoped teacher, and the surface is the queue that sentence names. **Nothing new is retained** by this plan either — crops are rendered on demand from the scan already in `Upload.storage_path`, which is exactly why the spec rejected generating them at persist time.

**A second question was put separately and answered separately:** whether to add a clarifying sentence anyway, as accuracy work rather than as a gate. That file's convention is to state what is verifiably true and to rewrite panels when behaviour makes them stale — it did so once already when client error reporting shipped. The user ruled **leave the page as it is**. Recorded here so a later reader does not read the absence of a sentence as an oversight: it was considered and declined.

**One thing Task 4's implementer must NOT read into this.** The ruling clears the disclosure question. It does not relax the authorization requirement, which is Task 4's headline risk and unchanged: the crop route reuses the review item's own visibility rule through one guarded lookup, and its first test is the one proving a teacher from another school gets no image. "A teacher can see the work of students in **their own classes**" is the disclosure this ruling rests on; a route that served any teacher any student's scan would break the disclosure the user just relied on.

Related and pre-existing, not created here: `_visible_class_map` grants `Role.platform_admin` broader visibility than class scope (`lemely/db/review_repo.py:453`), and the page's "who else can see your work" panel does not mention administrators at all. That applies to the whole review queue today, not just crops, so it is out of this plan's scope — but it is the kind of gap worth an issue rather than silence.

---

## Task 4: The crop route

**Files:**
- Modify: `lemely/db/review_repo.py` — one guarded lookup returning the crop inputs
- Modify: `lemely/web/routers/review.py` — the route
- Test: `tests/test_web_review.py`, `tests/test_review_repo.py`

**Interfaces:**
- Consumes: Task 2's columns, Task 3's flag.
- Produces: `GET /api/teacher/review/{item_id}/crop` returning `image/png`, and `ReviewService.get_item_crop_source(caller_id, caller_role, item_id) -> tuple[str, SourceBox]` raising the same `ReviewNotFoundError` / `ReviewOwnershipError` pair `get_item` raises.

**Authorization is this task's headline risk.** The route serves an image of a student's script. It must reuse the review item's existing visibility rule — `_visible_class_map`, `_find_any_item`, `caller_id` / `caller_role`, and `ReviewOwnershipError`'s documented 403-versus-404 discipline — rather than implement its own. Image endpoints are where IDOR gets written, because they read as "just serve bytes".

That is why the lookup is a **repository method that applies the same guard**, and not "call `get_item` for authorization, then fetch the path separately". One guarded entry point cannot drift from itself.

**Follow `get_paper_preview` (`lemely/web/routers/teacher.py:940-1003`).** It is the same problem already solved once: `storage.download` behind a role guard, `StorageObjectNotFoundError` to 404, `page_count == 0` to 422, an unrenderable file to 422 with the reason logged, `Response(media_type="image/png")`, and `Cache-Control: private, max-age=3600`. Read it in full before writing this route. Do **not** call `rasterise_pdf_to_pages`: it renders every page of the document and this route needs one.

The documented behaviours, from the spec:

| Condition | Cause | Behaviour |
|---|---|---|
| `upload_id` is `NULL` | console paper, quiz, seeded data | 404, no scan exists |
| `source_box_*` are `NULL` | common case | 404; the DTO already told the client not to ask |
| caller cannot see the student | another school's teacher | whatever `ReviewOwnershipError` maps to today, never an image |
| item does not exist | bad id | `ReviewNotFoundError`'s status |
| `storage_path` object missing | GCS lifecycle, dev filesystem cleared | 404, with a distinguishable reason logged |
| `source_box_page` out of range | box captured against a different render, or the upload was replaced | 422, and without rasterising the whole document to find out |
| all good | | `image/png`, cached private |

- [ ] **Step 1: Write the failing authorization test FIRST**

Before any implementation. This ordering is deliberate: the first test written for an image route should be the one that proves it cannot be used to read another school's student's work.

Add to `tests/test_web_review.py`, reusing the fixtures that already prove the detail route's visibility rule (find them with `grep -n "OwnershipError\|another school\|403" tests/test_web_review.py`):

```python
def test_crop_route_refuses_a_caller_who_cannot_see_the_student(...):
    """An image endpoint is where IDOR gets written. This is the first test.

    The route must reuse the review item's own visibility rule, so a teacher
    from another school gets exactly what the detail route gives them and never
    an image, whatever the status code is.
    """
    # ... assert the response status matches what GET /api/teacher/review/{item_id}
    # returns for the same caller and item, and that the content type is NOT
    # image/png.
```

Assert the status by comparing against the detail route's status for the same caller and item, rather than hard-coding a number. If the two ever diverge, that is the bug this test exists to catch.

- [ ] **Step 2: Write the failing tests for each degradation row**

One test per row of the table above. For the `page` out of range row, also assert that the response is produced **without** rendering the document — check the page count first. Make that observable, for instance by pointing the storage backend at a document you can assert was not opened, or by asserting the reason logged. State in your report how you established it.

- [ ] **Step 3: Write the failing happy-path test**

```python
def test_crop_route_returns_a_png_of_the_boxed_region(...):
    """The happy path, asserting the image is real and correctly sized.

    Build a synthetic multi-page PDF in the test -- never a real student scan,
    the repo is PUBLIC -- with a distinctive mark inside the box's region, and
    assert the returned PNG's dimensions are consistent with the box's
    proportion of the page, not merely that some bytes came back.
    """
```

Assert dimensions, not just a 200 and a content type. A route that returns a blank or whole-page PNG would pass the weaker assertion.

- [ ] **Step 4: Write the failing test that page indices agree between renderers**

The box was captured against a pypdfium2 render (`rasterise_pdf_to_pages`, `EXTRACTION_DPI = 200.0`); the route renders with pymupdf. Coordinates are normalised 0-1000 so renderer and DPI do not matter, but **page order must**.

```python
def test_page_indices_agree_between_the_extractor_and_the_crop_renderer(...):
    """`source_box.page` is an index into the extractor's render; the crop route
    renders with a different library. Both are 0-based document order, so the
    indices coincide -- but that is an assumption two dependencies could break
    independently, and nothing else in the codebase would notice.
    """
    # ... render a synthetic 3-page PDF with a different distinctive mark on
    # each page, via rasterise_pdf_to_pages and via pymupdf's load_page, and
    # assert page N shows the same mark under both.
```

- [ ] **Step 5: Run them all and confirm they fail**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_web_review.py -k crop --no-cov -p no:cacheprovider
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_web_review.py -k page_indices_agree --no-cov -p no:cacheprovider
```

Expected: 404 from an unregistered route for the crop tests. The page-index test should be written so it can pass immediately if the assumption holds — if it passes on the first run, say so: it is a characterisation test, and that it never went red is the honest report, not a problem to hide.

- [ ] **Step 6: Add the guarded lookup**

In `lemely/db/review_repo.py`, beside `get_item`:

```python
    def get_item_crop_source(
        self, caller_id: uuid.UUID | str, caller_role: Role | str, item_id: uuid.UUID | str
    ) -> tuple[str, SourceBox]:
        """Return the stored object path and box for one review item's scan crop.

        Applies the SAME visibility rule as `get_item` -- `_visible_class_map`
        then `_find_any_item` -- rather than letting the crop route implement
        its own. An image endpoint that resolves its own authorization is where
        IDOR gets written, because it reads as "just serve bytes".

        Raises:
            ReviewNotFoundError: no such item; or the item has no upload; or the
                item has no persisted box. All three are "there is no image
                here" and are deliberately indistinguishable to the caller: a
                404 that varied by reason would let a caller probe which
                students have scans.
            ReviewOwnershipError: the item exists but its attempt's owner is not
                one of the caller's visible students (403).
        """
```

Implement it by mirroring `get_item`'s opening exactly: `visible = self._visible_class_map(caller_id, caller_role)`, then `self._find_any_item(session, item_id, visible, caller_id=caller_id, caller_role=caller_role)`, then read the upload's `storage_path` and the five columns from `qr`. Reconstruct a real `SourceBox` from the columns, so the validator runs once more on the way out.

Note the deliberate collapse in the docstring: three distinct absences map to one `ReviewNotFoundError`. A caller must not be able to tell "this student has no scan" from "this item does not exist". Log the distinguishable reason server-side.

- [ ] **Step 7: Add the route**

In `lemely/web/routers/review.py`, after `get_review_item` (`:258`):

```python
@router.get(
    "/{item_id}/crop",
    responses={200: {"content": {"image/png": {}}, "description": "The boxed region of the scan"}},
)
def get_review_item_crop(
    item_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ReviewService, Depends(get_review_service)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> Response:
    """Render the region of the student's scan this question's answer was read from.

    Question-level, not per mark point: marking is text-only, so the marker
    never sees the page and cannot attribute a region to one mark point. This
    answers "where did this answer come from".

    A `def` route, not `async def`: FastAPI runs a synchronous handler in its
    own worker thread, so the blocking `storage.download` needs no explicit
    `anyio.to_thread` wrap -- the same reasoning `get_paper_preview` records.

    Authorization comes from `ReviewService.get_item_crop_source`, which
    applies the review item's own visibility rule. This route does not resolve
    ownership itself.
    """
```

Body, following `get_paper_preview` and reusing the existing exception mapping:

1. `try: object_path, box = service.get_item_crop_source(...)` and `except ReviewError as exc: _raise_for(exc)`.
2. `storage.download(settings.storage.bucket, object_path)`, `StorageObjectNotFoundError` to 404 with the reason logged.
3. Open with pymupdf as `get_paper_preview` does. **Check `doc.page_count` against `box.page` before rendering anything** and raise 422 if out of range, so a stale box costs a bounds check and not a render.
4. Render only `doc.load_page(box.page)` at a chosen DPI. State the DPI in a comment with the reason, as `get_paper_preview` does for its 72.
5. Build a `RasterisedPage(index=box.page, width=pixmap.width, height=pixmap.height, png_bytes=png)` and call `crop_and_upscale(page, box.box)`. Reuse it; do not re-derive the arithmetic. It already handles the degenerate-rounding case, which is the kind of edge a second copy gets wrong.
6. Return `Response(content=..., media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})`. The stored scan never changes for an item id, so the crop is cacheable for the same reason the thumbnail is.

- [ ] **Step 8: Run every crop test, confirm they pass**

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/test_web_review.py tests/test_review_repo.py --no-cov -p no:cacheprovider 2>&1 | tail -3
```

- [ ] **Step 9: Prove the authorization test discriminates**

Replace `service.get_item_crop_source(...)` with an unguarded lookup that ignores `caller_id` and `caller_role`, and re-run the authorization test. It must FAIL, returning an image to a caller who may not see the student. Record that failure, then revert.

This is the single most important verification in this plan. An authorization test never observed failing is not evidence that the route is guarded.

- [ ] **Step 10: Full gate sweep, then commit**

```bash
git commit -S -- lemely/db/review_repo.py lemely/web/routers/review.py tests/test_review_repo.py tests/test_web_review.py
```

Message must state: authorization reuses the review item's visibility rule via one guarded lookup, the three absences deliberately collapse to one 404, and the route renders one page with pymupdf following `get_paper_preview` rather than rasterising the document.

---

## Task 5: Render the crop on the teacher review screen

**Files:**
- Modify: `web/src/portals/teacher/screens/ReviewItem.tsx` — the evidence card (`~:716-740`) and the banner
- Modify: `web/src/lib/teacherTypes.ts` — only if Task 3 left anything for this task
- Test: the vitest file covering `ReviewItem.tsx`, and `web/e2e/teacher-review.spec.ts` (created by Plan 1's Task 7)

**Interfaces:**
- Consumes: `hasSourceBox` from Task 3, and `GET /api/teacher/review/{item_id}/crop` from Task 4.
- Produces: no new backend surface.

**The banner has to change again, and correctly.** As committed at `e0717433` it reads, in full:

> "This screen does not display the original scan. What's below is Lemely's own transcription of the student's answer."

That is the whole sentence. **Do not reintroduce a clause about the mark scheme's wording.** An earlier draft of this task quoted a longer version claiming *"The mark scheme's own wording isn't stored anywhere in this product"* and instructed that the clause "stays true in both branches and must survive". That was wrong: the clause is **false** — `AnswerPoint.point` is "Exact text of the mark point, preserved from the source", snapshotted onto the non-nullable `question_result_points.point_text`, and rendered on this very screen as `point.pointText`. It was deleted in `e0717433` for exactly that reason, along with the same claim in two eyebrow labels, which now read only "Matched mark-scheme point identifiers".

What this task changes: when a crop renders, "this screen does not display the original scan" becomes false. So that clause is **conditional** — when `hasSourceBox` is true the screen does show a region of the scan and the copy must say so. The transcription sentence stays in both branches.

Get this right rather than approximately. This one sentence has now been wrong **twice already**: first claiming the scan is not stored when `Upload.storage_path` retains it, then claiming the scheme's wording is not stored when `point_text` holds it. If this task is careless it will be wrong a third time, claiming the scan is not displayed on a screen displaying it. Before you write any wording, check each clause against the code rather than against this plan's prose — this plan has been wrong about this sentence once already.

- [ ] **Step 1: Write the failing test for the crop affordance**

vitest is `environment: "node"` with no jsdom, by deliberate decision, so this suite tests source text. Write **anchored** assertions — an unanchored regex on this project once passed against a deliberately widened alias.

In the vitest file that covers `ReviewItem.tsx`, assert that the source contains a `hasSourceBox`-guarded image whose `src` is built from the crop route, and that the guard wraps the image rather than sitting elsewhere in the file. Then assert the conditional banner: both branches present, and the transcription sentence outside the conditional. Assert that no clause about the mark scheme's wording being stored has reappeared.

Be explicit in your report about what these assertions can and cannot prove. They cannot establish "renders" or "does not render". Step 4 is what establishes that.

- [ ] **Step 2: Run it, confirm it fails, then implement**

Render, inside the evidence card and guarded on `detail.hasSourceBox`:

- an `<img>` whose `src` is the crop route for this item id, with `alt` text describing it as the region of the student's scan this answer was read from, and `loading="lazy"` so a queue of items does not fetch every crop at once;
- a caption naming what it is, in the design system's existing caption style. The region is question-level: the caption must not imply it justifies a particular mark point.

Follow the component vocabulary already in the file. Do not introduce a lightbox, a zoom control, or a fallback placeholder image: none was asked for, and an affordance that appears when there is nothing to show is the exact defect `hasSourceBox` exists to prevent.

The image can still fail to load after `hasSourceBox` was true — the object may have expired between the detail request and the crop request. Handle that as absence, quietly. A broken-image icon on a teacher's screen is worse than no crop.

- [ ] **Step 3: Check the copy**

```bash
cd web && npm run check:copy
```

No em-dashes, no exclamation marks. Then `npm run typecheck` (not `tsc --noEmit`) and the vitest suite; report the summary line against the 197 files / 3422 tests baseline.

- [ ] **Step 4: Extend the Playwright spec, and prove it discriminates**

`web/e2e/teacher-review.spec.ts` exists from Plan 1's Task 7. Add:

1. a boxless question shows **no** crop affordance;
2. a box-bearing question shows the crop, and the image actually loads (assert the element's `naturalWidth` is greater than zero through `page.evaluate`, not merely that the element is present — an `<img>` with a 404 src is still in the DOM).

Plan 1's Task 6b seeded a verdict-bearing e2e scenario. It did **not** seed a `source_box`, so point 2 needs seed data that carries one. Extend `scripts/seed_e2e.py` in the same way Task 6b did: `CorrectedQuestion.source_box` is now a field, the seed constructs `CorrectedQuestion` directly, and Task 2 persists whatever it carries. The seeded upload must also resolve to a real stored object, or the crop route correctly 404s and point 2 tests nothing. Check what Task 6b's scenario does about `upload_id` and storage, and report it.

Then prove the spec discriminates: invert the `hasSourceBox` guard in the component so the affordance renders unconditionally, and confirm the boxless assertion goes RED while vitest stays green. That contrast is the deliverable — it is the whole reason a Playwright spec exists for this screen, since a source-text suite cannot tell rendered from not rendered. Revert afterwards.

- [ ] **Step 5: Full gate sweep, then commit**

```bash
git commit -S -- web/src/portals/teacher/screens/ReviewItem.tsx web/e2e/teacher-review.spec.ts scripts/seed_e2e.py <the vitest file>
```

Message must state: the banner's display clause is now conditional and why, and that the boxless assertion was observed going red with the guard inverted.

---

## Self-review of this plan

**Spec coverage.** Story E's five hops map to Tasks 1 (hops 1 and 2), 2 (hop 3), 4 (hop 4) and 3 (hop 5). Story F maps to Task 5. The Disclosure human gate sits between Tasks 3 and 4, which is the point the spec names — "must not proceed past the point of serving crops". The Enabling-the-flag gate belongs to Plan 1's story B and is not restated here. Every spec testing bullet for E has a step: `_flatten_answers` both branches (Task 1 Steps 1-2), NIT-B duplicate (Step 3), migration round trip with a raw non-ORM INSERT (Task 2 Step 3), crop route authorization first then each degradation then dimensions (Task 4 Steps 1-3), malformed box degrades to `NULL` with the attempt surviving (Task 2 Step 6). F's "a boxless point shows no crop affordance" is Task 5 Step 4.

**Placeholder scan.** No "TBD", no "add error handling", no "similar to Task N". Three places name a helper by shape rather than by name — the MCQ scheme helpers in Task 1 Step 8, the persist fixtures in Task 2 Step 6, the visibility fixtures in Task 4 Step 1 — each with the `grep` that finds the real one and an instruction not to invent a replacement. That is a deliberate instruction to check, not an unfilled blank: inventing a second fixture where one exists is how this branch grew eight formulations of one concept.

**Type consistency.** `source_box: SourceBox | None` on `CorrectedQuestion` (Task 1) → five `int | None` columns (Task 2) → `has_source_box: bool` (Task 3) → `hasSourceBox: boolean` (Task 3) → consumed in Task 5. `_source_box_columns` is named identically in Task 2 Steps 6 and 8. `get_item_crop_source` returns `tuple[str, SourceBox]` in Task 4's Interfaces and Step 6.

**Where this plan corrects the spec**, all five measured rather than argued: the function name; the dedup rule already being explicit and inherited structurally rather than restated; **nine** `CorrectedQuestion(` sites rather than four, which is why the field is set once at the assembly; the savepoint precedent not applying to a column on the attempt's own dependent row, so the guard is pure instead; and the web layer already rendering single pages with pymupdf via `get_paper_preview`, so no new entry point in `rasterise.py` is needed. The fifth changes the shape of Task 4 substantially: the spec budgeted for adding a single-page render, and the work is instead to follow a route that already exists.

**One thing I could not settle from the code, flagged rather than guessed.** Task 2 Step 4 asks the implementer to report whether the new migration test is picked up by whatever CI job runs `0041`'s, and whether it SKIPs without a real Postgres. If it silently skips in CI, the CHECK constraints — the whole reason for explicit columns over jsonb — are unverified on every run, and the plan's strongest claim rests on a test nobody executes. That is worth knowing before Task 2 is marked complete, not after.
