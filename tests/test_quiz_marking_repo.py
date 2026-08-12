"""Tests for the quiz marking path (P3.5 chunk F1, ``docs/quiz-model.md`` §4).

Three layers, per the chunk brief:

* :func:`~lemely.db.quiz_marking_repo.quiz_question_to_scheme_question` — the
  pure adapter, unit-tested with no DB session at all.
* :meth:`~lemely.db.attempt_repo.AttemptRepository._persist` (via the public
  ``persist_quiz_correction``) — Postgres-integration tests of the
  ``prediction=None`` branch: percentage arithmetic, NULL grade columns,
  weakest-band confidence, and the synthetic-metadata trap
  (``docs/quiz-model.md`` §4.3).
* :class:`~lemely.db.quiz_marking_repo.QuizMarkingService` end to end, always
  against a fake/stubbed marker — MCQ quizzes exercise ``correct_paper``'s
  deterministic path (no Gemini call at all); the one non-MCQ test stubs the
  raw ``google-genai`` SDK boundary exactly as ``test_correction_ai.py`` does,
  never a live call (the Gemini budget is hard-capped).
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    WeakArea,
    WeaknessReport,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import ClassEnrollment, User
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import (
    AttemptOrigin,
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    QuizSubmissionStatus,
    Role,
)
from lemely.db.models.enums import (
    ConfidenceBand as DBConfidenceBand,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.models.quizzes import QuestionBank, QuizQuestion, QuizSubmission
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_marking_repo import (
    MarkSubmissionResult,
    QuizMarkingNotFoundError,
    QuizMarkingService,
    QuizMarkingValidationError,
    quiz_question_to_scheme_question,
)
from lemely.db.quiz_repo import QuizService
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.db.review_repo import ReviewService
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import DatabaseSettings, PathsSettings, load_settings

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixture: throwaway Postgres database (mirrors test_quiz_taking_repo.py).
# ---------------------------------------------------------------------------


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


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def bank_service(pg_sessionmaker: sessionmaker[Session]) -> QuestionBankService:
    return QuestionBankService(pg_sessionmaker)


@pytest.fixture
def quiz_service(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> QuizService:
    return QuizService(pg_sessionmaker, class_service, bank_service)


@pytest.fixture
def taking_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> QuizTakingService:
    return QuizTakingService(pg_sessionmaker, class_service)


@pytest.fixture
def attempt_repo(pg_sessionmaker: sessionmaker[Session]) -> AttemptRepository:
    return AttemptRepository(pg_sessionmaker)


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


def _seed_user(
    sm: sessionmaker[Session], role: Role, *, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_bank_row(
    sm: sessionmaker[Session],
    *,
    subject_code: str,
    question_type: str = "explanation",
    mark_scheme_points: list[str] | None = None,
    mcq_options: list[str] | None = None,
    mcq_answer: str | None = None,
    total_marks: int = 3,
    topic: str | None = "Waves",
) -> uuid.UUID:
    row_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionBank(
                id=row_id,
                board=ExamBoard.caie,
                subject_code=subject_code,
                source=QuestionSource.generated,
                difficulty=QuestionDifficulty.standard,
                difficulty_source=DifficultySource.declared_by_generator,
                question_type=question_type,
                topic=topic,
                prompt="Explain the phenomenon.",
                model_answer="SECRET model answer",
                mark_scheme_points=mark_scheme_points if mark_scheme_points is not None else ["p"],
                mcq_options=mcq_options,
                mcq_answer=mcq_answer,
                total_marks=total_marks,
            )
        )
    return row_id


def _assigned_quiz(
    quiz_service: QuizService,
    class_service: ClassService,
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0625",
    mcq: bool = False,
    mark_scheme_points: list[str] | None = None,
    total_marks: int = 3,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Build a teacher, an assigned one-question quiz, and an empty class.

    Returns ``(teacher_id, class_id, assignment_id)``.
    """
    teacher = _seed_user(sm, Role.teacher)
    if mcq:
        _seed_bank_row(
            sm,
            subject_code=subject_code,
            question_type="mcq",
            mark_scheme_points=[],
            mcq_options=["Option A", "Option B", "Option C", "Option D"],
            mcq_answer="B",
            total_marks=total_marks,
        )
    else:
        _seed_bank_row(
            sm,
            subject_code=subject_code,
            mark_scheme_points=mark_scheme_points,
            total_marks=total_marks,
        )
    created = quiz_service.create_quiz(teacher, subject_code, "Recap quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    quiz_service.generate_questions(teacher, created.quiz_id)
    cls = class_service.create_class(teacher, "9A")
    assignment = quiz_service.create_assignment(
        teacher, Role.teacher, created.quiz_id, cls.class_id
    )
    return teacher, cls.class_id, assignment.assignment_id


def _enroll(sm: sessionmaker[Session], class_id: uuid.UUID) -> uuid.UUID:
    student = _seed_user(sm, Role.student, display_name="Amira")
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student))
    return student


def _submit_with_answer(
    taking_service: QuizTakingService,
    student: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    answer_text: str,
) -> uuid.UUID:
    take = taking_service.get_take(student, assignment_id)
    ref = take.questions[0].question_ref
    taking_service.save_answer(student, assignment_id, ref, answer_text=answer_text)
    result = taking_service.submit(student, assignment_id)
    return result.submission_id


# ---------------------------------------------------------------------------
# Fake Gemini client (mirrors tests/test_correction_ai.py's boundary mock —
# the raw google-genai SDK client is replaced, never a live call).
# ---------------------------------------------------------------------------


def _mock_marker_response(awarded: int, confidence: float, feedback: str = "ok") -> MagicMock:
    body = {
        "awarded_marks": awarded,
        "confidence": confidence,
        "matched_point_ids": [],
        "feedback": feedback,
    }
    return MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
    )


def _gemini_client(tmp_path: Path, responses: list[MagicMock]) -> GeminiClient:
    mock_genai = MagicMock()
    mock_genai.models.generate_content.side_effect = responses
    mock_genai.files.upload.return_value = MagicMock()
    settings = load_settings(toml_path=None, cwd=tmp_path)
    settings = settings.model_copy(update={"paths": PathsSettings(cache_dir=tmp_path / ".cache")})
    return GeminiClient(settings, _genai_client=mock_genai)


def _never_called_gemini_client(tmp_path: Path) -> GeminiClient:
    """A client whose raw SDK boundary asserts it is never touched (MCQ-only tests)."""
    mock_genai = MagicMock()
    mock_genai.models.generate_content.side_effect = AssertionError(
        "Gemini must not be called for an all-MCQ quiz"
    )
    settings = load_settings(toml_path=None, cwd=tmp_path)
    settings = settings.model_copy(update={"paths": PathsSettings(cache_dir=tmp_path / ".cache")})
    return GeminiClient(settings, _genai_client=mock_genai)


# ---------------------------------------------------------------------------
# 1. The pure adapter — no DB session.
# ---------------------------------------------------------------------------


def _qq(**overrides: object) -> QuizQuestion:
    defaults: dict[str, object] = dict(
        question_ref="q1",
        total_marks=3,
        question_type="explanation",
        topic="Forces",
        mark_scheme_points=["p"],
        mcq_answer=None,
    )
    defaults.update(overrides)
    return QuizQuestion(**defaults)  # type: ignore[arg-type]


def test_adapter_question_ref_becomes_question_id() -> None:
    qq = _qq(question_ref="q7")
    question = quiz_question_to_scheme_question(qq)
    assert question.id == "q7"


def test_adapter_non_mcq_maps_marks_and_points() -> None:
    qq = _qq(
        question_type="explanation",
        total_marks=5,
        topic="Waves",
        mark_scheme_points=["gravity acts", "no resistance", "correct direction"],
        mcq_answer=None,
    )
    question = quiz_question_to_scheme_question(qq)
    assert question.marks == 5
    assert question.type.value == "explanation"
    assert question.topic_hint == "Waves"
    assert question.mcq_answer is None
    assert [p.id for p in question.answer_points] == ["p1", "p2", "p3"]
    assert [p.point for p in question.answer_points] == [
        "gravity acts",
        "no resistance",
        "correct direction",
    ]
    # The split sums exactly to total_marks and never exceeds any point's share.
    assert sum(p.marks for p in question.answer_points) == 5
    assert [p.marks for p in question.answer_points] == [2, 2, 1]


def test_adapter_mcq_sets_mcq_answer_and_no_points() -> None:
    qq = _qq(
        question_type="mcq",
        total_marks=1,
        mark_scheme_points=[],
        mcq_answer="B",
    )
    question = quiz_question_to_scheme_question(qq)
    assert question.type.value == "mcq"
    assert question.mcq_answer is not None
    assert question.mcq_answer.value == "B"
    assert question.answer_points == []


def test_adapter_empty_points_list_is_empty_answer_points() -> None:
    qq = _qq(mark_scheme_points=[])
    question = quiz_question_to_scheme_question(qq)
    assert question.answer_points == []


# ---------------------------------------------------------------------------
# 2. AttemptRepository._persist via persist_quiz_correction (prediction=None).
# ---------------------------------------------------------------------------


def _quiz_metadata(subject_code: str = "0625") -> ExamMetadata:
    """The exact synthetic shape ``_build_mark_scheme``/``_exam_metadata`` produce."""
    return ExamMetadata(
        subject_code=subject_code,
        paper_number=1,
        paper_variant=1,
        session_month="Specimen",
        session_year=None,
    )


def test_persist_quiz_correction_percentage_and_null_grade_columns(
    pg_sessionmaker: sessionmaker[Session], attempt_repo: AttemptRepository
) -> None:
    user_id = str(_seed_user(pg_sessionmaker, Role.student))
    high = CorrectedQuestion(
        question_id="q1",
        awarded_marks=3,
        maximum_marks=3,
        confidence=ConfidenceBand.HIGH,
        confidence_score=0.95,
        needs_teacher_review=False,
        marker_source="deterministic",
    )
    low = CorrectedQuestion(
        question_id="q2",
        awarded_marks=1,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.5,
        needs_teacher_review=True,
        marker_source="ai",
    )
    correction = CorrectionResult(metadata=_quiz_metadata(), questions=[high, low])
    weaknesses = WeaknessReport(weak_areas=[])

    attempt_id = attempt_repo.persist_quiz_correction(
        user_id=user_id, correction=correction, weaknesses=weaknesses
    )

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.origin == AttemptOrigin.quiz
        assert attempt.awarded_marks == 4
        assert attempt.maximum_marks == 5
        assert attempt.percentage == 80.0
        assert attempt.grade is None
        assert attempt.predicted_grade is None
        assert attempt.boundary_source is None
        # Weakest band across [HIGH, LOW] is LOW.
        assert attempt.confidence_band == DBConfidenceBand.low


def test_persist_quiz_correction_zero_maximum_guards_percentage(
    pg_sessionmaker: sessionmaker[Session], attempt_repo: AttemptRepository
) -> None:
    user_id = str(_seed_user(pg_sessionmaker, Role.student))
    zero = CorrectedQuestion(
        question_id="q1",
        awarded_marks=0,
        maximum_marks=0,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=False,
        marker_source="deterministic",
    )
    correction = CorrectionResult(metadata=_quiz_metadata(), questions=[zero])
    attempt_id = attempt_repo.persist_quiz_correction(
        user_id=user_id, correction=correction, weaknesses=WeaknessReport(weak_areas=[])
    )

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.percentage == 0.0


def test_persist_quiz_correction_never_persists_synthetic_metadata(
    pg_sessionmaker: sessionmaker[Session], attempt_repo: AttemptRepository
) -> None:
    """The synthetic-metadata trap (§4.3): only subject_code survives.

    ``correction.metadata`` carries the exact fiction ``_build_mark_scheme``
    synthesizes (paper_number=1, paper_variant=1, session_month="Specimen")
    — ``persist_quiz_correction`` must write NULL to all four
    paper/session columns regardless.
    """
    user_id = str(_seed_user(pg_sessionmaker, Role.student))
    question = CorrectedQuestion(
        question_id="q1",
        awarded_marks=2,
        maximum_marks=2,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=False,
        marker_source="deterministic",
    )
    correction = CorrectionResult(
        metadata=_quiz_metadata(subject_code="0680"), questions=[question]
    )
    attempt_id = attempt_repo.persist_quiz_correction(
        user_id=user_id, correction=correction, weaknesses=WeaknessReport(weak_areas=[])
    )

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.subject_code == "0680"
        assert attempt.paper_number is None
        assert attempt.paper_variant is None
        assert attempt.session_month is None
        assert attempt.session_year is None
        assert attempt.origin == AttemptOrigin.quiz


def test_persist_quiz_correction_writes_review_queue_for_low_confidence(
    pg_sessionmaker: sessionmaker[Session], attempt_repo: AttemptRepository
) -> None:
    """Confidence below REVIEW_CONFIDENCE_THRESHOLD queues a low_confidence item.

    Same fixture shape ``tests/test_attempt_repo.py`` uses for the past-paper
    persistence tests — the fan-out lives in ``_persist``, shared by both
    writers (docs/quiz-model.md §4.4).
    """
    user_id = str(_seed_user(pg_sessionmaker, Role.student))
    low = CorrectedQuestion(
        question_id="q1",
        awarded_marks=0,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.3,
        needs_teacher_review=True,
        marker_source="ai",
        review_reason="confidence 0.30 below review threshold 0.90",
    )
    correction = CorrectionResult(metadata=_quiz_metadata(), questions=[low])
    attempt_id = attempt_repo.persist_quiz_correction(
        user_id=user_id, correction=correction, weaknesses=WeaknessReport(weak_areas=[])
    )

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        assert len(items) == 1
        assert items[0].attempt_id == attempt_id
        assert items[0].reason.value == "low_confidence"


# ---------------------------------------------------------------------------
# 3. QuizMarkingService end to end, against a fake/stubbed marker.
# ---------------------------------------------------------------------------


def test_mark_submission_mcq_end_to_end_never_calls_gemini(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    tmp_path: Path,
) -> None:
    """The synthetic-metadata trap end to end (§4.3): mark a real submission.

    An all-MCQ quiz exercises ``correct_paper``'s deterministic path, so the
    Gemini client is asserted never called — the strictest possible stub.
    """
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker, mcq=True, subject_code="0625"
    )
    student = _enroll(pg_sessionmaker, class_id)
    submission_id = _submit_with_answer(taking_service, student, assignment_id, answer_text="B")

    service = QuizMarkingService(
        pg_sessionmaker, attempt_repo, _never_called_gemini_client(tmp_path)
    )
    result = service.mark_submission(submission_id)

    assert result.status == QuizSubmissionStatus.marked
    assert result.attempt_id is not None
    assert result.marking_error is None

    with pg_sessionmaker() as session:
        submission = session.get(QuizSubmission, submission_id)
        assert submission is not None
        assert submission.status == QuizSubmissionStatus.marked
        assert submission.attempt_id == result.attempt_id
        assert submission.marked_at is not None
        assert submission.marking_error is None

        attempt = session.get(Attempt, result.attempt_id)
        assert attempt is not None
        assert attempt.origin == AttemptOrigin.quiz
        assert attempt.subject_code == "0625"
        # The synthetic-metadata trap: none of these ever reach the row.
        assert attempt.paper_number is None
        assert attempt.paper_variant is None
        assert attempt.session_month is None
        assert attempt.session_year is None
        assert attempt.grade is None
        assert attempt.predicted_grade is None
        assert attempt.boundary_source is None
        # Correct MCQ answer -> full marks, deterministic HIGH confidence.
        assert attempt.awarded_marks == attempt.maximum_marks
        assert attempt.confidence_band == DBConfidenceBand.high


def test_mark_submission_is_idempotent(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    tmp_path: Path,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker, mcq=True
    )
    student = _enroll(pg_sessionmaker, class_id)
    submission_id = _submit_with_answer(taking_service, student, assignment_id, answer_text="B")

    service = QuizMarkingService(
        pg_sessionmaker, attempt_repo, _never_called_gemini_client(tmp_path)
    )
    first = service.mark_submission(submission_id)
    second = service.mark_submission(submission_id)

    assert second.status == QuizSubmissionStatus.marked
    assert second.attempt_id == first.attempt_id

    with pg_sessionmaker() as session:
        attempts = session.scalars(select(Attempt)).all()
        assert len(attempts) == 1


def test_mark_submission_not_submitted_is_validation_error(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    tmp_path: Path,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker, mcq=True
    )
    student = _enroll(pg_sessionmaker, class_id)
    # Open the quiz (creates an in_progress submission) but never submit it.
    taking_service.get_take(student, assignment_id)
    with pg_sessionmaker() as session:
        submission = session.scalars(select(QuizSubmission)).one()
        submission_id = submission.id

    service = QuizMarkingService(
        pg_sessionmaker, attempt_repo, _never_called_gemini_client(tmp_path)
    )
    with pytest.raises(QuizMarkingValidationError):
        service.mark_submission(submission_id)


def test_mark_submission_unknown_id_is_not_found(
    pg_sessionmaker: sessionmaker[Session], attempt_repo: AttemptRepository, tmp_path: Path
) -> None:
    service = QuizMarkingService(
        pg_sessionmaker, attempt_repo, _never_called_gemini_client(tmp_path)
    )
    with pytest.raises(QuizMarkingNotFoundError):
        service.mark_submission(uuid.uuid4())


def test_mark_submission_records_marking_error_and_leaves_status_submitted(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    tmp_path: Path,
) -> None:
    """A quiz whose subject code cannot satisfy ExamMetadata's 4-digit pattern
    fails inside the marking phase; the submission must stay observable
    (``submitted`` + ``marking_error``), not silently vanish or get stuck
    unmarked with no explanation."""
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker, mcq=True, subject_code="BAD"
    )
    student = _enroll(pg_sessionmaker, class_id)
    submission_id = _submit_with_answer(taking_service, student, assignment_id, answer_text="B")

    service = QuizMarkingService(
        pg_sessionmaker, attempt_repo, _never_called_gemini_client(tmp_path)
    )
    result = service.mark_submission(submission_id)

    assert result.status == QuizSubmissionStatus.submitted
    assert result.attempt_id is None
    assert result.marking_error is not None

    with pg_sessionmaker() as session:
        submission = session.get(QuizSubmission, submission_id)
        assert submission is not None
        assert submission.status == QuizSubmissionStatus.submitted
        assert submission.attempt_id is None
        assert submission.marking_error is not None
        attempts = session.scalars(select(Attempt)).all()
        assert attempts == []


def test_mark_submission_low_confidence_non_mcq_queues_review(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    tmp_path: Path,
) -> None:
    """A non-MCQ answer marked below REVIEW_CONFIDENCE_THRESHOLD by the (stubbed)
    AI marker produces a low_confidence ReviewQueueItem — the same P3.4 queue
    a past paper uses."""
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service,
        class_service,
        pg_sessionmaker,
        mcq=False,
        mark_scheme_points=["key point"],
        total_marks=2,
    )
    student = _enroll(pg_sessionmaker, class_id)
    submission_id = _submit_with_answer(
        taking_service, student, assignment_id, answer_text="A partial answer"
    )

    gemini = _gemini_client(tmp_path, [_mock_marker_response(awarded=1, confidence=0.5)])
    service = QuizMarkingService(pg_sessionmaker, attempt_repo, gemini)
    result = service.mark_submission(submission_id)

    assert result.status == QuizSubmissionStatus.marked
    assert result.attempt_id is not None

    with pg_sessionmaker() as session:
        items = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == result.attempt_id)
        ).all()
        assert len(items) == 1
        assert items[0].reason.value == "low_confidence"


# ---------------------------------------------------------------------------
# 4. The review guard (§4.5): overriding a quiz attempt never invents a grade.
# ---------------------------------------------------------------------------


def test_resolve_override_on_quiz_attempt_leaves_grade_null(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    attempt_repo: AttemptRepository,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    low = CorrectedQuestion(
        question_id="q1",
        awarded_marks=0,
        maximum_marks=3,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.2,
        needs_teacher_review=True,
        topic="Waves",
        marker_source="ai",
    )
    correction = CorrectionResult(metadata=_quiz_metadata(), questions=[low])
    attempt_id = attempt_repo.persist_quiz_correction(
        user_id=str(student),
        correction=correction,
        weaknesses=WeaknessReport(
            weak_areas=[
                WeakArea(
                    topic="Waves",
                    lost_marks=3,
                    maximum_marks=3,
                    accuracy=0.0,
                    question_ids=["q1"],
                )
            ]
        ),
    )

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.grade is None
        item = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt_id)
        ).one()
        item_id = item.id

    review_service = ReviewService(pg_sessionmaker, class_service)
    row = review_service.resolve(
        teacher, Role.teacher, item_id, override_marks=3, note="Full credit"
    )
    assert row.ai_awarded_marks == 0

    with pg_sessionmaker() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        # The mandatory quiz guard: still no grade, ever.
        assert attempt.grade is None
        assert attempt.predicted_grade is None
        assert attempt.boundary_source is None
        # But the totals DID update from the override.
        assert attempt.awarded_marks == 3
        assert attempt.percentage == 100.0


# ---------------------------------------------------------------------------
# 5. Structural leak guard.
# ---------------------------------------------------------------------------


def test_mark_submission_result_carries_no_marking_material() -> None:
    """Pinned structurally (D3.8's discipline): F1 adds no student-facing read
    of the marking result at all, so there is no field here for
    model_answer/mark_scheme_points/mcq_answer to leak into."""
    names = {f.name for f in dataclasses.fields(MarkSubmissionResult)}
    assert names == {"submission_id", "status", "attempt_id", "marking_error"}
