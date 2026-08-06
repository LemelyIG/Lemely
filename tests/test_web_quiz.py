"""Route tests for the quiz-builder endpoints (``lemely.web.routers.quiz``, P3.5 chunk D).

Self-contained (mirrors ``tests/test_web_review.py``/``tests/test_class_repo.py``)
— a throwaway Postgres DB per test, skipped cleanly when unreachable. Covers
payload shape for the CRUD/pool-count routes and the full authz matrix: a
teacher must never see, patch, transition, or edit another teacher's quiz.
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
from lemely.db.models import User
from lemely.db.models.enums import QuestionDifficulty, QuestionSource, QuizStatus, Role
from lemely.db.models.quizzes import QuestionBank
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_quiz_service

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


def _use_quiz_service(client: TestClient, quiz_service: QuizService) -> None:
    client.app.dependency_overrides[get_quiz_service] = lambda: quiz_service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_teacher(sm: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.teacher))
    return uid


def _seed_bank_row(
    sm: sessionmaker[Session],
    *,
    subject_code: str,
    difficulty: QuestionDifficulty = QuestionDifficulty.standard,
    owner_id: uuid.UUID | None = None,
    source: QuestionSource = QuestionSource.generated,
) -> uuid.UUID:
    from lemely.db.models.enums import DifficultySource, ExamBoard

    row_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionBank(
                id=row_id,
                board=ExamBoard.caie,
                subject_code=subject_code,
                source=source,
                owner_id=owner_id,
                difficulty=difficulty,
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="explanation",
                prompt="A dummy prompt",
                total_marks=2,
            )
        )
    return row_id


# ---------------------------------------------------------------------------
# CRUD happy path.
# ---------------------------------------------------------------------------


def test_create_and_get_quiz_round_trip(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post("/api/teacher/quizzes", json={"subjectCode": "0625", "title": "Recap"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["builderStep"] == 1
    assert body["questionCount"] == 0
    quiz_id = body["id"]

    get_resp = client.get(f"/api/teacher/quizzes/{quiz_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["quiz"]["id"] == quiz_id
    assert detail["questions"] == []


def test_list_quizzes_returns_only_callers_own(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher_a = _seed_teacher(pg_sessionmaker)
    teacher_b = _seed_teacher(pg_sessionmaker)
    quiz_service.create_quiz(teacher_a, "0625", "A's quiz")
    quiz_service.create_quiz(teacher_b, "0625", "B's quiz")

    _auth_as(client, teacher_a, Role.teacher)
    resp = client.get("/api/teacher/quizzes")
    assert resp.status_code == 200
    titles = {q["title"] for q in resp.json()["quizzes"]}
    assert titles == {"A's quiz"}


def test_patch_draft_partial_update(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    created = quiz_service.create_quiz(teacher, "0625", "Recap")

    resp = client.patch(
        f"/api/teacher/quizzes/{created.quiz_id}",
        json={"targetGrade": "B", "includedTopics": ["Waves"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["targetGrade"] == "B"
    assert body["includedTopics"] == ["Waves"]
    assert body["title"] == "Recap"  # untouched


def test_patch_draft_unknown_grade_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    created = quiz_service.create_quiz(teacher, "0625", "Recap")

    resp = client.patch(f"/api/teacher/quizzes/{created.quiz_id}", json={"targetGrade": "Q"})
    assert resp.status_code == 422


def test_set_status_transition(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    created = quiz_service.create_quiz(teacher, "0625", "Recap")

    resp = client.post(
        f"/api/teacher/quizzes/{created.quiz_id}/status", json={"status": "assigned"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "assigned"


def test_set_status_backwards_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    created = quiz_service.create_quiz(teacher, "0625", "Recap")
    quiz_service.set_status(teacher, created.quiz_id, QuizStatus.assigned)

    resp = client.post(f"/api/teacher/quizzes/{created.quiz_id}/status", json={"status": "draft"})
    assert resp.status_code == 422


def test_generate_and_remove_question(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    _seed_bank_row(pg_sessionmaker, subject_code="0625")
    created = quiz_service.create_quiz(teacher, "0625", "Recap")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )

    gen_resp = client.post(f"/api/teacher/quizzes/{created.quiz_id}/questions/generate")
    assert gen_resp.status_code == 200
    created_questions = gen_resp.json()["created"]
    assert len(created_questions) == 1
    ref = created_questions[0]["questionRef"]

    del_resp = client.delete(f"/api/teacher/quizzes/{created.quiz_id}/questions/{ref}")
    assert del_resp.status_code == 200
    assert del_resp.json()["questionCount"] == 0


# ---------------------------------------------------------------------------
# Pool-count.
# ---------------------------------------------------------------------------


def test_pool_count_happy_path_shape(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    _seed_bank_row(pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.standard)

    resp = client.get(
        "/api/teacher/quizzes/pool-count",
        params={
            "subject_code": "0625",
            "requested_count": 1,
            "source": "generated",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matching"] == 1
    assert body["requested"] == 1
    assert body["byBand"]["standard"] >= 0
    assert body["difficultyEstimated"] is False


def test_pool_count_honest_zero_message_for_past_paper(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(
        "/api/teacher/quizzes/pool-count",
        params={"subject_code": "0625-empty", "requested_count": 5, "source": "past_paper"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matching"] == 0
    assert body["shortfall"] is not None
    assert body["message"] is not None
    assert "0625-empty" in body["message"]
    assert "use generated questions" in body["message"].lower()


def test_pool_count_route_registered_before_quiz_id_route(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    """``GET /pool-count`` must never be swallowed by ``GET /{quiz_id}``."""
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(
        "/api/teacher/quizzes/pool-count",
        params={"subject_code": "0625", "requested_count": 0},
    )
    assert resp.status_code == 200
    assert "matching" in resp.json()


# ---------------------------------------------------------------------------
# Tenancy negatives — a teacher must never reach another teacher's quiz.
# ---------------------------------------------------------------------------


def test_get_another_teachers_quiz_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(owner, "0625", "Owner's quiz")

    _auth_as(client, intruder, Role.teacher)
    resp = client.get(f"/api/teacher/quizzes/{created.quiz_id}")
    assert resp.status_code == 403


def test_patch_another_teachers_quiz_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(owner, "0625", "Owner's quiz")

    _auth_as(client, intruder, Role.teacher)
    resp = client.patch(f"/api/teacher/quizzes/{created.quiz_id}", json={"title": "Hijacked"})
    assert resp.status_code == 403


def test_set_status_another_teachers_quiz_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(owner, "0625", "Owner's quiz")

    _auth_as(client, intruder, Role.teacher)
    resp = client.post(
        f"/api/teacher/quizzes/{created.quiz_id}/status", json={"status": "assigned"}
    )
    assert resp.status_code == 403


def test_generate_questions_another_teachers_quiz_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(owner, "0625", "Owner's quiz")
    quiz_service.patch_draft(
        owner, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )

    _auth_as(client, intruder, Role.teacher)
    resp = client.post(f"/api/teacher/quizzes/{created.quiz_id}/questions/generate")
    assert resp.status_code == 403


def test_remove_question_another_teachers_quiz_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(owner, "0625", "Owner's quiz")

    _auth_as(client, intruder, Role.teacher)
    resp = client.delete(f"/api/teacher/quizzes/{created.quiz_id}/questions/q1")
    assert resp.status_code == 403


def test_get_unknown_quiz_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/quizzes/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_unauthenticated_call_is_401(client: TestClient) -> None:
    resp = client.get("/api/teacher/quizzes")
    assert resp.status_code == 401


def test_student_role_cannot_reach_quiz_routes(
    client: TestClient, quiz_service: QuizService
) -> None:
    _use_quiz_service(client, quiz_service)
    _auth_as(client, uuid.uuid4(), Role.student)

    resp = client.get("/api/teacher/quizzes")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Assignments (§1.6, P3.5 chunk E).
# ---------------------------------------------------------------------------


def _assignable_quiz_id(
    client: TestClient, quiz_service: QuizService, sm: sessionmaker[Session], teacher: uuid.UUID
) -> str:
    _seed_bank_row(sm, subject_code="0625")
    created = quiz_service.create_quiz(teacher, "0625", "Assignable quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    quiz_service.generate_questions(teacher, created.quiz_id)
    return str(created.quiz_id)


def test_create_assignment_route_happy_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)
    cls = class_service.create_class(teacher, "9A")

    resp = client.post(
        f"/api/teacher/quizzes/{quiz_id}/assignments",
        json={"classId": str(cls.class_id)},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["classId"] == str(cls.class_id)
    assert body["className"] == "9A"
    assert body["rosterSize"] == 0
    assert body["submissionCounts"] == {
        "not_started": 0,
        "in_progress": 0,
        "submitted": 0,
        "marked": 0,
    }
    assert body["dueAt"] is None
    assert body["closesAt"] is None

    quiz_after = client.get(f"/api/teacher/quizzes/{quiz_id}").json()
    assert quiz_after["quiz"]["status"] == "assigned"


def test_create_assignment_route_with_due_and_closes_at(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)
    cls = class_service.create_class(teacher, "9A")

    resp = client.post(
        f"/api/teacher/quizzes/{quiz_id}/assignments",
        json={
            "classId": str(cls.class_id),
            "dueAt": "2026-02-01T00:00:00+00:00",
            "closesAt": "2026-02-03T00:00:00+00:00",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["dueAt"] == "2026-02-01T00:00:00+00:00"
    assert body["closesAt"] == "2026-02-03T00:00:00+00:00"


def test_create_assignment_route_closes_before_due_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)
    cls = class_service.create_class(teacher, "9A")

    resp = client.post(
        f"/api/teacher/quizzes/{quiz_id}/assignments",
        json={
            "classId": str(cls.class_id),
            "dueAt": "2026-02-03T00:00:00+00:00",
            "closesAt": "2026-02-01T00:00:00+00:00",
        },
    )
    assert resp.status_code == 422


def test_create_assignment_route_naive_datetime_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)
    cls = class_service.create_class(teacher, "9A")

    resp = client.post(
        f"/api/teacher/quizzes/{quiz_id}/assignments",
        json={"classId": str(cls.class_id), "dueAt": "2026-02-03T00:00:00"},
    )
    assert resp.status_code == 422


def test_create_assignment_route_empty_quiz_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    created = quiz_service.create_quiz(teacher, "0625", "Empty")
    cls = class_service.create_class(teacher, "9A")

    resp = client.post(
        f"/api/teacher/quizzes/{created.quiz_id}/assignments",
        json={"classId": str(cls.class_id)},
    )
    assert resp.status_code == 422


def test_create_assignment_route_out_of_scope_class_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    other_teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)
    other_cls = class_service.create_class(other_teacher, "Not mine")

    resp = client.post(
        f"/api/teacher/quizzes/{quiz_id}/assignments",
        json={"classId": str(other_cls.class_id)},
    )
    assert resp.status_code == 403


def test_create_assignment_route_another_teachers_quiz_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, owner)
    cls = class_service.create_class(intruder, "Intruder's class")

    _auth_as(client, intruder, Role.teacher)
    resp = client.post(
        f"/api/teacher/quizzes/{quiz_id}/assignments",
        json={"classId": str(cls.class_id)},
    )
    assert resp.status_code == 403


def test_list_assignments_route_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)
    cls = class_service.create_class(teacher, "9A")
    quiz_service.create_assignment(teacher, Role.teacher, uuid.UUID(quiz_id), cls.class_id)

    resp = client.get(f"/api/teacher/quizzes/{quiz_id}/assignments")
    assert resp.status_code == 200
    assignments = resp.json()["assignments"]
    assert len(assignments) == 1
    assert assignments[0]["classId"] == str(cls.class_id)
    assert assignments[0]["rosterSize"] == 0


def test_list_assignments_route_another_teachers_quiz_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
) -> None:
    _use_quiz_service(client, quiz_service)
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, owner)

    _auth_as(client, intruder, Role.teacher)
    resp = client.get(f"/api/teacher/quizzes/{quiz_id}/assignments")
    assert resp.status_code == 403


def test_delete_assignment_route_happy_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)
    cls = class_service.create_class(teacher, "9A")
    assignment = quiz_service.create_assignment(
        teacher, Role.teacher, uuid.UUID(quiz_id), cls.class_id
    )

    resp = client.delete(f"/api/teacher/quizzes/{quiz_id}/assignments/{assignment.assignment_id}")
    assert resp.status_code == 204

    remaining = client.get(f"/api/teacher/quizzes/{quiz_id}/assignments").json()
    assert remaining["assignments"] == []


def test_delete_assignment_route_refused_once_started(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    from lemely.db.models.enums import QuizSubmissionStatus
    from lemely.db.models.quizzes import QuizSubmission

    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)
    cls = class_service.create_class(teacher, "9A")
    assignment = quiz_service.create_assignment(
        teacher, Role.teacher, uuid.UUID(quiz_id), cls.class_id
    )
    student = _seed_teacher(pg_sessionmaker)  # any user id works as student_id here
    with pg_sessionmaker.begin() as session:
        session.add(
            QuizSubmission(
                assignment_id=assignment.assignment_id,
                student_id=student,
                status=QuizSubmissionStatus.in_progress,
            )
        )

    resp = client.delete(f"/api/teacher/quizzes/{quiz_id}/assignments/{assignment.assignment_id}")
    assert resp.status_code == 422


def test_delete_assignment_route_another_teachers_quiz_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    _use_quiz_service(client, quiz_service)
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, owner)
    cls = class_service.create_class(owner, "9A")
    assignment = quiz_service.create_assignment(
        owner, Role.teacher, uuid.UUID(quiz_id), cls.class_id
    )

    _auth_as(client, intruder, Role.teacher)
    resp = client.delete(f"/api/teacher/quizzes/{quiz_id}/assignments/{assignment.assignment_id}")
    assert resp.status_code == 403


def test_delete_assignment_route_unknown_assignment_is_404(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
) -> None:
    _use_quiz_service(client, quiz_service)
    teacher = _seed_teacher(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)
    quiz_id = _assignable_quiz_id(client, quiz_service, pg_sessionmaker, teacher)

    resp = client.delete(f"/api/teacher/quizzes/{quiz_id}/assignments/{uuid.uuid4()}")
    assert resp.status_code == 404
