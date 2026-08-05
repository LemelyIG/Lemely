"""HTTP-layer tests for the class-model endpoints (D3.1/P3.1).

Exercises the two paths carried over from the old implicit-cohort endpoints
(``GET /api/teacher/classes``, ``GET /api/classes/{class_id}``) plus the CRUD/
roster/enrolment/join surface, against a real :class:`ClassService` bound to a
throwaway Postgres database (mirrors ``test_seat_repo.py``'s skip-cleanly
fixture) with a real :class:`HistoryStore` for the analytics side. Ownership
logic itself is proven in ``tests/test_class_repo.py``; this file proves the
HTTP layer — DTO field names, status-code mapping, and (the regression that
matters most after P3.1) that class analytics are computed over the class's
*real* enrolled roster, never every student in the store.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.base import Base
from lemely.db.class_repo import ClassService, JoinCodeError
from lemely.db.models import School, SchoolMembership, Seat, User
from lemely.db.models.enums import MembershipRole, Role, SeatStatus
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_class_service,
    get_history_store,
    get_settings,
)
from lemely.web.routers.classes import _raise_for

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures.
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
    """A sessionmaker bound to a throwaway Postgres DB; skips if unreachable."""
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
def settings(tmp_path: Path) -> Settings:
    base = load_settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    return Settings.model_validate(data)


@pytest.fixture
def history_store(settings: Settings) -> HistoryStore:
    return HistoryStore(settings.paths.output_dir / "history")


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def client(
    settings: Settings,
    history_store: HistoryStore,
    class_service: ClassService,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_history_store] = lambda: history_store
    app.dependency_overrides[get_class_service] = lambda: class_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_user(sm: sessionmaker[Session], role: Role, display_name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_history(
    store: HistoryStore,
    student_id: uuid.UUID,
    *,
    percentage: float,
    grade: str,
    days_ago: int = 0,
) -> None:
    """Append one paper to a student's history.

    ``days_ago`` matters: since P3.2 the class-detail "At risk" card runs the
    D3.3 rules engine, whose inactivity rule fires at >= 14 days. Seeding
    defaults to *now* so a fixture student is "active" unless a test explicitly
    makes them stale.
    """
    metadata = ExamMetadata(
        subject_code="0625",
        paper_number=3,
        paper_variant=1,
        session_month="May/June",
        session_year=2020,
    )
    recorded_at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    store.append(
        str(student_id),
        PaperRecord(
            student_id=str(student_id),
            metadata=metadata,
            awarded_marks=int(percentage / 100 * 80),
            maximum_marks=80,
            percentage=percentage,
            grade=grade,
            weak_areas=[
                WeakArea(
                    topic="Thermal physics",
                    lost_marks=10,
                    maximum_marks=40,
                    accuracy=0.75,
                    question_ids=["3a"],
                )
            ],
            recorded_at=recorded_at,
        ),
    )


# ---------------------------------------------------------------------------
# GET /api/teacher/classes — real roster, teacher-scoped.
# ---------------------------------------------------------------------------


def test_list_classes_empty_for_teacher_with_none(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    assert client.get("/api/teacher/classes").json()["classes"] == []


def test_list_classes_summarises_real_roster(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    amelia = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    jonas = _seed_user(pg_sessionmaker, Role.student, display_name="Jonas")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(amelia, cls.join_code)
    class_service.join_by_code(jonas, cls.join_code)
    _seed_history(history_store, amelia, percentage=90.0, grade="A")
    _seed_history(history_store, jonas, percentage=50.0, grade="D")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    classes = client.get("/api/teacher/classes").json()["classes"]
    assert len(classes) == 1
    assert classes[0]["id"] == str(cls.class_id)
    assert classes[0]["label"] == "Physics 10A"
    assert classes[0]["studentCount"] == 2
    assert classes[0]["average"] == 70.0
    assert classes[0]["joinCode"] == cls.join_code


def test_list_classes_excludes_other_teachers_classes(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    other_teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_service.create_class(other_teacher, "Not mine")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    assert client.get("/api/teacher/classes").json()["classes"] == []


# ---------------------------------------------------------------------------
# GET /api/classes/{class_id} — analytics over the real roster only.
# ---------------------------------------------------------------------------


def test_class_detail_scopes_to_enrolled_roster_only(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """A student with history but NOT enrolled must not appear in the class.

    This is the precise regression P3.1 fixes: the old implicit endpoint
    treated *every* student with history as one cohort — a cross-tenant leak.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    amelia = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    outsider = _seed_user(pg_sessionmaker, Role.student, display_name="Outsider")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(amelia, cls.join_code)
    _seed_history(history_store, amelia, percentage=90.0, grade="A")
    # Has history, but was never enrolled in this class.
    _seed_history(history_store, outsider, percentage=50.0, grade="D")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    body = client.get(f"/api/classes/{cls.class_id}").json()
    names = {r["name"] for r in body["students"]}
    ids = {r["studentId"] for r in body["students"]}
    assert names == {"Amelia"}
    assert ids == {str(amelia)}
    dist = {b["grade"]: b["count"] for b in body["distribution"]}
    assert dist["A"] == 1
    assert dist["D"] == 0  # outsider's D must not leak in
    assert body["stats"] == [s for s in body["stats"] if s["key"] != "At risk" or s["value"] == "0"]


def test_class_detail_unknown_id_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.get(f"/api/classes/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_class_detail_malformed_id_is_4xx_not_500(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.get("/api/classes/not-a-uuid")
    assert 400 <= resp.status_code < 500


def test_class_detail_by_non_owner_is_403_not_leaked_data(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(owner, "Physics 10A")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(stranger), role=Role.teacher.value
    )
    resp = client.get(f"/api/classes/{cls.class_id}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/classes/{class_id}/analytics — T-04 cohort analytics (P3.3).
# ---------------------------------------------------------------------------


def test_class_analytics_happy_path_payload_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    amelia = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    jonas = _seed_user(pg_sessionmaker, Role.student, display_name="Jonas")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(amelia, cls.join_code)
    class_service.join_by_code(jonas, cls.join_code)
    _seed_history(history_store, amelia, percentage=90.0, grade="A")
    _seed_history(history_store, jonas, percentage=50.0, grade="D")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    body = client.get(f"/api/classes/{cls.class_id}/analytics").json()

    # Both students share the seeded "Thermal physics" weak area -> ranked #1.
    assert body["topicWeaknesses"]
    top = body["topicWeaknesses"][0]
    assert top["topic"] == "Thermal physics"
    assert set(top["studentIds"]) == {str(amelia), str(jonas)}

    heatmap_students = {c["studentId"] for c in body["heatmap"]}
    assert heatmap_students == {str(amelia), str(jonas)}

    assert len(body["gradeDistribution"]) == 7  # full GRADE_ORDER ladder
    dist = {b["grade"]: b["count"] for b in body["gradeDistribution"]}
    assert dist["A"] == 1
    assert dist["D"] == 1

    assert body["trend"]
    assert body["paperComparison"]
    paper = body["paperComparison"][0]
    assert paper["studentCount"] == 2
    assert paper["attemptCount"] == 2

    engagement = body["engagement"]
    assert engagement["neverActiveCount"] == 0
    assert engagement["activeStudentsLast7Days"] == 2


def test_class_analytics_scopes_to_enrolled_roster_only(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """An outsider with history but not enrolled must not leak into analytics."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    amelia = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    outsider = _seed_user(pg_sessionmaker, Role.student, display_name="Outsider")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(amelia, cls.join_code)
    _seed_history(history_store, amelia, percentage=90.0, grade="A")
    _seed_history(history_store, outsider, percentage=10.0, grade="U")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    body = client.get(f"/api/classes/{cls.class_id}/analytics").json()
    dist = {b["grade"]: b["count"] for b in body["gradeDistribution"]}
    assert dist["U"] == 0  # outsider's U must not leak in
    heatmap_students = {c["studentId"] for c in body["heatmap"]}
    assert str(outsider) not in heatmap_students


def test_class_analytics_empty_class_is_a_coherent_empty_payload(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Empty Class")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    body = client.get(f"/api/classes/{cls.class_id}/analytics").json()
    assert body["topicWeaknesses"] == []
    assert body["heatmap"] == []
    assert body["trend"] == []
    assert body["paperComparison"] == []
    assert body["engagement"]["neverActiveCount"] == 0
    assert body["engagement"]["medianDaysSinceLastSubmission"] is None


def test_class_analytics_unknown_id_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.get(f"/api/classes/{uuid.uuid4()}/analytics")
    assert resp.status_code == 404


def test_class_analytics_malformed_id_is_4xx_not_500(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.get("/api/classes/not-a-uuid/analytics")
    assert 400 <= resp.status_code < 500


def test_class_analytics_by_non_owner_is_403_not_leaked_data(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(owner, "Physics 10A")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(stranger), role=Role.teacher.value
    )
    resp = client.get(f"/api/classes/{cls.class_id}/analytics")
    assert resp.status_code == 403


def test_class_analytics_platform_admin_gets_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """No super-role bypass (D1.6/D1.10): platform_admin sees no class analytics."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    admin = _seed_user(pg_sessionmaker, Role.platform_admin)
    cls = class_service.create_class(teacher, "Physics 10A")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(admin), role=Role.platform_admin.value
    )
    resp = client.get(f"/api/classes/{cls.class_id}/analytics")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# CRUD + roster + enrolment + join.
# ---------------------------------------------------------------------------


def test_create_class_independent_teacher(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.post("/api/classes", json={"name": "Home Tuition"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["label"] == "Home Tuition"
    assert body["schoolId"] is None
    assert body["joinCode"]


def test_create_class_school_admin_rejected(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(admin), role=Role.school_admin.value
    )
    resp = client.post("/api/classes", json={"name": "Not allowed"})
    assert resp.status_code == 403


def test_enroll_by_seat_requires_seat(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    school_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(School(id=school_id, name="Test School", seat_quota=5))
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=teacher, membership_role=MembershipRole.teacher
            )
        )
    cls = class_service.create_class(teacher, "Physics 10A", school_id=school_id)

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.post(f"/api/classes/{cls.class_id}/enroll", json={"studentId": str(student)})
    assert resp.status_code == 409


def test_student_join_by_code_and_get_roster(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(student), role=Role.student.value
    )
    join_resp = client.post("/api/student/classes/join", json={"joinCode": cls.join_code})
    assert join_resp.status_code == 200
    assert join_resp.json() == {"classId": str(cls.class_id), "className": "Physics 10A"}

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    roster = client.get(f"/api/classes/{cls.class_id}/roster").json()["students"]
    assert roster == [{"studentId": str(student), "displayName": "Amelia"}]


def test_student_join_unknown_code_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(student), role=Role.student.value
    )
    resp = client.post("/api/student/classes/join", json={"joinCode": "NOPE1234"})
    assert resp.status_code == 404


def test_remove_student_then_roster_empty(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.delete(f"/api/classes/{cls.class_id}/students/{student}")
    assert resp.status_code == 204
    assert client.get(f"/api/classes/{cls.class_id}/roster").json()["students"] == []
    # Idempotent.
    resp2 = client.delete(f"/api/classes/{cls.class_id}/students/{student}")
    assert resp2.status_code == 204


def test_enroll_by_seat_succeeds_for_seated_student(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """The direct-add happy path: a student holding a seat in the class's school."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    school_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(School(id=school_id, name="Test School", seat_quota=5))
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=teacher, membership_role=MembershipRole.teacher
            )
        )
        session.add(Seat(school_id=school_id, assigned_user_id=student, status=SeatStatus.assigned))
    cls = class_service.create_class(teacher, "Physics 10A", school_id=school_id)

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.post(f"/api/classes/{cls.class_id}/enroll", json={"studentId": str(student)})
    assert resp.status_code == 200
    assert resp.json() == {"studentId": str(student), "displayName": "Amelia"}
    # Idempotent — re-enrolling the same student does not duplicate the roster row.
    assert (
        client.post(
            f"/api/classes/{cls.class_id}/enroll", json={"studentId": str(student)}
        ).status_code
        == 200
    )
    assert len(client.get(f"/api/classes/{cls.class_id}/roster").json()["students"]) == 1


def test_enroll_into_independent_class_is_409(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """An independent teacher's class has no seat pool, so direct-add cannot apply."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    cls = class_service.create_class(teacher, "Home Tuition")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.post(f"/api/classes/{cls.class_id}/enroll", json={"studentId": str(student)})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# "At risk" means the D3.3 rules engine here, exactly as it does on the
# teacher overview — not the shallower "latest grade is D/E/U" test (P3.2).
# ---------------------------------------------------------------------------


def _at_risk_card(body: dict[str, object]) -> str:
    stats = body["stats"]
    assert isinstance(stats, list)
    return next(s["value"] for s in stats if s["key"] == "At risk")


def test_at_risk_card_ignores_a_low_but_stable_active_grade(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """A steady D who is still submitting is NOT "at risk" under the D3.3 rules.

    The pre-P3.2 card counted any D/E/U. That is a different question ("is this
    grade low?") from the one the flag engine answers ("is this student on a
    declining trajectory / inactive / far below target?"), and the per-row
    ``gradeAtRisk`` badge still answers the former.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Steady")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    # Flat, recent, and low: no decline, no inactivity.
    _seed_history(history_store, student, percentage=45.0, grade="D", days_ago=2)

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    body = client.get(f"/api/classes/{cls.class_id}").json()
    assert _at_risk_card(body) == "0"
    # ...but the low grade still shows on the student's own row badge.
    assert body["students"][0]["gradeAtRisk"] is True


def test_at_risk_card_counts_an_inactive_student(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """A strong grade does not exempt a student who stopped submitting."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Vanished")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    _seed_history(history_store, student, percentage=88.0, grade="A", days_ago=30)

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    body = client.get(f"/api/classes/{cls.class_id}").json()
    assert _at_risk_card(body) == "1"
    assert body["students"][0]["gradeAtRisk"] is False


# ---------------------------------------------------------------------------
# Role scoping at the HTTP layer (D3.1: school_admin reads, platform_admin never).
# ---------------------------------------------------------------------------


def test_school_admin_sees_classes_in_their_school(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(School(id=school_id, name="Test School", seat_quota=5))
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=teacher, membership_role=MembershipRole.teacher
            )
        )
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=admin, membership_role=MembershipRole.school_admin
            )
        )
    cls = class_service.create_class(teacher, "Physics 10A", school_id=school_id)

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(admin), role=Role.school_admin.value
    )
    classes = client.get("/api/teacher/classes").json()["classes"]
    assert [c["id"] for c in classes] == [str(cls.class_id)]
    assert client.get(f"/api/classes/{cls.class_id}").status_code == 200


def test_platform_admin_sees_no_classes(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """No super-role bypass: a platform_admin gets an empty list and a 403 on detail."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    admin = _seed_user(pg_sessionmaker, Role.platform_admin)
    cls = class_service.create_class(teacher, "Physics 10A")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(admin), role=Role.platform_admin.value
    )
    assert client.get("/api/teacher/classes").json()["classes"] == []
    assert client.get(f"/api/classes/{cls.class_id}").status_code == 403


def test_create_class_in_a_school_without_membership_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A teacher cannot plant a class in a school they do not belong to."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    school_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(School(id=school_id, name="Someone Else's School", seat_quota=5))

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.post("/api/classes", json={"name": "Trespass", "schoolId": str(school_id)})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Update / delete — owner-scoped, and their error mappings.
# ---------------------------------------------------------------------------


def test_update_class_renames_it(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.patch(
        f"/api/classes/{cls.class_id}", json={"name": "Physics 10B", "subjectCode": "0625"}
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "Physics 10B"
    assert resp.json()["subjectCode"] == "0625"


def test_update_class_by_non_owner_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(owner, "Physics 10A")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(stranger), role=Role.teacher.value
    )
    assert (
        client.patch(f"/api/classes/{cls.class_id}", json={"name": "Hijacked"}).status_code == 403
    )
    # And the rename did not happen.
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(owner), role=Role.teacher.value
    )
    assert client.get(f"/api/classes/{cls.class_id}").json()["label"] == "Physics 10A"


def test_delete_class_then_detail_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    assert client.delete(f"/api/classes/{cls.class_id}").status_code == 204
    assert client.get(f"/api/classes/{cls.class_id}").status_code == 404


def test_delete_class_by_non_owner_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(owner, "Physics 10A")

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(stranger), role=Role.teacher.value
    )
    assert client.delete(f"/api/classes/{cls.class_id}").status_code == 403
    # And the class survived.
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(owner), role=Role.teacher.value
    )
    assert client.get(f"/api/classes/{cls.class_id}").status_code == 200


def test_roster_by_non_owner_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(owner, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(stranger), role=Role.teacher.value
    )
    resp = client.get(f"/api/classes/{cls.class_id}/roster")
    assert resp.status_code == 403
    assert "Amelia" not in resp.text


# ---------------------------------------------------------------------------
# Malformed ids are a clean 4xx on every route, never a 500.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("patch", "/api/classes/not-a-uuid", {"name": "x"}),
        ("delete", "/api/classes/not-a-uuid", None),
        ("get", "/api/classes/not-a-uuid/roster", None),
        ("post", "/api/classes/not-a-uuid/enroll", {"studentId": str(uuid.uuid4())}),
        ("delete", f"/api/classes/not-a-uuid/students/{uuid.uuid4()}", None),
    ],
)
def test_malformed_ids_are_4xx_not_500(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.request(method.upper(), path, json=body)
    assert 400 <= resp.status_code < 500


def test_enroll_with_malformed_student_id_is_4xx(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher), role=Role.teacher.value
    )
    resp = client.post(f"/api/classes/{cls.class_id}/enroll", json={"studentId": "not-a-uuid"})
    assert 400 <= resp.status_code < 500


def test_list_classes_with_malformed_caller_id_is_422(client: TestClient) -> None:
    """A token whose ``sub`` is not a UUID must not reach the DB as a 500."""
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id="not-a-uuid", role=Role.teacher.value
    )
    assert client.get("/api/teacher/classes").status_code == 422


def test_raise_for_maps_an_unenumerated_class_error_to_409() -> None:
    """The defensive fallback in ``_raise_for``: no ``ClassError`` escapes as a 500."""
    with pytest.raises(HTTPException) as excinfo:
        _raise_for(JoinCodeError("some other class-domain failure"))
    assert excinfo.value.status_code == 409
