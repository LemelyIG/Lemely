"""``SelfReviewService`` (self-review spec, 2026-09-17) against real Postgres.

Same throwaway-database fixture as ``tests/test_review_repo.py``. The scheme
is two point-based questions: "1" (2 marks, p1/p2) and "2" (3 marks,
p1/p2/p3); each test chooses the confidence of each question.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime  # noqa: F401
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
from lemely.core.self_review import JudgeRequest, JudgeVerdict  # noqa: F401
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult  # noqa: F401
from lemely.db.models.enums import ReviewReason, ReviewStatus, RevisionSource, Role  # noqa: F401
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.self_review_repo import (
    SELFMARK_RESOLUTION_NOTE,  # noqa: F401
    PendingPoint,
    PendingSelfReview,
    PointVerdict,
    RevealedSelfReview,  # noqa: F401
    SelfReviewAlreadySubmittedError,  # noqa: F401
    SelfReviewNotFoundError,
    SelfReviewService,
    SelfReviewValidationError,  # noqa: F401
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


def _load_qr(sm: sessionmaker[Session], qr_id: uuid.UUID) -> QuestionResult:  # noqa: F401
    with sm() as session:
        qr = session.get(QuestionResult, qr_id)
        assert qr is not None
        _ = qr.points, qr.revisions  # load before the session closes
        return qr


def _queue_rows(sm: sessionmaker[Session], qr_id: uuid.UUID) -> list[ReviewQueueItem]:  # noqa: F401
    with sm() as session:
        return list(
            session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.question_result_id == qr_id)
            ).all()
        )


def _service(sm: sessionmaker[Session], judge: object | None = None) -> SelfReviewService:
    return SelfReviewService(sm, judge=judge)  # type: ignore[arg-type]


def _all_earned(point_ids: list[str], evidence: str | None = None) -> list[PointVerdict]:  # noqa: F401
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
