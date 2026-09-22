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
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.analytics import summarize_weaknesses
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult, WeaknessRecord
from lemely.db.models.enums import Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import (
    ReviewAlreadyClosedError,
    ReviewNotFoundError,
    ReviewOwnershipError,
    ReviewService,
    ReviewValidationError,
)
from lemely.db.teacher_paper_repo import TeacherPaperRepository
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
    topic: str = "Waves",
    marker_source: str = "ai",
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
        topic=topic,
        marker_source=marker_source,
        review_reason=review_reason,
        plagiarism_flagged=plagiarism_flagged,
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
    # Real weaknesses, computed the same way the marking pipeline does —
    # AttemptRepository.persist_correction writes WeaknessRecord rows straight
    # from report.weaknesses.weak_areas, so a fixture that leaves this empty
    # would silently make every weakness-record assertion vacuous.
    return AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=prediction,
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


def _seed_console_paper(
    pg_sessionmaker: sessionmaker[Session],
    *,
    uploader: uuid.UUID,
    questions: list[CorrectedQuestion],
) -> uuid.UUID:
    """Grade a paper through the console repository, as a finished run would."""
    repo = TeacherPaperRepository(pg_sessionmaker, stale_after=timedelta(minutes=10))
    paper_id = uuid.uuid4()
    repo.create(
        paper_id=paper_id,
        uploaded_by=uploader,
        storage_path=f"teacher/{uploader}/{paper_id.hex}/scan.pdf",
        scheme_storage_path=None,
        original_filename="scan.pdf",
        content_type="application/pdf",
        byte_size=15,
    )
    repo.claim_run(paper_id)
    repo.finish(paper_id, _report(questions))
    return paper_id


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

    rows_a = review_service.list_queue(teacher_a, Role.teacher).rows
    assert len(rows_a) == 1
    assert rows_a[0].student_id == student_a
    assert rows_a[0].student_display_name == "A"

    rows_b = review_service.list_queue(teacher_b, Role.teacher).rows
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

    result = review_service.list_queue(admin, Role.platform_admin)
    assert result.rows == []
    assert result.total == 0


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

    result = review_service.list_queue(teacher, Role.teacher, class_id=class_x.class_id)
    assert [r.student_id for r in result.rows] == [student_x]
    assert result.total == 1


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

    matched = review_service.list_queue(teacher, Role.teacher, reason="plagiarism_flag")
    assert len(matched.rows) == 1
    assert matched.total == 1
    # Unrecognised reason values yield no matches, never a 500.
    unmatched = review_service.list_queue(teacher, Role.teacher, reason="not_a_real_reason")
    assert unmatched.rows == []
    assert unmatched.total == 0


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

    assert len(review_service.list_queue(teacher, Role.teacher, min_age_hours=48).rows) == 1
    assert len(review_service.list_queue(teacher, Role.teacher, min_age_hours=1000).rows) == 0


# ── Cursor pagination (B6a) ──────────────────────────────────────────────────


def _seed_n_items_with_created_at(
    pg_sessionmaker: sessionmaker[Session],
    student: uuid.UUID,
    timestamps: list,
) -> list[uuid.UUID]:
    """Seed one open review item per timestamp (oldest first) and backdate
    each item's ``created_at`` to the given value. Returns the item ids in
    the same order as ``timestamps``."""
    item_ids: list[uuid.UUID] = []
    for i, ts in enumerate(timestamps):
        attempt_id = _seed_attempt_with_review_items(
            pg_sessionmaker,
            student,
            [_question(str(i), awarded=0, maximum=2, confidence_score=0.3, needs_review=True)],
        )
        items = _review_items_for_attempt(pg_sessionmaker, attempt_id)
        assert len(items) == 1
        item_id = items[0].id
        with pg_sessionmaker() as session:
            session.execute(
                sa.text("UPDATE review_queue SET created_at = :ts WHERE id = :id"),
                {"ts": ts, "id": item_id},
            )
            session.commit()
        item_ids.append(item_id)
    return item_ids


def test_list_queue_cursor_pagination_no_overlap_no_gap(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    from datetime import UTC, datetime, timedelta

    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    base = datetime.now(UTC) - timedelta(hours=5)
    item_ids = _seed_n_items_with_created_at(
        pg_sessionmaker, student, [base + timedelta(minutes=i) for i in range(5)]
    )

    page1_result = review_service.list_queue(teacher, Role.teacher, limit=2)
    # `limit + 1` rows come back so the caller can detect `has_more`.
    page1 = page1_result.rows
    assert len(page1) == 3
    assert [r.item_id for r in page1[:2]] == item_ids[:2]
    # `total` is the count ignoring `cursor`/`limit`, not `len(rows)`.
    assert page1_result.total == 5

    cursor = (page1[1].created_at, page1[1].item_id)
    page2_result = review_service.list_queue(teacher, Role.teacher, limit=2, cursor=cursor)
    page2 = page2_result.rows
    assert len(page2) == 3
    assert [r.item_id for r in page2[:2]] == item_ids[2:4]
    assert page2_result.total == 5

    seen = [r.item_id for r in page1[:2]] + [r.item_id for r in page2[:2]]
    assert seen == item_ids[:4]
    assert len(set(seen)) == len(seen)


def test_list_queue_cursor_stable_under_equal_created_at(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    from datetime import UTC, datetime

    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    same_ts = datetime.now(UTC)
    item_ids = _seed_n_items_with_created_at(pg_sessionmaker, student, [same_ts] * 3)

    full = review_service.list_queue(teacher, Role.teacher).rows
    assert [r.item_id for r in full] == sorted(item_ids)

    page1 = review_service.list_queue(teacher, Role.teacher, limit=1).rows
    assert len(page1) == 2
    assert page1[0].item_id == full[0].item_id

    cursor = (page1[0].created_at, page1[0].item_id)
    page2 = review_service.list_queue(teacher, Role.teacher, limit=1, cursor=cursor).rows
    assert page2[0].item_id == full[1].item_id


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


def test_get_item_marker_source_agrees_between_attempt_and_console_paths(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """US-038: the divergence this story exists to remove.

    Before migration ``0038_marker_source_dropped``, a dropped question
    reached ``ReviewItemDetail.marker_source`` via two siblings that
    disagreed: the student-attempt path (``review_repo.py:440``) read the
    DB's ``MarkerSource`` enum, which had no ``"dropped"`` member and so
    could only ever report ``"missing"``; the console path
    (``_console_item_detail``, ``review_repo.py:1042``) read the
    in-memory ``CorrectedQuestion`` straight out of ``report_json``, which
    was never narrowed and so reported ``"dropped"`` faithfully. A teacher
    working ONE review queue could see two different labels for the
    identical situation. With the enum member added and the write-side
    mapping in ``attempt_repo.py`` removed, both readers must now agree.
    """
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    dropped_question = _question(
        "1",
        awarded=0,
        maximum=1,
        confidence_score=0.0,
        needs_review=True,
        review_reason="answer discarded as malformed",
        marker_source="dropped",
    )

    attempt_id = _seed_attempt_with_review_items(pg_sessionmaker, student, [dropped_question])
    attempt_item = _review_items_for_attempt(pg_sessionmaker, attempt_id)[0]
    attempt_detail = review_service.get_item(teacher, Role.teacher, attempt_item.id)

    paper_id = _seed_console_paper(pg_sessionmaker, uploader=teacher, questions=[dropped_question])
    with pg_sessionmaker() as session:
        console_item = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.teacher_paper_id == paper_id)
        ).one()
    console_detail = review_service.get_item(teacher, Role.teacher, console_item.id)

    assert attempt_detail.marker_source == "dropped"
    assert console_detail.marker_source == "dropped"
    assert attempt_detail.marker_source == console_detail.marker_source


def test_review_queue_exempts_the_us039_unflagged_blank_console_path(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Console twin of ``test_review_queue_exempts_the_us039_unflagged_blank``
    (``tests/test_attempt_repo.py``) — MUST-FIX A, second independent review
    of ``4166e535``.

    ``4166e535`` added the US-039 unflagged-blank exemption to
    ``AttemptRepository.persist_correction`` only. ``_review_items_for``
    (``lemely/db/teacher_paper_repo.py``) — the console/teacher-paper twin
    producer whose own docstring claims it applies "the same three-reason
    rule" — kept queuing every blank via its own ``low_confidence`` arm
    regardless: exactly the "8 unattempted parts, 8 queue items a teacher
    bulk-dismisses" scenario the product owner rejected, just reached via
    ``lemely.web.services.grading.grade_paper`` (which calls
    ``TeacherPaperRepository.finish``) instead of a student submission. Both
    producers now share ``lemely.db.review_queue_rules.review_reasons_for``,
    so a genuine blank graded through the console must be exempted exactly
    like one graded through a student attempt.
    """
    from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON

    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    genuinely_low_confidence = _question(
        "2", awarded=0, maximum=1, confidence_score=0.2, needs_review=True
    )
    blank = _question(
        "3",
        awarded=0,
        maximum=1,
        confidence_score=0.0,
        needs_review=False,
        review_reason=_BLANK_ANSWER_REVIEW_REASON,
        marker_source="missing",
    )
    paper_id = _seed_console_paper(
        pg_sessionmaker, uploader=teacher, questions=[genuinely_low_confidence, blank]
    )

    with pg_sessionmaker() as session:
        items = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.teacher_paper_id == paper_id)
        ).all()
        # Question "2" (genuinely low-confidence) still queues; the unflagged
        # blank ("3") must NOT.
        assert {item.question_id for item in items} == {"2"}


def _real_plagiarism_review_reason() -> str:
    """The exact ``review_reason`` segment ``apply_integrity_checks`` appends for a flagged answer.

    Derived by running the REAL integrity-check pipeline
    (``lemely.io.integrity.apply_integrity_checks``) against a
    verbatim-copied answer -- not retyped or invented -- so a fixture built
    from this cannot silently drift from what the real producer actually
    appends (``lemely/io/integrity.py:102``,
    ``f"plagiarism (score {finding.score:.2f})"``).

    (Independent review, third pass: an earlier version of this test's
    fixture hand-typed ``"copied from another candidate"`` as the appended
    reason -- a string no builder in this codebase produces. This function
    exists so that mistake cannot recur here.)
    """
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.integrity import apply_integrity_checks
    from lemely.runtime.config import IntegritySettings

    verbatim = "gravity acts on the object"
    scheme = MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_extended",
                "maximum_mark": 1,
                "scheme_format": "mixed",
            },
            "questions": [
                {
                    "id": "1",
                    "marks": 1,
                    "type": "explanation",
                    "answer_points": [{"id": "p1", "point": verbatim, "marks": 1}],
                },
            ],
        }
    )
    near_verbatim = CorrectedQuestion(
        question_id="1",
        awarded_marks=1,
        maximum_marks=1,
        confidence=ConfidenceBand.HIGH,
        confidence_score=0.95,
        needs_teacher_review=False,
        student_answer=verbatim,
        expected_answer=verbatim,
        marker_source="ai",
    )
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[near_verbatim],
    )
    result = apply_integrity_checks(
        correction, scheme, gemini_client=None, settings=IntegritySettings()
    )
    flagged = result.questions[0]
    assert flagged.plagiarism_flagged is True
    assert flagged.review_reason is not None
    return flagged.review_reason


def test_review_queue_blank_with_integrity_flag_queues_plagiarism_only_console_path(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Console twin of ``test_review_queue_blank_with_integrity_flag_queues_plagiarism_only``
    (``tests/test_attempt_repo.py``) — third round of independent review.

    ``apply_integrity_checks`` APPENDS to ``review_reason`` rather than
    replacing it, so a genuine blank that also picked up an integrity flag
    carries the blank's own reason plus the real appended plagiarism reason
    (see :func:`_real_plagiarism_review_reason` below) — not equal to the
    bare blank reason. The exemption in
    ``lemely.db.review_queue_rules.review_reasons_for`` now checks
    membership of the blank's reason among the ``" | "``-split segments
    instead of whole-field equality, so this must be exempted from
    ``low_confidence`` on the console path exactly as it is on the attempt
    path, leaving only the real ``plagiarism_flag`` reason.
    """
    from lemely.db.models.enums import ReviewReason
    from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON

    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    flagged_blank = _question(
        "3",
        awarded=0,
        maximum=1,
        confidence_score=0.0,
        needs_review=True,
        review_reason=f"{_BLANK_ANSWER_REVIEW_REASON} | {_real_plagiarism_review_reason()}",
        marker_source="missing",
        plagiarism_flagged=True,
    )
    paper_id = _seed_console_paper(pg_sessionmaker, uploader=teacher, questions=[flagged_blank])

    with pg_sessionmaker() as session:
        items = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.teacher_paper_id == paper_id)
        ).all()
        reasons = {item.reason for item in items}
        # ONLY plagiarism_flag -- no fabricated low_confidence row.
        assert reasons == {ReviewReason.plagiarism_flag}


def test_review_reasons_for_structural_flag_survives_plagiarism_flag() -> None:
    """Finding A (US-039 consumer-fixes brief) -- Important, MUST-FIX.

    ``marking_flagged = needs_teacher_review and not plagiarism_flagged``
    used to drop the marking side's ``low_confidence`` row for *every*
    plagiarism-flagged question, including one the marker flagged for a
    structural reason (here, an out-of-range mark) at a confidence
    **above** ``REVIEW_CONFIDENCE_THRESHOLD``. The four structural reasons
    (``out_of_range``, ``value_mismatch``, ``coherence_mismatch``,
    ``no_span``) are documented as independent of the stated confidence
    (``correction_ai.py:1043-1055``), so losing the row loses the sole
    signal that the marker misread the mark scheme -- not a spurious
    duplicate.

    No unit test at this producer x flag tuple existed before this fix.
    Runs the REAL ``apply_integrity_checks`` pipeline to append the
    plagiarism segment (mirrors ``_real_plagiarism_review_reason`` above),
    rather than hand-typing it, so this cannot silently drift from what the
    real producer appends.
    """
    from lemely.core.loose_schemas import MarkScheme
    from lemely.db.models.enums import ReviewReason
    from lemely.db.review_queue_rules import review_reasons_for
    from lemely.io.integrity import apply_integrity_checks
    from lemely.runtime.config import IntegritySettings

    verbatim = "gravity acts on the object"
    scheme = MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_extended",
                "maximum_mark": 3,
                "scheme_format": "mixed",
            },
            "questions": [
                {
                    "id": "1",
                    "marks": 3,
                    "type": "explanation",
                    "answer_points": [{"id": "p1", "point": verbatim, "marks": 3}],
                },
            ],
        }
    )
    out_of_range_reason = "marker returned 4 marks for a 3-mark question (clamped to 3)"
    structural = CorrectedQuestion(
        question_id="1",
        awarded_marks=3,
        maximum_marks=3,
        confidence=ConfidenceBand.HIGH,
        confidence_score=0.97,
        needs_teacher_review=True,
        review_reason=out_of_range_reason,
        student_answer=verbatim,
        expected_answer=verbatim,
        marker_source="ai",
    )
    # Sanity: before any integrity flag, the structural reason alone queues.
    assert list(review_reasons_for(structural)) == [ReviewReason.low_confidence]

    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[structural],
    )
    flagged = apply_integrity_checks(
        correction, scheme, gemini_client=None, settings=IntegritySettings()
    ).questions[0]
    assert flagged.plagiarism_flagged is True
    assert flagged.review_reason == f"{out_of_range_reason} | plagiarism (score 1.00)"

    # The bug this guards: with the old ``not plagiarism_flagged`` check,
    # both disjuncts of ``low_confidence`` were silenced by the plagiarism
    # flag, leaving only ``plagiarism_flag``. With the fix, the structural
    # reason survives alongside it.
    assert set(review_reasons_for(flagged)) == {
        ReviewReason.low_confidence,
        ReviewReason.plagiarism_flag,
    }


def test_review_reasons_for_blank_carveout_does_not_fire_without_plagiarism_flag() -> None:
    """Regression guard for a bug this fix's own first draft introduced.

    Fixing Finding A by adding an ``_is_unflagged_blank(question)`` disjunct
    to ``marking_flagged``'s suppression, on its own, is wrong: it also fires
    for a NON-blank question whose ``review_reason`` happens to collide with
    ``_BLANK_ANSWER_REVIEW_REASON`` (the ``--mcq-only`` known-limit collision
    ``review_queue_rules.py``'s own docstring already discusses), even with
    NO plagiarism flag anywhere in sight -- silencing a real marking-side
    ``low_confidence`` row that has nothing to do with plagiarism. The
    exemption must be gated on ``question.plagiarism_flagged`` as well:
    ``_is_unflagged_blank`` only stands in for "``needs_teacher_review`` was
    forced True by integrity, not set genuinely by the builder", which is
    only true when integrity actually ran (i.e. the question IS flagged).

    Simulates the collision the module's own docstring already names rather
    than inventing a new one -- ``_build_missing_corrected``'s real
    ``--mcq-only`` literal, forced equal to ``_BLANK_ANSWER_REVIEW_REASON``.
    """
    from lemely.db.models.enums import ReviewReason
    from lemely.db.review_queue_rules import review_reasons_for
    from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON

    colliding_missing_question = CorrectedQuestion(
        question_id="1",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=True,
        review_reason=_BLANK_ANSWER_REVIEW_REASON,
        marker_source="missing",
        plagiarism_flagged=False,
    )
    # The bug this guards: gating the blank carve-out on
    # ``_is_unflagged_blank`` alone -- without also requiring
    # ``plagiarism_flagged`` -- silences this row entirely (``[]``) even
    # though no integrity check ever ran to force ``needs_teacher_review``.
    assert list(review_reasons_for(colliding_missing_question)) == [ReviewReason.low_confidence]


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
    retrievable on the question row itself. Also proves the weakness-record
    fix: both questions share topic "Waves", so restoring question "2" to
    full marks drops the topic's net lost marks to zero — its weakness row
    must disappear from ``weak_areas`` entirely, not linger claiming marks the
    teacher just restored."""
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    # Two questions, same topic, 5 marks total; question "2" is low-confidence
    # and flagged.
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

    # Before the override: 2/5 = 40% = grade U (< 50 threshold), and "Waves"
    # is a weak area (3 marks lost of 5, from question "2").
    before = DbHistoryStore(pg_sessionmaker).load(str(student)).records[-1]
    assert before.awarded_marks == 2
    assert before.percentage == 40.0
    assert before.grade == "U"
    before_waves = next(a for a in before.weak_areas if a.topic == "Waves")
    assert before_waves.lost_marks == 3
    assert before_waves.maximum_marks == 5

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
    # "Waves" no longer claims any lost marks — restored to full marks, it is
    # gone from the weakness set entirely (matching how a freshly-marked,
    # fully-correct attempt would be represented; no stale accuracy=1.0 row).
    assert all(a.topic != "Waves" for a in after.weak_areas)
    assert after.weak_areas == []

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.awarded_marks == 5
        assert attempt.percentage == 100.0
        assert attempt.grade == "A"
        assert attempt.predicted_grade == "A"

        # The WeaknessRecord row itself is gone, not just excluded by a
        # zero-loss filter somewhere downstream — proof the deletion is real.
        remaining_weakness_records = session.scalars(
            select(WeaknessRecord).where(WeaknessRecord.attempt_id == attempt_id)
        ).all()
        assert remaining_weakness_records == []

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


def test_resolve_override_updates_weakness_record_in_place_when_topic_still_weak(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """A partial restore that does not fully clear a topic's lost marks must
    update the existing ``WeaknessRecord`` in place — not delete it, and not
    leave it claiming the pre-override numbers."""
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    attempt_id = _seed_attempt_with_review_items(
        pg_sessionmaker,
        student,
        [
            # Overridden below: 0/3 -> 3/3.
            _question(
                "2a", awarded=0, maximum=3, confidence_score=0.2, needs_review=True, topic="Forces"
            ),
            # Same topic, untouched: still losing 1/2.
            _question("2b", awarded=1, maximum=2, confidence_score=1.0, topic="Forces"),
        ],
    )
    with pg_sessionmaker() as session:
        before_record = session.scalars(
            select(WeaknessRecord).where(
                WeaknessRecord.attempt_id == attempt_id, WeaknessRecord.topic == "Forces"
            )
        ).one()
        before_record_id = before_record.id
        assert before_record.lost_marks == 4  # 3 (2a) + 1 (2b)
        assert before_record.maximum_marks == 5
        assert set(before_record.question_ids) == {"2a", "2b"}

    with pg_sessionmaker() as session:
        item_id = session.scalars(
            select(ReviewQueueItem.id)
            .join(QuestionResult, ReviewQueueItem.question_result_id == QuestionResult.id)
            .where(ReviewQueueItem.attempt_id == attempt_id, QuestionResult.question_id == "2a")
        ).one()
    review_service.resolve(teacher, Role.teacher, item_id, override_marks=3)

    after = DbHistoryStore(pg_sessionmaker).load(str(student)).records[-1]
    forces = next(a for a in after.weak_areas if a.topic == "Forces")
    assert forces.lost_marks == 1  # only "2b" still lossy
    assert forces.maximum_marks == 5
    assert forces.question_ids == ["2b"]  # "2a" no longer claims lost marks

    with pg_sessionmaker() as session:
        records = session.scalars(
            select(WeaknessRecord).where(
                WeaknessRecord.attempt_id == attempt_id, WeaknessRecord.topic == "Forces"
            )
        ).all()
        # Updated in place — same row, not deleted-and-recreated.
        assert len(records) == 1
        assert records[0].id == before_record_id
        assert records[0].lost_marks == 1


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
