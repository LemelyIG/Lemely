"""Route tests for the student quiz-taking endpoints (``/api/student/quizzes/*``, S-26).

Self-contained (mirrors ``tests/test_web_quiz.py``) — a throwaway Postgres DB
per test, skipped cleanly when unreachable. Covers payload shape, the
403-vs-404 tenancy split (a student not enrolled in the assigned class must
never reach the assignment), and — the one way this chunk can leak marking
material — an explicit assertion that the take payload's raw JSON contains
none of ``modelAnswer``/``markSchemePoints``/``mcqAnswer``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import ClassEnrollment, User
from lemely.db.models.enums import (
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    Role,
)
from lemely.db.models.quizzes import QuestionBank
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizService
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_quiz_taking_service

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


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


def _use_taking_service(client: TestClient, taking_service: QuizTakingService) -> None:
    client.app.dependency_overrides[get_quiz_taking_service] = (  # type: ignore[union-attr]
        lambda: taking_service
    )


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


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
    prompt: str = "Explain photosynthesis.",
    model_answer: str = "SECRET model answer text",
    mark_scheme_points: list[str] | None = None,
    mcq_options: list[str] | None = None,
    mcq_answer: str | None = None,
    question_type: str = "explanation",
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
                prompt=prompt,
                model_answer=model_answer,
                mark_scheme_points=mark_scheme_points or ["SECRET marking point one"],
                mcq_options=mcq_options,
                mcq_answer=mcq_answer,
                total_marks=3,
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
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Build a teacher, an assigned quiz with one question, and an empty class.

    Returns ``(teacher_id, class_id, assignment_id)``.
    """
    teacher = _seed_user(sm, Role.teacher, display_name="Mr Osei")
    if mcq:
        _seed_bank_row(
            sm,
            subject_code=subject_code,
            question_type="mcq",
            mcq_options=["Option A", "Option B", "Option C", "Option D"],
            mcq_answer="B",
        )
    else:
        _seed_bank_row(sm, subject_code=subject_code)
    created = quiz_service.create_quiz(teacher, subject_code, "Recap quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    quiz_service.generate_questions(teacher, created.quiz_id)
    cls = class_service.create_class(teacher, "9A")
    assignment = quiz_service.create_assignment(
        teacher, Role.teacher, created.quiz_id, cls.class_id
    )
    return teacher, cls.class_id, str(assignment.assignment_id)


def _enroll(sm: sessionmaker[Session], class_id: uuid.UUID) -> uuid.UUID:
    student = _seed_user(sm, Role.student, display_name="Amira")
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student))
    return student


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------


def test_list_student_quizzes_happy_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(pg_sessionmaker, class_id)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/quizzes")
    assert resp.status_code == 200
    quizzes = resp.json()["quizzes"]
    assert len(quizzes) == 1
    assert quizzes[0]["assignmentId"] == assignment_id
    assert quizzes[0]["teacherName"] == "Mr Osei"
    assert quizzes[0]["submissionStatus"] == "not_started"
    assert quizzes[0]["isOpen"] is True


def test_list_student_quizzes_empty_when_not_enrolled_anywhere(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, outsider, Role.student)

    resp = client.get("/api/student/quizzes")
    assert resp.status_code == 200
    assert resp.json()["quizzes"] == []


# ---------------------------------------------------------------------------
# Take payload + answer-leak guard.
# ---------------------------------------------------------------------------


def test_get_take_route_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(pg_sessionmaker, class_id)
    _auth_as(client, student, Role.student)

    resp = client.get(f"/api/student/quizzes/{assignment_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["header"]["quizTitle"] == "Recap quiz"
    assert body["header"]["teacherName"] == "Mr Osei"
    assert body["header"]["submissionStatus"] == "in_progress"
    assert body["header"]["unansweredCount"] == 1
    assert len(body["questions"]) == 1
    q = body["questions"][0]
    assert q["prompt"] == "Explain photosynthesis."
    assert q["answerText"] is None


def test_get_take_route_never_leaks_marking_material(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    """The one way this chunk can leak answers to a student: guard it explicitly."""
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker, mcq=True
    )
    student = _enroll(pg_sessionmaker, class_id)
    _auth_as(client, student, Role.student)

    resp = client.get(f"/api/student/quizzes/{assignment_id}")
    assert resp.status_code == 200
    raw = resp.text

    assert "modelAnswer" not in raw
    assert "markSchemePoints" not in raw
    assert "mcqAnswer" not in raw
    assert "SECRET model answer text" not in raw
    assert "SECRET marking point one" not in raw
    # The MCQ correct-answer letter ("B") must not appear as a value anywhere
    # a student can read it either.
    question = resp.json()["questions"][0]
    assert set(question.keys()) == {
        "id",
        "questionRef",
        "position",
        "topic",
        "difficulty",
        "questionType",
        "prompt",
        "totalMarks",
        "mcqOptions",
        "answerText",
        "workingText",
        "answeredAt",
    }


def test_get_take_route_not_enrolled_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, outsider, Role.student)

    resp = client.get(f"/api/student/quizzes/{assignment_id}")
    assert resp.status_code == 403


def test_get_take_route_unknown_assignment_is_404(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    student = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, student, Role.student)

    resp = client.get(f"/api/student/quizzes/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_teacher_role_cannot_reach_student_quiz_routes(
    client: TestClient, taking_service: QuizTakingService
) -> None:
    _use_taking_service(client, taking_service)
    _auth_as(client, uuid.uuid4(), Role.teacher)

    resp = client.get("/api/student/quizzes")
    assert resp.status_code == 403


def test_unauthenticated_call_is_401(client: TestClient) -> None:
    resp = client.get("/api/student/quizzes")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Answer auto-save.
# ---------------------------------------------------------------------------


def test_save_answer_route_upserts(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(pg_sessionmaker, class_id)
    _auth_as(client, student, Role.student)
    take = client.get(f"/api/student/quizzes/{assignment_id}").json()
    ref = take["questions"][0]["questionRef"]

    resp = client.put(
        f"/api/student/quizzes/{assignment_id}/answers/{ref}",
        json={"answerText": "Photosynthesis is..."},
    )
    assert resp.status_code == 200
    assert resp.json()["answerText"] == "Photosynthesis is..."

    resp2 = client.put(
        f"/api/student/quizzes/{assignment_id}/answers/{ref}",
        json={"answerText": "Final version"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["answerText"] == "Final version"

    take_after = client.get(f"/api/student/quizzes/{assignment_id}").json()
    assert take_after["questions"][0]["answerText"] == "Final version"


def test_save_answer_route_unknown_ref_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(pg_sessionmaker, class_id)
    _auth_as(client, student, Role.student)

    resp = client.put(f"/api/student/quizzes/{assignment_id}/answers/q99", json={"answerText": "x"})
    assert resp.status_code == 422


def test_save_answer_route_not_enrolled_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, outsider, Role.student)

    resp = client.put(f"/api/student/quizzes/{assignment_id}/answers/q1", json={"answerText": "x"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Submit.
# ---------------------------------------------------------------------------


def test_submit_route_happy_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(pg_sessionmaker, class_id)
    _auth_as(client, student, Role.student)
    take = client.get(f"/api/student/quizzes/{assignment_id}").json()
    ref = take["questions"][0]["questionRef"]
    client.put(
        f"/api/student/quizzes/{assignment_id}/answers/{ref}", json={"answerText": "Answered"}
    )

    resp = client.post(f"/api/student/quizzes/{assignment_id}/submit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["submissionStatus"] == "submitted"
    assert body["answeredCount"] == 1
    assert body["unansweredCount"] == 0


def test_submit_route_second_submit_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(pg_sessionmaker, class_id)
    _auth_as(client, student, Role.student)
    client.get(f"/api/student/quizzes/{assignment_id}")
    client.post(f"/api/student/quizzes/{assignment_id}/submit")

    resp = client.post(f"/api/student/quizzes/{assignment_id}/submit")
    assert resp.status_code == 422


def test_submit_route_without_opening_first_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(pg_sessionmaker, class_id)
    _auth_as(client, student, Role.student)

    resp = client.post(f"/api/student/quizzes/{assignment_id}/submit")
    assert resp.status_code == 422


def test_submit_route_not_enrolled_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
) -> None:
    _use_taking_service(client, taking_service)
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, outsider, Role.student)

    resp = client.post(f"/api/student/quizzes/{assignment_id}/submit")
    assert resp.status_code == 403
