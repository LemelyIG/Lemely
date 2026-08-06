"""Postgres-integration tests for :class:`ReviewService` (P3.4/T-07/T-08).

Exercises the review-queue listing, item detail, resolve/override, dismiss,
and bulk-approve guarantees against a throwaway database, skipping cleanly
when no local Postgres is reachable (mirrors ``test_class_repo.py``):

* **Tenancy** — a teacher sees/touches only review items for students in
  their own classes; a class the caller does not own is invisible, never a
  data leak. No super-role bypass for ``platform_admin`` (D1.6/D1.10).
* **Override consistency** — overriding a question rewrites the attempt's
  stored total (awarded marks, percentage, grade) so every existing reader of
  ``Attempt`` (``DbHistoryStore``, and therefore the student/teacher portals)
  sees the correction with no changes of its own, while the AI's original
  mark stays retrievable.
* **Integrity-dismissal privacy** — dismissing a plagiarism/AI-detection flag
  never touches the underlying question result; the student-facing payload
  (``DbHistoryStore.load(...)``) is byte-identical before and after.
* **Bulk-approve is skip-and-report** — one out-of-scope/unknown/already-closed
  id does not sink the rest of the batch.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

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
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import (
    ReviewAlreadyClosedError,
    ReviewNotFoundError,
    ReviewOwnershipError,
    ReviewService,
    ReviewValidationError,
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


# ── Seed helpers ────────────────────────────────────────────────────────────


def _seed_user(
    sm: sessionmaker[Session], role: Role = Role.teacher, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _metadata() -> ExamMetadata:
    # subject_code "9999" matches nothing in the bundled boundary data, so the
    # resolved boundary source is deterministically "global_default" —
    # DEFAULT_GRADE_BOUNDARIES exactly — keeping the recompute assertions
    # below simple and not coupled to real historical boundary data.
    return ExamMetadata(
        subject_code="9999",
        paper_number=1,
        paper_variant=1,
        session_month="May/June",
        session_year=2020,
    )


def _question(
    question_id: str,
    *,
    awarded: int,
    maximum: int,
    confidence_score: float = 0.95,
    needs_review: bool = False,
    review_reason: str | None = None,
    plagiarism_flagged: bool = False,
    ai_detection_flagged: bool = False,
) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=question_id,
        awarded_marks=awarded,
        maximum_marks=maximum,
        confidence=ConfidenceBand.LOW if needs_review else ConfidenceBand.HIGH,
        confidence_score=confidence_score,
        needs_teacher_review=needs_review,
        student_answer=f"answer-{question_id}",
        expected_answer=f"expected-{question_id}",
        topic="Waves",
        marker_source="ai",
        review_reason=review_reason,
        plagiarism_flagged=plagiarism_flagged,
        ai_detection_flagged=ai_detection_flagged,
        matched_point_ids=["p1"] if awarded else [],
    )


def _report(questions: list[CorrectedQuestion]) -> AccuracyReport:
    correction = CorrectionResult(metadata=_metadata(), questions=questions)
    awarded, maximum = correction.awarded_marks, correction.maximum_marks
    pct = round((awarded / maximum) * 100.0, 2) if maximum else 0.0
    grade = "A" if pct >= 80 else "B" if pct >= 70 else "C" if pct >= 60 else "U"
    prediction = GradePrediction(
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=pct,
        grade=grade,
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=correction.needs_teacher_review,
        boundary_source="global_default",
    )
    return AccuracyReport(
        correction=correction, weaknesses=WeaknessReport(weak_areas=[]), grade_prediction=prediction
    )


def _seed_attempt_with_review_items(
    pg_sessionmaker: sessionmaker[Session], user_id: uuid.UUID, questions: list[CorrectedQuestion]
) -> uuid.UUID:
    """Persist an attempt via the real repo, returning its id."""
    return AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(user_id), report=_report(questions)
    )


def _seed_teacher_with_student(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    *,
    student_name: str = "Amelia",
) -> tuple[uuid.UUID, uuid.UUID]:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name=student_name)
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    return teacher, student


def _review_items_for_attempt(
    pg_sessionmaker: sessionmaker[Session], attempt_id: uuid.UUID
) -> list[ReviewQueueItem]:
    with pg_sessionmaker() as session:
        return list(
            session.scalars(
                select(ReviewQueueItem)
                .where(ReviewQueueItem.attempt_id == attempt_id)
                .order_by(ReviewQueueItem.created_at)
            ).all()
        )


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def review_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> ReviewService:
    return ReviewService(pg_sessionmaker, class_service)


# ── Listing / tenancy ────────────────────────────────────────────────────────


def test_list_queue_scoped_to_callers_students(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher_a, student_a = _seed_teacher_with_student(
        pg_sessionmaker, class_service, student_name="A"
    )
    teacher_b, student_b = _seed_teacher_with_student(
        pg_sessionmaker, class_service, student_name="B"
    )
    _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_a,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_b,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )

    rows_a = review_service.list_queue(teacher_a, Role.teacher)
    assert len(rows_a) == 1
    assert rows_a[0].student_id == student_a
    assert rows_a[0].student_display_name == "A"

    rows_b = review_service.list_queue(teacher_b, Role.teacher)
    assert len(rows_b) == 1
    assert rows_b[0].student_id == student_b


def test_list_queue_platform_admin_sees_none(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    _, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    admin = _seed_user(pg_sessionmaker, Role.platform_admin)

    assert review_service.list_queue(admin, Role.platform_admin) == []


def test_list_queue_filters_by_class(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student_x = _seed_user(pg_sessionmaker, Role.student, display_name="X")
    student_y = _seed_user(pg_sessionmaker, Role.student, display_name="Y")
    class_x = class_service.create_class(teacher, "Class X")
    class_y = class_service.create_class(teacher, "Class Y")
    assert class_x.join_code is not None
    assert class_y.join_code is not None
    class_service.join_by_code(student_x, class_x.join_code)
    class_service.join_by_code(student_y, class_y.join_code)
    _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_x,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_y,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )

    rows = review_service.list_queue(teacher, Role.teacher, class_id=class_x.class_id)
    assert [r.student_id for r in rows] == [student_x]


def test_list_queue_filters_by_reason(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [
            _question(
                "1",
                awarded=1,
                maximum=1,
                confidence_score=1.0,
                needs_review=True,
                review_reason="plagiarism (score 0.95)",
                plagiarism_flagged=True,
            )
        ],
    )

    assert len(review_service.list_queue(teacher, Role.teacher, reason="plagiarism_flag")) == 1
    # Unrecognised reason values yield no matches, never a 500.
    assert review_service.list_queue(teacher, Role.teacher, reason="not_a_real_reason") == []


def test_list_queue_min_age_hours(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    from datetime import UTC, datetime, timedelta

    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    # Backdate the item's created_at so it reads as > 48h old.
    stale = datetime.now(UTC) - timedelta(hours=72)
    with pg_sessionmaker() as session:
        session.execute(sa.text("UPDATE review_queue SET created_at = :ts"), {"ts": stale})
        session.commit()

    assert len(review_service.list_queue(teacher, Role.teacher, min_age_hours=48)) == 1
    assert len(review_service.list_queue(teacher, Role.teacher, min_age_hours=1000)) == 0


# ── get_item ─────────────────────────────────────────────────────────────────


def test_get_item_happy_path(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [_question("2", awarded=0, maximum=1, confidence_score=0.1, needs_review=True)],
    )
    item = _review_items_for_attempt(pg_sessionmaker, attempt_id)[0]

    detail = review_service.get_item(teacher, Role.teacher, item.id)
    assert detail.row.question_id == "2"
    assert detail.row.ai_awarded_marks == 0
    assert detail.student_answer == "answer-2"
    assert detail.expected_answer == "expected-2"
    assert detail.is_overridden is False
    assert detail.teacher_awarded_marks is None


def test_get_item_unknown_id_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    with pytest.raises(ReviewNotFoundError):
        review_service.get_item(teacher, Role.teacher, uuid.uuid4())


def test_get_item_out_of_scope_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _, student_b = _seed_teacher_with_student(pg_sessionmaker, class_service, student_name="B")
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_b,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    item = _review_items_for_attempt(pg_sessionmaker, attempt_id)[0]

    with pytest.raises(ReviewOwnershipError):
        review_service.get_item(teacher_a, Role.teacher, item.id)


def test_get_item_malformed_id_is_value_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    with pytest.raises(ValueError, match="must be a UUID"):
        review_service.get_item(teacher, Role.teacher, "not-a-uuid")


# ── resolve (accept / override) ─────────────────────────────────────────────


def test_resolve_accept_as_is_does_not_change_marks(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [_question("1", awarded=1, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    item = _review_items_for_attempt(pg_sessionmaker, attempt_id)[0]

    row = review_service.resolve(teacher, Role.teacher, item.id, note="looks fine")
    assert row.status.value == "resolved"

    with pg_sessionmaker() as session:
        qr = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).one()
        assert qr.teacher_awarded_marks is None
        assert qr.awarded_marks == 1
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.awarded_marks == 1  # unchanged


def test_resolve_override_recomputes_attempt_total_everywhere(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """The core override-consistency guarantee: overriding one question makes
    the attempt total, percentage, and grade agree on every student-facing
    read path (``DbHistoryStore``), while the AI's original mark stays
    retrievable on the question row itself."""
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    # Two questions, 5 marks total; question "2" is low-confidence and flagged.
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [
            _question("1", awarded=2, maximum=2, confidence_score=1.0, needs_review=False),
            _question("2", awarded=0, maximum=3, confidence_score=0.2, needs_review=True),
        ],
    )
    item = next(
        i
        for i in _review_items_for_attempt(pg_sessionmaker, attempt_id)
        if i.question_result_id is not None
    )

    # Before the override: 2/5 = 40% = grade U (< 50 threshold).
    before = DbHistoryStore(pg_sessionmaker).load(str(student)).records[-1]
    assert before.awarded_marks == 2
    assert before.percentage == 40.0
    assert before.grade == "U"

    row = review_service.resolve(
        teacher,
        Role.teacher,
        item.id,
        override_marks=3,
        breakdown={"methodMarks": 2, "accuracyMarks": 1},
        note="Method was correct; award full marks.",
    )
    assert row.status.value == "resolved"

    # After: 2 + 3 = 5/5 = 100% = grade A. Every reader of Attempt agrees.
    after = DbHistoryStore(pg_sessionmaker).load(str(student)).records[-1]
    assert after.awarded_marks == 5
    assert after.percentage == 100.0
    assert after.grade == "A"

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.awarded_marks == 5
        assert attempt.percentage == 100.0
        assert attempt.grade == "A"
        assert attempt.predicted_grade == "A"

        qr = session.scalars(
            select(QuestionResult).where(
                QuestionResult.attempt_id == attempt_id, QuestionResult.question_id == "2"
            )
        ).one()
        # The teacher's mark wins...
        assert qr.effective_marks == 3
        assert qr.teacher_awarded_marks == 3
        assert qr.teacher_note == "Method was correct; award full marks."
        assert qr.teacher_breakdown == {"methodMarks": 2, "accuracyMarks": 1}
        assert qr.overridden_by == teacher
        assert qr.overridden_at is not None
        # ...but the AI's original mark is never erased — still retrievable.
        assert qr.awarded_marks == 0

        untouched = session.scalars(
            select(QuestionResult).where(
                QuestionResult.attempt_id == attempt_id, QuestionResult.question_id == "1"
            )
        ).one()
        assert untouched.teacher_awarded_marks is None
        assert untouched.effective_marks == 2


def test_resolve_override_out_of_range_is_validation_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    item = _review_items_for_attempt(pg_sessionmaker, attempt_id)[0]

    with pytest.raises(ReviewValidationError):
        review_service.resolve(teacher, Role.teacher, item.id, override_marks=3)


def test_resolve_already_closed_is_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    item = _review_items_for_attempt(pg_sessionmaker, attempt_id)[0]
    review_service.resolve(teacher, Role.teacher, item.id)

    with pytest.raises(ReviewAlreadyClosedError):
        review_service.resolve(teacher, Role.teacher, item.id)


def test_resolve_out_of_scope_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _, student_b = _seed_teacher_with_student(pg_sessionmaker, class_service, student_name="B")
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_b,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    item = _review_items_for_attempt(pg_sessionmaker, attempt_id)[0]

    with pytest.raises(ReviewOwnershipError):
        review_service.resolve(teacher_a, Role.teacher, item.id)


def test_resolve_override_without_question_result_is_validation_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """A manual review row with no ``question_result_id`` cannot be overridden
    (there is nothing to write the correction onto) — accept-as-is still works."""
    from lemely.db.models.enums import ReviewReason

    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker, student, [_question("1", awarded=1, maximum=1, confidence_score=1.0)]
    )
    with pg_sessionmaker() as session, session.begin():
        item = ReviewQueueItem(
            attempt_id=attempt_id, question_result_id=None, reason=ReviewReason.manual
        )
        session.add(item)
        session.flush()
        item_id = item.id

    with pytest.raises(ReviewValidationError):
        review_service.resolve(teacher, Role.teacher, item_id, override_marks=1)

    # Accept-as-is still works fine.
    row = review_service.resolve(teacher, Role.teacher, item_id)
    assert row.status.value == "resolved"


# ── dismiss ──────────────────────────────────────────────────────────────────


def test_dismiss_leaves_no_student_visible_record(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """The MISSION §4 / UI-spec §1.4 guarantee: dismissing an integrity flag
    must leave no trace a student could ever see. Proven two ways: the
    student-facing ``DbHistoryStore`` payload is byte-identical before/after,
    and the underlying question result's fields are untouched."""
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [
            _question(
                "1",
                awarded=1,
                maximum=1,
                confidence_score=1.0,
                needs_review=True,
                review_reason="plagiarism (score 0.95)",
                plagiarism_flagged=True,
            )
        ],
    )
    item = next(
        i
        for i in _review_items_for_attempt(pg_sessionmaker, attempt_id)
        if i.reason.value == "plagiarism_flag"
    )

    history = DbHistoryStore(pg_sessionmaker)
    before_payload = history.load(str(student)).model_dump()
    with pg_sessionmaker() as session:
        before_qr = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).one()
        before_fields = {
            c.name: getattr(before_qr, c.name) for c in QuestionResult.__table__.columns
        }

    row = review_service.dismiss(teacher, Role.teacher, item.id, note="checked manually, it's fine")
    assert row.status.value == "dismissed"

    after_payload = history.load(str(student)).model_dump()
    assert after_payload == before_payload

    with pg_sessionmaker() as session:
        after_qr = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt_id)
        ).one()
        after_fields = {c.name: getattr(after_qr, c.name) for c in QuestionResult.__table__.columns}
    assert after_fields == before_fields

    with pg_sessionmaker() as session:
        refreshed = session.get(ReviewQueueItem, item.id)
        assert refreshed is not None
        assert refreshed.resolution_note == "checked manually, it's fine"
        assert refreshed.resolved_by == teacher


def test_dismiss_non_integrity_reason_is_validation_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    item = _review_items_for_attempt(pg_sessionmaker, attempt_id)[0]
    assert item.reason.value == "low_confidence"

    with pytest.raises(ReviewValidationError):
        review_service.dismiss(teacher, Role.teacher, item.id)


def test_dismiss_already_closed_is_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [
            _question(
                "1",
                awarded=1,
                maximum=1,
                confidence_score=1.0,
                needs_review=True,
                review_reason="plagiarism (score 0.95)",
                plagiarism_flagged=True,
            )
        ],
    )
    item = next(
        i
        for i in _review_items_for_attempt(pg_sessionmaker, attempt_id)
        if i.reason.value == "plagiarism_flag"
    )
    review_service.dismiss(teacher, Role.teacher, item.id)

    with pytest.raises(ReviewAlreadyClosedError):
        review_service.dismiss(teacher, Role.teacher, item.id)


# ── bulk_approve ─────────────────────────────────────────────────────────────


def test_bulk_approve_is_skip_and_report(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher_a, student_a = _seed_teacher_with_student(
        pg_sessionmaker, class_service, student_name="A"
    )
    _, student_b = _seed_teacher_with_student(pg_sessionmaker, class_service, student_name="B")

    attempt_a = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_a,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    attempt_b = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_b,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    item_in_scope = _review_items_for_attempt(pg_sessionmaker, attempt_a)[0]
    item_out_of_scope = _review_items_for_attempt(pg_sessionmaker, attempt_b)[0]
    unknown_id = uuid.uuid4()

    # Pre-close a second in-scope item so "already_closed" is exercised too.
    attempt_a2 = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student_a,
        [_question("1", awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
    )
    item_already_closed = _review_items_for_attempt(pg_sessionmaker, attempt_a2)[0]
    review_service.resolve(teacher_a, Role.teacher, item_already_closed.id)

    result = review_service.bulk_approve(
        teacher_a,
        Role.teacher,
        [item_in_scope.id, item_out_of_scope.id, unknown_id, item_already_closed.id],
    )

    assert result.approved == [item_in_scope.id]
    skipped_by_id = {skip.item_id: skip.reason for skip in result.skipped}
    assert skipped_by_id[item_out_of_scope.id] == "forbidden"
    assert skipped_by_id[unknown_id] == "not_found"
    assert skipped_by_id[item_already_closed.id] == "already_closed"

    with pg_sessionmaker() as session:
        approved_item = session.get(ReviewQueueItem, item_in_scope.id)
        assert approved_item is not None
        assert approved_item.status.value == "resolved"
        # Untouched: still open.
        untouched_item = session.get(ReviewQueueItem, item_out_of_scope.id)
        assert untouched_item is not None
        assert untouched_item.status.value == "open"


# ── Input validation ─────────────────────────────────────────────────────────


def test_non_uuid_caller_id_rejected(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    with pytest.raises(ValueError, match="must be a UUID"):
        review_service.list_queue("not-a-uuid", Role.teacher)
