# Per-Question Marking Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a per-mark-point ledger, marker reasoning, and an append-only re-mark history for every corrected question, so a later spec can build student self-review on top of real data.

**Architecture:** Two new tables (`question_result_points`, `question_result_revisions`) plus additive nullable columns on `question_results`. Rows are derived at attempt-write time inside the existing single writer `AttemptRepository._persist`, from the parsed `MarkScheme` object threaded in from the correction call site. No marker prompt change, no backfill.

**Tech Stack:** Python 3, SQLAlchemy 2 (`Mapped`/`mapped_column`), Alembic, Pydantic v2, pytest, Postgres (JSONB, `gen_random_uuid()`).

**Spec:** `docs/superpowers/specs/2026-09-17-per-question-marking-detail-design.md`

## Global Constraints

- Signed commits only: `git commit -S`. Conventional messages with scopes (`feat(db):`, `test(db):`, `refactor(core):`).
- Run `pre-commit run --all-files` and fix every failure before creating any commit. The venv must be on PATH for `mypy` and `lint-imports` to resolve: `PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files`.
- Do not run the full test suite locally. Run only the test files this plan touches.
- **Every `pytest` command in this plan ends with `--no-cov`.** This repo's pytest config enforces a 70% global coverage gate, which any single-file run fails on total coverage regardless of whether the tests themselves passed. Without `--no-cov` every task's "Expected: PASS" reads as a red FAIL.
- DB-backed tests use the `pg_sessionmaker` fixture (a `sessionmaker[Session]`, not a `Session`). It creates and drops a throwaway database per test and skips cleanly when Postgres is unreachable. Schema comes from `Base.metadata.create_all`, **not** from Alembic — so these tests do not exercise the migration, and Task 4 Step 6 is the only thing that does. `_seed_user(pg_sessionmaker)` takes the sessionmaker and returns a user-id string.
- Verified at plan time: `DatabaseSettings().url` resolves to `127.0.0.1:54322` (the project's Supabase container) and `pytest tests/test_attempt_repo.py --no-cov` passes 21 tests there. If tests skip with "local Postgres not reachable", start that container rather than editing the fixture.
- `awarded_marks` on `question_results` is never mutated or erased by anything in this plan. It is what keeps `lemely/eval` accuracy measurement honest.
- Per-point reasons are never invented. `rationale` stays NULL until a marker emits one (spec D2).
- Nothing in this plan may cause a correction to fail. A derivation error yields no point rows and a log line; it never propagates.
- Every new column is nullable or has a server default. No existing column changes type or meaning.
- Alembic head at time of writing is `0036_upload_idempotency_key`. New revision ids are `<=32` chars (`alembic_version.version_num` is `varchar(32)`).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `lemely/db/models/attempts.py` | Modify. Add `QuestionResultPoint` and `QuestionResultRevision` models; add six nullable columns to `QuestionResult`. |
| `lemely/db/models/enums.py` | Modify. Add `RevisionSource` and `EvidenceVerdict` enums; add `student_evidence_unjudged` to `ReviewReason`. |
| `lemely/db/migrations/versions/0037_question_result_points.py` | Create. Two tables, six columns, three enum types, one enum value. No data migration. |
| `lemely/db/question_points.py` | Create. Pure derivation: `(CorrectedQuestion, MarkScheme | None) -> list[dict]`. No session, no I/O, no model layer — the unit under test. |
| `lemely/db/attempt_repo.py` | Modify. Thread `mark_scheme` through `persist_correction`/`_persist`; call the derivation; write revision 1; carry the three dropped fields in `_to_question_result`. |
| `lemely/core/schemas.py` | Modify. Add `rationale` and `point_notes` to `CorrectedQuestion`. |
| `lemely/web/routers/student.py` | Modify. One call site (`:1059`) gains `mark_scheme=mark_scheme`. |
| `tests/test_question_points.py` | Create. Pure-function derivation tests. No database needed. |
| `tests/test_attempt_repo.py` | Modify. Integration tests for persistence, revision 1, the snapshot rule, and the dropped fields. |
| `tests/test_student_correct.py` | Modify. Two tests pinning that the route passes the scheme and no paper_id, reusing its existing `client` fixture. |

Derivation lives in its own module rather than inside `attempt_repo.py` because it is pure and the interesting logic: it deserves fast tests that need no Postgres, and `attempt_repo.py` is already 400+ lines doing persistence.

---

### Task 1: Add the `rationale` and `point_notes` fields to `CorrectedQuestion`

**Files:**
- Modify: `lemely/core/schemas.py:117-143`
- Test: `tests/test_schemas_corrected_question.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `CorrectedQuestion.rationale: str | None` and `CorrectedQuestion.point_notes: dict[str, str] | None`, both defaulting to `None`. Task 5 reads `rationale`; Task 3 reads `point_notes`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_schemas_corrected_question.py`:

```python
"""The two additive marker-reasoning fields on :class:`CorrectedQuestion`.

Both default to ``None`` so no marker prompt change is required to ship the
per-question detail work (spec 2026-09-17 D1). When the marker starts emitting
them, they stop being null and nothing else has to change.
"""

from __future__ import annotations

from lemely.core.schemas import ConfidenceBand, CorrectedQuestion


def _question(**overrides: object) -> CorrectedQuestion:
    base: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 2,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
    }
    base.update(overrides)
    return CorrectedQuestion(**base)  # type: ignore[arg-type]


def test_rationale_and_point_notes_default_to_none() -> None:
    question = _question()
    assert question.rationale is None
    assert question.point_notes is None


def test_rationale_and_point_notes_round_trip_when_supplied() -> None:
    question = _question(
        rationale="Method correct, final value not given to 3sf.",
        point_notes={"p1": "method shown", "p2": "rounding wrong"},
    )
    assert question.rationale == "Method correct, final value not given to 3sf."
    assert question.point_notes == {"p1": "method shown", "p2": "rounding wrong"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_schemas_corrected_question.py -v --no-cov
```

Expected: FAIL. `CorrectedQuestion` is a `StrictModel`, so the second test raises a Pydantic `ValidationError` for unexpected keyword arguments `rationale` and `point_notes`.

- [ ] **Step 3: Add the two fields**

In `lemely/core/schemas.py`, inside `class CorrectedQuestion(StrictModel)`, immediately after the `extraction_confidence` field and its docstring:

```python
    rationale: str | None = None
    """The marker's own reasoning for this question's mark, verbatim.

    Distinct from ``feedback``, which is written for the student. This is the
    marker explaining itself. ``None`` until a marker emits one — never
    synthesised from the mark scheme text, per spec 2026-09-17 D2.
    """
    point_notes: dict[str, str] | None = None
    """Per-mark-point reasoning, keyed by ``AnswerPoint.id``.

    ``None`` until a marker emits it. Keys that do not correspond to a point in
    the mark scheme are ignored by the derivation rather than written as rows
    for points that do not exist.
    """
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_schemas_corrected_question.py -v --no-cov
```

Expected: PASS, 2 passed.

- [ ] **Step 5: Run pre-commit and commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/core/schemas.py tests/test_schemas_corrected_question.py
git commit -S -m "feat(core): add rationale and point_notes to CorrectedQuestion

Both default to None, so the marker needs no prompt change to ship the
per-question detail work. They stop being null when the marker starts
emitting them."
```

---

### Task 2: Add the enums

**Files:**
- Modify: `lemely/db/models/enums.py`
- Test: `tests/test_enums_marking_detail.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `RevisionSource` (members `ai`, `teacher`, `student_selfmark`, `remark`), `EvidenceVerdict` (members `accepted`, `rejected`, `not_required`), and `ReviewReason.student_evidence_unjudged`. Tasks 3, 4 and 5 use all three.

- [ ] **Step 1: Write the failing test**

Create `tests/test_enums_marking_detail.py`:

```python
"""Enums introduced by the per-question marking detail work (spec 2026-09-17).

``student_evidence_unjudged`` is created here, unused, deliberately: spec D5
says the student self-review spec adds no migration of its own, so every value
it writes must already exist.
"""

from __future__ import annotations

from lemely.db.models.enums import EvidenceVerdict, ReviewReason, RevisionSource


def test_revision_source_members() -> None:
    assert {member.value for member in RevisionSource} == {
        "ai",
        "teacher",
        "student_selfmark",
        "remark",
    }


def test_evidence_verdict_members() -> None:
    assert {member.value for member in EvidenceVerdict} == {
        "accepted",
        "rejected",
        "not_required",
    }


def test_review_reason_gains_student_evidence_unjudged() -> None:
    assert ReviewReason.student_evidence_unjudged.value == "student_evidence_unjudged"


def test_existing_review_reasons_are_untouched() -> None:
    values = {member.value for member in ReviewReason}
    assert {"low_confidence", "plagiarism_flag", "ai_detection_flag"} <= values
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_enums_marking_detail.py -v --no-cov
```

Expected: FAIL with `ImportError: cannot import name 'EvidenceVerdict'`.

- [ ] **Step 3: Add the enums**

In `lemely/db/models/enums.py`, add the new value to `ReviewReason` alongside the existing members:

```python
    student_evidence_unjudged = "student_evidence_unjudged"
```

and add two new enum classes at the end of the module:

```python
class RevisionSource(enum.Enum):
    """What produced a :class:`QuestionResultRevision`.

    ``ai`` is written at correction time. ``teacher`` is written by the
    override path. ``student_selfmark`` and ``remark`` are written by the
    student self-review spec; they exist here so that spec needs no enum
    migration of its own (spec 2026-09-17 D5).
    """

    ai = "ai"
    teacher = "teacher"
    student_selfmark = "student_selfmark"
    remark = "remark"


class EvidenceVerdict(enum.Enum):
    """Outcome of judging a student's written claim on a mark point.

    Written by the student self-review spec; created here per D5.
    """

    accepted = "accepted"
    rejected = "rejected"
    not_required = "not_required"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_enums_marking_detail.py -v --no-cov
```

Expected: PASS, 4 passed.

- [ ] **Step 5: Run pre-commit and commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/models/enums.py tests/test_enums_marking_detail.py
git commit -S -m "feat(db): add RevisionSource, EvidenceVerdict, student_evidence_unjudged

Created ahead of use so the student self-review spec adds no enum
migration of its own (spec 2026-09-17 D5)."
```

---

### Task 3: The derivation function

This is the interesting logic and it is pure. No session, no I/O, no Postgres needed to test it.

**Files:**
- Create: `lemely/db/question_points.py`
- Test: `tests/test_question_points.py` (create)

**Interfaces:**
- Consumes: `CorrectedQuestion` with `rationale`/`point_notes` from Task 1.
- Produces:

```python
def derive_point_rows(
    cq: CorrectedQuestion,
    mark_scheme: MarkScheme | None,
) -> list[dict[str, object]]
```

Returns a list of plain dicts, one per mark point in the scheme, each carrying the keys `mark_point_id`, `ordinal`, `mark_type`, `tariff`, `point_text`, `awarded`, `rationale`. Task 4 turns these into ORM rows; Task 5 calls this. Returning dicts rather than ORM objects is what keeps this module free of the model layer and the test free of a database.

- [ ] **Step 1: Write the failing test**

Create `tests/test_question_points.py`:

```python
"""Per-mark-point derivation (spec 2026-09-17, "Write path").

Pure-function tests: no database, no session. The behaviour that matters most
is the inversion — a row is written per point in the MARK SCHEME, not per id in
``matched_point_ids`` — because missed points are exactly what a breakdown is
for.
"""

from __future__ import annotations

from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    MathMarkType,
    PaperType,
    SchemeFormat,
)
from lemely.core.loose_schemas import Question as SchemeQuestion
from lemely.core.loose_schemas import QuestionType as SchemeQuestionType
from lemely.core.loose_schemas import SessionMonth as LooseSessionMonth
from lemely.core.schemas import ConfidenceBand, CorrectedQuestion
from lemely.db.question_points import derive_point_rows


def _scheme() -> MarkScheme:
    """A one-question scheme with three points: p1 (M, 1), p2 (A, 1), p3 (B, 1).

    Field names here are verified against the real schema, not guessed:
    ``Question`` takes ``type=`` (not ``question_type=``), every enum member is
    UPPERCASE, and ``MarkSchemeMetadata`` requires ``subject`` and
    ``maximum_mark`` as well as the obvious fields.
    """
    question = SchemeQuestion(
        id="1a",
        marks=3,
        type=SchemeQuestionType.CALCULATION,
        answer_points=[
            AnswerPoint(id="p1", point="Correct method", marks=1, math_mark_type=MathMarkType.M),
            AnswerPoint(id="p2", point="Answer to 3sf", marks=1, math_mark_type=MathMarkType.A),
            AnswerPoint(id="p3", point="Units stated", marks=1, math_mark_type=MathMarkType.B),
        ],
    )
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Mathematics",
            subject_code="0580",
            paper_number=2,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2024,
            paper_type=PaperType.THEORY_EXTENDED,
            maximum_mark=3,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[question],
    )


def _corrected(**overrides: object) -> CorrectedQuestion:
    base: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 1,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "matched_point_ids": ["p1"],
    }
    base.update(overrides)
    return CorrectedQuestion(**base)  # type: ignore[arg-type]


def test_writes_a_row_per_scheme_point_not_per_matched_id() -> None:
    """The inversion. Two missed points must still become rows."""
    rows = derive_point_rows(_corrected(), _scheme())

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]
    assert [row["awarded"] for row in rows] == [True, False, False]


def test_carries_tariff_mark_type_and_text_from_the_scheme() -> None:
    rows = derive_point_rows(_corrected(), _scheme())

    assert rows[1] == {
        "mark_point_id": "p2",
        "ordinal": 1,
        "mark_type": "A",
        "tariff": 1,
        "point_text": "Answer to 3sf",
        "awarded": False,
        "rationale": None,
    }


def test_rationale_comes_from_point_notes_when_the_marker_supplied_it() -> None:
    rows = derive_point_rows(
        _corrected(point_notes={"p2": "wrote 12.47, needed 12.5"}),
        _scheme(),
    )

    assert rows[1]["rationale"] == "wrote 12.47, needed 12.5"
    assert rows[0]["rationale"] is None


def test_point_notes_for_unknown_points_are_ignored() -> None:
    """A note keyed to a point the scheme lacks must not mint a row."""
    rows = derive_point_rows(
        _corrected(point_notes={"p99": "note for a point that does not exist"}),
        _scheme(),
    )

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]


def test_dangling_matched_ids_do_not_become_rows() -> None:
    """An id the marker claimed but the scheme lacks is dropped, not invented."""
    rows = derive_point_rows(_corrected(matched_point_ids=["p1", "p_ghost"]), _scheme())

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]
    assert [row["awarded"] for row in rows] == [True, False, False]


def test_no_scheme_yields_no_rows() -> None:
    """The quiz case: persist_quiz_correction has no scheme to pass."""
    assert derive_point_rows(_corrected(), None) == []


def test_question_absent_from_the_scheme_yields_no_rows() -> None:
    assert derive_point_rows(_corrected(question_id="99z"), _scheme()) == []


def test_question_with_no_answer_points_yields_no_rows() -> None:
    """Levels-based questions carry descriptors, not points."""
    scheme = _scheme()
    scheme.questions[0].answer_points = []

    assert derive_point_rows(_corrected(), scheme) == []


def test_mark_type_is_none_for_a_non_maths_point() -> None:
    scheme = _scheme()
    scheme.questions[0].answer_points[0].math_mark_type = None

    rows = derive_point_rows(_corrected(), scheme)

    assert rows[0]["mark_type"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_question_points.py -v --no-cov
```

Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.question_points'`.

- [ ] **Step 3: Write the derivation**

Create `lemely/db/question_points.py`:

```python
"""Derive a per-mark-point ledger from a marked question and its mark scheme.

Pure: no session, no I/O. Returns plain dicts, which
:mod:`lemely.db.attempt_repo` turns into ``QuestionResultPoint`` rows — keeping
this module free of the model layer and its tests free of a database.

The rule that matters: one row per point **in the mark scheme**, not per id in
``matched_point_ids``. A ledger of only the matched points has nothing to say
about the marks a student did not get, which is the entire reason to have one
(spec 2026-09-17, "Write path").

Nothing here is invented. ``tariff``, ``point_text`` and ``mark_type`` are
copied from the scheme; ``rationale`` is copied from the marker's
``point_notes`` when present and left ``None`` otherwise (D2). An id the marker
claimed but the scheme does not define produces no row at all — never a row
with a null tariff pretending to be a mark point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.schemas import CorrectedQuestion


def derive_point_rows(
    cq: CorrectedQuestion,
    mark_scheme: MarkScheme | None,
) -> list[dict[str, object]]:
    """One dict per mark point in ``cq``'s question, in scheme order.

    Args:
        cq: The marked question. ``matched_point_ids`` decides ``awarded``;
            ``point_notes`` supplies ``rationale`` where the marker wrote one.
        mark_scheme: The parsed scheme this question was marked against, or
            ``None`` when the caller has none (a quiz).

    Returns:
        A list of dicts carrying ``mark_point_id``, ``ordinal``, ``mark_type``,
        ``tariff``, ``point_text``, ``awarded`` and ``rationale``. Empty when
        there is no scheme, no matching question, or the question has no
        answer points.
    """
    if mark_scheme is None:
        return []

    question = mark_scheme.get_question_by_id(cq.question_id)
    if question is None or not question.answer_points:
        return []

    matched = set(cq.matched_point_ids)
    notes = cq.point_notes or {}

    return [
        {
            "mark_point_id": point.id,
            "ordinal": ordinal,
            "mark_type": point.math_mark_type.value if point.math_mark_type else None,
            "tariff": point.marks,
            "point_text": point.point,
            "awarded": point.id in matched,
            "rationale": notes.get(point.id),
        }
        for ordinal, point in enumerate(question.answer_points)
    ]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_question_points.py -v --no-cov
```

Expected: PASS, 9 passed.

- [ ] **Step 5: Run pre-commit and commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/question_points.py tests/test_question_points.py
git commit -S -m "feat(db): derive a per-mark-point ledger from a scheme and a marked question

One row per point in the mark scheme, not per matched id: the missed
points are the ones a breakdown exists to explain. Pure function, so the
tests need no Postgres."
```

---

### Task 4: The ORM models and the migration

**Files:**
- Modify: `lemely/db/models/attempts.py`
- Create: `lemely/db/migrations/versions/0037_question_result_points.py`
- Test: `tests/test_attempt_repo.py` (add one test)

**Interfaces:**
- Consumes: `RevisionSource`, `EvidenceVerdict` from Task 2.
- Produces: `QuestionResultPoint` and `QuestionResultRevision` ORM classes, importable from `lemely.db.models.attempts`; `QuestionResult.points` and `QuestionResult.revisions` relationships; six new `QuestionResult` columns. Task 5 writes all of them.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_attempt_repo.py`, and add `QuestionResultPoint, QuestionResultRevision` to the existing `from lemely.db.models.attempts import ...` line:

```python
def test_marking_detail_tables_exist_and_relate(pg_sessionmaker: sessionmaker[Session]) -> None:
    """The two new tables and the six additive columns are reachable from the ORM.

    A schema-shape test, not a behaviour test — Task 5 is what fills them.
    """
    assert QuestionResultPoint.__tablename__ == "question_result_points"
    assert QuestionResultRevision.__tablename__ == "question_result_revisions"

    columns = QuestionResult.__table__.columns
    for name in (
        "extraction_confidence",
        "plagiarism_flagged",
        "ai_detection_flagged",
        "rationale",
        "student_selfmark_marks",
        "student_selfmarked_at",
    ):
        assert name in columns, f"{name} missing from question_results"

    assert "points" in QuestionResult.__mapper__.relationships
    assert "revisions" in QuestionResult.__mapper__.relationships
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py -k marking_detail_tables -v --no-cov
```

Expected: FAIL with `ImportError: cannot import name 'QuestionResultPoint'`.

- [ ] **Step 3: Add the models**

In `lemely/db/models/attempts.py`, add the six columns to `QuestionResult` immediately before its `attempt` relationship:

```python
    extraction_confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    """Extraction-stage confidence, distinct from ``confidence_score``.

    Computed by the pipeline (``CorrectedQuestion.extraction_confidence``) and,
    before spec 2026-09-17, discarded at persist time.
    """
    plagiarism_flagged: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    ai_detection_flagged: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    """Integrity flags, persisted rather than only fanned out to the review queue.

    Teacher-only on every surface (QUALITY-BAR.md): these must never reach a
    student-facing screen, where they would read as an accusation.
    """
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    student_selfmark_marks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    student_selfmarked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Written by the student self-review spec. Created here per its D5."""
```

Add the two relationships beside the existing `review_queue_items`:

```python
    points: Mapped[list[QuestionResultPoint]] = relationship(
        "QuestionResultPoint",
        back_populates="question_result",
        cascade="all, delete-orphan",
        order_by="QuestionResultPoint.ordinal",
    )
    revisions: Mapped[list[QuestionResultRevision]] = relationship(
        "QuestionResultRevision",
        back_populates="question_result",
        cascade="all, delete-orphan",
        order_by="QuestionResultRevision.revision",
    )
```

Then add both classes after `QuestionResult`:

```python
class QuestionResultPoint(TimestampMixin, Base):
    """One mark point of one marked question.

    Derived at attempt-write time from the parsed mark scheme
    (:func:`lemely.db.question_points.derive_point_rows`). ``tariff``,
    ``point_text`` and ``mark_type`` are **snapshotted**, not joined live: mark
    schemes get re-parsed and corrected, and a student's marked paper must not
    change meaning underneath them months later (spec 2026-09-17 D3).

    ``mark_type`` is text, not an enum. ``MathMarkType`` has fifteen members
    and a narrower DB enum would silently drop most of them.
    """

    __tablename__ = "question_result_points"
    __table_args__ = (
        sa.UniqueConstraint(
            "question_result_id", "mark_point_id", name="uq_question_result_points_point"
        ),
        sa.Index("ix_question_result_points_question_result_id", "question_result_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    question_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("question_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    mark_point_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    mark_type: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    tariff: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    point_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    awarded: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    student_selfmark: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    student_selfmark_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    student_evidence: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    evidence_verdict: Mapped[EvidenceVerdict | None] = mapped_column(
        sa.Enum(EvidenceVerdict, name="evidenceverdict"), nullable=True
    )

    question_result: Mapped[QuestionResult] = relationship(
        "QuestionResult", back_populates="points"
    )


class QuestionResultRevision(TimestampMixin, Base):
    """One recorded state of a question's marks. Append-only.

    Revision 1 is written at correction time with ``source=ai``. The existing
    ``question_results`` row stays the current projection, so no read surface
    has to change to keep working (spec 2026-09-17 D4).
    """

    __tablename__ = "question_result_revisions"
    __table_args__ = (
        sa.UniqueConstraint(
            "question_result_id", "revision", name="uq_question_result_revisions_revision"
        ),
        sa.Index("ix_question_result_revisions_question_result_id", "question_result_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    question_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("question_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source: Mapped[RevisionSource] = mapped_column(
        sa.Enum(RevisionSource, name="revisionsource"), nullable=False
    )
    awarded_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    points_snapshot: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    question_result: Mapped[QuestionResult] = relationship(
        "QuestionResult", back_populates="revisions"
    )
```

Extend the enum import at the top of the module to include `EvidenceVerdict` and `RevisionSource`.

- [ ] **Step 4: Write the migration**

Create `lemely/db/migrations/versions/0037_question_result_points.py`:

```python
"""question_result_points + revisions: per-mark-point detail (spec 2026-09-17)

Revision ID: 0037_question_result_pts
Revises: 0036_upload_idempotency_key
Create Date: 2026-09-17 00:00:00.000000

Two additive tables and six additive nullable columns. **No data migration.**
Existing attempts have no usable link to a paper — ``attempts.paper_id`` was
never written by ``AttemptRepository._persist`` — so there is no honest mark
scheme to derive their point rows from, and a best-effort match would attach
today's parsed scheme to a paper marked against a possibly different one (D7).
Point rows accrue from the first correction after this ships.

``mark_type`` is text, not an enum: ``MathMarkType`` has fifteen members and a
narrower type would silently drop most of them.

Three enum types are created here and two of them
(``evidenceverdict``, and ``student_evidence_unjudged`` on ``reviewreason``)
are unused until the student self-review spec, which by design adds no
migration of its own (D5).

Reversible: ``downgrade`` drops both tables, the six columns, and the two enum
types this migration created. The added ``reviewreason`` value is NOT removed —
Postgres cannot drop an enum value, and recreating the type would require
rewriting every dependent column for no benefit.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0037_question_result_pts"
down_revision: str | Sequence[str] | None = "0036_upload_idempotency_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVISION_SOURCE = postgresql.ENUM(
    "ai", "teacher", "student_selfmark", "remark", name="revisionsource"
)
_EVIDENCE_VERDICT = postgresql.ENUM(
    "accepted", "rejected", "not_required", name="evidenceverdict"
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    _REVISION_SOURCE.create(bind, checkfirst=True)
    _EVIDENCE_VERDICT.create(bind, checkfirst=True)
    op.execute("ALTER TYPE reviewreason ADD VALUE IF NOT EXISTS 'student_evidence_unjudged'")

    op.create_table(
        "question_result_points",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("question_result_id", sa.UUID(), nullable=False),
        sa.Column("mark_point_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("mark_type", sa.Text(), nullable=True),
        sa.Column("tariff", sa.Integer(), nullable=False),
        sa.Column("point_text", sa.Text(), nullable=False),
        sa.Column("awarded", sa.Boolean(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("student_selfmark", sa.Boolean(), nullable=True),
        sa.Column("student_selfmark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("student_evidence", sa.Text(), nullable=True),
        sa.Column(
            "evidence_verdict",
            postgresql.ENUM(name="evidenceverdict", create_type=False),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["question_result_id"], ["question_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_result_id", "mark_point_id", name="uq_question_result_points_point"),
    )
    op.create_index(
        "ix_question_result_points_question_result_id",
        "question_result_points",
        ["question_result_id"],
    )

    op.create_table(
        "question_result_revisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("question_result_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", postgresql.ENUM(name="revisionsource", create_type=False), nullable=False),
        sa.Column("awarded_marks", sa.Integer(), nullable=False),
        sa.Column(
            "points_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["question_result_id"], ["question_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_result_id", "revision", name="uq_question_result_revisions_revision"),
    )
    op.create_index(
        "ix_question_result_revisions_question_result_id",
        "question_result_revisions",
        ["question_result_id"],
    )

    op.add_column("question_results", sa.Column("extraction_confidence", sa.Float(), nullable=True))
    op.add_column(
        "question_results",
        sa.Column("plagiarism_flagged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "question_results",
        sa.Column("ai_detection_flagged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("question_results", sa.Column("rationale", sa.Text(), nullable=True))
    op.add_column("question_results", sa.Column("student_selfmark_marks", sa.Integer(), nullable=True))
    op.add_column(
        "question_results",
        sa.Column("student_selfmarked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    for column in (
        "student_selfmarked_at",
        "student_selfmark_marks",
        "rationale",
        "ai_detection_flagged",
        "plagiarism_flagged",
        "extraction_confidence",
    ):
        op.drop_column("question_results", column)

    op.drop_index(
        "ix_question_result_revisions_question_result_id",
        table_name="question_result_revisions",
    )
    op.drop_table("question_result_revisions")
    op.drop_index(
        "ix_question_result_points_question_result_id", table_name="question_result_points"
    )
    op.drop_table("question_result_points")

    bind = op.get_bind()
    _EVIDENCE_VERDICT.drop(bind, checkfirst=True)
    _REVISION_SOURCE.drop(bind, checkfirst=True)
```

Note for the implementer: this repo has a settled pattern for extending a Postgres enum — read `lemely/db/migrations/versions/0019_activation_review.py` and follow it. It calls `op.execute("ALTER TYPE <type> ADD VALUE IF NOT EXISTS '<value>'")` directly in `upgrade()`, and its own docstring records why that is safe: `ALTER TYPE ... ADD VALUE` is transaction-safe from PostgreSQL 12 onward provided the new value is not *used* in the same transaction, which it is not here — this migration only declares it. `0034_parent_invites.py` follows the same pattern.

Its downgrade is deliberately asymmetric and yours must be too: PostgreSQL has no `ALTER TYPE ... DROP VALUE`, and rebuilding the type would have to decide what to do with rows already holding the value. Drop the tables, the columns, and the two enum types this migration creates; leave the added `reviewreason` value in place.

- [ ] **Step 5: Run the test to verify it passes**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py -k marking_detail_tables -v --no-cov
```

Expected: PASS. (The suite skips cleanly if no local Postgres is reachable; if it skips, start Postgres before continuing — Task 5 cannot be verified without it.)

- [ ] **Step 6: Verify the migration applies and reverses**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" alembic upgrade head
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" alembic downgrade -1
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" alembic upgrade head
```

Expected: three clean runs, no error. Confirm a single head with `alembic heads` — output must be exactly one revision, `0037_question_result_pts`.

- [ ] **Step 7: Run pre-commit and commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/models/attempts.py lemely/db/migrations/versions/0037_question_result_points.py tests/test_attempt_repo.py
git commit -S -m "feat(db): add question_result_points and question_result_revisions

Two additive tables plus six nullable columns on question_results. No data
migration: existing attempts have no usable link to a paper, so there is no
honest mark scheme to derive their rows from (spec 2026-09-17 D7)."
```

---

### Task 5: Write the rows from `_persist`

**Files:**
- Modify: `lemely/db/attempt_repo.py` — `persist_correction` (`:113`), `_persist` (`:200`), `_to_question_result` (`:363`)
- Test: `tests/test_attempt_repo.py`

**Interfaces:**
- Consumes: `derive_point_rows` (Task 3), the models (Task 4), `RevisionSource` (Task 2), `CorrectedQuestion.rationale` (Task 1).
- Produces: `persist_correction(..., mark_scheme: MarkScheme | None = None)`. Task 6 calls it with a scheme.

**Note:** `attempts.paper_id` is deliberately untouched (spec D6). The correction route's `payload.paperId` is an *upload* id, not a `papers.id`, so there is nothing valid to write there. Do not add it "while you're in here."

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_attempt_repo.py`:

```python
def _points_for(
    pg_sessionmaker: sessionmaker[Session], attempt_id: uuid.UUID
) -> list[QuestionResultPoint]:
    with pg_sessionmaker() as session:
        return list(
            session.scalars(
                select(QuestionResultPoint)
                .join(QuestionResult)
                .where(QuestionResult.attempt_id == attempt_id)
                .order_by(QuestionResultPoint.ordinal)
            ).all()
        )


def _revisions_for(
    pg_sessionmaker: sessionmaker[Session], attempt_id: uuid.UUID
) -> list[QuestionResultRevision]:
    with pg_sessionmaker() as session:
        return list(
            session.scalars(
                select(QuestionResultRevision)
                .join(QuestionResult)
                .where(QuestionResult.attempt_id == attempt_id)
            ).all()
        )


def _only_result(
    pg_sessionmaker: sessionmaker[Session], attempt_id: uuid.UUID
) -> QuestionResult:
    with pg_sessionmaker() as session:
        return session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).one()


def test_persist_writes_point_rows_including_missed_points(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The inversion, end to end: a missed point is a row with awarded=False."""
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=_scheme(),
    )

    points = _points_for(pg_sessionmaker, attempt_id)

    assert [p.mark_point_id for p in points] == ["p1", "p2", "p3"]
    assert [p.awarded for p in points] == [True, False, False]
    assert [p.tariff for p in points] == [1, 1, 1]
    assert points[0].mark_type == "M"


def test_persist_writes_revision_one(pg_sessionmaker: sessionmaker[Session]) -> None:
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=_scheme(),
    )

    revisions = _revisions_for(pg_sessionmaker, attempt_id)

    assert len(revisions) == 1
    assert revisions[0].revision == 1
    assert revisions[0].source is RevisionSource.ai
    assert len(revisions[0].points_snapshot) == 3


def test_persist_without_a_scheme_writes_no_points(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The quiz case. The attempt itself must still persist normally."""
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=None,
    )

    assert _points_for(pg_sessionmaker, attempt_id) == []
    with pg_sessionmaker() as session:
        assert session.get(Attempt, attempt_id) is not None


def test_persist_carries_the_previously_dropped_fields(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(
            matched_point_ids=["p1"],
            extraction_confidence=0.82,
            plagiarism_flagged=True,
            rationale="Method correct, rounding wrong.",
        ),
        mark_scheme=_scheme(),
    )

    result = _only_result(pg_sessionmaker, attempt_id)

    assert result.extraction_confidence == 0.82
    assert result.plagiarism_flagged is True
    assert result.ai_detection_flagged is False
    assert result.rationale == "Method correct, rounding wrong."


def test_awarded_marks_is_untouched_by_the_point_ledger(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The accuracy guard: lemely/eval reads awarded_marks and must not shift."""
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"], awarded_marks=1),
        mark_scheme=_scheme(),
    )

    result = _only_result(pg_sessionmaker, attempt_id)

    assert result.awarded_marks == 1
    assert result.effective_marks == 1


def test_snapshot_is_independent_of_later_scheme_edits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D3: a re-parsed scheme must not change a paper already marked."""
    scheme = _scheme()
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=_seed_user(pg_sessionmaker),
        report=_report_with_one_question(matched_point_ids=["p1"]),
        mark_scheme=scheme,
    )

    scheme.questions[0].answer_points[0].point = "COMPLETELY DIFFERENT TEXT"
    scheme.questions[0].answer_points[0].marks = 99

    point = _points_for(pg_sessionmaker, attempt_id)[0]

    assert point.point_text == "Correct method"
    assert point.tariff == 1
```

These tests need two helpers. `_seed_user` already exists in this file — reuse it, do not write another. Add `_report_with_one_question`, and import `_scheme` rather than copying it:

```python
from tests.test_question_points import _scheme


def _report_with_one_question(**overrides: object) -> AccuracyReport:
    """An AccuracyReport carrying exactly one question against ``_scheme()``.

    Keyword overrides land on the CorrectedQuestion, so a test can vary
    ``matched_point_ids``, ``extraction_confidence``, the integrity flags or
    ``rationale`` without rebuilding the whole report.
    """
    question: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 1,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "matched_point_ids": ["p1"],
    }
    question.update(overrides)

    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0580",
            session_month="may_june",
            session_year=2024,
            paper_number=2,
            paper_variant=1,
        ),
        questions=[CorrectedQuestion(**question)],  # type: ignore[arg-type]
    )
    return AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        prediction=GradePrediction(
            awarded_marks=1,
            maximum_marks=3,
            percentage=33.33,
            grade="E",
            confidence=ConfidenceBand.HIGH,
        ),
    )
```

If `AccuracyReport`'s real field names differ from `correction`/`weaknesses`/`prediction`, read `lemely/core/schemas.py` and follow the actual shape — do not force these names.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py -k "point_rows or revision_one or without_a_scheme or dropped_fields or untouched or snapshot" -v --no-cov
```

Expected: FAIL with `TypeError: persist_correction() got an unexpected keyword argument 'mark_scheme'`.

- [ ] **Step 3: Thread the arguments and write the rows**

In `lemely/db/attempt_repo.py`:

Add to both `persist_correction` and `_persist` signatures, keyword-only, after the existing parameters:

```python
        mark_scheme: MarkScheme | None = None,
```

`persist_correction` passes it straight through to `_persist`. The `Attempt(...)` constructor is not changed — `paper_id` stays absent, per spec D6.

Extend `_to_question_result` to carry the four fields that previously went nowhere:

```python
def _to_question_result(cq: CorrectedQuestion) -> QuestionResult:
    return QuestionResult(
        # … every existing keyword argument unchanged …
        extraction_confidence=cq.extraction_confidence,
        plagiarism_flagged=cq.plagiarism_flagged,
        ai_detection_flagged=cq.ai_detection_flagged,
        rationale=cq.rationale,
    )
```

Inside `_persist`'s existing `for qr, cq in zip(attempt.question_results, correction.questions, strict=True):` loop — before the review-queue fan-out, so a derivation failure cannot skip a queue row — add:

```python
                point_rows = _safe_derive_point_rows(cq, mark_scheme, qr.id)
                for row in point_rows:
                    session.add(QuestionResultPoint(question_result_id=qr.id, **row))
                session.add(
                    QuestionResultRevision(
                        question_result_id=qr.id,
                        revision=1,
                        source=RevisionSource.ai,
                        awarded_marks=qr.awarded_marks,
                        points_snapshot=point_rows,
                    )
                )
```

And add the guard as a module-level function:

```python
def _safe_derive_point_rows(
    cq: CorrectedQuestion,
    mark_scheme: MarkScheme | None,
    question_result_id: uuid.UUID,
) -> list[dict[str, object]]:
    """Derive point rows, or none at all if the scheme is unusable.

    A malformed mark scheme must never fail a correction: a student losing
    their marked paper because a breakdown could not be derived is strictly
    worse than a missing breakdown (spec 2026-09-17, "Error handling").
    """
    try:
        return derive_point_rows(cq, mark_scheme)
    except Exception as exc:  # noqa: BLE001 — see docstring
        log.warning(
            "question_point_derivation_failed",
            question_result_id=str(question_result_id),
            question_id=cq.question_id,
            error=str(exc),
        )
        return []
```

Add the imports: `derive_point_rows` from `lemely.db.question_points`, `QuestionResultPoint` and `QuestionResultRevision` from `lemely.db.models.attempts`, `RevisionSource` from `lemely.db.models.enums`, and `MarkScheme` from `lemely.core.loose_schemas` under `TYPE_CHECKING`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py -v --no-cov
```

Expected: PASS, including every pre-existing test in the file — none of them pass `mark_scheme`, and all must still work because it defaults to `None`.

- [ ] **Step 5: Run pre-commit and commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/db/attempt_repo.py tests/test_attempt_repo.py
git commit -S -m "feat(db): persist the per-point ledger, revision 1, and the dropped fields

_persist now derives point rows from the mark scheme threaded in by the
caller, writes revision 1, and carries extraction_confidence, both integrity
flags and rationale onto the row instead of discarding them.

A derivation failure yields no point rows and a log line. It never fails
the correction."
```

---

### Task 6: Thread the mark scheme from the correction call site

**Files:**
- Modify: `lemely/web/routers/student.py` — the `persist_correction` call sites
- Test: `tests/test_student_correct_persists_points.py` (create)

**Interfaces:**
- Consumes: `persist_correction(..., mark_scheme=...)` from Task 5.
- Produces: nothing downstream. This is the last wiring step.

**The call site** is `lemely/web/routers/student.py:1059-1061`, inside `student_correct`'s `run()` closure:

```python
                attempt_id = attempt_repo.persist_correction(
                    user_id=auth.user_id, report=report, upload_id=owned.id
                )
```

`mark_scheme` is a local on that line's scope, assigned at `:1039` by `resolve_mark_scheme` and guaranteed non-`None` — the `if mark_scheme is None:` guard at `:1042` returns before reaching here. This is the only `persist_correction` call site in the file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_student_correct_persists_points.py`:

```python
"""The correction route hands the parsed mark scheme to the repository.

Without this, ``persist_correction``'s ``mark_scheme`` default of ``None``
silently applies and no paper ever gets a point ledger — a failure with no
error, which is why it is pinned here rather than left to integration.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import MarkScheme


def test_persist_correction_receives_the_parsed_mark_scheme() -> None:
    with patch(
        "lemely.db.attempt_repo.AttemptRepository.persist_correction"
    ) as persist:
        persist.return_value = MagicMock()
        _run_one_correction()

    assert persist.call_count == 1
    scheme = persist.call_args.kwargs["mark_scheme"]
    assert isinstance(scheme, MarkScheme), "route passed no scheme; ledger would be empty"


def test_persist_correction_is_not_passed_a_paper_id() -> None:
    """payload.paperId is an UPLOAD id and must never reach attempts.paper_id."""
    with patch(
        "lemely.db.attempt_repo.AttemptRepository.persist_correction"
    ) as persist:
        persist.return_value = MagicMock()
        _run_one_correction()

    assert "paper_id" not in persist.call_args.kwargs
```

**Do not build a harness — one already exists.** `tests/test_student_correct.py` has a `client` fixture (at its line ~300) that yields `(TestClient, student_id, upload_repo)` wired to real repos over a throwaway database, with `student.resolve_mark_scheme` monkeypatched to return `_mcq_scheme()` and `student.extract_answers` to return `_extracted()`, and Gemini replaced by a `MagicMock`. Existing tests there drive the endpoint with `api.post("/api/student/correct", json={"paperId": paper_id})`.

Put these two tests in that file, reuse that fixture and its upload-seeding helper the way the neighbouring tests do, and monkeypatch `AttemptRepository.persist_correction` to capture its kwargs. Because the fixture already pins `resolve_mark_scheme` to `_mcq_scheme()`, the assertion is precise: the object handed to `persist_correction` as `mark_scheme` must be that same scheme, not merely non-`None`.

Delete the `tests/test_student_correct_persists_points.py` file named earlier in this task — it is not needed.

When patching anything used as a context manager on this path (the storage download, the temp directory), set `mock.__enter__ = MagicMock(return_value=mock)`. The default `MagicMock.__enter__()` returns a *new* mock, so the test would appear to configure the right object while assertions ran against an unconfigured one.

- [ ] **Step 2: Run the test to verify it fails**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_student_correct_persists_points.py -v --no-cov
```

Expected: the first test FAILS with `KeyError: 'mark_scheme'`. The second already passes — it is a guard against a plausible wrong fix, not a driver.

- [ ] **Step 3: Pass the scheme at the call site**

At `lemely/web/routers/student.py:1059`:

```python
                attempt_id = attempt_repo.persist_correction(
                    user_id=auth.user_id,
                    report=report,
                    upload_id=owned.id,
                    mark_scheme=mark_scheme,
                )
```

Do not add `paper_id=payload.paperId`. That value is an upload id (`:978`), and `attempts.paper_id` is a FK to `papers.id` — passing it would violate the constraint at insert time.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_student_correct_persists_points.py tests/test_attempt_repo.py -v --no-cov
```

Expected: PASS.

- [ ] **Step 6: Run pre-commit and commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add lemely/web/routers/student.py tests/test_student_correct_persists_points.py
git commit -S -m "feat(web): pass the parsed mark scheme into persist_correction

The scheme is already live on this path. Threading it explicitly derives
the point ledger from the exact scheme the paper was marked against,
rather than whatever a later re-parse produced.

No paper_id: payload.paperId is an upload id, not a papers.id."
```

---

### Task 7: Confirm the quiz path still persists cleanly

`persist_quiz_correction` has no mark scheme to pass and must keep working untouched. This task is verification, not change — if it needs a code change, the defaults in Task 5 were wrong.

**Files:**
- Test: `tests/test_attempt_repo.py` (add one test)

- [ ] **Step 1: Write the test**

```python
def test_quiz_correction_persists_with_no_points(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """persist_quiz_correction passes no scheme and must be unaffected."""
    attempt_id = AttemptRepository(pg_sessionmaker).persist_quiz_correction(
        user_id=_seed_user(pg_sessionmaker),
        correction=_report_with_one_question(matched_point_ids=["p1"]).correction,
        weaknesses=WeaknessReport(weak_areas=[]),
    )

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.paper_id is None

    assert _points_for(pg_sessionmaker, attempt_id) == []
    assert len(_revisions_for(pg_sessionmaker, attempt_id)) == 1, (
        "revision 1 is written even with no points"
    )
```

- [ ] **Step 2: Run it**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_attempt_repo.py -k quiz_correction -v --no-cov
```

Expected: PASS with no production change. If it fails, fix Task 5 rather than this test.

- [ ] **Step 3: Run the full set of touched files and commit**

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_question_points.py tests/test_attempt_repo.py tests/test_enums_marking_detail.py tests/test_schemas_corrected_question.py tests/test_student_correct_persists_points.py -v --no-cov
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
git add tests/test_attempt_repo.py
git commit -S -m "test(db): pin that the quiz path persists with no point rows

persist_quiz_correction has no scheme to pass. Revision 1 is still
written, so history exists for every marked question regardless."
```

---

## Verification

Before calling this plan complete:

```bash
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_question_points.py tests/test_attempt_repo.py tests/test_enums_marking_detail.py tests/test_schemas_corrected_question.py tests/test_student_correct_persists_points.py -v --no-cov
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --all-files
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" alembic heads
```

Expected: all tests pass; every pre-commit hook passes; `alembic heads` prints exactly one revision.

Do not run the full suite locally — CI does that.

## Out of scope

- Any change to the marker prompt or `CorrectedQuestion`'s per-point output (spec D1). `rationale` and `point_notes` stay null until that separate, separately-measured change lands.
- Backfill of existing attempts (spec D7).
- Everything in the student self-review spec: the API, the screen, the lenient judge, the precedence change. This plan creates the columns that spec writes; it writes none of them.
