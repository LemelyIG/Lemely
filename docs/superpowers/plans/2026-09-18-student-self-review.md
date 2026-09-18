# Student Self-Review of Flagged Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a student self-mark each mark point of a marked question before the marker's verdict is revealed, apply the student's verdict where the marker was unsure (or where a lenient judge accepts written evidence), and surface the result on the paper-result screen — with every authority rule enforced server-side.

**Architecture:** A new `SelfReviewService` (`lemely/db/self_review_repo.py`) owns the two-step flow over the `question_result_points` / `question_result_revisions` tables spec 1 already created: a reveal-withholding GET and a one-pass POST that writes self-marks, consults a lenient Gemini judge for high-confidence challenges, appends a `student_selfmark` revision, recomputes totals through the existing recompute in `review_repo.py`, and auto-resolves the `low_confidence` queue row. The authority rule itself is a pure function in `lemely/core/self_review.py`. `QuestionResult.effective_marks` gains a student tier (teacher > student > AI). The React screen adds a `SelfReviewPanel` inside each question row, driven by a pure state machine in `web/src/lib/selfReview.ts`.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2 (`Mapped`/`mapped_column`), Pydantic v2, structlog, Gemini via `GeminiClient.generate_structured`, pytest + Postgres; React 19 + TypeScript, @tanstack/react-query, vitest (node env), Playwright.

**Specs:** `docs/superpowers/specs/2026-09-17-student-self-review-design.md` (this spec) and `docs/superpowers/specs/2026-09-17-per-question-marking-detail-design.md` (spec 1, shipped — every table and column below already exists).

## Scope check and recommended split

This spec crosses four subsystems. Each part below is independently shippable and testable, and **should land as its own PR in this order**; a reviewer can approve Part 1 without Part 3 existing. The tasks are numbered continuously so a single executor can also run them straight through.

| Part | Tasks | Ships | Depends on |
| --- | --- | --- | --- |
| 1. Backend core | 1–9 | Precedence, authority, service, routes, `questionResultId` on the complete frame. Feature works end-to-end over the API with `judge=None` (every high-confidence challenge lands in the teacher queue as `student_evidence_unjudged`). | — |
| 2. Lenient judge | 10–11 | The Gemini judge, its prompt, its config knob, and the accept-rate log line; wired into the service. | Part 1 |
| 3. Frontend | 12–15 | Types, state machine, hooks, `SelfReviewPanel`, `PaperResult` wiring from the live (post-correction) result. | Part 1 |
| 4. Reachability after refresh + E2E | 16–19 | `attemptId` on the history result, `GET /attempts/{id}/questions`, the history branch of `PaperResult` renders real rows, seed + Playwright. | Parts 1, 3 |
| 5. Study-plan misconception signal | 20 | Misconception counts by topic on the study-plan DTO and screen. | Part 1 |

**Why Part 4 exists.** The spec places the surface on `PaperResult.tsx`, which today renders per-question rows only from `location.state` set right after `/student/correct`. A refresh or a visit from the paper-history table hits `GET /student/result/{index}`, which is index-based over `HistoryStoreProtocol` and returns `theory=[]` — no rows, no attempt id. Without Part 4 the feature works exactly once, in the tab that marked the paper, and the spec's Playwright requirement cannot be met (the seed script persists attempts directly, never through the live SSE flow). Part 4 is the smallest change that makes the surface reachable after a refresh. It is reported to the lead as a scope addition the spec implies but does not state.

## Global Constraints

- Signed commits only: `git commit -S`. Conventional messages with scopes (`feat(db):`, `feat(web):`, `test(web):`, `refactor(db):`, `feat(io):`, `feat(ui):`).
- Run `PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files` and fix every failure before every commit. **The venv is at `/home/sico/Code/Lemely/.venv`, not `$PWD/.venv`** — this worktree has none. Without the PATH prefix `mypy` and `lint-imports` report "Executable not found".
- **Every `pytest` command ends with `--no-cov`.** The repo enforces a 70% global coverage gate that any single-file run fails on total coverage regardless of whether its tests passed.
- **Never run the full suite locally; CI does** (~5077 tests × Python 3.12/3.13/3.14, ~20 min). Run only the files a task touches.
- DB tests use the `pg_sessionmaker` fixture — a `sessionmaker[Session]`, **not** a `Session`. It creates and drops a throwaway database per test from `Base.metadata.create_all` (never Alembic) and skips when Postgres at `127.0.0.1:54322` is unreachable. It is defined per test module (`tests/test_student_correct.py`, `tests/test_attempt_repo.py`, `tests/test_review_repo.py` each carry their own copy); new DB test files copy the fixture verbatim as those files do. `_seed_user(pg_sessionmaker)` in `tests/test_student_correct.py` returns a user-id **string**; the one in `tests/test_review_repo.py` returns a `uuid.UUID`.
- **No migration.** `question_result_points.student_selfmark / student_selfmark_at / student_evidence / evidence_verdict`, `question_results.student_selfmark_marks / student_selfmarked_at`, `EvidenceVerdict`, `RevisionSource.student_selfmark` and `ReviewReason.student_evidence_unjudged` all exist (migration `0037_question_result_pts`, current Alembic head). No task adds a table, column or enum value; `tests/test_db_schema.py::EXPECTED_TABLES` is untouched.
- `_scheme()` lives in `tests/conftest.py`: one question `"1a"` (3 marks) with points `p1` (M, 1), `p2` (A, 1), `p3` (B, 1). Import it (`from tests.conftest import _scheme`); never write another.
- Symbol names, all verified: enum members on the core/loose side are UPPERCASE (`ConfidenceBand.HIGH`, `LooseSessionMonth.MAY_JUNE`, `SchemeFormat.POINT_BASED`, `QuestionType.RECALL`); DB enums are lowercase (`DBConfidenceBand.high`, `ReviewReason.low_confidence`, `ReviewStatus.open`, `RevisionSource.student_selfmark`, `EvidenceVerdict.accepted`). `Question` takes `type=`, not `question_type=`. `MarkSchemeMetadata` requires `subject` and `maximum_mark`. `AccuracyReport`'s field is `grade_prediction`. `ExamMetadata.session_month` is a `Literal["May/June", ...]` string.
- `tests/test_student_correct.py` has a `client` fixture yielding `(TestClient, student_id, upload_repo)` over a throwaway DB with Gemini mocked. Endpoint tests reuse it by importing the fixtures into the new module (`from tests.test_student_correct import client, corpus_repo, gemini_client, pg_sessionmaker, settings  # noqa: F401`) and add the one extra override they need on `api.app.dependency_overrides`. Do not build another harness.
- `awarded_marks` on `question_results` is **never mutated**. `lemely/eval` reads it. Every task that moves `effective_marks` asserts `awarded_marks` unchanged.
- Integrity flags (`plagiarism_flagged`, `ai_detection_flagged`) grant no authority and are never rendered to a student. No DTO in this plan carries them; no copy names them.
- Totals go through `recompute_attempt_totals` / `recompute_weakness_records` in `lemely/db/review_repo.py` (Task 3 extracts them from `ReviewService`); there is never a second implementation.
- The pre-submission GET payload contains no key whose name contains `awarded`, at any depth. Task 7 pins this with a recursive assertion.
- Frontend: `web/node_modules` is present in this worktree. Every frontend task runs `cd web && npm run typecheck && npm run lint` before committing; vitest runs a single file with `npx vitest run tests/unit/<file>.test.ts` (vitest is node-only — no jsdom, no component rendering; component behaviour is covered by Playwright).
- Migrations, if one were ever needed, are verified on a throwaway database via `LEMELY_DATABASE__URL`, never the developer's live Supabase container. This plan needs none.

---

## File Structure

| File | Part | Responsibility |
| --- | --- | --- |
| `lemely/db/models/attempts.py` | 1 | Modify. `effective_marks` gains the student tier; new `is_self_marked` property. |
| `lemely/db/attempt_repo.py` | 1 | Modify. Extract `is_marking_low_confidence(qr)` from `_persist` (the one definition of "low confidence"); add `question_result_ids(attempt_id)`. |
| `lemely/db/review_repo.py` | 1 | Modify. Extract `recompute_attempt_totals`, `recompute_weakness_records`, `boundaries_for` to module level; `ReviewService` delegates. |
| `lemely/core/self_review.py` | 1 | Create. Pure: `PointDecision`, `decide_point(...)`, `JudgeRequest`, `JudgeVerdict`, `EvidenceJudge` protocol. No I/O, no ORM. |
| `lemely/db/self_review_repo.py` | 1 | Create. `SelfReviewService` (get / submit), its errors and view dataclasses. Owns the transaction. |
| `lemely/web/schemas_student_self_review.py` | 1 | Create. Pending / revealed DTOs, submission DTO with input sanitisation. |
| `lemely/web/routers/student_self_review.py` | 1, 4 | Create. `GET`/`POST …/self-review`; Part 4 adds `GET /attempts/{id}/questions`. |
| `lemely/web/deps.py` | 1, 2 | Modify. `get_self_review_service`. |
| `lemely/web/app.py` | 1 | Modify. Mount the router. |
| `lemely/web/schemas.py` | 1 | Modify. `QuestionResultDTO.questionResultId`; `question_to_dto(..., question_result_id=)`. |
| `lemely/web/routers/student.py` | 1, 4 | Modify. Complete frame carries `questionResultId`; Part 4: `ResultDTO.attemptId`. |
| `lemely/io/prompts/self_review_judge.py` | 2 | Create. Versioned prompt for the lenient judge. |
| `lemely/io/evidence_judge.py` | 2 | Create. `GeminiEvidenceJudge` — one bounded call per challenged point, accept-rate log line. |
| `lemely/runtime/config.py` | 2 | Modify. `GeminiSettings.self_review_judge_model` + `model_for("self_review_judge")`. |
| `web/src/lib/selfReviewTypes.ts` | 3 | Create. Wire types mirroring the DTOs. |
| `web/src/lib/selfReview.ts` | 3 | Create. Pure draft/state-machine helpers (vitest-covered). |
| `web/src/lib/hooks/useSelfReviewApi.ts` | 3, 4 | Create. `useSelfReview`, `useSubmitSelfReview`; Part 4 adds `useAttemptQuestions`. |
| `web/src/portals/student/components/SelfReviewPanel.tsx` | 3 | Create. The panel rendered inside a `QuestionRow`. |
| `web/src/portals/student/screens/PaperResult.tsx` | 3, 4 | Modify. Pass `attemptId` + `questionResultId` into rows; Part 4: history branch renders real rows. |
| `web/src/portals/student/screens/CorrectPaper.tsx` | 3 | Modify. `attemptId` into the navigated live state. |
| `web/src/lib/studentTypes.ts` | 1, 3, 4 | Modify. `QuestionResult.questionResultId`, `Result.attemptId`. |
| `lemely/core/history.py`, `lemely/db/history_repo.py` | 4 | Modify. `PaperRecord.attempt_id` (optional), filled by `attempt_to_record`. |
| `lemely/web/schemas_student.py` | 4 | Modify. `ResultDTO.attemptId`. |
| `scripts/seed_e2e.py`, `web/e2e/seed.ts`, `web/e2e/seed-contract.spec.ts` | 4 | Modify. A point-based, low-confidence attempt for the `correctedPaper` student. |
| `web/e2e/self-review.spec.ts` | 4 | Create. End-to-end flow. |
| `lemely/db/study_plan_repo.py`, `lemely/web/schemas_study_plan.py`, `lemely/web/routers/study_plan.py`, `web/src/lib/studyPlanTypes.ts`, `web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx` | 5 | Modify. Misconception counts by topic. |
| Tests | all | `tests/test_effective_marks.py`, `tests/test_core_self_review.py`, `tests/test_self_review_repo.py`, `tests/test_student_self_review_web.py`, `tests/test_evidence_judge.py`, `tests/test_attempt_repo.py`, `tests/test_review_repo.py`, `tests/test_student_correct.py`, `tests/test_authz_matrix.py`, `tests/test_authz_matrix_complete.py`, `tests/test_config_new_tasks.py`, `tests/test_history_repo_parity.py`, `tests/test_web_student.py`, `tests/test_study_plan_repo.py`, `web/tests/unit/selfReview.test.ts`, `web/tests/unit/studyPlan.test.ts`. |

The authority rule is a pure function in `lemely.core` rather than inline in the service because it is the feature; it deserves a table test that needs no database. The service is its own module rather than a growth of `attempt_repo.py` (658 lines) or `review_repo.py` (1086 lines): it is the only writer of the self-mark columns and the only reader that withholds `awarded`.

## Decisions taken where the spec is silent (reported to the lead)

1. **A revision is appended on every submission**, not only on a mark change. The spec lists the revision under "On a mark change"; but a rejected judge verdict carries a reason the student must be able to see again, and `evidence_verdict` is an enum with no room for it. The revision's `points_snapshot` is the only existing place to keep the judge's reason without a new column, so the revision is written on every pass (`awarded_marks` = the question's `effective_marks` after the pass). An unchanged-marks revision is honest history: "the student self-marked, nothing moved".
2. **Downward self-marks on a high-confidence point go through the judge too** ("on the same terms", D6). The judge question is symmetric: "is the student's claim contradicted by their own recorded answer?"
3. **The queue row auto-resolves only on a mark change**, literally per "On a mark change, in one transaction: … the open `low_confidence` queue row resolved". Agreement on a low-confidence question leaves the row open — "Agreement does nothing beyond confirming it to the student".
4. **A granted change also recomputes `WeaknessRecord` rows** (through the existing `recompute_weakness_records`). The spec's "does not enter `WeaknessRecord`'s accuracy arithmetic" is about *misconceptions* (no change granted). A granted change moves `effective_marks`, which D5 says reaches every surface; leaving weakness rows stale would be the "corrected on one screen, stale on another" failure the teacher-override path already fixed.
5. **Student's marks are the AI's marks plus the tariffs of granted points (minus tariffs of granted downward points), clamped to `[0, maximum_marks]`** — a delta, not a re-sum of ticked tariffs. `is_alternative` / `is_optional` groups make a re-sum wrong (`QuestionResultPoint` docstring), and the delta honours "on the same terms" for both directions.
6. **Teacher override present at submission** (`qr.is_overridden`): self-marks and evidence are recorded, no judge call is made, no marks move, `teacher_settled=True` in the response. Precedence makes the outcome identical either way; skipping the judge saves a call whose answer cannot matter.
7. **Judge failure includes "no judge configured"** (`judge=None`, e.g. no Gemini key): every high-confidence challenge with evidence opens a `student_evidence_unjudged` row. That is what makes Part 1 shippable before Part 2.
8. **Misconception query** (Part 5): points where `student_selfmark = true`, `awarded = false`, and `evidence_verdict` is `NULL` or `rejected`. `not_required` and `accepted` both mean a change was granted.

---

# Part 1 — Backend core

### Task 1: `effective_marks` gains the student tier

**Files:**
- Modify: `lemely/db/models/attempts.py` (the `effective_marks` property, ~line 262)
- Test: `tests/test_effective_marks.py` (create)

**Interfaces:**
- Consumes: `QuestionResult.teacher_awarded_marks`, `.student_selfmark_marks`, `.awarded_marks` (all existing columns).
- Produces: `QuestionResult.effective_marks -> int` with precedence teacher > student > AI; `QuestionResult.is_self_marked -> bool` (`student_selfmarked_at is not None`). Tasks 4–5 and Part 5 read both.

- [ ] **Step 1: Write the failing test**

Create `tests/test_effective_marks.py`:

```python
"""``QuestionResult.effective_marks`` precedence: teacher > student > AI.

Pure ORM-object tests — no database. The property is the single accessor
every read surface uses (P3.4), so the precedence is pinned here in both
directions, including a student self-marking *downward* (spec D6).
"""

from __future__ import annotations

from datetime import UTC, datetime

from lemely.db.models.attempts import QuestionResult
from lemely.db.models.enums import ConfidenceBand, MarkerSource


def _qr(**overrides: object) -> QuestionResult:
    base: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 1,
        "maximum_marks": 3,
        "confidence_band": ConfidenceBand.high,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "marker_source": MarkerSource.ai,
    }
    base.update(overrides)
    return QuestionResult(**base)  # type: ignore[arg-type]


def test_ai_mark_when_nothing_else_is_recorded() -> None:
    assert _qr().effective_marks == 1


def test_student_selfmark_beats_ai() -> None:
    assert _qr(student_selfmark_marks=3).effective_marks == 3


def test_student_selfmark_downward_beats_ai() -> None:
    assert _qr(awarded_marks=2, student_selfmark_marks=0).effective_marks == 0


def test_teacher_beats_student_and_ai() -> None:
    assert _qr(student_selfmark_marks=3, teacher_awarded_marks=2).effective_marks == 2


def test_teacher_zero_still_beats_student() -> None:
    assert _qr(student_selfmark_marks=3, teacher_awarded_marks=0).effective_marks == 0


def test_student_zero_still_beats_ai() -> None:
    assert _qr(awarded_marks=2, student_selfmark_marks=0).effective_marks == 0


def test_awarded_marks_is_never_touched_by_the_accessor() -> None:
    qr = _qr(student_selfmark_marks=3, teacher_awarded_marks=2)
    assert qr.effective_marks == 2
    assert qr.awarded_marks == 1


def test_is_self_marked_reads_the_timestamp_not_the_marks() -> None:
    assert _qr().is_self_marked is False
    # A pass that changed nothing still counts as a pass (one pass per question).
    assert _qr(student_selfmarked_at=datetime.now(UTC)).is_self_marked is True
    assert _qr(student_selfmark_marks=3).is_self_marked is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_effective_marks.py -v --no-cov
```

Expected: `test_student_selfmark_beats_ai`, `test_student_selfmark_downward_beats_ai`, `test_student_zero_still_beats_ai` FAIL (`assert 1 == 3` etc.); `test_is_self_marked_reads_the_timestamp_not_the_marks` FAILS with `AttributeError: 'QuestionResult' object has no attribute 'is_self_marked'`.

- [ ] **Step 3: Change the accessor**

In `lemely/db/models/attempts.py`, replace the `effective_marks` property and add `is_self_marked` directly after it:

```python
    @property
    def effective_marks(self) -> int:
        """The mark that must reach every student-facing surface.

        Precedence: the teacher's override, else the student's self-mark, else
        the AI's ``awarded_marks`` unchanged. **The single accessor** — anything
        (a route, a DTO converter, a report) that needs "this question's mark"
        reads this, never ``awarded_marks`` directly, so a correction can never
        be shown on one screen and silently missing on another (P3.4).

        The student tier (spec 2026-09-17 self-review, D5) is an accepted
        trade-off, not an oversight: self-reported marks reach teacher class
        analytics (``quiz_results_repo``), placement (``placement_repo``) and
        the student's own grade. The alternative — a second accessor for
        teacher-facing surfaces — was rejected as two numbers for one question.
        ``student_selfmark_marks`` is only ever set where the marker was
        low-confidence or a lenient judge accepted the student's evidence;
        a self-mark that moved marks *down* (D6) is honoured on the same terms.
        """
        if self.teacher_awarded_marks is not None:
            return self.teacher_awarded_marks
        if self.student_selfmark_marks is not None:
            return self.student_selfmark_marks
        return self.awarded_marks

    @property
    def is_self_marked(self) -> bool:
        """Whether the student has completed their one self-review pass.

        Reads the timestamp, not the marks: a pass that agreed with the marker
        on every point sets ``student_selfmarked_at`` and leaves
        ``student_selfmark_marks`` NULL, and it still counts as the pass.
        """
        return self.student_selfmarked_at is not None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_effective_marks.py -v --no-cov
```

Expected: 8 passed.

- [ ] **Step 5: Run the existing override tests to prove nothing regressed**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_review_repo.py tests/test_teacher_review_total.py --no-cov -q
```

Expected: all passed (or skipped with "local Postgres not reachable" — if so, start the Supabase container and re-run; these must actually run).

- [ ] **Step 6: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/models/attempts.py tests/test_effective_marks.py
git commit -S -m "feat(db): effective_marks precedence teacher > student > AI"
```

---

### Task 2: One definition of "low confidence" — `is_marking_low_confidence`

**Files:**
- Modify: `lemely/db/attempt_repo.py` (`_persist` lines 374–384, module `__all__`)
- Test: `tests/test_attempt_repo.py` (append)

**Interfaces:**
- Consumes: `QuestionResult.needs_teacher_review`, `.plagiarism_flagged`, `.ai_detection_flagged`, `.confidence_score`; `REVIEW_CONFIDENCE_THRESHOLD`.
- Produces: `is_marking_low_confidence(qr: QuestionResult) -> bool` — exactly the condition under which `_persist` opens a `low_confidence` queue row. Task 5 uses it for authority.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_attempt_repo.py` (no database — these build `QuestionResult` objects in memory):

```python
# ── The one definition of "low confidence" (self-review spec, Authority) ──────


def _qr_for_authority(
    *,
    confidence_score: float,
    needs_review: bool,
    plagiarism: bool = False,
    ai_detection: bool = False,
) -> QuestionResult:
    return QuestionResult(
        question_id="1a",
        awarded_marks=1,
        maximum_marks=3,
        confidence_band=DBConfidenceBand.low if needs_review else DBConfidenceBand.high,
        confidence_score=confidence_score,
        needs_teacher_review=needs_review,
        marker_source=MarkerSource.ai,
        plagiarism_flagged=plagiarism,
        ai_detection_flagged=ai_detection,
    )


def test_low_confidence_score_is_low_confidence() -> None:
    assert is_marking_low_confidence(_qr_for_authority(confidence_score=0.55, needs_review=True))


def test_structural_review_flag_without_integrity_flags_is_low_confidence() -> None:
    # The D2.4 out-of-range / value-mismatch signal: high score, review forced.
    assert is_marking_low_confidence(_qr_for_authority(confidence_score=0.99, needs_review=True))


def test_integrity_only_flag_is_not_low_confidence() -> None:
    # Purely plagiarism/AI-flagged: review is needed, but not for a marking reason.
    assert not is_marking_low_confidence(
        _qr_for_authority(confidence_score=0.99, needs_review=True, plagiarism=True)
    )
    assert not is_marking_low_confidence(
        _qr_for_authority(confidence_score=0.99, needs_review=True, ai_detection=True)
    )


def test_low_score_with_integrity_flag_is_still_low_confidence() -> None:
    # The score is a marking-side signal in its own right; an integrity flag
    # on top does not launder it away.
    assert is_marking_low_confidence(
        _qr_for_authority(confidence_score=0.55, needs_review=True, plagiarism=True)
    )


def test_confident_unflagged_question_is_not_low_confidence() -> None:
    assert not is_marking_low_confidence(_qr_for_authority(confidence_score=0.95, needs_review=False))
```

Add `is_marking_low_confidence` to the existing import line `from lemely.db.attempt_repo import AttemptRepository, fill_correction_topics` in that file.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py -k "low_confidence or integrity_only or confident_unflagged" -v --no-cov
```

Expected: `ImportError: cannot import name 'is_marking_low_confidence'`.

- [ ] **Step 3: Extract the function and use it in `_persist`**

In `lemely/db/attempt_repo.py`, replace this block inside `_persist`:

```python
                marking_flagged = qr.needs_teacher_review and not (
                    cq.plagiarism_flagged or cq.ai_detection_flagged
                )
                if marking_flagged or qr.confidence_score < REVIEW_CONFIDENCE_THRESHOLD:
                    session.add(
```

with:

```python
                if is_marking_low_confidence(qr):
                    session.add(
```

(the `ReviewQueueItem(... reason=ReviewReason.low_confidence)` body and the comment above it stay as they are). Then add the function after `_weakest_confidence_band` (module level):

```python
def is_marking_low_confidence(qr: QuestionResult) -> bool:
    """Whether a question was flagged for a *marking* reason — the one definition.

    True when the marker's own score is below ``REVIEW_CONFIDENCE_THRESHOLD``
    or when review was forced by a marking-side structural signal (the D2.4
    out-of-range / value-mismatch flag) rather than *only* by an integrity
    check. This is exactly the condition under which :meth:`AttemptRepository._persist`
    opens a ``low_confidence`` review-queue row, and it is also the condition
    under which a student's self-mark carries authority (self-review spec,
    "Authority"). Both read this function so the two can never draw the line
    differently: a question flagged purely ``plagiarism_flag`` /
    ``ai_detection_flag`` is *not* low-confidence — integrity flags grant no
    authority and are never shown to a student.

    Reads the persisted ``QuestionResult`` columns, which
    :func:`_to_question_result` fills from the same ``CorrectedQuestion``
    fields ``_persist`` used to read directly — so calling this on a freshly
    built row inside ``_persist`` and on a loaded row months later gives the
    same answer.
    """
    marking_flagged = qr.needs_teacher_review and not (
        qr.plagiarism_flagged or qr.ai_detection_flagged
    )
    return marking_flagged or qr.confidence_score < REVIEW_CONFIDENCE_THRESHOLD
```

Update `__all__`:

```python
__all__ = [
    "REVIEW_CONFIDENCE_THRESHOLD",
    "AttemptRepository",
    "fill_correction_topics",
    "is_marking_low_confidence",
]
```

- [ ] **Step 4: Run the whole file**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py --no-cov -q
```

Expected: all passed. `test_review_queue_low_confidence_row_survives_alongside_integrity_flags` and `test_review_queue_includes_integrity_flag_rows` are the regression guards for the fan-out.

- [ ] **Step 5: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/attempt_repo.py tests/test_attempt_repo.py
git commit -S -m "refactor(db): extract is_marking_low_confidence from the review fan-out"
```

---

### Task 3: Extract the totals recompute to module level in `review_repo.py`

**Files:**
- Modify: `lemely/db/review_repo.py` (`_recompute_attempt_totals` :716, `_recompute_weakness_records` :754, `_boundaries_for` :814, `__all__`)
- Test: `tests/test_review_repo.py` (existing tests are the regression suite; one new delegation test)

**Interfaces:**
- Produces (module-level, `lemely/db/review_repo.py`):
  - `recompute_attempt_totals(session: Session, attempt: Attempt, results: Sequence[QuestionResult], *, boundary_store: GradeBoundaryStore) -> None`
  - `recompute_weakness_records(session: Session, attempt: Attempt, results: Sequence[QuestionResult]) -> None`
  - `boundaries_for(attempt: Attempt, boundary_store: GradeBoundaryStore) -> tuple[dict[str, float], BoundarySource]`
  - `ReviewService._recompute_attempt_totals` / `_recompute_weakness_records` / `_boundaries_for` keep their signatures and delegate. Task 5 calls the module-level pair.

- [ ] **Step 1: Write the failing delegation test**

Append to `tests/test_review_repo.py`:

```python
def test_module_level_recompute_is_what_the_service_uses(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    """The self-review path calls the module-level functions directly; the
    override path must run the *same* code, not a private copy. Both
    recompute a two-question attempt to the identical total."""
    from lemely.db.review_repo import recompute_attempt_totals, recompute_weakness_records
    from lemely.io.grade_boundaries import GradeBoundaryStore

    _teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [
            _question("1", awarded=2, maximum=2),
            _question("2", awarded=0, maximum=3, confidence_score=0.2, needs_review=True),
        ],
    )
    with pg_sessionmaker() as session, session.begin():
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        results = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).all()
        # Simulate a correction on "2" through the accessor's student tier.
        next(qr for qr in results if qr.question_id == "2").student_selfmark_marks = 3
        recompute_attempt_totals(session, attempt, results, boundary_store=GradeBoundaryStore())
        recompute_weakness_records(session, attempt, results)

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.awarded_marks == 5
        assert attempt.percentage == 100.0
        assert attempt.grade == "A"
        assert session.scalars(
            select(WeaknessRecord).where(WeaknessRecord.attempt_id == attempt_id)
        ).all() == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_review_repo.py -k module_level_recompute -v --no-cov
```

Expected: FAIL with `ImportError: cannot import name 'recompute_attempt_totals'`.

- [ ] **Step 3: Extract the three functions**

In `lemely/db/review_repo.py`, replace the bodies of the three private methods with delegations:

```python
    def _recompute_attempt_totals(
        self, session: Session, attempt: Attempt, results: Sequence[QuestionResult]
    ) -> None:
        """Delegates to :func:`recompute_attempt_totals` (see it for the contract)."""
        recompute_attempt_totals(session, attempt, results, boundary_store=self._boundaries)

    def _recompute_weakness_records(
        self, session: Session, attempt: Attempt, results: Sequence[QuestionResult]
    ) -> None:
        """Delegates to :func:`recompute_weakness_records`."""
        recompute_weakness_records(session, attempt, results)

    def _boundaries_for(self, attempt: Attempt) -> tuple[dict[str, float], BoundarySource]:
        """Delegates to :func:`boundaries_for`."""
        return boundaries_for(attempt, self._boundaries)
```

Then add the module-level functions immediately before `def _to_row(`, moving the original bodies and docstrings verbatim (only the `self._boundaries` / `self._boundaries_for(attempt)` references change):

```python
def recompute_attempt_totals(
    session: Session,
    attempt: Attempt,
    results: Sequence[QuestionResult],
    *,
    boundary_store: GradeBoundaryStore,
) -> None:
    """Recompute the attempt's stored total after a mark changed.

    Sums every question's ``effective_marks`` (teacher override, else student
    self-mark, else the AI mark) and re-grades it with the same deterministic
    boundary lookup the original grade used — see the module docstring.
    ``results`` is every :class:`QuestionResult` on this attempt, passed in
    (not re-queried) so the caller can share one fetch with
    :func:`recompute_weakness_records`.

    Module-level, not a method, because it has two callers with different
    tenancy — :meth:`ReviewService.resolve` (a teacher) and
    :meth:`lemely.db.self_review_repo.SelfReviewService.submit` (a student) —
    and the self-review spec's totals invariant is exactly that the two cannot
    round differently for the same marks. One implementation, not two.

    **The quiz guard (``docs/quiz-model.md`` §4.5, mandatory).** For
    ``attempt.origin == AttemptOrigin.quiz``, ``grade``/``predicted_grade``/
    ``boundary_source`` are left exactly as the marking path wrote them
    (NULL) and :func:`boundaries_for` is never even called.
    ``awarded_marks``/``percentage`` are still recomputed regardless of origin.
    """
    awarded = sum(qr.effective_marks for qr in results)
    maximum = attempt.maximum_marks
    percentage = round((awarded / maximum) * 100.0, 2) if maximum else 0.0
    attempt.awarded_marks = awarded
    attempt.percentage = percentage
    if attempt.origin != AttemptOrigin.quiz:
        boundaries, boundary_source = boundaries_for(attempt, boundary_store)
        grade = grade_for_percentage(percentage, boundaries)
        attempt.grade = grade
        attempt.predicted_grade = grade
        attempt.boundary_source = boundary_source
    session.flush()


def recompute_weakness_records(
    session: Session, attempt: Attempt, results: Sequence[QuestionResult]
) -> None:
    """Recompute this attempt's :class:`WeaknessRecord` rows after a mark changed.

    Re-groups every question's ``effective_marks`` with
    :func:`~lemely.core.analytics.group_weak_areas` — the identical
    topic-bucketing algorithm ``summarize_weaknesses`` used when this attempt
    was first persisted — and diffs the fresh set against what is currently
    stored, keyed by topic: an existing topic's numbers are updated in place,
    a newly-created loss gets a fresh row, and a topic whose lost marks
    dropped to zero is deleted outright (see module docstring).
    """
    items = [
        WeakAreaInput(
            question_id=qr.question_id,
            topic=qr.topic,
            awarded_marks=qr.effective_marks,
            maximum_marks=qr.maximum_marks,
        )
        for qr in results
    ]
    fresh_by_topic = {area.topic: area for area in group_weak_areas(items)}

    existing = session.scalars(
        select(WeaknessRecord).where(WeaknessRecord.attempt_id == attempt.id)
    ).all()
    existing_by_topic = {record.topic: record for record in existing}

    for topic, area in fresh_by_topic.items():
        record = existing_by_topic.pop(topic, None)
        if record is None:
            session.add(
                WeaknessRecord(
                    user_id=attempt.user_id,
                    attempt_id=attempt.id,
                    topic=area.topic,
                    lost_marks=area.lost_marks,
                    maximum_marks=area.maximum_marks,
                    accuracy=area.accuracy,
                    question_ids=list(area.question_ids),
                )
            )
        else:
            record.lost_marks = area.lost_marks
            record.maximum_marks = area.maximum_marks
            record.accuracy = area.accuracy
            record.question_ids = list(area.question_ids)

    for stale in existing_by_topic.values():
        session.delete(stale)
    session.flush()


def boundaries_for(
    attempt: Attempt, boundary_store: GradeBoundaryStore
) -> tuple[dict[str, float], BoundarySource]:
    """Re-derive the exact boundary map the original grade used.

    Pure function of the exam metadata already on ``attempt`` — deterministic,
    so this returns the identical boundaries the marking pipeline resolved at
    persist time. Falls back to the global default (logged, never raised) if
    the attempt's metadata cannot round-trip through
    :class:`~lemely.core.schemas.ExamMetadata`.
    """
    try:
        metadata = ExamMetadata(
            subject_code=attempt.subject_code or "",
            paper_number=attempt.paper_number or 1,
            paper_variant=attempt.paper_variant or 1,
            session_month=SESSION_MONTH_LABELS.get(attempt.session_month, "Specimen")
            if attempt.session_month is not None
            else "Specimen",
            session_year=attempt.session_year,
        )
        boundaries, source = boundary_store.resolve(metadata)
        return boundaries, BoundarySource(source)
    except (ValidationError, ValueError) as exc:
        log.warning(
            "review_boundary_resolution_failed", attempt_id=str(attempt.id), error=str(exc)
        )
        return (
            DEFAULT_GRADE_BOUNDARIES,
            attempt.boundary_source or BoundarySource.global_default,
        )
```

Add the three names to `__all__` (`"boundaries_for"`, `"recompute_attempt_totals"`, `"recompute_weakness_records"`, keeping the list sorted).

- [ ] **Step 4: Run the review-repo suite**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_review_repo.py tests/test_teacher_review_total.py tests/test_web_review.py --no-cov -q
```

Expected: all passed, including the new delegation test.

- [ ] **Step 5: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/review_repo.py tests/test_review_repo.py
git commit -S -m "refactor(db): lift the totals/weakness recompute to module level for a second caller"
```

---

### Task 4: The authority rule and the judge seam, pure (`lemely/core/self_review.py`)

**Files:**
- Create: `lemely/core/self_review.py`
- Test: `tests/test_core_self_review.py` (create)

**Interfaces:**
- Produces:
  - `PointDecision` (`StrEnum`): `AGREE`, `GRANT`, `JUDGE`, `NO_CHANGE`.
  - `decide_point(*, ai_awarded: bool, student_earned: bool, low_confidence: bool, has_evidence: bool) -> PointDecision`.
  - `JudgeRequest` (frozen dataclass): `subject_code: str`, `question_id: str`, `point_text: str`, `mark_type: str | None`, `tariff: int`, `student_answer: str | None`, `marker_rationale: str | None`, `student_claims_earned: bool`, `student_evidence: str`.
  - `JudgeVerdict` (frozen dataclass): `accepted: bool`, `reason: str`.
  - `EvidenceJudge` (Protocol): `judge(self, request: JudgeRequest) -> JudgeVerdict`.
  - Task 6 calls `decide_point`; Tasks 6–7 use the dataclasses; Task 10 implements the protocol.

- [ ] **Step 1: Write the failing table test**

Create `tests/test_core_self_review.py`:

```python
"""The self-review authority rule (spec 2026-09-17 self-review, "Authority").

Pure table test over every cell: flag state x direction x evidence. The rule
is the feature, so every cell is named — a cell nobody checked is a cell
nobody can defend.
"""

from __future__ import annotations

import pytest

from lemely.core.self_review import PointDecision, decide_point


@pytest.mark.parametrize(
    ("ai_awarded", "student_earned", "low_confidence", "has_evidence", "expected"),
    [
        # Agreement does nothing, whatever else is true.
        (True, True, True, True, PointDecision.AGREE),
        (True, True, False, False, PointDecision.AGREE),
        (False, False, True, False, PointDecision.AGREE),
        (False, False, False, True, PointDecision.AGREE),
        # Low confidence: the student wins outright, evidence optional (D2).
        (False, True, True, False, PointDecision.GRANT),
        (False, True, True, True, PointDecision.GRANT),
        # ...and downward on the same terms (D6).
        (True, False, True, False, PointDecision.GRANT),
        (True, False, True, True, PointDecision.GRANT),
        # High confidence: evidence unlocks the judge (D3); no evidence, no change.
        (False, True, False, True, PointDecision.JUDGE),
        (True, False, False, True, PointDecision.JUDGE),
        (False, True, False, False, PointDecision.NO_CHANGE),
        (True, False, False, False, PointDecision.NO_CHANGE),
    ],
)
def test_decide_point(
    ai_awarded: bool,
    student_earned: bool,
    low_confidence: bool,
    has_evidence: bool,
    expected: PointDecision,
) -> None:
    assert (
        decide_point(
            ai_awarded=ai_awarded,
            student_earned=student_earned,
            low_confidence=low_confidence,
            has_evidence=has_evidence,
        )
        is expected
    )


def test_every_combination_is_decided() -> None:
    """The four booleans give 16 inputs; none may raise or return None."""
    for ai in (True, False):
        for student in (True, False):
            for low in (True, False):
                for evidence in (True, False):
                    decision = decide_point(
                        ai_awarded=ai,
                        student_earned=student,
                        low_confidence=low,
                        has_evidence=evidence,
                    )
                    assert isinstance(decision, PointDecision)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_core_self_review.py -v --no-cov
```

Expected: `ModuleNotFoundError: No module named 'lemely.core.self_review'`.

- [ ] **Step 3: Write the module**

Create `lemely/core/self_review.py`:

```python
"""Student self-review: the authority rule and the judge seam, both pure.

The rule (spec 2026-09-17 self-review, "Authority"), per mark point where the
student and the marker disagree:

* the question is **low-confidence** (the marker said it was unsure) — the
  student's verdict is applied outright, evidence optional (D2), in either
  direction (D6);
* otherwise the student must have **written evidence**, and a lenient judge
  decides (D3); a bare disagreement with no evidence is recorded as a
  misconception signal and changes nothing.

"Low-confidence" is decided by the caller with
:func:`lemely.db.attempt_repo.is_marking_low_confidence` — the same function
that opens the ``low_confidence`` review-queue row — so an integrity-only flag
(plagiarism / AI detection) never reaches here as ``low_confidence=True``.
Integrity flags grant no authority.

This module has no I/O and imports nothing outside the standard library, so
the rule is table-tested without a database
(``tests/test_core_self_review.py``). The judge itself lives in
:mod:`lemely.io.evidence_judge`; this module only defines what a judge is
asked and what it answers, so the service can be tested with a scripted one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class PointDecision(StrEnum):
    """What to do with one mark point after the student's verdict arrives."""

    AGREE = "agree"
    """Student and marker concur. Nothing to apply; the agreement is confirmed."""
    GRANT = "grant"
    """Low-confidence question: the student's verdict is applied as-is."""
    JUDGE = "judge"
    """High-confidence question with evidence: ask the lenient judge."""
    NO_CHANGE = "no_change"
    """High-confidence question, no evidence: recorded, not applied."""


def decide_point(
    *,
    ai_awarded: bool,
    student_earned: bool,
    low_confidence: bool,
    has_evidence: bool,
) -> PointDecision:
    """The authority rule for one point. Pure; see the module docstring."""
    if ai_awarded == student_earned:
        return PointDecision.AGREE
    if low_confidence:
        return PointDecision.GRANT
    if has_evidence:
        return PointDecision.JUDGE
    return PointDecision.NO_CHANGE


@dataclass(frozen=True, slots=True)
class JudgeRequest:
    """Everything the lenient judge is given for one challenged point.

    ``student_answer`` is the transcribed answer the marker saw;
    ``marker_rationale`` is the marker's own reason for the verdict (the
    per-point ``rationale`` when a marker emitted one, else the question's
    ``rationale``, else its student-facing ``feedback``). ``student_claims_earned``
    says which direction the challenge runs — a student may also argue they
    did *not* earn a point the marker awarded (D6).
    """

    subject_code: str
    question_id: str
    point_text: str
    mark_type: str | None
    tariff: int
    student_answer: str | None
    marker_rationale: str | None
    student_claims_earned: bool
    student_evidence: str


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """Accept or reject, plus the short reason the student is shown."""

    accepted: bool
    reason: str


class EvidenceJudge(Protocol):
    """The seam :class:`lemely.db.self_review_repo.SelfReviewService` calls.

    Any exception raised by :meth:`judge` is a judge *failure*, which the
    service turns into a ``student_evidence_unjudged`` review-queue row —
    never a silent accept or reject.
    """

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        """Decide one challenged point."""
        ...


__all__ = [
    "EvidenceJudge",
    "JudgeRequest",
    "JudgeVerdict",
    "PointDecision",
    "decide_point",
]
```

- [ ] **Step 4: Run the tests**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_core_self_review.py -v --no-cov
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/core/self_review.py tests/test_core_self_review.py
git commit -S -m "feat(core): self-review authority rule and judge seam"
```

---

### Task 5: `SelfReviewService.get` — ownership, absence, and the reveal-withholding view

**Files:**
- Create: `lemely/db/self_review_repo.py`
- Test: `tests/test_self_review_repo.py` (create)

**Interfaces:**
- Consumes: `is_marking_low_confidence` (Task 2), `QuestionResult.is_self_marked` / `.effective_marks` (Task 1), `recompute_attempt_totals` / `recompute_weakness_records` (Task 3, used in Task 6), `JudgeRequest`/`JudgeVerdict`/`PointDecision`/`decide_point` (Task 4).
- Produces (all in `lemely/db/self_review_repo.py`):
  - Errors: `SelfReviewError`, `SelfReviewNotFoundError` (→ 404), `SelfReviewAlreadySubmittedError` (→ 409), `SelfReviewValidationError` (→ 422).
  - `PointVerdict(mark_point_id: str, earned: bool, evidence: str | None = None)`.
  - `PendingPoint(mark_point_id, ordinal, mark_type, tariff, point_text)` — **no `awarded` field exists on this class.**
  - `RevealedPoint(mark_point_id, ordinal, mark_type, tariff, point_text, awarded: bool, student_selfmark: bool, student_evidence: str | None, evidence_verdict: str | None, mark_changed: bool, judge_reason: str | None)`.
  - `PendingSelfReview(state: Literal["not_started"], attempt_id: uuid.UUID, question_result_id: uuid.UUID, question_id: str, maximum_marks: int, evidence_required: bool, points: list[PendingPoint])`.
  - `RevealedSelfReview(state: Literal["revealed", "settled"], attempt_id, question_result_id, question_id, maximum_marks, evidence_required, ai_marks: int, effective_marks: int, student_marks: int | None, teacher_settled: bool, pending_teacher: bool, submitted_at: datetime, points: list[RevealedPoint])`.
  - `SelfReviewService(sessionmaker, *, judge: EvidenceJudge | None, boundary_store: GradeBoundaryStore | None = None)` with `get(student_id, attempt_id, question_result_id) -> PendingSelfReview | RevealedSelfReview` (this task) and `submit(student_id, attempt_id, question_result_id, verdicts: Sequence[PointVerdict]) -> RevealedSelfReview` (Task 6).
  - Constants `SELFMARK_RESOLUTION_NOTE = "Resolved by student self-mark"`, `MAX_EVIDENCE_CHARS = 2000`, `MAX_JUDGE_REASON_CHARS = 500`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_self_review_repo.py`. The fixture block mirrors `tests/test_review_repo.py` exactly; the scheme has two point-based questions so a low-confidence and a high-confidence question can coexist on one attempt.

```python
"""``SelfReviewService`` (self-review spec, 2026-09-17) against real Postgres.

Same throwaway-database fixture as ``tests/test_review_repo.py``. The scheme
is two point-based questions: "1" (2 marks, p1/p2) and "2" (3 marks,
p1/p2/p3); each test chooses the confidence of each question.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.analytics import summarize_weaknesses
from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    PaperType,
    SchemeFormat,
)
from lemely.core.loose_schemas import Question as SchemeQuestion
from lemely.core.loose_schemas import QuestionType as SchemeQuestionType
from lemely.core.loose_schemas import SessionMonth as LooseSessionMonth
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
)
from lemely.core.self_review import JudgeRequest, JudgeVerdict
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import ReviewReason, ReviewStatus, RevisionSource, Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.self_review_repo import (
    SELFMARK_RESOLUTION_NOTE,
    PendingPoint,
    PendingSelfReview,
    PointVerdict,
    RevealedSelfReview,
    SelfReviewAlreadySubmittedError,
    SelfReviewNotFoundError,
    SelfReviewService,
    SelfReviewValidationError,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


# ── Fixtures: a two-question point-based scheme and a report against it ───────


def _scheme() -> MarkScheme:
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=1,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2020,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=5,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            SchemeQuestion(
                id="1",
                marks=2,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="States the law", marks=1),
                    AnswerPoint(id="p2", point="Gives the unit", marks=1),
                ],
            ),
            SchemeQuestion(
                id="2",
                marks=3,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="Correct method", marks=1),
                    AnswerPoint(id="p2", point="Correct substitution", marks=1),
                    AnswerPoint(id="p3", point="Answer awarded to 2 sf", marks=1),
                ],
            ),
        ],
    )


def _question(
    question_id: str,
    *,
    matched: list[str],
    maximum: int,
    confidence_score: float = 0.95,
    needs_review: bool = False,
    plagiarism_flagged: bool = False,
    ai_detection_flagged: bool = False,
) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=question_id,
        awarded_marks=len(matched),
        maximum_marks=maximum,
        confidence=ConfidenceBand.LOW if needs_review else ConfidenceBand.HIGH,
        confidence_score=confidence_score,
        needs_teacher_review=needs_review,
        student_answer=f"answer-{question_id}",
        expected_answer=f"expected-{question_id}",
        topic="Waves",
        marker_source="ai",
        feedback="Method not shown.",
        plagiarism_flagged=plagiarism_flagged,
        ai_detection_flagged=ai_detection_flagged,
        matched_point_ids=matched,
    )


def _low(question_id: str = "2", *, matched: list[str] | None = None) -> CorrectedQuestion:
    """Question "2" (3 marks) at confidence 0.2 — low-confidence."""
    return _question(
        question_id, matched=matched or [], maximum=3, confidence_score=0.2, needs_review=True
    )


def _high(question_id: str = "1", *, matched: list[str] | None = None) -> CorrectedQuestion:
    """Question "1" (2 marks) at confidence 0.95 — high-confidence."""
    return _question(question_id, matched=matched if matched is not None else ["p1"], maximum=2)


def _report(questions: list[CorrectedQuestion]) -> AccuracyReport:
    # subject_code "9999" matches no bundled boundary data, so grades resolve
    # against DEFAULT_GRADE_BOUNDARIES deterministically (as test_review_repo).
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="9999",
            paper_number=1,
            paper_variant=1,
            session_month="May/June",
            session_year=2020,
        ),
        questions=questions,
    )
    awarded, maximum = correction.awarded_marks, correction.maximum_marks
    pct = round((awarded / maximum) * 100.0, 2) if maximum else 0.0
    return AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=GradePrediction(
            awarded_marks=awarded,
            maximum_marks=maximum,
            percentage=pct,
            grade="U",
            confidence=ConfidenceBand.LOW,
            needs_teacher_review=correction.needs_teacher_review,
            boundary_source="global_default",
        ),
    )


def _seed_attempt(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    questions: list[CorrectedQuestion],
    *,
    with_scheme: bool = True,
) -> uuid.UUID:
    return AttemptRepository(sm).persist_correction(
        user_id=str(student),
        report=_report(questions),
        mark_scheme=_scheme() if with_scheme else None,
    )


def _qr_id(sm: sessionmaker[Session], attempt_id: uuid.UUID, question_id: str) -> uuid.UUID:
    with sm() as session:
        return session.scalars(
            select(QuestionResult.id).where(
                QuestionResult.attempt_id == attempt_id, QuestionResult.question_id == question_id
            )
        ).one()


def _load_qr(sm: sessionmaker[Session], qr_id: uuid.UUID) -> QuestionResult:
    with sm() as session:
        qr = session.get(QuestionResult, qr_id)
        assert qr is not None
        _ = qr.points, qr.revisions  # load before the session closes
        return qr


def _queue_rows(sm: sessionmaker[Session], qr_id: uuid.UUID) -> list[ReviewQueueItem]:
    with sm() as session:
        return list(
            session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.question_result_id == qr_id)
            ).all()
        )


def _service(sm: sessionmaker[Session], judge: object | None = None) -> SelfReviewService:
    return SelfReviewService(sm, judge=judge)  # type: ignore[arg-type]


def _all_earned(point_ids: list[str], evidence: str | None = None) -> list[PointVerdict]:
    return [PointVerdict(mark_point_id=pid, earned=True, evidence=evidence) for pid in point_ids]


# ── get ────────────────────────────────────────────────────────────────────


def test_get_before_submission_is_pending_and_carries_no_verdict(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    view = _service(pg_sessionmaker).get(student, attempt_id, qr_id)

    assert isinstance(view, PendingSelfReview)
    assert view.state == "not_started"
    assert view.question_id == "2"
    assert view.maximum_marks == 3
    assert view.evidence_required is False  # low-confidence: the student wins
    assert [p.mark_point_id for p in view.points] == ["p1", "p2", "p3"]
    assert [p.tariff for p in view.points] == [1, 1, 1]
    assert view.points[0].point_text == "Correct method"
    # The reveal is server-enforced: the pending point type has no such field.
    assert "awarded" not in {f.name for f in dataclasses.fields(PendingPoint)}
    assert not any("awarded" in f.name for f in dataclasses.fields(PendingSelfReview))


def test_get_reports_evidence_required_on_a_high_confidence_question(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    view = _service(pg_sessionmaker).get(student, attempt_id, _qr_id(pg_sessionmaker, attempt_id, "1"))
    assert view.evidence_required is True


def test_get_treats_an_integrity_only_flag_as_high_confidence(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Integrity flags grant no authority — and nothing in the view says why."""
    student = _seed_user(pg_sessionmaker)
    flagged = _question("1", matched=["p1"], maximum=2, needs_review=True, plagiarism_flagged=True)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [flagged, _low()])
    view = _service(pg_sessionmaker).get(student, attempt_id, _qr_id(pg_sessionmaker, attempt_id, "1"))
    assert view.evidence_required is True
    assert not any("plagiar" in f.name or "integrity" in f.name for f in dataclasses.fields(view))


def test_get_unknown_attempt_is_not_found(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(student, uuid.uuid4(), uuid.uuid4())


def test_get_malformed_ids_are_not_found_not_a_500(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(student, "not-a-uuid", "also-not")


def test_get_another_students_attempt_is_not_found(pg_sessionmaker: sessionmaker[Session]) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, owner, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(other, attempt_id, qr_id)


def test_get_question_from_a_different_attempt_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A question id that exists, on an attempt the caller owns, but not on
    the attempt named in the path — must not resolve by question id alone."""
    student = _seed_user(pg_sessionmaker)
    first = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    second = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_on_second = _qr_id(pg_sessionmaker, second, "2")
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(student, first, qr_on_second)


def test_get_without_point_rows_is_not_found(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A quiz, or a paper corrected before spec 1 shipped: the surface is
    absent, derived from the absence of rows, not from a flag."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()], with_scheme=False)
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).get(student, attempt_id, _qr_id(pg_sessionmaker, attempt_id, "2"))
```

`datetime`, `UTC`, `JudgeRequest`, `JudgeVerdict`, `Attempt`, `ReviewReason`, `ReviewStatus`, `RevisionSource`, `SELFMARK_RESOLUTION_NOTE`, `RevealedSelfReview`, `SelfReviewAlreadySubmittedError`, `SelfReviewValidationError`, `_load_qr`, `_queue_rows` and `_all_earned` are used by Tasks 6–7's tests in this same file. Ruff will flag the unused imports at this commit: add `# noqa: F401` on those import lines for now and remove it in Task 6.

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_self_review_repo.py -v --no-cov
```

Expected: `ModuleNotFoundError: No module named 'lemely.db.self_review_repo'`.

- [ ] **Step 3: Write the service module with `get` (and a `submit` stub that Task 6 fills)**

Create `lemely/db/self_review_repo.py`:

```python
"""Student self-review of marked questions (spec 2026-09-17 self-review).

The one writer of ``question_result_points.student_selfmark*`` /
``evidence_verdict`` and ``question_results.student_selfmark_marks`` /
``student_selfmarked_at``, and the one reader that **withholds the marker's
verdict** until the student has committed to their own.

**The reveal is server-enforced.** :meth:`SelfReviewService.get` returns a
:class:`PendingSelfReview` before submission, whose point type
(:class:`PendingPoint`) has no ``awarded`` attribute at all — not a nulled one.
The verdict exists only on :class:`RevealedPoint`, which is only ever built
after ``student_selfmarked_at`` is set. A client cannot read a field the
payload does not contain.

**Authority** is :func:`lemely.core.self_review.decide_point`, fed by
:func:`lemely.db.attempt_repo.is_marking_low_confidence` — the same function
that opened the ``low_confidence`` review-queue row at correction time, so
"the marker was unsure" means one thing across both paths. Integrity flags
never reach the rule.

**One transaction.** Point rows, ``student_selfmark_marks``, the
``student_selfmark`` revision, the totals/weakness recompute (the module-level
functions in :mod:`lemely.db.review_repo` — the same code the teacher-override
path runs, so identical marks can never round differently) and the
``low_confidence`` queue auto-resolve all commit together or not at all. The
``QuestionResult`` row is locked ``FOR UPDATE`` for the pass, which is what
turns a racing second POST into a 409 rather than a second self-mark.

**Judge failure is never a decision.** ``judge=None`` (no Gemini key), an
exception, or a malformed answer all leave ``evidence_verdict`` NULL, move no
marks, and open a ``student_evidence_unjudged`` queue row so a teacher looks.

**A revision is appended on every pass**, not only when marks moved: the
judge's reason for a *rejected* claim has no column of its own and the
student must be able to read it again, so it lives in the revision's
``points_snapshot``. An unchanged-marks revision is honest history.

**Marks move by delta**, not by re-summing ticked tariffs: ``awarded_marks``
plus the tariff of every granted upward point minus every granted downward
one, clamped to ``[0, maximum_marks]``. ``is_alternative``/``is_optional``
groups make a re-sum wrong (see ``QuestionResultPoint``), and a delta honours
"on the same terms" in both directions (D6). ``awarded_marks`` itself is never
written — ``lemely/eval`` reads it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import structlog
from sqlalchemy import func, select

from lemely.core.self_review import JudgeRequest, JudgeVerdict, PointDecision, decide_point
from lemely.db.attempt_repo import is_marking_low_confidence
from lemely.db.models.attempts import (
    Attempt,
    QuestionResult,
    QuestionResultPoint,
    QuestionResultRevision,
)
from lemely.db.models.enums import EvidenceVerdict, ReviewReason, ReviewStatus, RevisionSource
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import recompute_attempt_totals, recompute_weakness_records
from lemely.io.grade_boundaries import GradeBoundaryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.self_review import EvidenceJudge

log = structlog.get_logger(__name__)

#: Written to ``review_queue.resolution_note`` when a self-mark closes a
#: ``low_confidence`` row (D4). Provenance proper lives in the revision's
#: ``source``; this is the human-readable trace on the queue row.
SELFMARK_RESOLUTION_NOTE = "Resolved by student self-mark"
#: Upper bound on stored evidence; the DTO layer enforces the same figure.
MAX_EVIDENCE_CHARS = 2000
#: Upper bound on a judge's stored reason (LLM output: bounded before it
#: reaches JSONB).
MAX_JUDGE_REASON_CHARS = 500


class SelfReviewError(Exception):
    """Base class for self-review failures."""


class SelfReviewNotFoundError(SelfReviewError):
    """The attempt/question is not the caller's, does not exist, or has no point rows (→ 404)."""


class SelfReviewAlreadySubmittedError(SelfReviewError):
    """The student has already completed their one pass on this question (→ 409)."""


class SelfReviewValidationError(SelfReviewError):
    """The submission is not a complete, well-formed set of verdicts (→ 422)."""


@dataclass(frozen=True, slots=True)
class PointVerdict:
    """One point of a student's submission."""

    mark_point_id: str
    earned: bool
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class PendingPoint:
    """A mark point before the reveal. Deliberately has no ``awarded``."""

    mark_point_id: str
    ordinal: int
    mark_type: str | None
    tariff: int
    point_text: str


@dataclass(frozen=True, slots=True)
class RevealedPoint:
    """A mark point after the reveal: the marker's verdict beside the student's."""

    mark_point_id: str
    ordinal: int
    mark_type: str | None
    tariff: int
    point_text: str
    awarded: bool
    student_selfmark: bool
    student_evidence: str | None
    evidence_verdict: str | None
    mark_changed: bool
    judge_reason: str | None


@dataclass(frozen=True, slots=True)
class PendingSelfReview:
    """``GET`` before submission. No verdict anywhere in it."""

    state: Literal["not_started"]
    attempt_id: uuid.UUID
    question_result_id: uuid.UUID
    question_id: str
    maximum_marks: int
    evidence_required: bool
    points: list[PendingPoint]


@dataclass(frozen=True, slots=True)
class RevealedSelfReview:
    """``GET`` after submission, and the ``POST`` response.

    ``revealed`` means a teacher still has to look (a judge failure opened a
    ``student_evidence_unjudged`` row that is still open); ``settled`` means
    nothing is pending. ``teacher_settled`` says a teacher override already
    decides this question's mark, so the self-mark was recorded without
    moving anything.
    """

    state: Literal["revealed", "settled"]
    attempt_id: uuid.UUID
    question_result_id: uuid.UUID
    question_id: str
    maximum_marks: int
    evidence_required: bool
    ai_marks: int
    effective_marks: int
    student_marks: int | None
    teacher_settled: bool
    pending_teacher: bool
    submitted_at: datetime
    points: list[RevealedPoint]


class SelfReviewService:
    """Get and submit a student's self-review of one marked question."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        judge: EvidenceJudge | None,
        boundary_store: GradeBoundaryStore | None = None,
    ) -> None:
        """``judge=None`` means every judged claim is a judge *failure* (see module docstring)."""
        self._sessionmaker = sessionmaker
        self._judge = judge
        self._boundaries = boundary_store or GradeBoundaryStore()

    def get(
        self,
        student_id: uuid.UUID | str,
        attempt_id: uuid.UUID | str,
        question_result_id: uuid.UUID | str,
    ) -> PendingSelfReview | RevealedSelfReview:
        """The self-review state of one question, for its owner only.

        Raises:
            SelfReviewNotFoundError: not the caller's attempt, no such question
                on that attempt, malformed ids, or no point rows (404 — never
                a 403, matching the other student routes).
        """
        student_uuid = _as_uuid(student_id)
        attempt_uuid = _as_uuid(attempt_id)
        qr_uuid = _as_uuid(question_result_id)
        with self._sessionmaker() as session:
            _attempt, qr = _owned_question(
                session, student_uuid, attempt_uuid, qr_uuid, for_update=False
            )
            return _to_view(session, qr)

    def submit(
        self,
        student_id: uuid.UUID | str,
        attempt_id: uuid.UUID | str,
        question_result_id: uuid.UUID | str,
        verdicts: Sequence[PointVerdict],
    ) -> RevealedSelfReview:
        """Record the student's one self-mark pass and reveal the marker's verdict."""
        raise NotImplementedError  # Task 6


# ── Internals ────────────────────────────────────────────────────────────────


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce to UUID; a malformed id is a 404, like every other student route."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise SelfReviewNotFoundError(f"No such question: {value!r}") from exc


def _owned_question(
    session: Session,
    student_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    qr_uuid: uuid.UUID,
    *,
    for_update: bool,
) -> tuple[Attempt, QuestionResult]:
    """Load the caller's question or raise 404. Every failure is the same 404."""
    attempt = session.get(Attempt, attempt_uuid)
    if attempt is None or attempt.user_id != student_uuid:
        raise SelfReviewNotFoundError(f"No question {qr_uuid} on attempt {attempt_uuid}")
    qr = session.get(QuestionResult, qr_uuid, with_for_update=for_update)
    if qr is None or qr.attempt_id != attempt.id:
        raise SelfReviewNotFoundError(f"No question {qr_uuid} on attempt {attempt_uuid}")
    if not qr.points:
        # A quiz, or a paper corrected before the per-point ledger existed
        # (spec 1 D7, no backfill): there is nothing to self-mark against, so
        # the surface is absent — derived from the rows, not a flag.
        raise SelfReviewNotFoundError(f"Question {qr_uuid} has no mark points to self-review")
    return attempt, qr


def _to_view(session: Session, qr: QuestionResult) -> PendingSelfReview | RevealedSelfReview:
    evidence_required = not is_marking_low_confidence(qr)
    if not qr.is_self_marked:
        return PendingSelfReview(
            state="not_started",
            attempt_id=qr.attempt_id,
            question_result_id=qr.id,
            question_id=qr.question_id,
            maximum_marks=qr.maximum_marks,
            evidence_required=evidence_required,
            points=[
                PendingPoint(
                    mark_point_id=p.mark_point_id,
                    ordinal=p.ordinal,
                    mark_type=p.mark_type,
                    tariff=p.tariff,
                    point_text=p.point_text,
                )
                for p in qr.points
            ],
        )
    return _revealed_view(session, qr, evidence_required=evidence_required)


def _revealed_view(
    session: Session, qr: QuestionResult, *, evidence_required: bool
) -> RevealedSelfReview:
    reasons = _judge_reasons(session, qr)
    pending_teacher = _has_open_unjudged_row(session, qr)
    submitted_at = qr.student_selfmarked_at
    if submitted_at is None:
        raise ValueError(f"Question {qr.id} is not self-marked")
    return RevealedSelfReview(
        state="revealed" if pending_teacher else "settled",
        attempt_id=qr.attempt_id,
        question_result_id=qr.id,
        question_id=qr.question_id,
        maximum_marks=qr.maximum_marks,
        evidence_required=evidence_required,
        ai_marks=qr.awarded_marks,
        effective_marks=qr.effective_marks,
        student_marks=qr.student_selfmark_marks,
        teacher_settled=qr.is_overridden,
        pending_teacher=pending_teacher,
        submitted_at=submitted_at,
        points=[
            RevealedPoint(
                mark_point_id=p.mark_point_id,
                ordinal=p.ordinal,
                mark_type=p.mark_type,
                tariff=p.tariff,
                point_text=p.point_text,
                awarded=p.awarded,
                student_selfmark=bool(p.student_selfmark),
                student_evidence=p.student_evidence,
                evidence_verdict=p.evidence_verdict.value if p.evidence_verdict else None,
                mark_changed=_mark_changed(p),
                judge_reason=reasons.get(p.mark_point_id),
            )
            for p in qr.points
        ],
    )


def _mark_changed(point: QuestionResultPoint) -> bool:
    """Whether this point's verdict was applied: a disagreement that was granted."""
    if point.student_selfmark is None or point.student_selfmark == point.awarded:
        return False
    return point.evidence_verdict in (EvidenceVerdict.not_required, EvidenceVerdict.accepted)


def _judge_reasons(session: Session, qr: QuestionResult) -> dict[str, str | None]:
    """``mark_point_id -> judge_reason`` from the latest self-mark revision's snapshot."""
    revision = session.scalars(
        select(QuestionResultRevision)
        .where(
            QuestionResultRevision.question_result_id == qr.id,
            QuestionResultRevision.source == RevisionSource.student_selfmark,
        )
        .order_by(QuestionResultRevision.revision.desc())
    ).first()
    if revision is None:
        return {}
    reasons: dict[str, str | None] = {}
    for entry in revision.points_snapshot:
        if isinstance(entry, dict) and isinstance(entry.get("mark_point_id"), str):
            reason = entry.get("judge_reason")
            reasons[entry["mark_point_id"]] = reason if isinstance(reason, str) else None
    return reasons


def _has_open_unjudged_row(session: Session, qr: QuestionResult) -> bool:
    count = session.scalar(
        select(func.count())
        .select_from(ReviewQueueItem)
        .where(
            ReviewQueueItem.question_result_id == qr.id,
            ReviewQueueItem.reason == ReviewReason.student_evidence_unjudged,
            ReviewQueueItem.status == ReviewStatus.open,
        )
    )
    return (count or 0) > 0


__all__ = [
    "MAX_EVIDENCE_CHARS",
    "MAX_JUDGE_REASON_CHARS",
    "SELFMARK_RESOLUTION_NOTE",
    "PendingPoint",
    "PendingSelfReview",
    "PointVerdict",
    "RevealedPoint",
    "RevealedSelfReview",
    "SelfReviewAlreadySubmittedError",
    "SelfReviewError",
    "SelfReviewNotFoundError",
    "SelfReviewService",
    "SelfReviewValidationError",
]
```

`JudgeRequest`, `JudgeVerdict`, `PointDecision`, `decide_point`, `UTC`, `datetime`, `recompute_attempt_totals` and `recompute_weakness_records` are imported now and used by Task 6. If `pre-commit` fails on F401 at this commit, add `# noqa: F401` to those import lines and remove it in Task 6.

- [ ] **Step 4: Run the get tests**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_self_review_repo.py -v --no-cov
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/self_review_repo.py tests/test_self_review_repo.py
git commit -S -m "feat(db): SelfReviewService.get with server-enforced reveal withholding"
```

---

### Task 6: `SelfReviewService.submit` — the one-pass write, without a judge

**Files:**
- Modify: `lemely/db/self_review_repo.py` (replace the `submit` stub; add the write helpers)
- Test: `tests/test_self_review_repo.py` (append)

**Interfaces:**
- Consumes: everything Task 5 defined; `decide_point`, `PointDecision` (Task 4); `recompute_attempt_totals`, `recompute_weakness_records` (Task 3).
- Produces: `SelfReviewService.submit(...) -> RevealedSelfReview` as declared in Task 5. With `judge=None`, every `PointDecision.JUDGE` is a judge failure. Task 7 adds the judge call inside `_judge_safely`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_self_review_repo.py` (remove any `# noqa: F401` markers Task 5 added):

```python
# ── submit, no judge configured ────────────────────────────────────────────


def _attempt_row(sm: sessionmaker[Session], attempt_id: uuid.UUID) -> Attempt:
    with sm() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        _ = attempt.weakness_records
        return attempt


def test_low_confidence_grant_moves_marks_through_the_whole_attempt(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The headline path (D2 + D4 + D5): student says earned on every point of
    a low-confidence question the marker gave 0/3 — the marks, the attempt
    total, the grade, the weakness rows and the queue row all move together,
    and the AI's mark is untouched."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1", "p2"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    before = _attempt_row(pg_sessionmaker, attempt_id)
    assert before.awarded_marks == 2 and before.percentage == 40.0

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"])
    )

    assert isinstance(view, RevealedSelfReview)
    assert view.state == "settled"
    assert view.ai_marks == 0
    assert view.student_marks == 3
    assert view.effective_marks == 3
    assert view.teacher_settled is False and view.pending_teacher is False
    assert [p.awarded for p in view.points] == [False, False, False]
    assert [p.student_selfmark for p in view.points] == [True, True, True]
    assert [p.evidence_verdict for p in view.points] == ["not_required"] * 3
    assert all(p.mark_changed for p in view.points)

    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.awarded_marks == 0  # the accuracy guard: lemely/eval reads this
    assert qr.student_selfmark_marks == 3
    assert qr.student_selfmarked_at is not None
    assert all(p.student_selfmark is True and p.student_selfmark_at is not None for p in qr.points)
    assert [r.revision for r in qr.revisions] == [1, 2]
    assert qr.revisions[1].source is RevisionSource.student_selfmark
    assert qr.revisions[1].awarded_marks == 3
    assert qr.revisions[1].actor_user_id == student
    assert {e["mark_point_id"] for e in qr.revisions[1].points_snapshot} == {"p1", "p2", "p3"}

    after = _attempt_row(pg_sessionmaker, attempt_id)
    assert after.awarded_marks == 5
    assert after.percentage == 100.0
    assert after.grade == "A" and after.predicted_grade == "A"
    assert after.weakness_records == []  # "Waves" no longer loses marks

    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [r.reason for r in rows] == [ReviewReason.low_confidence]
    assert rows[0].status is ReviewStatus.resolved
    assert rows[0].resolved_by == student
    assert rows[0].resolved_at is not None
    assert rows[0].resolution_note == SELFMARK_RESOLUTION_NOTE


def test_low_confidence_downward_self_mark_is_honoured(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D6: a student who says they did *not* earn an awarded point loses it."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low(matched=["p1", "p2"])])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    view = _service(pg_sessionmaker).submit(
        student,
        attempt_id,
        qr_id,
        [
            PointVerdict("p1", earned=False),
            PointVerdict("p2", earned=True),
            PointVerdict("p3", earned=False),
        ],
    )

    assert view.ai_marks == 2
    assert view.student_marks == 1
    assert view.effective_marks == 1
    assert [p.mark_changed for p in view.points] == [True, False, False]
    assert _load_qr(pg_sessionmaker, qr_id).awarded_marks == 2


def test_agreement_changes_nothing_but_records_the_pass(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low(matched=["p1"])])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    view = _service(pg_sessionmaker).submit(
        student,
        attempt_id,
        qr_id,
        [
            PointVerdict("p1", earned=True),
            PointVerdict("p2", earned=False),
            PointVerdict("p3", earned=False),
        ],
    )

    assert view.state == "settled"
    assert view.student_marks is None
    assert view.effective_marks == 1
    assert not any(p.mark_changed for p in view.points)
    assert [p.evidence_verdict for p in view.points] == [None, None, None]
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert qr.is_self_marked
    # Agreement does nothing beyond confirming it: the queue row stays open.
    assert [r.status for r in _queue_rows(pg_sessionmaker, qr_id)] == [ReviewStatus.open]
    # ...but the pass itself is history.
    assert [r.source for r in qr.revisions] == [RevisionSource.ai, RevisionSource.student_selfmark]
    assert qr.revisions[1].awarded_marks == 1


def test_second_submission_is_rejected_and_writes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    service = _service(pg_sessionmaker)
    service.submit(student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"]))
    first = _load_qr(pg_sessionmaker, qr_id)

    with pytest.raises(SelfReviewAlreadySubmittedError):
        service.submit(
            student,
            attempt_id,
            qr_id,
            [PointVerdict(p, earned=False) for p in ("p1", "p2", "p3")],
        )

    second = _load_qr(pg_sessionmaker, qr_id)
    assert second.student_selfmarked_at == first.student_selfmarked_at
    assert second.student_selfmark_marks == 3
    assert len(second.revisions) == 2


@pytest.mark.parametrize(
    ("verdicts", "message"),
    [
        (_all_earned(["p1", "p2"]), "missing"),  # partial: reveal-by-halves is refused
        (_all_earned(["p1", "p2", "p3", "p9"]), "Unknown"),
        (_all_earned(["p1", "p2", "p3", "p3"]), "Duplicate"),
        ([], "missing"),
    ],
)
def test_incomplete_or_malformed_submissions_are_rejected_before_any_write(
    pg_sessionmaker: sessionmaker[Session], verdicts: list[PointVerdict], message: str
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    with pytest.raises(SelfReviewValidationError, match=message):
        _service(pg_sessionmaker).submit(student, attempt_id, qr_id, verdicts)

    qr = _load_qr(pg_sessionmaker, qr_id)
    assert not qr.is_self_marked
    assert all(p.student_selfmark is None for p in qr.points)
    assert len(qr.revisions) == 1


def test_high_confidence_disagreement_without_evidence_is_a_misconception_only(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D3: on a confident point a bare self-mark changes nothing — but the
    misconception (claimed, not awarded, nothing granted) is recorded."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker).submit(student, attempt_id, qr_id, _all_earned(["p1", "p2"]))

    assert view.state == "settled"
    assert view.effective_marks == 1 and view.student_marks is None
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.awarded is False and p2.student_selfmark is True
    assert p2.evidence_verdict is None and p2.mark_changed is False
    assert _queue_rows(pg_sessionmaker, qr_id) == []


def test_high_confidence_challenge_with_evidence_and_no_judge_goes_to_a_teacher(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """No judge configured is a judge failure: never a silent accept or reject."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker, judge=None).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True), PointVerdict("p2", True, evidence="I wrote the unit, N.")],
    )

    assert view.state == "revealed"
    assert view.pending_teacher is True
    assert view.effective_marks == 1
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict is None and p2.mark_changed is False
    assert p2.student_evidence == "I wrote the unit, N."
    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [r.reason for r in rows] == [ReviewReason.student_evidence_unjudged]
    assert rows[0].status is ReviewStatus.open


def test_integrity_only_flag_behaves_as_high_confidence(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    flagged = _question(
        "1", matched=["p1"], maximum=2, needs_review=True, ai_detection_flagged=True
    )
    attempt_id = _seed_attempt(pg_sessionmaker, student, [flagged, _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker).submit(student, attempt_id, qr_id, _all_earned(["p1", "p2"]))

    assert view.effective_marks == 1 and view.student_marks is None
    # The integrity row is never touched by a self-mark.
    assert [r.reason for r in _queue_rows(pg_sessionmaker, qr_id)] == [ReviewReason.ai_detection_flag]
    assert _queue_rows(pg_sessionmaker, qr_id)[0].status is ReviewStatus.open


def test_teacher_override_already_recorded_wins_and_skips_nothing_else(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The race: a teacher settled this question mid-pass. The self-mark and
    its misconception signal are still recorded; marks do not move."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    with pg_sessionmaker() as session, session.begin():
        qr = session.get(QuestionResult, qr_id)
        assert qr is not None
        qr.teacher_awarded_marks = 2
        qr.overridden_at = datetime.now(UTC)
        for row in session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.question_result_id == qr_id)
        ):
            row.status = ReviewStatus.resolved

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"])
    )

    assert view.teacher_settled is True
    assert view.effective_marks == 2
    assert view.student_marks is None
    assert not any(p.mark_changed for p in view.points)
    qr = _load_qr(pg_sessionmaker, qr_id)
    assert all(p.student_selfmark is True for p in qr.points)
    assert qr.is_self_marked


def test_evidence_with_a_nul_byte_is_stored_stripped_not_fatal(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Postgres rejects NUL in text and JSONB; a student's paste must not
    abort their own pass (the spec-1 lesson: loose input meeting a strict
    constraint lost a whole transaction)."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")

    view = _service(pg_sessionmaker).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"], evidence="see\x00 line 2")
    )

    assert view.points[0].student_evidence == "see line 2"
    assert _load_qr(pg_sessionmaker, qr_id).is_self_marked


def test_self_marked_and_teacher_overridden_attempts_with_identical_marks_agree(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The totals invariant: one recompute, so the two paths cannot round
    differently. Attempt A is self-marked to 3/3 on question 2; attempt B has
    a teacher override to 3 on the same question."""
    from lemely.db.review_repo import recompute_attempt_totals, recompute_weakness_records
    from lemely.io.grade_boundaries import GradeBoundaryStore

    student = _seed_user(pg_sessionmaker)
    a = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    b = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])

    _service(pg_sessionmaker).submit(
        student, a, _qr_id(pg_sessionmaker, a, "2"), _all_earned(["p1", "p2", "p3"])
    )
    with pg_sessionmaker() as session, session.begin():
        attempt_b = session.get(Attempt, b)
        assert attempt_b is not None
        results = session.scalars(select(QuestionResult).where(QuestionResult.attempt_id == b)).all()
        next(qr for qr in results if qr.question_id == "2").teacher_awarded_marks = 3
        recompute_attempt_totals(session, attempt_b, results, boundary_store=GradeBoundaryStore())
        recompute_weakness_records(session, attempt_b, results)

    ra, rb = _attempt_row(pg_sessionmaker, a), _attempt_row(pg_sessionmaker, b)
    assert (ra.awarded_marks, ra.percentage, ra.grade) == (rb.awarded_marks, rb.percentage, rb.grade)
    assert {(w.topic, w.lost_marks) for w in ra.weakness_records} == {
        (w.topic, w.lost_marks) for w in rb.weakness_records
    }
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_self_review_repo.py -k "submit or grant or downward or agreement or second or incomplete or high_confidence or integrity_only_flag_behaves or teacher_override or nul or identical" -v --no-cov
```

Expected: every new test FAILS with `NotImplementedError`.

- [ ] **Step 3: Implement `submit` and its helpers**

In `lemely/db/self_review_repo.py`, replace the `submit` stub with:

```python
    def submit(
        self,
        student_id: uuid.UUID | str,
        attempt_id: uuid.UUID | str,
        question_result_id: uuid.UUID | str,
        verdicts: Sequence[PointVerdict],
    ) -> RevealedSelfReview:
        """Record the student's one self-mark pass and reveal the marker's verdict.

        One transaction; see the module docstring for what moves and why.

        Raises:
            SelfReviewNotFoundError: as :meth:`get` (404).
            SelfReviewAlreadySubmittedError: the pass already happened (409).
            SelfReviewValidationError: not exactly one verdict per point of
                the question — a partial pass would let a student reveal
                three points and calibrate the other two (422).
        """
        student_uuid = _as_uuid(student_id)
        attempt_uuid = _as_uuid(attempt_id)
        qr_uuid = _as_uuid(question_result_id)
        with self._sessionmaker() as session, session.begin():
            attempt, qr = _owned_question(
                session, student_uuid, attempt_uuid, qr_uuid, for_update=True
            )
            if qr.is_self_marked:
                raise SelfReviewAlreadySubmittedError(
                    f"Question {qr.id} has already been self-marked"
                )
            by_point = _verdicts_by_point(verdicts, qr.points)

            now = datetime.now(UTC)
            low_confidence = is_marking_low_confidence(qr)
            teacher_settled = qr.is_overridden
            delta = 0
            changed = False
            unjudged = False
            snapshot: list[dict[str, object]] = []

            for point in qr.points:
                verdict = by_point[point.mark_point_id]
                evidence = _clean_text(verdict.evidence, MAX_EVIDENCE_CHARS)
                point.student_selfmark = verdict.earned
                point.student_selfmark_at = now
                point.student_evidence = evidence
                point.evidence_verdict = None
                judge_reason: str | None = None
                granted = False

                decision = decide_point(
                    ai_awarded=point.awarded,
                    student_earned=verdict.earned,
                    low_confidence=low_confidence,
                    has_evidence=evidence is not None,
                )
                if teacher_settled and decision is not PointDecision.AGREE:
                    # Precedence already settles this question; the self-mark
                    # is recorded for its learning signal and nothing moves,
                    # so a judge call could not change any outcome.
                    decision = PointDecision.NO_CHANGE

                if decision is PointDecision.GRANT:
                    point.evidence_verdict = EvidenceVerdict.not_required
                    granted = True
                elif decision is PointDecision.JUDGE:
                    outcome = self._judge_safely(
                        JudgeRequest(
                            subject_code=attempt.subject_code or "",
                            question_id=qr.question_id,
                            point_text=point.point_text,
                            mark_type=point.mark_type,
                            tariff=point.tariff,
                            student_answer=qr.student_answer,
                            marker_rationale=point.rationale or qr.rationale or qr.feedback,
                            student_claims_earned=verdict.earned,
                            student_evidence=evidence or "",
                        ),
                        qr,
                    )
                    if outcome is None:
                        unjudged = True
                    else:
                        point.evidence_verdict = (
                            EvidenceVerdict.accepted if outcome.accepted else EvidenceVerdict.rejected
                        )
                        judge_reason = outcome.reason
                        granted = outcome.accepted

                if granted:
                    delta += point.tariff if verdict.earned else -point.tariff
                    changed = True
                snapshot.append(
                    {
                        "mark_point_id": point.mark_point_id,
                        "ai_awarded": point.awarded,
                        "student_selfmark": verdict.earned,
                        "evidence_verdict": (
                            point.evidence_verdict.value if point.evidence_verdict else None
                        ),
                        "mark_changed": granted,
                        "judge_reason": judge_reason,
                    }
                )

            qr.student_selfmarked_at = now
            if changed:
                qr.student_selfmark_marks = max(
                    0, min(qr.maximum_marks, qr.awarded_marks + delta)
                )
            session.flush()
            _append_revision(session, qr, actor=student_uuid, snapshot=snapshot, changed=changed)

            if changed:
                results = session.scalars(
                    select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
                ).all()
                recompute_attempt_totals(session, attempt, results, boundary_store=self._boundaries)
                recompute_weakness_records(session, attempt, results)
                _resolve_low_confidence_rows(session, qr, resolver=student_uuid, now=now)
            if unjudged:
                session.add(
                    ReviewQueueItem(
                        attempt_id=attempt.id,
                        question_result_id=qr.id,
                        reason=ReviewReason.student_evidence_unjudged,
                    )
                )
            session.flush()
            log.info(
                "self_review_submitted",
                attempt_id=str(attempt.id),
                question_result_id=str(qr.id),
                low_confidence=low_confidence,
                marks_changed=changed,
                unjudged=unjudged,
                teacher_settled=teacher_settled,
            )
            return _revealed_view(session, qr, evidence_required=not low_confidence)

    def _judge_safely(self, request: JudgeRequest, qr: QuestionResult) -> JudgeVerdict | None:
        """Ask the judge; ``None`` on any failure (no judge, exception, junk).

        A failure is never a decision — the caller opens a
        ``student_evidence_unjudged`` queue row. The verdict's reason is an
        LLM string bound for JSONB, so it is NUL-stripped and truncated here.
        """
        if self._judge is None:
            log.warning("self_review_judge_unavailable", question_result_id=str(qr.id))
            return None
        try:
            verdict = self._judge.judge(request)
        except Exception as exc:  # noqa: BLE001 — any failure is "unjudged", by design
            log.warning(
                "self_review_judge_failed", question_result_id=str(qr.id), error=str(exc)
            )
            return None
        return JudgeVerdict(
            accepted=bool(verdict.accepted),
            reason=_clean_text(verdict.reason, MAX_JUDGE_REASON_CHARS) or "",
        )
```

Then add these helpers after `_has_open_unjudged_row`:

```python
def _verdicts_by_point(
    verdicts: Sequence[PointVerdict], points: Sequence[QuestionResultPoint]
) -> dict[str, PointVerdict]:
    """Exactly one verdict per point of the question, or a validation error.

    Checked before anything is written, so a rejected submission leaves the
    question exactly as it was — a second, complete POST is still allowed.
    """
    expected = {p.mark_point_id for p in points}
    seen: dict[str, PointVerdict] = {}
    for verdict in verdicts:
        if verdict.mark_point_id in seen:
            raise SelfReviewValidationError(f"Duplicate verdict for point {verdict.mark_point_id}")
        if verdict.mark_point_id not in expected:
            raise SelfReviewValidationError(f"Unknown point {verdict.mark_point_id}")
        seen[verdict.mark_point_id] = verdict
    missing = expected - seen.keys()
    if missing:
        raise SelfReviewValidationError(
            f"Every point needs a verdict; missing {sorted(missing)}"
        )
    return seen


def _clean_text(text: str | None, limit: int) -> str | None:
    """Strip NUL bytes (Postgres text/JSONB reject them), trim, bound, blank→None."""
    if text is None:
        return None
    cleaned = text.replace("\x00", "").strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _append_revision(
    session: Session,
    qr: QuestionResult,
    *,
    actor: uuid.UUID,
    snapshot: list[dict[str, object]],
    changed: bool,
) -> None:
    """Append the ``student_selfmark`` revision — on every pass (module docstring)."""
    latest = session.scalar(
        select(func.max(QuestionResultRevision.revision)).where(
            QuestionResultRevision.question_result_id == qr.id
        )
    )
    session.add(
        QuestionResultRevision(
            question_result_id=qr.id,
            revision=(latest or 0) + 1,
            source=RevisionSource.student_selfmark,
            awarded_marks=qr.effective_marks,
            points_snapshot=snapshot,
            actor_user_id=actor,
            reason="Student self-mark: marks changed" if changed else "Student self-mark: no change",
        )
    )
    session.flush()


def _resolve_low_confidence_rows(
    session: Session, qr: QuestionResult, *, resolver: uuid.UUID, now: datetime
) -> None:
    """D4: close the open ``low_confidence`` row(s) with the student as resolver.

    Only that reason. An integrity row on the same question is a teacher's
    to dismiss and is never touched here.
    """
    rows = session.scalars(
        select(ReviewQueueItem).where(
            ReviewQueueItem.question_result_id == qr.id,
            ReviewQueueItem.reason == ReviewReason.low_confidence,
            ReviewQueueItem.status == ReviewStatus.open,
        )
    ).all()
    for row in rows:
        row.status = ReviewStatus.resolved
        row.resolved_by = resolver
        row.resolved_at = now
        row.resolution_note = SELFMARK_RESOLUTION_NOTE
```

- [ ] **Step 4: Run the file**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_self_review_repo.py -v --no-cov
```

Expected: 22 passed (8 from Task 5, 14 new including the 4 parametrized cases).

- [ ] **Step 5: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/self_review_repo.py tests/test_self_review_repo.py
git commit -S -m "feat(db): SelfReviewService.submit — one-pass self-mark with authority, revision, totals and queue resolve"
```

---

### Task 7: The judge in the loop, and the authority matrix

**Files:**
- Modify: `lemely/db/self_review_repo.py` (no logic change expected; this task proves the judge path)
- Test: `tests/test_self_review_repo.py` (append)

**Interfaces:**
- Consumes: `EvidenceJudge` protocol (Task 4) via a scripted test double.
- Produces: proof that `submit` honours accept / reject / fail, sanitises the judge's reason, never calls the judge on a low-confidence question, and the full authority matrix.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_self_review_repo.py`:

```python
# ── submit, with a judge ───────────────────────────────────────────────────


class ScriptedJudge:
    """An ``EvidenceJudge`` that answers from a script and records every call."""

    def __init__(self, outcome: str, reason: str = "Plausible and not contradicted.") -> None:
        self.outcome = outcome  # "accept" | "reject" | "fail"
        self.reason = reason
        self.calls: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        self.calls.append(request)
        if self.outcome == "fail":
            raise RuntimeError("gemini timeout")
        return JudgeVerdict(accepted=self.outcome == "accept", reason=self.reason)


def _challenge_p2(evidence: str | None = "I wrote 'N' as the unit.") -> list[PointVerdict]:
    return [PointVerdict("p1", True), PointVerdict("p2", True, evidence=evidence)]


def test_judge_accept_grants_the_point_and_keeps_the_reason(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = ScriptedJudge("accept", reason="The unit is present in the answer.")

    view = _service(pg_sessionmaker, judge).submit(student, attempt_id, qr_id, _challenge_p2())

    assert view.state == "settled"
    assert view.student_marks == 2 and view.effective_marks == 2
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict == "accepted" and p2.mark_changed is True
    assert p2.judge_reason == "The unit is present in the answer."
    # The reason survives a fresh GET (it lives in the revision snapshot).
    again = _service(pg_sessionmaker, judge).get(student, attempt_id, qr_id)
    assert isinstance(again, RevealedSelfReview)
    assert next(p for p in again.points if p.mark_point_id == "p2").judge_reason == (
        "The unit is present in the answer."
    )
    # What the judge was given.
    assert len(judge.calls) == 1
    request = judge.calls[0]
    assert request.point_text == "Gives the unit"
    assert request.student_answer == "answer-1"
    assert request.marker_rationale == "Method not shown."
    assert request.student_claims_earned is True
    assert request.student_evidence == "I wrote 'N' as the unit."
    assert request.subject_code == "9999"


def test_judge_reject_keeps_the_mark_and_shows_the_reason(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = ScriptedJudge("reject", reason="The recorded answer has no unit at all.")

    view = _service(pg_sessionmaker, judge).submit(student, attempt_id, qr_id, _challenge_p2())

    assert view.state == "settled"
    assert view.student_marks is None and view.effective_marks == 1
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict == "rejected" and p2.mark_changed is False
    assert p2.judge_reason == "The recorded answer has no unit at all."
    assert _queue_rows(pg_sessionmaker, qr_id) == []


def test_judge_failure_opens_a_queue_row_and_moves_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    view = _service(pg_sessionmaker, ScriptedJudge("fail")).submit(
        student, attempt_id, qr_id, _challenge_p2()
    )

    assert view.state == "revealed" and view.pending_teacher is True
    assert view.effective_marks == 1
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.evidence_verdict is None and p2.judge_reason is None
    rows = _queue_rows(pg_sessionmaker, qr_id)
    assert [r.reason for r in rows] == [ReviewReason.student_evidence_unjudged]


def test_judge_is_never_consulted_on_a_low_confidence_question(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "2")
    judge = ScriptedJudge("reject")

    view = _service(pg_sessionmaker, judge).submit(
        student, attempt_id, qr_id, _all_earned(["p1", "p2", "p3"], evidence="because")
    )

    assert judge.calls == []
    assert view.student_marks == 3


def test_a_judge_reason_with_a_nul_byte_does_not_abort_the_pass(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """JSONB rejects NUL escapes; an LLM string must be bounded before it
    reaches the revision snapshot, or the whole pass — marks included — is
    lost to the judge's formatting."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=["p1"]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = ScriptedJudge("accept", reason="ok\x00" + "x" * 900)

    view = _service(pg_sessionmaker, judge).submit(student, attempt_id, qr_id, _challenge_p2())

    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    assert p2.mark_changed is True
    assert p2.judge_reason is not None
    assert "\x00" not in p2.judge_reason and len(p2.judge_reason) == 500


def test_mixed_points_apply_independently(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Two challenged points on one high-confidence question: one accepted,
    one that fails to be judged. The accepted one moves; the failure opens
    exactly one queue row for the question."""
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(matched=[]), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")

    class OneThenFail:
        def __init__(self) -> None:
            self.n = 0

        def judge(self, request: JudgeRequest) -> JudgeVerdict:
            self.n += 1
            if self.n == 1:
                return JudgeVerdict(accepted=True, reason="first")
            raise RuntimeError("second call fails")

    view = _service(pg_sessionmaker, OneThenFail()).submit(
        student,
        attempt_id,
        qr_id,
        [PointVerdict("p1", True, evidence="a"), PointVerdict("p2", True, evidence="b")],
    )

    assert view.student_marks == 1 and view.state == "revealed"
    assert [p.mark_changed for p in view.points] == [True, False]
    assert len(_queue_rows(pg_sessionmaker, qr_id)) == 1


# ── The authority matrix ───────────────────────────────────────────────────
#
# flag state x evidence present x judge outcome, for a student who claims a
# missed point. Every cell names what moves, what verdict is stored, whether
# the judge is called, and whether a teacher gets a queue row.

_FLAG = {
    "low": lambda: _question("1", matched=["p1"], maximum=2, confidence_score=0.2, needs_review=True),
    "high": lambda: _question("1", matched=["p1"], maximum=2),
    "integrity_only": lambda: _question(
        "1", matched=["p1"], maximum=2, needs_review=True, plagiarism_flagged=True
    ),
}


@pytest.mark.parametrize("flag", ["low", "high", "integrity_only"])
@pytest.mark.parametrize("evidence", ["present", "absent"])
@pytest.mark.parametrize("judge_outcome", ["accept", "reject", "fail"])
def test_authority_matrix(
    pg_sessionmaker: sessionmaker[Session], flag: str, evidence: str, judge_outcome: str
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_FLAG[flag](), _low()])
    qr_id = _qr_id(pg_sessionmaker, attempt_id, "1")
    judge = ScriptedJudge(judge_outcome)

    view = _service(pg_sessionmaker, judge).submit(
        student, attempt_id, qr_id, _challenge_p2("because" if evidence == "present" else None)
    )
    p2 = next(p for p in view.points if p.mark_point_id == "p2")
    unjudged_rows = [
        r
        for r in _queue_rows(pg_sessionmaker, qr_id)
        if r.reason is ReviewReason.student_evidence_unjudged
    ]

    if flag == "low":
        expected = (True, "not_required", 0, 0)
    elif evidence == "absent":
        expected = (False, None, 0, 0)
    elif judge_outcome == "accept":
        expected = (True, "accepted", 1, 0)
    elif judge_outcome == "reject":
        expected = (False, "rejected", 1, 0)
    else:
        expected = (False, None, 1, 1)

    assert (p2.mark_changed, p2.evidence_verdict, len(judge.calls), len(unjudged_rows)) == expected
    assert view.effective_marks == (2 if expected[0] else 1)
    assert _load_qr(pg_sessionmaker, qr_id).awarded_marks == 1
```

- [ ] **Step 2: Run the new tests**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_self_review_repo.py -k "judge or mixed or authority_matrix" -v --no-cov
```

Expected: all pass on the Task 6 implementation (6 named tests + 18 matrix cells). If any cell fails, the implementation is wrong, not the table — fix `submit`, not the expectation.

- [ ] **Step 3: Run the whole file, then commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_self_review_repo.py --no-cov -q
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add tests/test_self_review_repo.py lemely/db/self_review_repo.py
git commit -S -m "test(db): self-review judge path and the full authority matrix"
```

---

### Task 8: DTOs, the two routes, the dependency, and the authz matrices

**Files:**
- Create: `lemely/web/schemas_student_self_review.py`
- Create: `lemely/web/routers/student_self_review.py`
- Modify: `lemely/web/deps.py` (new `get_self_review_service`, next to `get_review_service` :432)
- Modify: `lemely/web/app.py:44-45` (import block) and `:129` (mount after `student_classes`)
- Modify: `tests/test_authz_matrix.py` (`STUDENT_GET_ROUTES` :45, `STUDENT_POST_ROUTES` :55)
- Modify: `tests/test_authz_matrix_complete.py` (`EXPECTED`, `# ── STUDENT (54)` block :256)
- Test: `tests/test_student_self_review_web.py` (create)

**Interfaces:**
- Consumes: `SelfReviewService`, its errors and views, `PointVerdict`, `MAX_EVIDENCE_CHARS` (Tasks 5–6); `require_role`, `AuthContext`, `get_sessionmaker`, `get_settings` (existing `deps.py`).
- Produces:
  - `GET /api/student/attempts/{attempt_id}/questions/{question_result_id}/self-review` → `SelfReviewPendingDTO | SelfReviewRevealedDTO`.
  - `POST` same path, body `SelfReviewSubmissionDTO` → `SelfReviewRevealedDTO`. 404 / 409 / 422 as the service errors map.
  - `get_self_review_service() -> SelfReviewService` in `lemely/web/deps.py` (judge `None` until Task 11).
  - Wire shapes (camelCase, mirrored in TS by Task 12): `SelfReviewPendingPointDTO{markPointId, ordinal, markType, tariff, pointText}`; `SelfReviewRevealedPointDTO` = that + `{awarded, studentSelfmark, studentEvidence, evidenceVerdict, markChanged, judgeReason}`; `SelfReviewPendingDTO{state:"not_started", attemptId, questionResultId, questionId, maxMarks, evidenceRequired, points}`; `SelfReviewRevealedDTO{state:"revealed"|"settled", attemptId, questionResultId, questionId, maxMarks, evidenceRequired, aiMarks, effectiveMarks, studentMarks, teacherSettled, pendingTeacher, submittedAt, points}`; `SelfReviewSubmissionDTO{points: [{markPointId, earned, evidence?}]}`.

- [ ] **Step 1: Write the failing endpoint tests**

Create `tests/test_student_self_review_web.py`:

```python
"""HTTP surface of student self-review (``/api/student/attempts/.../self-review``).

Reuses ``tests/test_student_correct.py``'s ``client`` fixture (real repos over
a throwaway database, Gemini mocked) and adds exactly one override: the
self-review service bound to the same throwaway sessionmaker, with no judge.
The attempt is seeded straight through ``AttemptRepository`` with the shared
``_scheme()`` so it has point rows — the fixture's own MCQ marking path has
none, by design (spec 1: no answer points, no ledger).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import FastAPI
from sqlalchemy import select

from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeaknessReport,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.models.attempts import QuestionResult
from lemely.db.self_review_repo import SelfReviewService
from lemely.web.deps import get_self_review_service
from tests.conftest import _scheme
from tests.test_student_correct import (  # noqa: F401 — pytest fixtures, reused by import
    _seed_user,
    client,
    corpus_repo,
    gemini_client,
    pg_sessionmaker,
    settings,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.upload_repo import StudentUploadRepository


def _low_confidence_report() -> AccuracyReport:
    """One question ("1a", 3 marks, p1 matched) at confidence 0.55 — low."""
    question = CorrectedQuestion(
        question_id="1a",
        awarded_marks=1,
        maximum_marks=3,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.55,
        needs_teacher_review=True,
        student_answer="F = ma so F = 12",
        marker_source="ai",
        feedback="Answer not given to 3 s.f.",
        matched_point_ids=["p1"],
    )
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0580",
            session_month="May/June",
            session_year=2024,
            paper_number=2,
            paper_variant=1,
        ),
        questions=[question],
    )
    return AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=GradePrediction(
            awarded_marks=1,
            maximum_marks=3,
            percentage=33.33,
            grade="E",
            confidence=ConfidenceBand.LOW,
        ),
    )


def _seed_attempt(sm: sessionmaker[Session], student_id: str) -> tuple[str, str]:
    attempt_id = AttemptRepository(sm).persist_correction(
        user_id=student_id, report=_low_confidence_report(), mark_scheme=_scheme()
    )
    with sm() as session:
        qr_id = session.scalars(
            select(QuestionResult.id).where(QuestionResult.attempt_id == attempt_id)
        ).one()
    return str(attempt_id), str(qr_id)


def _wire(
    client: tuple[TestClient, str, StudentUploadRepository],
    sm: sessionmaker[Session],
) -> tuple[TestClient, str]:
    api, student_id, _ = client
    app = cast(FastAPI, api.app)
    app.dependency_overrides[get_self_review_service] = lambda: SelfReviewService(sm, judge=None)
    return api, student_id


def _path(attempt_id: str, qr_id: str) -> str:
    return f"/api/student/attempts/{attempt_id}/questions/{qr_id}/self-review"


def _assert_no_key_containing(payload: object, needle: str) -> None:
    """Recursive: no dict key at any depth contains ``needle`` (case-insensitive)."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert needle not in str(key).lower(), f"key {key!r} leaks the verdict"
            _assert_no_key_containing(value, needle)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_key_containing(value, needle)


def _full_pass(evidence: str | None = None) -> dict[str, object]:
    return {
        "points": [
            {"markPointId": pid, "earned": True, "evidence": evidence} for pid in ("p1", "p2", "p3")
        ]
    }


def test_get_before_submission_withholds_the_verdict_entirely(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """THE test. If this payload ever carried the verdict under any key, the
    feature would be defeated by opening devtools while every other test
    still passed."""
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    resp = api.get(_path(attempt_id, qr_id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "not_started"
    assert body["attemptId"] == attempt_id
    assert body["questionResultId"] == qr_id
    assert body["questionId"] == "1a"
    assert body["maxMarks"] == 3
    assert body["evidenceRequired"] is False
    assert [p["markPointId"] for p in body["points"]] == ["p1", "p2", "p3"]
    assert body["points"][0] == {
        "markPointId": "p1",
        "ordinal": 0,
        "markType": "M",
        "tariff": 1,
        "pointText": "Correct method",
    }
    _assert_no_key_containing(body, "awarded")
    _assert_no_key_containing(body, "selfmark")
    _assert_no_key_containing(body, "verdict")
    _assert_no_key_containing(body, "marks")  # no aiMarks / effectiveMarks / studentMarks


def test_post_reveals_and_applies_a_low_confidence_self_mark(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    resp = api.post(_path(attempt_id, qr_id), json=_full_pass())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "settled"
    assert body["aiMarks"] == 1
    assert body["studentMarks"] == 3
    assert body["effectiveMarks"] == 3
    assert body["teacherSettled"] is False
    assert body["pendingTeacher"] is False
    assert body["submittedAt"]
    assert [p["awarded"] for p in body["points"]] == [True, False, False]
    assert [p["studentSelfmark"] for p in body["points"]] == [True, True, True]
    assert [p["markChanged"] for p in body["points"]] == [False, True, True]
    assert [p["evidenceVerdict"] for p in body["points"]] == [None, "not_required", "not_required"]

    # And a GET now reveals the same.
    again = api.get(_path(attempt_id, qr_id)).json()
    assert again["state"] == "settled"
    assert [p["awarded"] for p in again["points"]] == [True, False, False]


def test_second_post_is_409(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)
    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 200

    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 409


def test_partial_submission_is_422(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    resp = api.post(
        _path(attempt_id, qr_id),
        json={"points": [{"markPointId": "p1", "earned": True}]},
    )

    assert resp.status_code == 422
    assert "missing" in resp.json()["detail"]
    # Nothing was revealed by the refused pass.
    _assert_no_key_containing(api.get(_path(attempt_id, qr_id)).json(), "awarded")


def test_another_students_attempt_is_404_on_both_verbs(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, _ = _wire(client, pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, other)

    assert api.get(_path(attempt_id, qr_id)).status_code == 404
    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 404


def test_malformed_ids_are_404(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, _ = _wire(client, pg_sessionmaker)
    assert api.get(_path("not-a-uuid", "nope")).status_code == 404


def test_evidence_input_is_bounded_at_the_edge(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Loose input meets a strict constraint at the DTO, not in the transaction."""
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    assert api.post(_path(attempt_id, qr_id), json=_full_pass("ok\x00")).status_code == 422
    assert api.post(_path(attempt_id, qr_id), json=_full_pass("x" * 2001)).status_code == 422
    assert api.post(_path(attempt_id, qr_id), json={"points": []}).status_code == 422
    assert api.post(_path(attempt_id, qr_id), json={}).status_code == 422
    # None of those touched the row.
    assert api.get(_path(attempt_id, qr_id)).json()["state"] == "not_started"
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_student_self_review_web.py -v --no-cov
```

Expected: `ImportError: cannot import name 'get_self_review_service' from 'lemely.web.deps'`.

- [ ] **Step 3: Write the DTOs**

Create `lemely/web/schemas_student_self_review.py`:

```python
"""API DTOs for student self-review (``/api/student/attempts/.../self-review``).

Two response shapes, on purpose. :class:`SelfReviewPendingDTO` is what a
student sees **before** committing to their own verdicts and its point type
carries no ``awarded``, no marks, no verdict — the reveal is enforced by the
payload's shape, not by a client hiding a field (spec 2026-09-17
self-review, "Flow"). :class:`SelfReviewRevealedDTO` exists only after the
pass. Nothing here carries an integrity flag, and no copy mentions one.

Input is bounded at this edge: evidence is at most
:data:`~lemely.db.self_review_repo.MAX_EVIDENCE_CHARS` characters and may not
contain NUL, which Postgres rejects in ``text`` and JSONB — the spec-1
lesson that loosely-validated input meeting a strict constraint aborts the
whole transaction.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Literal

from pydantic import Field, field_validator

from lemely.db.self_review_repo import MAX_EVIDENCE_CHARS
from lemely.web.schemas import ApiModel

EvidenceVerdictWire = Literal["accepted", "rejected", "not_required"]


class SelfReviewPendingPointDTO(ApiModel):
    """A mark point before the reveal. No ``awarded`` — by construction."""

    markPointId: str
    ordinal: int
    markType: str | None
    tariff: int
    pointText: str


class SelfReviewRevealedPointDTO(SelfReviewPendingPointDTO):
    """A mark point after the reveal: the marker's verdict beside the student's."""

    awarded: bool
    studentSelfmark: bool
    studentEvidence: str | None
    evidenceVerdict: EvidenceVerdictWire | None
    markChanged: bool
    judgeReason: str | None


class SelfReviewPendingDTO(ApiModel):
    """``GET`` before submission."""

    state: Literal["not_started"]
    attemptId: str
    questionResultId: str
    questionId: str
    maxMarks: int
    evidenceRequired: bool
    points: list[SelfReviewPendingPointDTO]


class SelfReviewRevealedDTO(ApiModel):
    """``GET`` after submission, and every ``POST`` response."""

    state: Literal["revealed", "settled"]
    attemptId: str
    questionResultId: str
    questionId: str
    maxMarks: int
    evidenceRequired: bool
    aiMarks: int
    effectiveMarks: int
    studentMarks: int | None
    teacherSettled: bool
    pendingTeacher: bool
    submittedAt: datetime
    points: list[SelfReviewRevealedPointDTO]


class SelfReviewPointVerdictDTO(ApiModel):
    """One point of the student's submission."""

    markPointId: str = Field(min_length=1, max_length=200)
    earned: bool
    evidence: str | None = Field(default=None, max_length=MAX_EVIDENCE_CHARS)

    @field_validator("evidence")
    @classmethod
    def _no_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("evidence must not contain NUL characters")
        return value


class SelfReviewSubmissionDTO(ApiModel):
    """``POST`` body: a verdict for **every** point of the question."""

    points: list[SelfReviewPointVerdictDTO] = Field(min_length=1, max_length=100)


__all__ = [
    "SelfReviewPendingDTO",
    "SelfReviewPendingPointDTO",
    "SelfReviewPointVerdictDTO",
    "SelfReviewRevealedDTO",
    "SelfReviewRevealedPointDTO",
    "SelfReviewSubmissionDTO",
]
```

- [ ] **Step 4: Write the router**

Create `lemely/web/routers/student_self_review.py`:

```python
"""Student self-review endpoints (spec 2026-09-17 self-review, "API").

A new router file, mirroring :mod:`lemely.web.routers.student_announcements`:
thin, its own DTOs, no growth of ``student.py``. Every rule lives in
:class:`~lemely.db.self_review_repo.SelfReviewService`; this module only
maps its errors to status codes and its views to DTOs.

Identity is **always** ``auth.user_id``. Cross-student access is a 404 with
a fixed body, never a 403 — matching every other student route, so the
route is not an existence oracle for another student's attempts.
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.models.enums import Role
from lemely.db.self_review_repo import (
    PendingSelfReview,
    PointVerdict,
    RevealedSelfReview,
    SelfReviewAlreadySubmittedError,
    SelfReviewError,
    SelfReviewNotFoundError,
    SelfReviewService,
    SelfReviewValidationError,
)
from lemely.web.deps import AuthContext, get_self_review_service, require_role
from lemely.web.schemas_student_self_review import (
    SelfReviewPendingDTO,
    SelfReviewPendingPointDTO,
    SelfReviewRevealedDTO,
    SelfReviewRevealedPointDTO,
    SelfReviewSubmissionDTO,
)

router = APIRouter(prefix="/api/student/attempts")

_SELF_REVIEW_PATH = "/{attempt_id}/questions/{question_result_id}/self-review"


def _raise_for(exc: SelfReviewError) -> NoReturn:
    """Map a :class:`SelfReviewError` to its status. The 404 body is fixed."""
    if isinstance(exc, SelfReviewNotFoundError):
        raise HTTPException(status_code=404, detail="No such question") from exc
    if isinstance(exc, SelfReviewAlreadySubmittedError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, SelfReviewValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


def _pending_dto(view: PendingSelfReview) -> SelfReviewPendingDTO:
    return SelfReviewPendingDTO(
        state=view.state,
        attemptId=str(view.attempt_id),
        questionResultId=str(view.question_result_id),
        questionId=view.question_id,
        maxMarks=view.maximum_marks,
        evidenceRequired=view.evidence_required,
        points=[
            SelfReviewPendingPointDTO(
                markPointId=p.mark_point_id,
                ordinal=p.ordinal,
                markType=p.mark_type,
                tariff=p.tariff,
                pointText=p.point_text,
            )
            for p in view.points
        ],
    )


def _revealed_dto(view: RevealedSelfReview) -> SelfReviewRevealedDTO:
    return SelfReviewRevealedDTO(
        state=view.state,
        attemptId=str(view.attempt_id),
        questionResultId=str(view.question_result_id),
        questionId=view.question_id,
        maxMarks=view.maximum_marks,
        evidenceRequired=view.evidence_required,
        aiMarks=view.ai_marks,
        effectiveMarks=view.effective_marks,
        studentMarks=view.student_marks,
        teacherSettled=view.teacher_settled,
        pendingTeacher=view.pending_teacher,
        submittedAt=view.submitted_at,
        points=[
            SelfReviewRevealedPointDTO(
                markPointId=p.mark_point_id,
                ordinal=p.ordinal,
                markType=p.mark_type,
                tariff=p.tariff,
                pointText=p.point_text,
                awarded=p.awarded,
                studentSelfmark=p.student_selfmark,
                studentEvidence=p.student_evidence,
                evidenceVerdict=p.evidence_verdict,  # type: ignore[arg-type]
                markChanged=p.mark_changed,
                judgeReason=p.judge_reason,
            )
            for p in view.points
        ],
    )


@router.get(_SELF_REVIEW_PATH, response_model=SelfReviewPendingDTO | SelfReviewRevealedDTO)
def get_self_review(
    attempt_id: str,
    question_result_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[SelfReviewService, Depends(get_self_review_service)],
) -> SelfReviewPendingDTO | SelfReviewRevealedDTO:
    """The self-review state of one of the caller's questions.

    Before submission the payload is :class:`SelfReviewPendingDTO`, which
    carries no verdict at any depth. After it, :class:`SelfReviewRevealedDTO`.
    """
    try:
        view = service.get(auth.user_id, attempt_id, question_result_id)
    except SelfReviewError as exc:
        _raise_for(exc)
    if isinstance(view, PendingSelfReview):
        return _pending_dto(view)
    return _revealed_dto(view)


@router.post(_SELF_REVIEW_PATH, response_model=SelfReviewRevealedDTO)
def submit_self_review(
    attempt_id: str,
    question_result_id: str,
    payload: SelfReviewSubmissionDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[SelfReviewService, Depends(get_self_review_service)],
) -> SelfReviewRevealedDTO:
    """Record the caller's one self-mark pass and reveal the marker's verdict.

    409 once a pass exists; 422 unless every point carries exactly one verdict.
    """
    try:
        view = service.submit(
            auth.user_id,
            attempt_id,
            question_result_id,
            [
                PointVerdict(mark_point_id=p.markPointId, earned=p.earned, evidence=p.evidence)
                for p in payload.points
            ],
        )
    except SelfReviewError as exc:
        _raise_for(exc)
    return _revealed_dto(view)


__all__ = ["router"]
```

- [ ] **Step 5: Add the dependency and mount the router**

In `lemely/web/deps.py`, next to the `get_review_service` import block add `from lemely.db.self_review_repo import SelfReviewService`, and after `get_review_service` (line ~442) add:

```python
@lru_cache(maxsize=1)
def get_self_review_service() -> SelfReviewService:
    """Return the process-wide :class:`SelfReviewService` singleton.

    ``judge=None`` here: until the lenient judge is wired (Part 2 of the
    self-review plan) every high-confidence challenge that carries evidence
    is a judge *failure* and lands in the teacher queue as
    ``student_evidence_unjudged`` — never a silent accept or reject.
    """
    return SelfReviewService(get_sessionmaker(get_settings()), judge=None)
```

In `lemely/web/app.py`, add `student_self_review,` to the `from lemely.web.routers import (...)` block after `student_classes,` (line 45), and after `app.include_router(student_classes.router)` (line 129) add:

```python
    app.include_router(student_self_review.router)
```

- [ ] **Step 6: Register the routes in both authz matrices**

`tests/test_authz_matrix.py` — append to `STUDENT_GET_ROUTES`:

```python
    # Student self-review (spec 2026-09-17) — per-route guards, so both verbs
    # are listed. Ownership is enforced inside SelfReviewService (a 404, see
    # tests/test_student_self_review_web.py), not here.
    "/api/student/attempts/00000000-0000-0000-0000-000000000002/questions/00000000-0000-0000-0000-000000000003/self-review",
```

and to `STUDENT_POST_ROUTES`:

```python
    (
        "/api/student/attempts/00000000-0000-0000-0000-000000000002/questions/00000000-0000-0000-0000-000000000003/self-review",
        {"points": [{"markPointId": "p1", "earned": True}]},
    ),
```

`tests/test_authz_matrix_complete.py` — in the `# ── STUDENT (54)` block, change the header to `# ── STUDENT (56)` and add, keeping the block's path order (these sort before `/api/student/overview`):

```python
    # Student self-review (spec 2026-09-17): both verbs on the one path.
    (
        "GET",
        "/api/student/attempts/{attempt_id}/questions/{question_result_id}/self-review",
    ): STUDENT,
    (
        "POST",
        "/api/student/attempts/{attempt_id}/questions/{question_result_id}/self-review",
    ): STUDENT,
```

(`_PLACEHOLDERS` has no entry for `attempt_id` / `question_result_id`; `_concrete` substitutes a `uuid4()` for any unknown name, which routes fine.)

- [ ] **Step 7: Run the endpoint and authz tests**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_student_self_review_web.py tests/test_authz_matrix.py tests/test_authz_matrix_complete.py --no-cov -q
```

Expected: all passed. `test_every_route_is_declared` fails until Step 6 is complete — that is the registry doing its job.

- [ ] **Step 8: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/web/schemas_student_self_review.py lemely/web/routers/student_self_review.py lemely/web/deps.py lemely/web/app.py tests/test_student_self_review_web.py tests/test_authz_matrix.py tests/test_authz_matrix_complete.py
git commit -S -m "feat(web): student self-review GET/POST routes with server-enforced reveal"
```

---

### Task 9: The complete frame carries `questionResultId`

**Files:**
- Modify: `lemely/web/schemas.py:32-46` (`QuestionResultDTO`) and `:94-108` (`question_to_dto`)
- Modify: `lemely/db/attempt_repo.py` (new `AttemptRepository.question_result_ids`)
- Modify: `lemely/web/routers/student.py:1059-1063` (after `persist_correction`) and `:1162-1165` (the `questions=[...]` kwarg)
- Modify: `web/src/lib/studentTypes.ts` (`QuestionResult`, ~line 245)
- Test: `tests/test_attempt_repo.py` (append), `tests/test_student_correct.py` (append)

**Interfaces:**
- Produces: `AttemptRepository.question_result_ids(attempt_id: uuid.UUID) -> dict[str, uuid.UUID]` (question_id → question_results.id, first wins on a duplicated question id); `QuestionResultDTO.questionResultId: str | None = None`; `question_to_dto(question, *, question_result_id: str | None = None)`; the SSE `complete` frame's `questions[*].questionResultId`; TS `QuestionResult.questionResultId?: string | null`. Task 15's `PaperResult` reads the TS field.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_attempt_repo.py`:

```python
def test_question_result_ids_maps_question_id_to_row_id(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    repo = AttemptRepository(pg_sessionmaker)
    attempt_id = repo.persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=_scheme(),
    )

    ids = repo.question_result_ids(attempt_id)

    assert set(ids) == {"1a"}
    assert ids["1a"] == _only_result(pg_sessionmaker, attempt_id).id
    assert repo.question_result_ids(uuid.uuid4()) == {}
```

Append to `tests/test_student_correct.py`:

```python
def test_correct_complete_frame_carries_question_result_ids(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The self-review surface (spec 2026-09-17) is addressed by
    ``question_results.id``; the live result must carry it per question."""
    api, _, _ = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    paper_id = up.json()["paperId"]
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200

    complete_frame = next(
        json.loads(frame.removeprefix("data: "))
        for frame in resp.text.split("\n\n")
        if frame.startswith("data:") and '"phase": "complete"' in frame
    )
    with pg_sessionmaker() as session:
        rows = session.execute(
            select(QuestionResult.question_id, QuestionResult.id).where(
                QuestionResult.attempt_id == uuid.UUID(complete_frame["attempt_id"])
            )
        ).all()
    expected = {question_id: str(row_id) for question_id, row_id in rows}
    assert {q["questionId"]: q["questionResultId"] for q in complete_frame["questions"]} == expected
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py -k question_result_ids tests/test_student_correct.py -k question_result_ids --no-cov -v
```

Expected: `AttributeError: 'AttemptRepository' object has no attribute 'question_result_ids'`; the frame test fails with `KeyError: 'questionResultId'`.

- [ ] **Step 3: Implement**

`lemely/db/attempt_repo.py` — add `from sqlalchemy import select` to the imports and this method to `AttemptRepository` after `persist_quiz_correction`:

```python
    def question_result_ids(self, attempt_id: uuid.UUID) -> dict[str, uuid.UUID]:
        """``question_id -> question_results.id`` for one attempt.

        The student self-review routes (spec 2026-09-17) address a question
        by its ``question_results`` row id, so the ``/student/correct``
        complete frame carries one per question. First occurrence wins on a
        duplicated question id, mirroring ``get_question_by_id``'s
        depth-first "first match". Empty for an unknown attempt.
        """
        ids: dict[str, uuid.UUID] = {}
        with self._sm() as session:
            rows = session.execute(
                select(QuestionResult.question_id, QuestionResult.id)
                .where(QuestionResult.attempt_id == attempt_id)
                .order_by(QuestionResult.created_at, QuestionResult.id)
            ).all()
        for question_id, row_id in rows:
            ids.setdefault(question_id, row_id)
        return ids
```

`lemely/web/schemas.py` — add to `QuestionResultDTO` after `topic`:

```python
    questionResultId: str | None = None
    """``question_results.id`` once the attempt is persisted; the address the
    self-review routes take. ``None`` on a frame built before persistence
    (a teacher-console grade, which has no ``question_results`` row)."""
```

and change `question_to_dto`:

```python
def question_to_dto(
    question: CorrectedQuestion, *, question_result_id: str | None = None
) -> QuestionResultDTO:
    """Convert a core :class:`CorrectedQuestion` into a :class:`QuestionResultDTO`."""
    return QuestionResultDTO(
        questionId=question.question_id,
        awardedMarks=question.awarded_marks,
        maxMarks=question.maximum_marks,
        markerSource=question.marker_source,
        confidence=question.confidence_score,
        feedback=question.feedback,
        matchedPointIds=list(question.matched_point_ids) or None,
        reviewReason=question.review_reason,
        plagiarismFlagged=question.plagiarism_flagged,
        aiDetectionFlagged=question.ai_detection_flagged,
        topic=question.topic,
        questionResultId=question_result_id,
    )
```

`lemely/web/routers/student.py` — directly after the `attempt_id = attempt_repo.persist_correction(...)` call (line ~1064) add:

```python
                # The self-review routes address a question by its
                # question_results row id, which only exists once persisted.
                result_ids = attempt_repo.question_result_ids(attempt_id)
```

and replace the `questions=[...]` kwarg in the `complete` `bus.publish(...)` with:

```python
                    questions=[
                        question_to_dto(
                            q,
                            question_result_id=(
                                str(result_ids[q.question_id])
                                if q.question_id in result_ids
                                else None
                            ),
                        ).model_dump(by_alias=True)
                        for q in report.correction.questions
                    ],
```

`web/src/lib/studentTypes.ts` — extend the `QuestionResult` interface:

```ts
export interface QuestionResult extends BaseQuestionResult {
  plagiarismFlagged: boolean
  aiDetectionFlagged: boolean
  /**
   * `question_results.id`, the address the self-review routes take
   * (`/student/attempts/{attemptId}/questions/{questionResultId}/self-review`).
   * Present on every question of a `/student/correct` complete frame since
   * the self-review spec; absent on frames from before it.
   */
  questionResultId?: string | null
}
```

- [ ] **Step 4: Run the touched files**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py tests/test_student_correct.py tests/test_web_student.py tests/test_schemas.py --no-cov -q
cd web && npm run typecheck && cd ..
```

Expected: all passed; typecheck clean.

- [ ] **Step 5: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/attempt_repo.py lemely/web/schemas.py lemely/web/routers/student.py web/src/lib/studentTypes.ts tests/test_attempt_repo.py tests/test_student_correct.py
git commit -S -m "feat(web): complete frame carries questionResultId per question"
```

**Part 1 is shippable here.** Open a PR titled `feat(self-review): backend core — precedence, authority, routes (spec 2026-09-17, part 1/5)`.

---

# Part 2 — The lenient judge

### Task 10: `GeminiEvidenceJudge`, its prompt, its config knob, and its accept-rate log line

**Files:**
- Create: `lemely/io/prompts/self_review_judge.py`
- Create: `lemely/io/evidence_judge.py`
- Modify: `lemely/runtime/config.py:92-164` (`GeminiSettings`: new `self_review_judge_model`, `model_for` mapping)
- Test: `tests/test_evidence_judge.py` (create), `tests/test_config_new_tasks.py` (append)

**Interfaces:**
- Consumes: `JudgeRequest`, `JudgeVerdict` (Task 4); `GeminiClient.generate_structured(system_prompt=, user_prompt=, response_schema=, prompt_version=, task_tag=, extra_cache_key=)` (existing).
- Produces:
  - `GeminiEvidenceJudge(gemini_client: GeminiClient)` with `judge(request: JudgeRequest) -> JudgeVerdict`; `TASK_TAG = "self_review_judge"`. Raises whatever `generate_structured` raises (`ExternalServiceError`, `ParseError`) — the service treats any exception as "unjudged".
  - `JudgeOutcome(StrictModel)`: `accepted: bool`, `reason: str` — the structured response schema.
  - Log event `self_review_judge_verdict` with `subject_code`, `question_id`, `accepted`, `claims_earned` — the accept-rate metric, one line per call from day one.
  - `GeminiSettings.self_review_judge_model: str | None` and `model_for("self_review_judge")`.
  - Prompt module: `VERSION = "1"`, `JUDGE_SYSTEM_PROMPT: str`, `build_judge_user_prompt(request: JudgeRequest) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evidence_judge.py`:

```python
"""``GeminiEvidenceJudge`` — one bounded call per challenged point, Gemini mocked.

The judge is lenient by rule, not by vibe: the prompt instructs "accept
unless the student's evidence is contradicted by their own recorded answer".
These tests pin what the call is given and what it returns; the rule itself
is text in the prompt and is asserted as text.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

from lemely.core.self_review import JudgeRequest, JudgeVerdict
from lemely.io.evidence_judge import GeminiEvidenceJudge, JudgeOutcome
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.self_review_judge import JUDGE_SYSTEM_PROMPT, VERSION, build_judge_user_prompt
from lemely.runtime.errors import ExternalServiceError


def _request(**overrides: object) -> JudgeRequest:
    base: dict[str, object] = {
        "subject_code": "0625",
        "question_id": "3b",
        "point_text": "Gives the unit",
        "mark_type": "B",
        "tariff": 1,
        "student_answer": "F = ma = 2 x 6 = 12 N",
        "marker_rationale": "No unit given.",
        "student_claims_earned": True,
        "student_evidence": "I wrote N after the 12.",
    }
    base.update(overrides)
    return JudgeRequest(**base)  # type: ignore[arg-type]


def test_judge_returns_the_structured_verdict() -> None:
    client = MagicMock(spec=GeminiClient)
    client.generate_structured.return_value = JudgeOutcome(
        accepted=True, reason="The recorded answer does end in N."
    )

    verdict = GeminiEvidenceJudge(client).judge(_request())

    assert verdict == JudgeVerdict(accepted=True, reason="The recorded answer does end in N.")
    kwargs = client.generate_structured.call_args.kwargs
    assert kwargs["response_schema"] is JudgeOutcome
    assert kwargs["prompt_version"] == VERSION
    assert kwargs["task_tag"] == "self_review_judge"
    assert kwargs["system_prompt"] == JUDGE_SYSTEM_PROMPT
    assert "file_paths" not in kwargs  # text only: no scan is ever re-sent to the judge


def test_user_prompt_carries_every_input_and_the_direction() -> None:
    prompt = build_judge_user_prompt(_request())
    for needle in (
        "Gives the unit",
        "B",
        "F = ma = 2 x 6 = 12 N",
        "No unit given.",
        "I wrote N after the 12.",
        "3b",
    ):
        assert needle in prompt
    assert "claims they DID earn" in prompt
    assert "claims they did NOT earn" in build_judge_user_prompt(
        _request(student_claims_earned=False)
    )


def test_prompt_states_the_lenient_rule_as_an_instruction() -> None:
    assert "accept unless" in JUDGE_SYSTEM_PROMPT.lower()
    assert "contradicted" in JUDGE_SYSTEM_PROMPT.lower()


def test_missing_marker_rationale_and_answer_are_stated_not_invented() -> None:
    prompt = build_judge_user_prompt(_request(student_answer=None, marker_rationale=None))
    assert "(no answer was transcribed)" in prompt
    assert "(the marker gave no reason)" in prompt


def test_failures_propagate_to_the_caller() -> None:
    client = MagicMock(spec=GeminiClient)
    client.generate_structured.side_effect = ExternalServiceError("503")
    with pytest.raises(ExternalServiceError):
        GeminiEvidenceJudge(client).judge(_request())


def test_every_verdict_is_logged_with_its_subject_for_the_accept_rate_metric() -> None:
    client = MagicMock(spec=GeminiClient)
    client.generate_structured.return_value = JudgeOutcome(accepted=False, reason="Contradicted.")
    structlog.configure()  # ensure capture_logs sees the module logger
    with capture_logs() as logs:
        GeminiEvidenceJudge(client).judge(_request())
    verdicts = [entry for entry in logs if entry["event"] == "self_review_judge_verdict"]
    assert len(verdicts) == 1
    assert verdicts[0]["subject_code"] == "0625"
    assert verdicts[0]["accepted"] is False
    assert verdicts[0]["claims_earned"] is True


def test_cache_key_is_stable_across_processes() -> None:
    """Two calls with identical inputs must share a cache key (no ``hash()``)."""
    client = MagicMock(spec=GeminiClient)
    client.generate_structured.return_value = JudgeOutcome(accepted=True, reason="ok")
    judge = GeminiEvidenceJudge(client)
    judge.judge(_request())
    judge.judge(_request())
    first, second = (c.kwargs["extra_cache_key"] for c in client.generate_structured.call_args_list)
    assert first == second
    judge.judge(_request(student_evidence="different"))
    assert client.generate_structured.call_args_list[2].kwargs["extra_cache_key"] != first
```

Append to `tests/test_config_new_tasks.py`, inside `class TestModelForNewTags`:

```python
    def test_self_review_judge_falls_back_to_global(self) -> None:
        s = GeminiSettings(model="gemini-2.5-flash")
        assert s.model_for("self_review_judge") == "gemini-2.5-flash"

    def test_self_review_judge_override(self) -> None:
        s = GeminiSettings(self_review_judge_model="gemini-2.5-flash-lite")
        assert s.model_for("self_review_judge") == "gemini-2.5-flash-lite"
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_evidence_judge.py tests/test_config_new_tasks.py -k "judge" -v --no-cov
```

Expected: `ModuleNotFoundError: No module named 'lemely.io.evidence_judge'`; the config test fails with a Pydantic `ValidationError` (`extra_forbidden`) for `self_review_judge_model`.

- [ ] **Step 3: Write the prompt module**

Create `lemely/io/prompts/self_review_judge.py`:

```python
"""Versioned prompt for the lenient self-review evidence judge.

"Lenient" is operational (spec 2026-09-17 self-review, "The lenient judge"):
**accept unless the student's evidence is contradicted by their own recorded
answer.** The burden sits on rejection. Plausible-but-unproven clears the
bar; only a direct contradiction with what they actually wrote does not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lemely.core.self_review import JudgeRequest

VERSION = "1"

JUDGE_SYSTEM_PROMPT = (
    "You are a lenient examiner reviewing a student's challenge to one mark point "
    "on their marked exam answer. You are given the mark point, the marker's reason "
    "for its verdict, the student's transcribed answer exactly as it was marked, and "
    "the student's written case. "
    "Rule: ACCEPT UNLESS the student's case is directly contradicted by their own "
    "recorded answer. A claim that is plausible but not proven by the transcription "
    "is accepted. Reject only when the transcribed answer itself shows the claim to be "
    "false. Never reject for tone, brevity, or because the marker disagreed. "
    "Return ONLY valid JSON matching the JudgeOutcome schema: `accepted` (boolean) and "
    "`reason` (one or two plain sentences addressed to the student, no exclamation "
    "marks)."
)


def build_judge_user_prompt(request: JudgeRequest) -> str:
    """Lay out one challenged point for the judge. Nothing absent is invented."""
    direction = (
        "The student claims they DID earn this point although the marker withheld it."
        if request.student_claims_earned
        else "The student claims they did NOT earn this point although the marker awarded it."
    )
    mark_type = f" (mark type {request.mark_type})" if request.mark_type else ""
    answer = request.student_answer or "(no answer was transcribed)"
    rationale = request.marker_rationale or "(the marker gave no reason)"
    return (
        f"Subject: {request.subject_code}\n"
        f"Question: {request.question_id}\n"
        f"Mark point{mark_type}, worth {request.tariff}: {request.point_text}\n\n"
        f"{direction}\n\n"
        f"Student's transcribed answer:\n{answer}\n\n"
        f"Marker's reason:\n{rationale}\n\n"
        f"Student's case:\n{request.student_evidence}\n\n"
        "Decide: is the student's case contradicted by their own transcribed answer? "
        "If not, accept."
    )


__all__ = ["JUDGE_SYSTEM_PROMPT", "VERSION", "build_judge_user_prompt"]
```

- [ ] **Step 4: Write the judge**

Create `lemely/io/evidence_judge.py`:

```python
"""The lenient evidence judge for student self-review, on Gemini.

One bounded call per challenged point (:class:`JudgeRequest`), returning a
:class:`JudgeVerdict`. Implements :class:`lemely.core.self_review.EvidenceJudge`.

**Failure propagates.** ``generate_structured``'s ``ExternalServiceError`` /
``ParseError`` are not caught here; the service turns any exception into a
``student_evidence_unjudged`` review-queue row. Catching here and returning a
default verdict would be the silent decision the spec forbids.

**The metric.** Every verdict logs ``self_review_judge_verdict`` with the
subject code and the outcome. A judge that accepts everything is
indistinguishable from no guard at all; the accept rate per subject is what
tells the two apart, and it is emitted from the first call.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import structlog

from lemely.core.schemas import StrictModel
from lemely.core.self_review import JudgeVerdict
from lemely.io.prompts.self_review_judge import (
    JUDGE_SYSTEM_PROMPT,
    VERSION,
    build_judge_user_prompt,
)

if TYPE_CHECKING:
    from lemely.core.self_review import JudgeRequest
    from lemely.io.gemini import GeminiClient

log = structlog.get_logger(__name__)

#: ``GeminiSettings.model_for`` tag; ``self_review_judge_model`` overrides the model.
TASK_TAG = "self_review_judge"


class JudgeOutcome(StrictModel):
    """The judge's structured answer."""

    accepted: bool
    reason: str


class GeminiEvidenceJudge:
    """Judge one challenged mark point with a single Gemini call."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        """Decide one challenged point. Raises on any Gemini failure."""
        digest = hashlib.sha256(
            "\x1f".join(
                (
                    request.subject_code,
                    request.question_id,
                    request.point_text,
                    request.student_answer or "",
                    request.student_evidence,
                    "earned" if request.student_claims_earned else "not_earned",
                )
            ).encode()
        ).hexdigest()[:24]
        outcome = self._client.generate_structured(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=build_judge_user_prompt(request),
            response_schema=JudgeOutcome,
            prompt_version=VERSION,
            task_tag=TASK_TAG,
            extra_cache_key=digest,
        )
        log.info(
            "self_review_judge_verdict",
            subject_code=request.subject_code,
            question_id=request.question_id,
            accepted=outcome.accepted,
            claims_earned=request.student_claims_earned,
        )
        return JudgeVerdict(accepted=outcome.accepted, reason=outcome.reason)


__all__ = ["TASK_TAG", "GeminiEvidenceJudge", "JudgeOutcome"]
```

- [ ] **Step 5: Add the config knob**

In `lemely/runtime/config.py`, inside `GeminiSettings` after `scan_metadata_model: str | None = None` add:

```python
    self_review_judge_model: str | None = None
```

and in `model_for`'s `mapping` add:

```python
            "self_review_judge": self.self_review_judge_model,
```

- [ ] **Step 6: Run the tests**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_evidence_judge.py tests/test_config_new_tasks.py tests/test_config.py --no-cov -q
```

Expected: all passed. (`tests/test_config.py` may not exist; if `pytest` reports "file not found" for it, drop it from the command.)

- [ ] **Step 7: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/io/prompts/self_review_judge.py lemely/io/evidence_judge.py lemely/runtime/config.py tests/test_evidence_judge.py tests/test_config_new_tasks.py
git commit -S -m "feat(io): lenient Gemini evidence judge for student self-review"
```

---

### Task 11: Wire the judge into the service dependency

**Files:**
- Modify: `lemely/web/deps.py` (`get_self_review_service` from Task 8; new `build_self_review_judge`)
- Test: `tests/test_deps_self_review.py` (create)

**Interfaces:**
- Produces: `build_self_review_judge(settings: Settings, gemini_client: GeminiClient) -> EvidenceJudge | None` in `lemely/web/deps.py` — a `GeminiEvidenceJudge` when `settings.gemini_api_key` is set, else `None`. `get_self_review_service` uses it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_deps_self_review.py`:

```python
"""``get_self_review_service``'s judge wiring: a judge only when a key exists.

Without a Gemini key the service must run with ``judge=None`` — every
evidence-backed challenge then lands in the teacher queue as
``student_evidence_unjudged`` — rather than constructing a client that would
fail on first use and turn an infrastructure gap into a silent verdict.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from lemely.io.evidence_judge import GeminiEvidenceJudge
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings
from lemely.web.deps import build_self_review_judge


def _settings(*, key: str | None) -> Settings:
    data = Settings().model_dump()
    data["gemini_api_key"] = key
    return Settings.model_validate(data)


def test_no_key_means_no_judge() -> None:
    assert build_self_review_judge(_settings(key=None), MagicMock(spec=GeminiClient)) is None


def test_a_key_means_the_gemini_judge() -> None:
    judge = build_self_review_judge(_settings(key="test-key"), MagicMock(spec=GeminiClient))
    assert isinstance(judge, GeminiEvidenceJudge)
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_deps_self_review.py -v --no-cov
```

Expected: `ImportError: cannot import name 'build_self_review_judge'`.

- [ ] **Step 3: Implement**

In `lemely/web/deps.py`, add `from lemely.io.evidence_judge import GeminiEvidenceJudge` and `from lemely.core.self_review import EvidenceJudge` (the latter inside the existing `if TYPE_CHECKING:` block if one exists, else at top level) and replace `get_self_review_service`:

```python
def build_self_review_judge(settings: Settings, gemini_client: GeminiClient) -> EvidenceJudge | None:
    """The lenient judge, or ``None`` when no Gemini key is configured.

    ``None`` is a first-class state for :class:`SelfReviewService`: every
    evidence-backed challenge becomes a ``student_evidence_unjudged`` queue
    row for a teacher. Constructing a client that would fail on first use
    instead would surface the same gap as a judge failure per call — noisier,
    and no more honest.
    """
    if settings.gemini_api_key is None:
        return None
    return GeminiEvidenceJudge(gemini_client)


@lru_cache(maxsize=1)
def get_self_review_service() -> SelfReviewService:
    """Return the process-wide :class:`SelfReviewService` singleton.

    The judge is :func:`build_self_review_judge` over the shared
    :func:`get_gemini_client` (``ledger=None``, DS3 — one call per challenged
    point is the only budget; the cloud billing budget is the guard).
    """
    settings = get_settings()
    return SelfReviewService(
        get_sessionmaker(settings),
        judge=build_self_review_judge(settings, get_gemini_client()),
    )
```

- [ ] **Step 4: Run the tests and the endpoint tests (whose override is unaffected)**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_deps_self_review.py tests/test_student_self_review_web.py --no-cov -q
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/web/deps.py tests/test_deps_self_review.py
git commit -S -m "feat(web): wire the Gemini evidence judge into the self-review service"
```

**Part 2 is shippable here** (`feat(self-review): lenient judge (part 2/5)`).

---

# Part 3 — Frontend

### Task 12: Wire types and the pure self-review state helpers

**Files:**
- Create: `web/src/lib/selfReviewTypes.ts`
- Create: `web/src/lib/selfReview.ts`
- Test: `web/tests/unit/selfReview.test.ts` (create)

**Interfaces:**
- Consumes: the wire shapes of Task 8.
- Produces (`web/src/lib/selfReviewTypes.ts`): `EvidenceVerdict`, `SelfReviewPendingPoint`, `SelfReviewRevealedPoint`, `SelfReviewPending`, `SelfReviewRevealed`, `SelfReview`, `SelfReviewPointVerdict`, `SelfReviewSubmission`.
- Produces (`web/src/lib/selfReview.ts`): `SelfReviewPhase`, `SelfReviewDraft`, `EMPTY_DRAFT`, `setVerdict(draft, markPointId, earned)`, `setEvidence(draft, markPointId, text)`, `isComplete(draft, points)`, `toSubmission(draft, points)`, `phaseOf(view, draft)`, `PointOutcome`, `pointOutcome(point, view)`, `outcomeSummary(view)`, `OUTCOME_LABEL`, `outcomeDetail(point, outcome, evidenceRequired)`, `evidenceHint(evidenceRequired)`, `summaryLine(view)`, `UNAVAILABLE_COPY`. Task 14 renders exactly these.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/selfReview.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import type {
  SelfReviewPending,
  SelfReviewRevealed,
  SelfReviewRevealedPoint,
} from "@/lib/selfReviewTypes"
import {
  EMPTY_DRAFT,
  OUTCOME_LABEL,
  UNAVAILABLE_COPY,
  evidenceHint,
  isComplete,
  outcomeDetail,
  outcomeSummary,
  phaseOf,
  pointOutcome,
  setEvidence,
  setVerdict,
  summaryLine,
  toSubmission,
} from "@/lib/selfReview"

/*
 * Pure logic for the self-review panel (spec 2026-09-17). Every branch
 * carries its inverse so a helper that returns one thing unconditionally
 * cannot pass.
 */

const points = [
  { markPointId: "p1", ordinal: 0, markType: "M", tariff: 1, pointText: "Correct method" },
  { markPointId: "p2", ordinal: 1, markType: "A", tariff: 1, pointText: "Answer to 3sf" },
]

function pending(overrides: Partial<SelfReviewPending> = {}): SelfReviewPending {
  return {
    state: "not_started",
    attemptId: "a1",
    questionResultId: "q1",
    questionId: "1a",
    maxMarks: 2,
    evidenceRequired: false,
    points,
    ...overrides,
  }
}

function revealedPoint(overrides: Partial<SelfReviewRevealedPoint> = {}): SelfReviewRevealedPoint {
  return {
    ...points[0],
    awarded: false,
    studentSelfmark: true,
    studentEvidence: null,
    evidenceVerdict: null,
    markChanged: false,
    judgeReason: null,
    ...overrides,
  }
}

function revealed(overrides: Partial<SelfReviewRevealed> = {}): SelfReviewRevealed {
  return {
    state: "settled",
    attemptId: "a1",
    questionResultId: "q1",
    questionId: "1a",
    maxMarks: 2,
    evidenceRequired: true,
    aiMarks: 1,
    effectiveMarks: 1,
    studentMarks: null,
    teacherSettled: false,
    pendingTeacher: false,
    submittedAt: "2026-09-18T10:00:00Z",
    points: [revealedPoint()],
    ...overrides,
  }
}

describe("draft editing", () => {
  it("records a verdict per point without mutating the previous draft", () => {
    const next = setVerdict(EMPTY_DRAFT, "p1", true)
    expect(next.verdicts).toEqual({ p1: true })
    expect(EMPTY_DRAFT.verdicts).toEqual({})
  })

  it("records evidence per point", () => {
    expect(setEvidence(EMPTY_DRAFT, "p2", "I wrote it").evidence).toEqual({ p2: "I wrote it" })
  })

  it("is complete only when every point has a boolean verdict", () => {
    expect(isComplete(EMPTY_DRAFT, points)).toBe(false)
    expect(isComplete(setVerdict(EMPTY_DRAFT, "p1", true), points)).toBe(false)
    const both = setVerdict(setVerdict(EMPTY_DRAFT, "p1", true), "p2", false)
    expect(isComplete(both, points)).toBe(true)
    expect(isComplete(both, [])).toBe(false)
  })
})

describe("toSubmission", () => {
  it("sends every point, trimming evidence and omitting it when blank", () => {
    let draft = setVerdict(setVerdict(EMPTY_DRAFT, "p1", true), "p2", false)
    draft = setEvidence(setEvidence(draft, "p1", "  see line 2  "), "p2", "   ")
    expect(toSubmission(draft, points)).toEqual({
      points: [
        { markPointId: "p1", earned: true, evidence: "see line 2" },
        { markPointId: "p2", earned: false },
      ],
    })
  })

  it("refuses an incomplete draft rather than sending a partial pass", () => {
    expect(() => toSubmission(setVerdict(EMPTY_DRAFT, "p1", true), points)).toThrow(
      /every point/i,
    )
  })
})

describe("phaseOf", () => {
  it("is not_started with no view or an untouched draft", () => {
    expect(phaseOf(undefined, EMPTY_DRAFT)).toBe("not_started")
    expect(phaseOf(pending(), EMPTY_DRAFT)).toBe("not_started")
  })

  it("is self_marking once any verdict is chosen", () => {
    expect(phaseOf(pending(), setVerdict(EMPTY_DRAFT, "p1", false))).toBe("self_marking")
  })

  it("mirrors the server state after submission regardless of the draft", () => {
    expect(phaseOf(revealed({ state: "revealed" }), setVerdict(EMPTY_DRAFT, "p1", true))).toBe(
      "revealed",
    )
    expect(phaseOf(revealed({ state: "settled" }), EMPTY_DRAFT)).toBe("settled")
  })
})

describe("pointOutcome", () => {
  it("agreed when the two verdicts match, whichever way", () => {
    expect(pointOutcome(revealedPoint({ awarded: true, studentSelfmark: true }), revealed())).toBe(
      "agreed",
    )
    expect(pointOutcome(revealedPoint({ awarded: false, studentSelfmark: false }), revealed())).toBe(
      "agreed",
    )
  })

  it("changed when the disagreement was granted", () => {
    expect(
      pointOutcome(revealedPoint({ markChanged: true, evidenceVerdict: "not_required" }), revealed()),
    ).toBe("changed")
  })

  it("pending only for an unjudged, evidenced claim while a teacher is waiting", () => {
    const unjudged = revealedPoint({ studentEvidence: "because", evidenceVerdict: null })
    expect(pointOutcome(unjudged, revealed({ pendingTeacher: true }))).toBe("pending")
    expect(pointOutcome(unjudged, revealed({ pendingTeacher: false }))).toBe("kept")
    // No evidence: nothing was ever sent to a judge, so nothing is pending.
    expect(pointOutcome(revealedPoint(), revealed({ pendingTeacher: true }))).toBe("kept")
  })

  it("kept for a rejected claim", () => {
    expect(
      pointOutcome(revealedPoint({ studentEvidence: "x", evidenceVerdict: "rejected" }), revealed()),
    ).toBe("kept")
  })
})

describe("outcome copy", () => {
  it("shows the judge's reason when there is one, in both directions", () => {
    const accepted = revealedPoint({
      markChanged: true,
      evidenceVerdict: "accepted",
      judgeReason: "The unit is there.",
    })
    expect(outcomeDetail(accepted, "changed", true)).toBe("The unit is there.")
    const rejected = revealedPoint({ evidenceVerdict: "rejected", judgeReason: "No unit at all." })
    expect(outcomeDetail(rejected, "kept", true)).toBe("No unit at all.")
  })

  it("explains a low-confidence grant and an unevidenced high-confidence claim", () => {
    expect(
      outcomeDetail(revealedPoint({ markChanged: true, evidenceVerdict: "not_required" }), "changed", false),
    ).toMatch(/not sure/)
    expect(outcomeDetail(revealedPoint(), "kept", true)).toMatch(/give a reason/)
    expect(outcomeDetail(revealedPoint(), "kept", false)).toBeNull()
    expect(outcomeDetail(revealedPoint({ awarded: true }), "agreed", true)).toBeNull()
  })

  it("summarises outcomes and the marks movement", () => {
    const view = revealed({
      aiMarks: 0,
      effectiveMarks: 2,
      studentMarks: 2,
      points: [
        revealedPoint({ markChanged: true, evidenceVerdict: "not_required" }),
        revealedPoint({ ...points[1], markChanged: true, evidenceVerdict: "not_required" }),
      ],
    })
    expect(outcomeSummary(view)).toEqual({ agreed: 0, changed: 2, kept: 0, pending: 0 })
    expect(summaryLine(view)).toBe("Your self-mark moved this question from 0 to 2 out of 2.")
    expect(summaryLine(revealed())).toBe("This question stays at 1 out of 2.")
    expect(summaryLine(revealed({ teacherSettled: true }))).toMatch(/teacher has already/)
  })

  it("names the evidence rule per confidence, and never an integrity flag", () => {
    expect(evidenceHint(true)).toMatch(/confident/)
    expect(evidenceHint(false)).toMatch(/your verdict counts/i)
    const allCopy = [
      evidenceHint(true),
      evidenceHint(false),
      UNAVAILABLE_COPY,
      ...Object.values(OUTCOME_LABEL),
    ].join(" ")
    expect(allCopy).not.toMatch(/plagiar|AI-generated|cheat/i)
    // REDESIGN-MISSION §3.2 item 10: no em dashes, no exclamation marks in copy.
    expect(allCopy).not.toMatch(/[—!]/)
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && npx vitest run tests/unit/selfReview.test.ts
```

Expected: FAIL — `Cannot find module '@/lib/selfReview'`.

- [ ] **Step 3: Write the types**

Create `web/src/lib/selfReviewTypes.ts`:

```ts
/*
 * TS interfaces mirroring `lemely/web/schemas_student_self_review.py`
 * (student self-review, spec 2026-09-17). camelCase to match the wire.
 *
 * Two shapes, deliberately: `SelfReviewPending` is what the server sends
 * BEFORE the student commits to their own verdicts and its point type has no
 * `awarded` at all. The verdict exists only on `SelfReviewRevealed`. If a
 * field named `awarded` ever appears on the pending shape here, the backend
 * contract has been broken, not extended.
 */

export type EvidenceVerdict = "accepted" | "rejected" | "not_required"

export interface SelfReviewPendingPoint {
  markPointId: string
  ordinal: number
  /** `MathMarkType` letter (M/A/B/...) or null for non-maths questions. */
  markType: string | null
  tariff: number
  pointText: string
}

export interface SelfReviewRevealedPoint extends SelfReviewPendingPoint {
  awarded: boolean
  studentSelfmark: boolean
  studentEvidence: string | null
  evidenceVerdict: EvidenceVerdict | null
  markChanged: boolean
  judgeReason: string | null
}

interface SelfReviewBase {
  attemptId: string
  questionResultId: string
  questionId: string
  maxMarks: number
  /**
   * True when the marker was confident: a self-mark alone changes nothing,
   * and a written reason is what unlocks a (lenient) judge. False when the
   * marker was unsure: the student's verdict counts, reason optional.
   */
  evidenceRequired: boolean
}

export interface SelfReviewPending extends SelfReviewBase {
  state: "not_started"
  points: SelfReviewPendingPoint[]
}

export interface SelfReviewRevealed extends SelfReviewBase {
  /** `revealed` while a teacher still has to look at an unjudged claim. */
  state: "revealed" | "settled"
  aiMarks: number
  effectiveMarks: number
  studentMarks: number | null
  teacherSettled: boolean
  pendingTeacher: boolean
  submittedAt: string
  points: SelfReviewRevealedPoint[]
}

export type SelfReview = SelfReviewPending | SelfReviewRevealed

export interface SelfReviewPointVerdict {
  markPointId: string
  earned: boolean
  evidence?: string
}

/** `POST` body: a verdict for EVERY point. Partial passes are refused (422). */
export interface SelfReviewSubmission {
  points: SelfReviewPointVerdict[]
}
```

- [ ] **Step 4: Write the helpers**

Create `web/src/lib/selfReview.ts`:

```ts
import type {
  SelfReview,
  SelfReviewRevealed,
  SelfReviewRevealedPoint,
  SelfReviewSubmission,
} from "./selfReviewTypes"

/*
 * Pure state for the self-review panel (spec 2026-09-17), kept out of the
 * component so it is testable without jsdom (`web/vitest.config.ts` is
 * Node-only). The panel in `portals/student/components/SelfReviewPanel.tsx`
 * renders exactly what these return.
 *
 * Phases: `not_started` -> `self_marking` (client-only: the student has begun
 * choosing verdicts) -> `revealed` / `settled` (the server's own states).
 */

export type SelfReviewPhase = "not_started" | "self_marking" | "revealed" | "settled"

export interface SelfReviewDraft {
  readonly verdicts: Readonly<Record<string, boolean>>
  readonly evidence: Readonly<Record<string, string>>
}

export const EMPTY_DRAFT: SelfReviewDraft = { verdicts: {}, evidence: {} }

export function setVerdict(
  draft: SelfReviewDraft,
  markPointId: string,
  earned: boolean,
): SelfReviewDraft {
  return { ...draft, verdicts: { ...draft.verdicts, [markPointId]: earned } }
}

export function setEvidence(
  draft: SelfReviewDraft,
  markPointId: string,
  text: string,
): SelfReviewDraft {
  return { ...draft, evidence: { ...draft.evidence, [markPointId]: text } }
}

/** Every point has a verdict. The server refuses anything less (422). */
export function isComplete(
  draft: SelfReviewDraft,
  points: readonly { markPointId: string }[],
): boolean {
  return (
    points.length > 0 && points.every((p) => typeof draft.verdicts[p.markPointId] === "boolean")
  )
}

export function toSubmission(
  draft: SelfReviewDraft,
  points: readonly { markPointId: string }[],
): SelfReviewSubmission {
  if (!isComplete(draft, points)) {
    throw new Error("Every point needs a verdict before submitting")
  }
  return {
    points: points.map((p) => {
      const earned = draft.verdicts[p.markPointId] as boolean
      const evidence = (draft.evidence[p.markPointId] ?? "").trim()
      return evidence ? { markPointId: p.markPointId, earned, evidence } : { markPointId: p.markPointId, earned }
    }),
  }
}

export function phaseOf(view: SelfReview | undefined, draft: SelfReviewDraft): SelfReviewPhase {
  if (!view) return "not_started"
  if (view.state !== "not_started") return view.state
  return Object.keys(draft.verdicts).length > 0 ? "self_marking" : "not_started"
}

export type PointOutcome = "agreed" | "changed" | "kept" | "pending"

/**
 * `pending` is narrow on purpose: only a claim that was actually sent for
 * judging (it carried evidence), came back unjudged, and has an open teacher
 * row behind it. A bare disagreement with no reason was never pending.
 */
export function pointOutcome(
  point: SelfReviewRevealedPoint,
  view: Pick<SelfReviewRevealed, "pendingTeacher">,
): PointOutcome {
  if (point.studentSelfmark === point.awarded) return "agreed"
  if (point.markChanged) return "changed"
  if (view.pendingTeacher && point.evidenceVerdict === null && point.studentEvidence !== null) {
    return "pending"
  }
  return "kept"
}

export function outcomeSummary(view: SelfReviewRevealed): Record<PointOutcome, number> {
  const summary: Record<PointOutcome, number> = { agreed: 0, changed: 0, kept: 0, pending: 0 }
  for (const point of view.points) summary[pointOutcome(point, view)] += 1
  return summary
}

export const OUTCOME_LABEL: Record<PointOutcome, string> = {
  agreed: "You and the marker agree",
  changed: "Your mark was applied",
  kept: "The marker's mark stands",
  pending: "A teacher will look at this",
}

/** One short line under a point, or null when the label says it all. */
export function outcomeDetail(
  point: SelfReviewRevealedPoint,
  outcome: PointOutcome,
  evidenceRequired: boolean,
): string | null {
  switch (outcome) {
    case "agreed":
      return null
    case "changed":
      if (point.evidenceVerdict === "accepted") return point.judgeReason ?? "Your reason was accepted."
      return "The marker was not sure about this question, so your verdict counts."
    case "kept":
      if (point.evidenceVerdict === "rejected") return point.judgeReason ?? "Your reason was not accepted."
      return evidenceRequired ? "To challenge a confident mark you need to give a reason." : null
    case "pending":
      return "Your reason could not be checked automatically. A teacher will look at it."
  }
}

export function evidenceHint(evidenceRequired: boolean): string {
  return evidenceRequired
    ? "The marker was confident here. To challenge a point, say what in your answer earns it."
    : "The marker was not sure about this question, so your verdict counts. Adding a reason is optional."
}

export function summaryLine(view: SelfReviewRevealed): string {
  if (view.teacherSettled) {
    return "A teacher has already reviewed this question, so their mark stands."
  }
  if (view.effectiveMarks !== view.aiMarks) {
    return `Your self-mark moved this question from ${view.aiMarks} to ${view.effectiveMarks} out of ${view.maxMarks}.`
  }
  return `This question stays at ${view.effectiveMarks} out of ${view.maxMarks}.`
}

/**
 * Shown when the server has no point rows for the question (404): a paper
 * corrected before the per-point breakdown existed, or a quiz. Said plainly
 * rather than leaving a student to wonder why one paper offers this and an
 * older one does not (spec "Open items").
 */
export const UNAVAILABLE_COPY =
  "Self-review is not available for this paper. It is offered on papers marked after the per-point breakdown was introduced."
```

- [ ] **Step 5: Run the tests, typecheck and lint**

```bash
cd web && npx vitest run tests/unit/selfReview.test.ts && npm run typecheck && npm run lint
```

Expected: 14 tests passed; typecheck and lint clean.

- [ ] **Step 6: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add web/src/lib/selfReviewTypes.ts web/src/lib/selfReview.ts web/tests/unit/selfReview.test.ts
git commit -S -m "feat(web): self-review wire types and pure draft/outcome helpers"
```

---

### Task 13: React-query hooks for the two routes

**Files:**
- Create: `web/src/lib/hooks/useSelfReviewApi.ts`

**Interfaces:**
- Consumes: `request`, `ApiError` (`web/src/lib/api.ts`); the types of Task 12.
- Produces: `selfReviewKey(attemptId, questionResultId)`, `useSelfReview(attemptId, questionResultId): UseQueryResult<SelfReview, Error>`, `useSubmitSelfReview(): UseMutationResult<SelfReviewRevealed, Error, SubmitSelfReviewInput>` with `SubmitSelfReviewInput = { attemptId: string; questionResultId: string; submission: SelfReviewSubmission }`. Task 14 uses both hooks.

- [ ] **Step 1: Write the hooks**

Create `web/src/lib/hooks/useSelfReviewApi.ts`:

```ts
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
import type { SelfReview, SelfReviewRevealed, SelfReviewSubmission } from "@/lib/selfReviewTypes"

/*
 * React-query hooks for `/api/student/attempts/{a}/questions/{q}/self-review`
 * (spec 2026-09-17), following `useStudentApi.ts`'s conventions: one hook per
 * endpoint, no `fallback` passed to `request()`, so a real failure surfaces
 * as an error the panel renders rather than as empty data.
 */

export const selfReviewKey = (attemptId: string, questionResultId: string) =>
  ["student", "selfReview", attemptId, questionResultId] as const

function selfReviewPath(attemptId: string, questionResultId: string): string {
  return `/student/attempts/${encodeURIComponent(attemptId)}/questions/${encodeURIComponent(questionResultId)}/self-review`
}

/**
 * `GET`. A 404 is a real, final answer ("no point rows: not self-reviewable"),
 * so it is not retried; `SelfReviewPanel` renders `UNAVAILABLE_COPY` for it.
 */
export function useSelfReview(
  attemptId: string,
  questionResultId: string,
): UseQueryResult<SelfReview, Error> {
  return useQuery({
    queryKey: selfReviewKey(attemptId, questionResultId),
    queryFn: () => request<SelfReview>(selfReviewPath(attemptId, questionResultId)),
    enabled: !!attemptId && !!questionResultId,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  })
}

export interface SubmitSelfReviewInput {
  attemptId: string
  questionResultId: string
  submission: SelfReviewSubmission
}

/**
 * `POST`. On success the revealed view replaces the cached pending one in
 * place, and every total-bearing student surface is invalidated: a granted
 * self-mark moves the attempt's marks, percentage and grade (spec D5).
 */
export function useSubmitSelfReview(): UseMutationResult<
  SelfReviewRevealed,
  Error,
  SubmitSelfReviewInput
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ attemptId, questionResultId, submission }: SubmitSelfReviewInput) =>
      request<SelfReviewRevealed>(selfReviewPath(attemptId, questionResultId), {
        method: "POST",
        body: JSON.stringify(submission),
      }),
    onSuccess: (data, { attemptId, questionResultId }) => {
      queryClient.setQueryData(selfReviewKey(attemptId, questionResultId), data)
      queryClient.invalidateQueries({ queryKey: ["student", "overview"] })
      queryClient.invalidateQueries({ queryKey: ["student", "subject"] })
      queryClient.invalidateQueries({ queryKey: ["student", "result"] })
    },
  })
}
```

- [ ] **Step 2: Typecheck and lint**

```bash
cd web && npm run typecheck && npm run lint
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add web/src/lib/hooks/useSelfReviewApi.ts
git commit -S -m "feat(web): self-review query and submit hooks"
```

---

### Task 14: `SelfReviewPanel`

**Files:**
- Create: `web/src/portals/student/components/SelfReviewPanel.tsx`

**Interfaces:**
- Consumes: Task 12 helpers and types, Task 13 hooks; `Button`, `Chip`, `ListSkeleton`, `Radio`, `RadioGroup`, `Textarea`, `useToast` from `@/components/ui/*`; `ApiError`.
- Produces: `SelfReviewPanel({ attemptId, questionResultId }: { attemptId: string; questionResultId: string })`. Rendered by Task 15 inside a `QuestionRow`'s expanded slot. Test ids: `self-review-form`, `self-review-outcome`, `self-review-unavailable`.

- [ ] **Step 1: Write the component**

Create `web/src/portals/student/components/SelfReviewPanel.tsx`:

```tsx
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { Radio, RadioGroup } from "@/components/ui/radio"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import { useSelfReview, useSubmitSelfReview } from "@/lib/hooks/useSelfReviewApi"
import {
  EMPTY_DRAFT,
  OUTCOME_LABEL,
  UNAVAILABLE_COPY,
  evidenceHint,
  isComplete,
  outcomeDetail,
  outcomeSummary,
  pointOutcome,
  setEvidence,
  setVerdict,
  summaryLine,
  toSubmission,
  type PointOutcome,
  type SelfReviewDraft,
} from "@/lib/selfReview"
import type { SelfReviewPending, SelfReviewRevealed } from "@/lib/selfReviewTypes"

/*
 * Student self-review of one marked question (spec 2026-09-17), rendered in
 * a `QuestionRow`'s expanded slot on `PaperResult`.
 *
 * The panel never decides anything. Before submission the server sends no
 * verdict at all (`SelfReviewPending` has no `awarded`), so there is nothing
 * here to hide; after it, the server has already applied the authority rule
 * and this renders the outcome. One pass per question is enforced server-side
 * (a second POST is a 409), and the form disappears the moment the first one
 * succeeds because the cached view flips to `revealed`/`settled`.
 *
 * Copy: no integrity flag is ever named here (QUALITY-BAR.md), and per
 * REDESIGN-MISSION §3.2 item 10 there are no em dashes or exclamation marks.
 */

const OUTCOME_TONE: Record<PointOutcome, "ok" | "warn" | "neutral" | "info"> = {
  agreed: "neutral",
  changed: "ok",
  kept: "warn",
  pending: "info",
}

function verdictValue(earned: boolean | undefined): string | undefined {
  if (earned === undefined) return undefined
  return earned ? "earned" : "missed"
}

export function SelfReviewPanel({
  attemptId,
  questionResultId,
}: {
  attemptId: string
  questionResultId: string
}) {
  const query = useSelfReview(attemptId, questionResultId)
  const submit = useSubmitSelfReview()
  const { toast } = useToast()
  const [draft, setDraft] = useState<SelfReviewDraft>(EMPTY_DRAFT)

  if (query.isPending) return <ListSkeleton rows={2} />
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return (
        <p className="text-body-sm text-ink-muted" data-testid="self-review-unavailable">
          {UNAVAILABLE_COPY}
        </p>
      )
    }
    return (
      <p className="text-body-sm text-err">We couldn't load the self-review for this question.</p>
    )
  }

  const view = query.data
  if (view.state === "not_started") {
    return (
      <PendingForm
        view={view}
        draft={draft}
        onDraft={setDraft}
        submitting={submit.isPending}
        onSubmit={() =>
          submit.mutate(
            { attemptId, questionResultId, submission: toSubmission(draft, view.points) },
            {
              onError: (error) =>
                toast({
                  title:
                    error instanceof ApiError && error.status === 409
                      ? "This question has already been self-marked."
                      : "We couldn't submit your self-mark. Please try again.",
                }),
            },
          )
        }
      />
    )
  }
  return <RevealedOutcome view={view} />
}

function PendingForm({
  view,
  draft,
  onDraft,
  submitting,
  onSubmit,
}: {
  view: SelfReviewPending
  draft: SelfReviewDraft
  onDraft: (next: SelfReviewDraft) => void
  submitting: boolean
  onSubmit: () => void
}) {
  const complete = isComplete(draft, view.points)
  return (
    <form
      className="flex flex-col gap-4"
      data-testid="self-review-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (complete && !submitting) onSubmit()
      }}
    >
      <div className="flex flex-col gap-1">
        <h3 className="text-label text-ink">Mark your own answer first</h3>
        <p className="max-w-[56ch] text-pretty text-body-sm text-ink-muted">
          {evidenceHint(view.evidenceRequired)} The marker's verdict is revealed once you submit,
          and you can only do this once.
        </p>
      </div>
      {view.points.map((point) => (
        <div
          key={point.markPointId}
          className="flex flex-col gap-2 rounded-md bg-paper-sunk px-3.5 py-3"
        >
          <RadioGroup
            label={`${point.pointText} (${point.tariff} ${point.tariff === 1 ? "mark" : "marks"})`}
            value={verdictValue(draft.verdicts[point.markPointId])}
            onValueChange={(value) => onDraft(setVerdict(draft, point.markPointId, value === "earned"))}
            orientation="horizontal"
          >
            <Radio value="earned" label="I earned this" />
            <Radio value="missed" label="I did not earn this" />
          </RadioGroup>
          <Textarea
            label={
              view.evidenceRequired ? "Why? (needed to challenge the marker)" : "Why? (optional)"
            }
            rows={2}
            maxLength={2000}
            value={draft.evidence[point.markPointId] ?? ""}
            onChange={(event) => onDraft(setEvidence(draft, point.markPointId, event.target.value))}
          />
        </div>
      ))}
      <Button
        type="submit"
        variant="primary"
        disabled={!complete || submitting}
        loading={submitting}
        className="self-start"
      >
        Submit and reveal the marker's verdict
      </Button>
    </form>
  )
}

function RevealedOutcome({ view }: { view: SelfReviewRevealed }) {
  const summary = outcomeSummary(view)
  return (
    <div className="flex flex-col gap-3" data-testid="self-review-outcome">
      <p className="text-body-md text-ink">{summaryLine(view)}</p>
      <ul className="flex flex-col gap-2">
        {view.points.map((point) => {
          const outcome = pointOutcome(point, view)
          const detail = outcomeDetail(point, outcome, view.evidenceRequired)
          return (
            <li
              key={point.markPointId}
              className="flex flex-col gap-1.5 rounded-md bg-paper-sunk px-3.5 py-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-body-md text-ink">{point.pointText}</span>
                <Chip tone={OUTCOME_TONE[outcome]}>{OUTCOME_LABEL[outcome]}</Chip>
              </div>
              <div className="flex flex-wrap gap-3 text-body-sm text-ink-muted">
                <span>Marker: {point.awarded ? "awarded" : "not awarded"}</span>
                <span>You: {point.studentSelfmark ? "earned" : "not earned"}</span>
              </div>
              {detail ? <p className="text-body-sm text-ink-muted">{detail}</p> : null}
              {point.studentEvidence ? (
                <p className="text-body-sm text-ink-faint">Your reason: {point.studentEvidence}</p>
              ) : null}
            </li>
          )
        })}
      </ul>
      {view.pendingTeacher ? (
        <p className="text-body-sm text-info">
          {summary.pending === 1
            ? "One point is waiting for a teacher."
            : `${summary.pending} points are waiting for a teacher.`}
        </p>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 2: Typecheck, lint, copy gate**

```bash
cd web && npm run typecheck && npm run lint && npm run check:copy
```

Expected: clean. If `check:copy` reports a line in this file, the copy contains an em dash or exclamation mark — rewrite that sentence with a comma or full stop.

- [ ] **Step 3: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add web/src/portals/student/components/SelfReviewPanel.tsx
git commit -S -m "feat(ui): SelfReviewPanel for the paper-result question rows"
```

---

### Task 15: Mount the panel on `PaperResult` from the live result

**Files:**
- Modify: `web/src/lib/studentTypes.ts` (`Result` interface, ~line 180)
- Modify: `web/src/portals/student/screens/CorrectPaper.tsx:567-586` (the `assembled` object)
- Modify: `web/src/portals/student/screens/PaperResult.tsx` (`QuestionList` props/rows; the live branch)

**Interfaces:**
- Consumes: `SelfReviewPanel` (Task 14); `QuestionResult.questionResultId` (Task 9); the SSE frame's `attempt_id` (existing).
- Produces: `Result.attemptId?: string | null` (Part 4's backend fills it for history results); `QuestionList` gains `attemptId?: string | null`; a row renders `<SelfReviewPanel>` when both `attemptId` and `q.questionResultId` are present.

- [ ] **Step 1: Extend the `Result` type**

In `web/src/lib/studentTypes.ts`, add to `interface Result` after `provenance: string`:

```ts
  /**
   * `attempts.id` for this result. Set on the live result from the
   * `/student/correct` complete frame's `attempt_id` (CorrectPaper), and by
   * `GET /student/result/{paperId}` once the backend carries it (self-review
   * plan, Part 4). Absent on older frames and on file-store history records,
   * which is exactly when the self-review panel must not render.
   */
  attemptId?: string | null
```

- [ ] **Step 2: Carry `attemptId` into the live state**

In `web/src/portals/student/screens/CorrectPaper.tsx`, inside the `assembled` object add after `provenance: "",`:

```ts
          attemptId: frame.attempt_id ?? null,
```

- [ ] **Step 3: Render the panel per row**

In `web/src/portals/student/screens/PaperResult.tsx`:

Add the import next to the other component imports:

```tsx
import { SelfReviewPanel } from "@/portals/student/components/SelfReviewPanel"
```

Extend `QuestionList`'s props (both the type and the destructuring) with:

```tsx
  /**
   * Self-review (spec 2026-09-17): when the result knows its attempt and a
   * row knows its `question_results` id, the row's expanded slot carries the
   * self-mark panel. Both come from the backend, never guessed here, so a
   * history record from before either existed simply renders no panel.
   */
  attemptId?: string | null
```

and inside the row's `<div className="flex flex-col gap-2.5">` (after the `reviewReason` block) add:

```tsx
              {attemptId && q.questionResultId ? (
                <SelfReviewPanel attemptId={attemptId} questionResultId={q.questionResultId} />
              ) : null}
```

In the live branch pass it through:

```tsx
        <QuestionList
          questions={live.questions}
          subjectCode={live.code.split("/")[0]}
          onShare={shareHandler(live)}
          filter={filter}
          onFilterChange={setFilter}
          attemptId={live.attemptId}
        />
```

(The history branch keeps `questions={[]}` until Task 18.)

- [ ] **Step 4: Typecheck, lint, unit suite**

```bash
cd web && npm run typecheck && npm run lint && npx vitest run
```

Expected: clean; every unit test passes (the whole vitest suite runs in seconds and several files pin source invariants of these screens).

- [ ] **Step 5: See it in the browser (manual check, no commit gate)**

With the local stack up (`make db-up`, backend, `npm run dev`), correct a point-based paper as a student and expand a question row: the "Mark your own answer first" form appears; submitting reveals the outcome; refreshing the page loses the panel (the history result has no rows yet — Part 4 fixes this).

- [ ] **Step 6: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add web/src/lib/studentTypes.ts web/src/portals/student/screens/CorrectPaper.tsx web/src/portals/student/screens/PaperResult.tsx
git commit -S -m "feat(ui): self-review panel on the live paper result"
```

**Part 3 is shippable here** (`feat(self-review): frontend panel on the live result (part 3/5)`).

---

# Part 4 — Reachable after a refresh, and end-to-end

### Task 16: The history result knows its attempt

**Files:**
- Modify: `lemely/core/history.py:42-56` (`PaperRecord`)
- Modify: `lemely/db/history_repo.py:186-208` (`attempt_to_record`)
- Modify: `lemely/web/schemas_student.py:227-256` (`ResultDTO`)
- Modify: `lemely/web/routers/student.py:548-597` (`student_result`)
- Modify: `tests/test_history_repo_parity.py:112-133` (the parity comparison)
- Test: `tests/test_history_repo_parity.py` (append), `tests/test_web_student.py` (append)

**Interfaces:**
- Produces: `PaperRecord.attempt_id: str | None = None` (filled by `DbHistoryStore`, `None` from the JSON file store); `ResultDTO.attemptId: str | None = None`; TS `Result.attemptId` (already typed in Task 15) is now populated for history results.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_history_repo_parity.py`:

```python
def test_db_records_carry_their_attempt_id(pg_sessionmaker: sessionmaker[Session]) -> None:
    """The self-review surface is addressed by attempt id (spec 2026-09-17);
    a history record loaded from Postgres must say which attempt it is."""
    user_id = _seed_user(pg_sessionmaker)
    db_store = DbHistoryStore(pg_sessionmaker)
    db_store.append(user_id, _record(user_id, day=1, grade="C", topics=["Waves"]))

    [record] = db_store.load(user_id).records

    assert record.attempt_id is not None
    with pg_sessionmaker() as session:
        assert session.get(Attempt, uuid.UUID(record.attempt_id)) is not None
```

(`Attempt` and `uuid` — add `from lemely.db.models.attempts import Attempt` and `import uuid` to the file's imports if absent.)

Change the parity test's final assertion to exclude the one field the JSON store cannot know:

```python
    assert db_history.model_dump(exclude={"records": {"__all__": {"attempt_id"}}}) == (
        json_history.model_dump(exclude={"records": {"__all__": {"attempt_id"}}})
    )
    # The JSON store has no attempts table to point at; the DB store always does.
    assert all(r.attempt_id is None for r in json_history.records)
    assert all(r.attempt_id is not None for r in db_history.records)
```

Append to `tests/test_web_student.py` (next to `test_result_is_data_backed_with_empty_theory`):

```python
def test_result_attempt_id_is_null_for_file_store_records(client: TestClient) -> None:
    """The file-backed store has no attempts; the field is present and null,
    never fabricated — the frontend renders no self-review panel for it."""
    body = client.get("/api/student/result/0").json()
    assert "attemptId" in body
    assert body["attemptId"] is None
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_history_repo_parity.py tests/test_web_student.py -k "attempt_id or parity" -v --no-cov
```

Expected: `AttributeError: 'PaperRecord' object has no attribute 'attempt_id'`; the web test fails on `"attemptId" in body`.

- [ ] **Step 3: Implement**

`lemely/core/history.py` — add to `PaperRecord` after `origin`:

```python
    attempt_id: str | None = None
    """``attempts.id`` when the record was loaded from the relational store;
    ``None`` from the JSON file store, which has no attempts table. The
    student self-review routes (spec 2026-09-17) are addressed by attempt id,
    so a result screen needs this to reach them after a refresh. Optional and
    defaulted so every persisted history file loads unchanged.
    """
```

`lemely/db/history_repo.py` — in `attempt_to_record`, add after `origin=attempt.origin.value,`:

```python
        attempt_id=str(attempt.id),
```

`lemely/web/schemas_student.py` — add to `ResultDTO` after `provenance: str`:

```python
    attemptId: str | None = None
    """``attempts.id`` for a relationally-stored result; ``None`` for a
    file-store record. Addresses the self-review routes."""
```

`lemely/web/routers/student.py` — in `student_result`'s `ResultDTO(...)` add after `provenance=...`:

```python
        attemptId=record.attempt_id,
```

- [ ] **Step 4: Run the touched files**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_history_repo_parity.py tests/test_history_store.py tests/test_web_student.py tests/test_history_grade_bearing.py tests/test_attempt_repo.py --no-cov -q
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/core/history.py lemely/db/history_repo.py lemely/web/schemas_student.py lemely/web/routers/student.py tests/test_history_repo_parity.py tests/test_web_student.py
git commit -S -m "feat(web): history result carries its attempt id"
```

---

### Task 17: `GET /api/student/attempts/{attempt_id}/questions`

**Files:**
- Modify: `lemely/db/self_review_repo.py` (new `AttemptQuestion` dataclass and `SelfReviewService.list_questions`)
- Modify: `lemely/web/routers/student_self_review.py` (new route)
- Modify: `tests/test_authz_matrix.py`, `tests/test_authz_matrix_complete.py` (one GET row each)
- Test: `tests/test_self_review_repo.py` (append), `tests/test_student_self_review_web.py` (append)

**Interfaces:**
- Produces: `AttemptQuestion(question_result_id: uuid.UUID, question_id: str, effective_marks: int, maximum_marks: int, marker_source: str, confidence_score: float, feedback: str | None, review_reason: str | None, topic: str | None, matched_point_ids: list[str], self_reviewable: bool)`; `SelfReviewService.list_questions(student_id, attempt_id) -> list[AttemptQuestion]` (404 semantics as `get`); the route returns `list[QuestionResultDTO]` (Task 9's shape) with `awardedMarks = effective_marks`, `questionResultId` set, and both integrity flags always `False` — this student route never carries them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_self_review_repo.py`:

```python
# ── list_questions ─────────────────────────────────────────────────────────


def test_list_questions_returns_the_owners_rows_with_effective_marks(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()])
    service = _service(pg_sessionmaker)
    service.submit(
        student, attempt_id, _qr_id(pg_sessionmaker, attempt_id, "2"), _all_earned(["p1", "p2", "p3"])
    )

    rows = service.list_questions(student, attempt_id)

    by_id = {r.question_id: r for r in rows}
    assert set(by_id) == {"1", "2"}
    assert by_id["2"].effective_marks == 3  # the self-mark, not the AI's 0
    assert by_id["1"].effective_marks == 1
    assert all(r.self_reviewable for r in rows)
    assert by_id["2"].question_result_id == _qr_id(pg_sessionmaker, attempt_id, "2")


def test_list_questions_marks_rows_without_points_as_not_self_reviewable(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, student, [_high(), _low()], with_scheme=False)
    rows = _service(pg_sessionmaker).list_questions(student, attempt_id)
    assert len(rows) == 2 and not any(r.self_reviewable for r in rows)


def test_list_questions_is_owner_scoped(pg_sessionmaker: sessionmaker[Session]) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    attempt_id = _seed_attempt(pg_sessionmaker, owner, [_high(), _low()])
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).list_questions(other, attempt_id)
    with pytest.raises(SelfReviewNotFoundError):
        _service(pg_sessionmaker).list_questions(owner, uuid.uuid4())
```

Append to `tests/test_student_self_review_web.py`:

```python
def test_attempt_questions_route_lists_rows_with_ids_and_no_integrity_flags(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    resp = api.get(f"/api/student/attempts/{attempt_id}/questions")

    assert resp.status_code == 200, resp.text
    [row] = resp.json()
    assert row["questionId"] == "1a"
    assert row["questionResultId"] == qr_id
    assert row["awardedMarks"] == 1 and row["maxMarks"] == 3
    assert row["markerSource"] == "ai"
    assert row["confidence"] == 0.55
    assert row["plagiarismFlagged"] is False and row["aiDetectionFlagged"] is False

    # After a self-mark the list shows the effective mark.
    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 200
    assert api.get(f"/api/student/attempts/{attempt_id}/questions").json()[0]["awardedMarks"] == 3


def test_attempt_questions_route_is_404_for_another_student(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, _ = _wire(client, pg_sessionmaker)
    attempt_id, _ = _seed_attempt(pg_sessionmaker, _seed_user(pg_sessionmaker))
    assert api.get(f"/api/student/attempts/{attempt_id}/questions").status_code == 404
    assert api.get("/api/student/attempts/nope/questions").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_self_review_repo.py tests/test_student_self_review_web.py -k "list_questions or attempt_questions" -v --no-cov
```

Expected: `AttributeError: 'SelfReviewService' object has no attribute 'list_questions'`; the route tests get 404 (unmounted path) or 405.

- [ ] **Step 3: Implement the service method**

In `lemely/db/self_review_repo.py`, add the dataclass after `RevealedSelfReview`:

```python
@dataclass(frozen=True, slots=True)
class AttemptQuestion:
    """One question of the caller's attempt, as the result screen lists it.

    ``effective_marks`` (teacher > student > AI), never ``awarded_marks``.
    ``self_reviewable`` is derived from the presence of point rows — the same
    fact :meth:`SelfReviewService.get` 404s on — so the screen and the route
    can never disagree about which rows offer the panel.
    """

    question_result_id: uuid.UUID
    question_id: str
    effective_marks: int
    maximum_marks: int
    marker_source: str
    confidence_score: float
    feedback: str | None
    review_reason: str | None
    topic: str | None
    matched_point_ids: list[str]
    self_reviewable: bool
```

and the method on `SelfReviewService` after `submit`:

```python
    def list_questions(
        self, student_id: uuid.UUID | str, attempt_id: uuid.UUID | str
    ) -> list[AttemptQuestion]:
        """Every question of one of the caller's attempts, in persist order.

        Raises:
            SelfReviewNotFoundError: not the caller's attempt, or no such attempt (404).
        """
        student_uuid = _as_uuid(student_id)
        attempt_uuid = _as_uuid(attempt_id)
        with self._sessionmaker() as session:
            attempt = session.get(Attempt, attempt_uuid)
            if attempt is None or attempt.user_id != student_uuid:
                raise SelfReviewNotFoundError(f"No attempt {attempt_uuid}")
            results = session.scalars(
                select(QuestionResult)
                .where(QuestionResult.attempt_id == attempt.id)
                .order_by(QuestionResult.created_at, QuestionResult.id)
            ).all()
            return [
                AttemptQuestion(
                    question_result_id=qr.id,
                    question_id=qr.question_id,
                    effective_marks=qr.effective_marks,
                    maximum_marks=qr.maximum_marks,
                    marker_source=qr.marker_source.value,
                    confidence_score=qr.confidence_score,
                    feedback=qr.feedback,
                    review_reason=qr.review_reason,
                    topic=qr.topic,
                    matched_point_ids=list(qr.matched_point_ids),
                    self_reviewable=bool(qr.points),
                )
                for qr in results
            ]
```

Add `"AttemptQuestion"` to `__all__`.

- [ ] **Step 4: Add the route**

In `lemely/web/routers/student_self_review.py`, add `from lemely.db.self_review_repo import AttemptQuestion` to the existing import, `from lemely.web.schemas import QuestionResultDTO`, and:

```python
def _question_dto(row: AttemptQuestion) -> QuestionResultDTO:
    """The result screen's row shape. Integrity flags are never sent to a student."""
    return QuestionResultDTO(
        questionId=row.question_id,
        awardedMarks=row.effective_marks,
        maxMarks=row.maximum_marks,
        markerSource=row.marker_source,  # type: ignore[arg-type]
        confidence=row.confidence_score,
        feedback=row.feedback,
        matchedPointIds=row.matched_point_ids or None,
        reviewReason=row.review_reason,
        plagiarismFlagged=False,
        aiDetectionFlagged=False,
        topic=row.topic,
        questionResultId=str(row.question_result_id) if row.self_reviewable else None,
    )


@router.get("/{attempt_id}/questions", response_model=list[QuestionResultDTO])
def list_attempt_questions(
    attempt_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[SelfReviewService, Depends(get_self_review_service)],
) -> list[QuestionResultDTO]:
    """The per-question rows of one of the caller's attempts, for the result screen.

    ``awardedMarks`` is ``effective_marks`` (a self-mark or teacher override
    shows here). ``questionResultId`` is set only where the question has
    point rows, which is exactly where the self-review panel may render.
    """
    try:
        rows = service.list_questions(auth.user_id, attempt_id)
    except SelfReviewError as exc:
        _raise_for(exc)
    return [_question_dto(row) for row in rows]
```

Register it: `tests/test_authz_matrix.py` `STUDENT_GET_ROUTES` gets `"/api/student/attempts/00000000-0000-0000-0000-000000000002/questions",`; `tests/test_authz_matrix_complete.py` gets `("GET", "/api/student/attempts/{attempt_id}/questions"): STUDENT,` in the STUDENT block (header count `56` → `57`).

- [ ] **Step 5: Run**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_self_review_repo.py tests/test_student_self_review_web.py tests/test_authz_matrix.py tests/test_authz_matrix_complete.py --no-cov -q
```

Expected: all passed.

- [ ] **Step 6: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/self_review_repo.py lemely/web/routers/student_self_review.py tests/test_self_review_repo.py tests/test_student_self_review_web.py tests/test_authz_matrix.py tests/test_authz_matrix_complete.py
git commit -S -m "feat(web): list a student's attempt questions with effective marks and ids"
```

---

### Task 18: The history branch of `PaperResult` renders real rows

**Files:**
- Modify: `web/src/lib/hooks/useSelfReviewApi.ts` (new `useAttemptQuestions`)
- Modify: `web/src/portals/student/screens/PaperResult.tsx` (history branch)

**Interfaces:**
- Produces: `useAttemptQuestions(attemptId: string | null | undefined): UseQueryResult<QuestionResult[], Error>`; `PaperResult`'s history branch renders `QuestionList` with real rows and passes `attemptId`, so the panel works after a refresh.

- [ ] **Step 1: Add the hook**

Append to `web/src/lib/hooks/useSelfReviewApi.ts` (and add `import type { QuestionResult } from "@/lib/studentTypes"`):

```ts
export const attemptQuestionsKey = (attemptId: string) =>
  ["student", "attemptQuestions", attemptId] as const

/**
 * `GET /student/attempts/{attemptId}/questions` — the per-question rows of a
 * history-sourced result. Disabled without an attempt id (a file-store
 * record), in which case `PaperResult` keeps its honest "no per-question
 * detail" state.
 */
export function useAttemptQuestions(
  attemptId: string | null | undefined,
): UseQueryResult<QuestionResult[], Error> {
  return useQuery({
    queryKey: attemptQuestionsKey(attemptId ?? ""),
    queryFn: () =>
      request<QuestionResult[]>(`/student/attempts/${encodeURIComponent(attemptId ?? "")}/questions`),
    enabled: !!attemptId,
  })
}
```

Also add to `useSubmitSelfReview`'s `onSuccess`:

```ts
      queryClient.invalidateQueries({ queryKey: attemptQuestionsKey(attemptId) })
```

- [ ] **Step 2: Render real rows in the history branch**

In `web/src/portals/student/screens/PaperResult.tsx`, add the imports:

```tsx
import { useAttemptQuestions } from "@/lib/hooks/useSelfReviewApi"
```

Add this component above `export function PaperResult()`:

```tsx
/**
 * The history-sourced question list. A separate component so the hook is
 * called unconditionally inside `QueryState`'s render prop. `attemptId` is
 * null for a file-store record, which leaves the query disabled and the
 * list empty — the same honest state this screen always had for those.
 */
function HistoryQuestions({
  result,
  filter,
  onFilterChange,
  onShare,
}: {
  result: Result
  filter: QuestionFilter
  onFilterChange: (filter: QuestionFilter) => void
  onShare?: () => void
}) {
  const questions = useAttemptQuestions(result.attemptId)
  if (result.attemptId && questions.isPending) {
    return <ListSkeleton rows={5} />
  }
  const rows = questions.data ?? []
  const summary = confidenceSummaryOf(rows)
  return (
    <>
      {rows.length > 0 ? (
        <ConfidenceIndicatorSummary
          confident={summary.confident}
          uncertain={summary.uncertain}
          needsReview={summary.needsReview}
        />
      ) : null}
      <QuestionList
        questions={rows}
        subjectCode={result.code.split("/")[0]}
        onShare={onShare}
        filter={filter}
        onFilterChange={onFilterChange}
        attemptId={result.attemptId}
      />
    </>
  )
}
```

and replace the history branch's `<QuestionList questions={[]} ... />` (together with the long "PR 4 investigation" comment above it, which this supersedes) with:

```tsx
            <HistoryQuestions
              result={data}
              filter={filter}
              onFilterChange={setFilter}
              onShare={paperId ? shareHandler(data, paperId) : undefined}
            />
```

Update the screen's header comment: the "history" bullet now reads `GET /student/result/{paperId}` (useResult) for the header, plus `GET /student/attempts/{attemptId}/questions` for the rows when the record carries an attempt id; file-store records still show the honest note.

- [ ] **Step 3: Typecheck, lint, unit suite**

```bash
cd web && npm run typecheck && npm run lint && npx vitest run
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add web/src/lib/hooks/useSelfReviewApi.ts web/src/portals/student/screens/PaperResult.tsx
git commit -S -m "feat(ui): history paper result renders real question rows and the self-review panel"
```

---

### Task 19: Seed a self-reviewable paper and prove the flow in Playwright

**Files:**
- Modify: `scripts/seed_e2e.py` (imports; new `self_review_scheme()` / `self_review_report()` next to `accuracy_report_for_score` :683; new account + attempt in `seed()`; output contract)
- Modify: `web/e2e/seed.ts` (`SeedStudent`, `students`)
- Modify: `web/e2e/seed-contract.spec.ts:64` and `:233`
- Create: `web/e2e/self-review.spec.ts`
- Test: `tests/test_seed_e2e.py` (append)

**Interfaces:**
- Produces: seed contract `students.selfReview: SeedStudent & { selfReviewAttemptId: string }` — a standalone student with one point-based paper: question "1" (2 marks, both earned, confident) and question "2" (3 marks, one earned, confidence 0.55, low-confidence).

- [ ] **Step 1: Write the failing seed-helper test**

Append to `tests/test_seed_e2e.py`:

```python
class TestSelfReviewSeed:
    def test_the_paper_has_point_rows_and_one_low_confidence_question(self) -> None:
        from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD
        from lemely.db.question_points import derive_point_rows
        from scripts.seed_e2e import self_review_report, self_review_scheme

        report = self_review_report()
        scheme = self_review_scheme()
        by_id = {q.question_id: q for q in report.correction.questions}
        assert set(by_id) == {"1", "2"}
        assert by_id["1"].confidence_score >= REVIEW_CONFIDENCE_THRESHOLD
        assert by_id["2"].confidence_score < REVIEW_CONFIDENCE_THRESHOLD
        assert by_id["2"].needs_teacher_review is True
        assert not by_id["2"].plagiarism_flagged and not by_id["2"].ai_detection_flagged
        assert len(derive_point_rows(by_id["2"], scheme)) == 3
        assert [r["awarded"] for r in derive_point_rows(by_id["2"], scheme)] == [True, False, False]
        assert report.correction.awarded_marks == 3 and report.correction.maximum_marks == 5
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_seed_e2e.py -k SelfReviewSeed -v --no-cov
```

Expected: `ImportError: cannot import name 'self_review_report'`.

- [ ] **Step 3: Add the seed helpers and the account**

In `scripts/seed_e2e.py`, add to the imports:

```python
from lemely.core.analytics import summarize_weaknesses
from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    PaperType,
    SchemeFormat,
)
from lemely.core.loose_schemas import Question as SchemeQuestion
from lemely.core.loose_schemas import QuestionType as SchemeQuestionType
from lemely.core.loose_schemas import SessionMonth as LooseSessionMonth
```

Add after `accuracy_report_for_score`:

```python
#: Below ``REVIEW_CONFIDENCE_THRESHOLD`` (0.90): question "2" of the
#: self-review paper is genuinely low-confidence, so the student's verdict
#: carries authority there (self-review spec D2) with no judge and no key.
SELF_REVIEW_LOW_CONFIDENCE_SCORE = 0.55


def self_review_scheme() -> MarkScheme:
    """The point-based scheme the self-review student's paper was marked against.

    Two questions, five marks, every point tariff 1 — small enough to assert
    on by eye in ``web/e2e/self-review.spec.ts``.
    """
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code=SUBJECT_CODE,
            paper_number=3,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2023,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=5,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            SchemeQuestion(
                id="1",
                marks=2,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="States that speed is distance over time", marks=1),
                    AnswerPoint(id="p2", point="Gives the unit m/s", marks=1),
                ],
            ),
            SchemeQuestion(
                id="2",
                marks=3,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="Correct method", marks=1),
                    AnswerPoint(id="p2", point="Correct substitution", marks=1),
                    AnswerPoint(id="p3", point="Answer to 2 significant figures", marks=1),
                ],
            ),
        ],
    )


def self_review_report() -> AccuracyReport:
    """A 3/5 paper: "1" fully earned and confident; "2" 1/3 and low-confidence."""
    questions = [
        CorrectedQuestion(
            question_id="1",
            awarded_marks=2,
            maximum_marks=2,
            confidence=ConfidenceBand.HIGH,
            confidence_score=0.97,
            needs_teacher_review=False,
            student_answer="speed = distance / time = 10 / 2 = 5 m/s",
            expected_answer="5 m/s",
            topic="Motion",
            marker_source="ai",
            matched_point_ids=["p1", "p2"],
        ),
        CorrectedQuestion(
            question_id="2",
            awarded_marks=1,
            maximum_marks=3,
            confidence=ConfidenceBand.LOW,
            confidence_score=SELF_REVIEW_LOW_CONFIDENCE_SCORE,
            needs_teacher_review=True,
            student_answer="F = ma = 2 x 6 = 12",
            expected_answer="12 N",
            topic="Forces",
            marker_source="ai",
            review_reason="Working hard to read",
            feedback="Method shown, but the substitution and rounding were not clear.",
            matched_point_ids=["p1"],
        ),
    ]
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code=SUBJECT_CODE,
            paper_number=3,
            paper_variant=1,
            session_month="May/June",
            session_year=2023,
        ),
        questions=questions,
    )
    return AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=GradePrediction(
            awarded_marks=3,
            maximum_marks=5,
            percentage=60.0,
            grade="C",
            confidence=ConfidenceBand.LOW,
            needs_teacher_review=True,
            boundary_source="subject_default",
        ),
    )
```

(`SUBJECT_CODE` is the module's existing `"0625"` constant used by the other scenarios; if the name differs in the file, use that one.)

In `seed()`, after the `_log("Persisting the standalone corrected paper")` block add:

```python
    self_review = _signup_account("self-review", Role.student, run_tag)
    _log("Persisting the self-review student's point-based, low-confidence paper")
    self_review_attempt_id = attempt_repo.persist_correction(
        user_id=self_review["userId"],
        report=self_review_report(),
        recorded_at=corrected_recorded_at(now).isoformat(),
        mark_scheme=self_review_scheme(),
    )
```

(`attempt_repo` is the `deps.get_attempt_repo()` the surrounding block already uses.) In the `students = {...}` dict add after `"correctedPaper"`:

```python
        "selfReview": {
            **self_review,
            "expectedAtRiskReasons": [],
            "selfReviewAttemptId": str(self_review_attempt_id),
        },
```

- [ ] **Step 4: Extend the seed contract on the TS side**

`web/e2e/seed.ts` — in `SeedStudent` add:

```ts
  /** Only present on `students.selfReview`: the point-based paper's `attempts.id`. */
  selfReviewAttemptId?: string
```

and in `students` after `correctedPaper: SeedStudent`:

```ts
    /**
     * Self-review (spec 2026-09-17): a standalone student with ONE
     * point-based paper (5 marks; question "2" is low-confidence at 1/3).
     * Kept off every roster and every at-risk scenario so the flow can move
     * this student's marks without disturbing another spec's assertions.
     */
    selfReview: SeedStudent & { selfReviewAttemptId: string }
```

`web/e2e/seed-contract.spec.ts` — after `...account("students.correctedPaper"),` add `...account("students.selfReview"),`; after the `correctedPaperId` assertions add:

```ts
  expect(typeof resolve(seed, "students.selfReview.selfReviewAttemptId")).toBe("string")
  expect(resolve(seed, "students.selfReview.expectedAtRiskReasons")).toEqual([])
```

- [ ] **Step 5: Write the Playwright spec**

Create `web/e2e/self-review.spec.ts`:

```ts
import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Student self-review (spec 2026-09-17), end to end against the real
 * backend: the seeded `selfReview` student opens their one paper from
 * history (a refresh-safe route, not the live post-correction state),
 * self-marks the low-confidence question "2" as fully earned, and only then
 * sees the marker's verdict. The marks move 3/5 -> 5/5 because the marker
 * was unsure (D2); no judge and no Gemini key are involved.
 */

const ROW_2 = /^2 (Correct|Partial credit|Incorrect)\./

test("a student self-marks a low-confidence question and the verdict is revealed only after", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.selfReview

  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

  // This student's only paper is history index 0.
  await page.goto("/student/result/0")
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByLabel("3 out of 5 marks, 60 percent")).toBeVisible()

  await page.getByRole("button", { name: ROW_2 }).click()
  const form = page.getByTestId("self-review-form")
  await expect(form).toBeVisible()

  // Nothing about the marker's verdict is in the DOM before submission.
  await expect(page.getByTestId("self-review-outcome")).toHaveCount(0)
  await expect(page.getByText(/^Marker:/)).toHaveCount(0)

  const submit = form.getByRole("button", { name: /submit and reveal/i })
  await expect(submit).toBeDisabled()

  // Three points, one radio group each. Choose "earned" on all three.
  const groups = form.getByRole("group")
  await expect(groups).toHaveCount(3)
  for (const index of [0, 1, 2]) {
    await groups.nth(index).getByLabel("I earned this").check()
  }
  await expect(submit).toBeEnabled()
  await submit.click()

  const outcome = page.getByTestId("self-review-outcome")
  await expect(outcome).toBeVisible({ timeout: 15_000 })
  await expect(
    outcome.getByText("Your self-mark moved this question from 1 to 3 out of 3."),
  ).toBeVisible()
  await expect(outcome.getByText("Your mark was applied")).toHaveCount(2)
  await expect(outcome.getByText("You and the marker agree")).toHaveCount(1)
  await expect(page.getByTestId("self-review-form")).toHaveCount(0)

  // One pass per question: a reload shows the revealed state, never the form.
  await page.reload()
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByLabel("5 out of 5 marks, 100 percent")).toBeVisible()
  await page.getByRole("button", { name: ROW_2 }).click()
  await expect(page.getByTestId("self-review-outcome")).toBeVisible()
  await expect(page.getByTestId("self-review-form")).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})
```

- [ ] **Step 6: Run the seed test, then the E2E**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_seed_e2e.py --no-cov -q
cd web && npx playwright test e2e/seed-contract.spec.ts e2e/self-review.spec.ts
```

Expected: seed tests pass; both specs pass (Playwright boots the backend and runs the seed via `global-setup.ts`; it needs the local Supabase stack up, as every other spec does). If `self-review.spec.ts` fails on `getByRole("group")`, the `RadioGroup` renders its `<fieldset>` without an accessible name — check that `label` reached the `<legend>`, then re-run.

- [ ] **Step 7: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add scripts/seed_e2e.py tests/test_seed_e2e.py web/e2e/seed.ts web/e2e/seed-contract.spec.ts web/e2e/self-review.spec.ts
git commit -S -m "test(e2e): seed a self-reviewable paper and prove the self-review flow end to end"
```

**Part 4 is shippable here** (`feat(self-review): reachable after refresh, e2e (part 4/5)`).

---

# Part 5 — The misconception signal on the study plan

### Task 20: Misconception counts by topic, beside the weak areas

**Files:**
- Modify: `lemely/db/study_plan_repo.py` (`PlanView` :152, `_to_view` :523, new `_misconceptions`, imports)
- Modify: `lemely/web/schemas_study_plan.py` (`StudyPlanWeekDTO` :37; new `MisconceptionDTO`)
- Modify: `lemely/web/routers/study_plan.py:81-91` (`_plan_to_dto`)
- Modify: `web/src/lib/studyPlanTypes.ts` (`StudyPlanWeekDTO`), `web/tests/unit/studyPlan.test.ts` (`week()` fixture), `web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx` (after `<PlanBasis />`)
- Test: `tests/test_study_plan_repo.py` (append), `tests/test_web_study_plan.py` (append)

**Interfaces:**
- Consumes: `SelfReviewService.submit` (Task 6) to produce real misconception rows in tests; `QuestionResultPoint.student_selfmark / awarded / evidence_verdict`.
- Produces: `MisconceptionCount(topic: str, count: int)` and `PlanView.misconceptions: list[MisconceptionCount]` (defaulted, so `tests/test_widget_router.py`'s direct `PlanView(...)` construction is untouched); `MisconceptionDTO{topic, count}` and `StudyPlanWeekDTO.misconceptions: list[MisconceptionDTO]`; TS `StudyPlanWeekDTO.misconceptions: MisconceptionDTO[]`.
- Definition (spec "Weakness signal"): a point where `student_selfmark = true`, `awarded = false`, and no change was granted (`evidence_verdict` is `NULL` or `rejected`); counted by the question's `topic`, for the caller's attempts in the subject. Not fed into `build_study_plan`'s scheduling — it is *read alongside* the weak areas, exactly as the spec says, never mixed into `WeaknessRecord` arithmetic.

- [ ] **Step 1: Write the failing backend tests**

Append to `tests/test_study_plan_repo.py` (its module already has `pg_sessionmaker`, `study_plan_service`, `_seed_user`, `_seed_subject`):

```python
# ── Misconception signal (self-review spec, "Weakness signal") ────────────────


def _seed_self_reviewed_paper(sm: sessionmaker[Session], student_id: uuid.UUID) -> None:
    """One 0625 paper: a confident question "1" (topic Waves, 1/2) that the
    student challenges without evidence — a misconception — and a low-
    confidence "2" (topic Forces, 0/3) the student is granted outright."""
    from lemely.core.analytics import summarize_weaknesses
    from lemely.core.loose_schemas import (
        AnswerPoint,
        MarkScheme,
        MarkSchemeMetadata,
        PaperType,
        SchemeFormat,
    )
    from lemely.core.loose_schemas import Question as SchemeQuestion
    from lemely.core.loose_schemas import QuestionType as SchemeQuestionType
    from lemely.core.loose_schemas import SessionMonth as LooseSessionMonth
    from lemely.core.schemas import (
        AccuracyReport,
        ConfidenceBand,
        CorrectedQuestion,
        CorrectionResult,
        ExamMetadata,
        GradePrediction,
    )
    from lemely.db.attempt_repo import AttemptRepository
    from lemely.db.models.attempts import QuestionResult
    from lemely.db.self_review_repo import PointVerdict, SelfReviewService

    scheme = MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=3,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2023,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=5,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            SchemeQuestion(
                id="1",
                marks=2,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="States the law", marks=1),
                    AnswerPoint(id="p2", point="Gives the unit", marks=1),
                ],
            ),
            SchemeQuestion(
                id="2",
                marks=3,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="Method", marks=1),
                    AnswerPoint(id="p2", point="Substitution", marks=1),
                    AnswerPoint(id="p3", point="Answer", marks=1),
                ],
            ),
        ],
    )
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625", paper_number=3, paper_variant=1, session_month="May/June", session_year=2023
        ),
        questions=[
            CorrectedQuestion(
                question_id="1",
                awarded_marks=1,
                maximum_marks=2,
                confidence=ConfidenceBand.HIGH,
                confidence_score=0.96,
                needs_teacher_review=False,
                topic="Waves",
                marker_source="ai",
                matched_point_ids=["p1"],
            ),
            CorrectedQuestion(
                question_id="2",
                awarded_marks=0,
                maximum_marks=3,
                confidence=ConfidenceBand.LOW,
                confidence_score=0.3,
                needs_teacher_review=True,
                topic="Forces",
                marker_source="ai",
                matched_point_ids=[],
            ),
        ],
    )
    report = AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=GradePrediction(
            awarded_marks=1, maximum_marks=5, percentage=20.0, grade="U", confidence=ConfidenceBand.LOW
        ),
    )
    attempt_id = AttemptRepository(sm).persist_correction(
        user_id=str(student_id), report=report, mark_scheme=scheme
    )
    with sm() as session:
        ids = {
            question_id: qr_id
            for question_id, qr_id in session.execute(
                select(QuestionResult.question_id, QuestionResult.id).where(
                    QuestionResult.attempt_id == attempt_id
                )
            ).all()
        }
    service = SelfReviewService(sm, judge=None)
    # "1": claims p2 without evidence -> misconception, nothing granted.
    service.submit(student_id, attempt_id, ids["1"], [PointVerdict("p1", True), PointVerdict("p2", True)])
    # "2": low-confidence, all granted -> NOT misconceptions.
    service.submit(
        student_id, attempt_id, ids["2"], [PointVerdict(p, True) for p in ("p1", "p2", "p3")]
    )


def test_misconceptions_are_counted_by_topic_and_exclude_granted_points(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    from lemely.db.study_plan_repo import MisconceptionCount

    student = _seed_user(pg_sessionmaker)
    _seed_subject(pg_sessionmaker, "0625")
    _seed_self_reviewed_paper(pg_sessionmaker, student)

    plan = study_plan_service.generate(student, "0625")
    assert plan.misconceptions == [MisconceptionCount(topic="Waves", count=1)]
    current = study_plan_service.get_current(student, "0625")
    assert current is not None
    assert current.misconceptions == [MisconceptionCount(topic="Waves", count=1)]


def test_misconceptions_are_subject_and_owner_scoped(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_subject(pg_sessionmaker, "0625")
    _seed_subject(pg_sessionmaker, "0620")
    _seed_self_reviewed_paper(pg_sessionmaker, student)

    assert study_plan_service.generate(student, "0620").misconceptions == []
    assert study_plan_service.generate(other, "0625").misconceptions == []
```

(`select` is already imported in that module via `sqlalchemy`; if not, add `from sqlalchemy import select`.)

Append to `tests/test_web_study_plan.py`, next to `test_get_returns_a_real_available_plan_distinct_from_a_refusal`:

```python
def test_plan_payload_carries_misconceptions_list(client: TestClient) -> None:
    """The field is always present (an empty list, never absent) so the
    screen can render the section conditionally without a shape check."""
    create = client.post("/api/student/study-plan", json={"subjectCode": "0625"})
    assert create.status_code == 201, create.text
    assert create.json()["misconceptions"] == []
    current = client.get("/api/student/study-plan/0625").json()
    assert current["plan"]["misconceptions"] == []
```

(If that module's `client` fixture serves a fake `StudyPlanService`, put the assertion on whichever existing test already reads a real `plan` payload — the field must be on the wire either way.)

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_study_plan_repo.py tests/test_web_study_plan.py -k "misconception" -v --no-cov
```

Expected: `ImportError: cannot import name 'MisconceptionCount'`; the web test fails with `KeyError: 'misconceptions'`.

- [ ] **Step 3: Implement the backend**

`lemely/db/study_plan_repo.py`:

Imports — add `field` to the `dataclasses` import, `func, or_` to the `sqlalchemy` import, `QuestionResult, QuestionResultPoint` to the `lemely.db.models.attempts` import, and `EvidenceVerdict` to the enums import.

After `SessionView` add:

```python
@dataclass(frozen=True, slots=True)
class MisconceptionCount:
    """Self-review misconceptions in one topic (self-review spec, "Weakness signal").

    A misconception is a mark point the student said they earned, the marker
    did not award, and no change was granted. It is not lost marks and does
    not enter ``WeaknessRecord``'s accuracy arithmetic; it is read from the
    points table beside the weak areas.
    """

    topic: str
    count: int
```

On `PlanView` add the last field:

```python
    misconceptions: list[MisconceptionCount] = field(default_factory=list)
```

Add the query after `_weaknesses`:

```python
    def _misconceptions(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> list[MisconceptionCount]:
        """Misconception counts by topic over the caller's attempts in ``subject_code``.

        Rows where ``student_selfmark`` is true, ``awarded`` is false and
        ``evidence_verdict`` is NULL or ``rejected`` — ``not_required`` and
        ``accepted`` both mean the student's verdict was applied, which is a
        mark change, not a misconception. Questions with no ``topic`` are
        skipped rather than bucketed under a fallback label. Highest count
        first, ties by topic name.
        """
        stmt = (
            select(QuestionResult.topic, func.count())
            .select_from(QuestionResultPoint)
            .join(QuestionResult, QuestionResult.id == QuestionResultPoint.question_result_id)
            .join(Attempt, Attempt.id == QuestionResult.attempt_id)
            .where(
                Attempt.user_id == student_uuid,
                Attempt.subject_code == subject_code,
                QuestionResult.topic.is_not(None),
                QuestionResultPoint.student_selfmark.is_(True),
                QuestionResultPoint.awarded.is_(False),
                or_(
                    QuestionResultPoint.evidence_verdict.is_(None),
                    QuestionResultPoint.evidence_verdict == EvidenceVerdict.rejected,
                ),
            )
            .group_by(QuestionResult.topic)
            .order_by(func.count().desc(), QuestionResult.topic)
        )
        return [
            MisconceptionCount(topic=topic, count=count)
            for topic, count in session.execute(stmt).all()
        ]
```

Change `_to_view`'s signature to `_to_view(self, row, sessions, *, misconceptions: list[MisconceptionCount])` and pass `misconceptions=misconceptions` into the `PlanView(...)`. At **every** call site of `self._to_view(...)` (grep the file; `generate` and `get_current` at least) pass `misconceptions=self._misconceptions(session, student_uuid, row.subject_code)` computed inside the same open session. Add `"MisconceptionCount"` to `__all__` if the module has one.

`lemely/web/schemas_study_plan.py` — add `from pydantic import Field` and:

```python
class MisconceptionDTO(ApiModel):
    """Self-review misconceptions in one topic (self-review spec, "Weakness signal")."""

    topic: str
    count: int
```

and on `StudyPlanWeekDTO` after `sessions`:

```python
    misconceptions: list[MisconceptionDTO] = Field(default_factory=list)
    """Points the student claimed but was not granted, by topic. Read beside
    ``sessions``; never folded into weak-area arithmetic."""
```

`lemely/web/routers/study_plan.py` — import `MisconceptionDTO` and add to `_plan_to_dto`:

```python
        misconceptions=[
            MisconceptionDTO(topic=m.topic, count=m.count) for m in plan.misconceptions
        ],
```

- [ ] **Step 4: Run the backend tests**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_study_plan_repo.py tests/test_web_study_plan.py tests/test_widget_router.py --no-cov -q
```

Expected: all passed.

- [ ] **Step 5: Frontend type, fixture and rendering**

`web/src/lib/studyPlanTypes.ts` — add before `StudyPlanWeekDTO`:

```ts
/** Self-review misconceptions in one topic (mirrors `MisconceptionDTO`). */
export interface MisconceptionDTO {
  topic: string
  count: number
}
```

and to `StudyPlanWeekDTO` after `sessions`:

```ts
  /**
   * Points the student said they earned that the marker did not award and
   * nothing was granted, by topic (self-review spec, "Weakness signal").
   * Rendered beside the week, never mixed into the weakness arithmetic.
   */
  misconceptions: MisconceptionDTO[]
```

`web/tests/unit/studyPlan.test.ts` — in the `week()` fixture add `misconceptions: [],` after `sessions: [],`.

`web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx` — directly after `<PlanBasis />` in the plan branch add:

```tsx
              {plan.misconceptions.length > 0 ? (
                <Card>
                  <CardBody>
                    <h2 className="text-display-sm text-ink">Misconceptions to revisit</h2>
                    <p className="mt-1 max-w-[56ch] text-pretty text-body-sm text-ink-muted">
                      Points you thought you had earned that the marker did not award, from your
                      self-reviews. They are not counted as lost marks, but they are worth a second
                      look.
                    </p>
                    <ul className="mt-3 flex flex-col gap-1.5">
                      {plan.misconceptions.map((m) => (
                        <li
                          key={m.topic}
                          className="flex items-center justify-between gap-3 text-body-md text-ink"
                        >
                          <span>{m.topic}</span>
                          <span className="text-ink-muted">
                            {m.count === 1 ? "1 point" : `${m.count} points`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </CardBody>
                </Card>
              ) : null}
```

- [ ] **Step 6: Frontend checks**

```bash
cd web && npm run typecheck && npm run lint && npm run check:copy && npx vitest run
```

Expected: clean, all unit tests pass.

- [ ] **Step 7: Commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/study_plan_repo.py lemely/web/schemas_study_plan.py lemely/web/routers/study_plan.py tests/test_study_plan_repo.py tests/test_web_study_plan.py web/src/lib/studyPlanTypes.ts web/tests/unit/studyPlan.test.ts web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx
git commit -S -m "feat(study-plan): misconception counts by topic from student self-reviews"
```

**Part 5 is shippable here** (`feat(self-review): misconception signal on the study plan (part 5/5)`).

---

## Spec coverage (self-review of this plan)

| Spec requirement | Task(s) |
| --- | --- |
| D1 self-mark then reveal; reveal server-enforced; pre-submission GET omits `awarded` at any depth | 5 (dataclass has no field), 8 (recursive key assertion), 12 (TS pending type has no `awarded`) |
| D2 low-confidence: student wins, evidence optional; D6 downward honoured | 4 (`decide_point`), 6 (grant up/down tests), 7 (matrix) |
| D3 elsewhere evidence unlocks a lenient judge; "accept unless contradicted" | 4, 7, 10 (prompt text asserted) |
| D4 queue row auto-resolves via `resolved_by` / `resolved_at` / `resolution_note`; provenance in revision `source` | 6 |
| D5 single accessor, teacher > student > AI; self-marks reach every surface | 1, 3 (recompute reads `effective_marks`), 17 (`awardedMarks = effective_marks`) |
| Integrity flags grant no authority, never shown | 2 (`is_marking_low_confidence`), 5 + 7 (integrity-only tests), 12 (copy test), 17 (flags always false) |
| Low confidence = the `_persist` computation, reused not re-derived | 2 |
| Submission carries every point; partial rejected | 6 (`_verdicts_by_point`), 8 (422) |
| One pass per question, server-side; second POST 409 | 6 (`FOR UPDATE` + `is_self_marked`), 8 |
| `student_selfmarked_at` records the pass | 1 (`is_self_marked`), 6 |
| Judge input: point text, mark type, tariff, transcribed answer, marker rationale, evidence | 4 (`JudgeRequest`), 6 (construction), 10 (prompt) |
| Judge failure → `student_evidence_unjudged` row, no mark change, verdict null, student told a teacher will look | 6, 7, 12 (`pending` outcome copy), 14 |
| Accept rate per subject logged from day one | 10 (`self_review_judge_verdict` log line with `subject_code`) |
| `awarded_marks` never mutated; accuracy guard | 1, 6 (`awarded_marks == 0` after grant), 7 (matrix asserts `awarded_marks == 1`) |
| Totals via `_recompute_attempt_totals`, no second implementation; self-marked vs teacher-overridden identical | 3, 6 (`test_self_marked_and_teacher_overridden_attempts_with_identical_marks_agree`) |
| Standings unaffected | No change needed; `student_standings` reads no marks (verified at plan time, `routers/student.py:1195`) |
| Weakness signal: misconceptions from the points table, read by the study plan by topic | 20 |
| On a mark change, one transaction: point columns, `student_selfmark_marks`, revision, recompute, queue resolve | 6 |
| API: two student-scoped routes, own attempt only | 8 |
| Double submission 409 | 6, 8 |
| Teacher override races the student: still recorded, marks do not move | 6 (`test_teacher_override_already_recorded_wins...`) |
| No point rows → surface absent, derived from rows | 5 (404), 17 (`self_reviewable`), 14 (`UNAVAILABLE_COPY`) |
| Cross-student access 404 | 5, 8, 17 |
| Atomicity: failed recompute rolls everything back | 6 (single `session.begin()`; recompute inside it) |
| Authority matrix table test | 4 (rule) + 7 (18-cell integration) |
| Precedence tests both directions incl. downward | 1, 6 |
| Authz matrix entries | 8, 17 |
| Frontend unit tests for the state machine; Playwright end to end | 12, 19 |
| Older papers / quizzes: say so in UI copy | 12 (`UNAVAILABLE_COPY`), 14 |
| Judge model an implementation decision, measured against the metric | 10 (`self_review_judge_model` knob; defaults to the global model) |
| Loose input meeting a strict constraint must not lose the pass (lead's failure class) | 6 (NUL in evidence stripped), 7 (NUL/oversize judge reason bounded), 8 (422 at the edge) |

**Placeholder scan:** no "TBD"/"TODO"/"implement later"/"similar to Task N"; the only conditional instructions are environment checks with the exact fix stated (F401 markers between Tasks 5–6; `check:copy` output; `tests/test_config.py` existence; the `client` fixture shape in `tests/test_web_study_plan.py`).

**Type consistency:** `PointVerdict(mark_point_id, earned, evidence)` (Task 5) is what Tasks 6–8 and 20 construct; `RevealedSelfReview.state` values `"revealed" | "settled"` match `SelfReviewRevealedDTO.state` (Task 8) and TS `SelfReviewRevealed.state` (Task 12); `recompute_attempt_totals(session, attempt, results, *, boundary_store)` (Task 3) is called with that keyword in Tasks 6 and the totals test; `question_result_ids` (Task 9) returns `dict[str, uuid.UUID]` and the route stringifies; `AttemptQuestion.self_reviewable` (Task 17) drives `questionResultId` presence, which `PaperResult` (Task 15) gates the panel on; `PlanView.misconceptions` is defaulted so existing constructors compile.
