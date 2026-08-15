"""School-admin console (UI spec K-01/K-03) — service + HTTP, against Postgres.

``tests/test_seat_repo.py`` already proves the seat half (quota, ownership,
revocation). This file covers what P4.7 added: the K-01 counts, the enriched seat
row K-02 renders, the K-03 staff roster, and the two staffing mutations.

Four properties get most of the attention here, because each is a place where a
plausible implementation would be quietly wrong:

* **The school average is the class average's rule, not a second one.** A quiz
  attempt must not move it (``docs/quiz-model.md`` §5), and the denominator the
  screen shows must be the students the mean was actually taken over.
* **A seat row's classes are scoped to this school.** A seated student may also
  sit in an independent teacher's class, which is none of this admin's business.
* **Removing a teacher never orphans a class.** No target and owned classes is a
  refusal, not a cascade, and the teacher's *account* outlives their membership.
* **Distinct, not summed.** A student in two of a teacher's classes is one
  student that teacher is responsible for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata
from lemely.db.base import Base
from lemely.db.models import (
    Attempt,
    ClassEnrollment,
    School,
    SchoolClass,
    SchoolMembership,
    User,
)
from lemely.db.models.enums import AttemptOrigin, MembershipRole, Role, SessionMonth
from lemely.db.school_admin_repo import (
    ClassesWouldBeOrphanedError,
    InvalidReassignmentError,
    SchoolAdminService,
    SchoolOwnershipError,
    TeacherNotFoundError,
)
from lemely.db.seat_repo import SeatService
from lemely.runtime.config import DatabaseSettings
from lemely.web.app import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_history_store,
    get_school_admin_service,
    get_seat_service,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ── Fakes and fixtures ────────────────────────────────────────────────────────


class _FakeStudentCreator:
    """Inserts a ``student`` ``User`` row directly, standing in for GoTrue."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm
        self.created: list[tuple[str, str]] = []

    def create_student(
        self, email: str, password: str, display_name: str | None = None
    ) -> uuid.UUID:
        self.created.append((email, password))
        uid = uuid.uuid4()
        with self._sm.begin() as session:
            session.add(User(id=uid, email=email, role=Role.student, display_name=display_name))
        return uid


class _FakeTeacherCreator:
    """Inserts a ``teacher`` ``User`` row directly, standing in for GoTrue.

    Deliberately pinned to :attr:`Role.teacher` with no role parameter, mirroring
    :class:`~lemely.web.deps.AuthServiceTeacherCreator`: the role a provisioning
    path may mint is the security property, so the fake must not be able to mint
    anything else either.
    """

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm
        self.created: list[tuple[str, str]] = []

    def create_teacher(
        self, email: str, password: str, display_name: str | None = None
    ) -> uuid.UUID:
        self.created.append((email, password))
        uid = uuid.uuid4()
        with self._sm.begin() as session:
            session.add(User(id=uid, email=email, role=Role.teacher, display_name=display_name))
        return uid


class _StubHistoryStore:
    """Returns a canned :class:`StudentHistory` per student id."""

    def __init__(self, histories: dict[str, list[PaperRecord]]) -> None:
        self._histories = histories

    def load(self, student_id: str) -> StudentHistory:
        return StudentHistory(
            student_id=student_id, records=list(self._histories.get(student_id, []))
        )


def _record(*, student_id: str, percentage: float, origin: str, recorded_at: str) -> PaperRecord:
    """Build the smallest :class:`PaperRecord` the average path actually reads.

    ``session_month`` follows ``test_web_quiz_origin_filtering.py``'s convention:
    a quiz carries "Specimen" and no year, because it is not sat in a session.
    """
    return PaperRecord(
        student_id=student_id,
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=4,
            paper_variant=1,
            session_month="May/June" if origin == "past_paper" else "Specimen",
            session_year=2024 if origin == "past_paper" else None,
        ),
        awarded_marks=int(percentage),
        maximum_marks=100,
        percentage=percentage,
        grade="B",
        recorded_at=recorded_at,
        weak_areas=[],
        origin=origin,
    )


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
    """A throwaway database, dropped afterwards (mirrors ``test_seat_repo.py``)."""
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


# ── Seeding helpers ───────────────────────────────────────────────────────────


def _user(sm: sessionmaker[Session], role: Role, name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=name))
    return uid


def _school(
    sm: sessionmaker[Session], *, quota: int, admin_id: uuid.UUID, name: str = "Test School"
) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name=name, seat_quota=quota))
        session.add(
            SchoolMembership(
                school_id=school_id,
                user_id=admin_id,
                membership_role=MembershipRole.school_admin,
            )
        )
    return school_id


def _staff(sm: sessionmaker[Session], school_id: uuid.UUID, teacher_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(
            SchoolMembership(
                school_id=school_id,
                user_id=teacher_id,
                membership_role=MembershipRole.teacher,
            )
        )


def _class(
    sm: sessionmaker[Session],
    *,
    school_id: uuid.UUID | None,
    teacher_id: uuid.UUID,
    name: str,
    students: list[uuid.UUID] | None = None,
) -> uuid.UUID:
    class_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            SchoolClass(
                id=class_id,
                school_id=school_id,
                teacher_id=teacher_id,
                name=name,
                join_code=uuid.uuid4().hex[:8],
            )
        )
        for student_id in students or []:
            session.add(ClassEnrollment(class_id=class_id, student_id=student_id))
    return class_id


def _attempt(
    sm: sessionmaker[Session], student_id: uuid.UUID, *, when: datetime, origin: AttemptOrigin
) -> None:
    with sm.begin() as session:
        session.add(
            Attempt(
                user_id=student_id,
                subject_code=None,
                session_month=SessionMonth.may_june if origin is AttemptOrigin.past_paper else None,
                awarded_marks=40,
                maximum_marks=50,
                percentage=80.0,
                recorded_at=when,
                origin=origin,
            )
        )


def _services(
    sm: sessionmaker[Session],
) -> tuple[SeatService, SchoolAdminService, _FakeTeacherCreator]:
    teacher_creator = _FakeTeacherCreator(sm)
    return (
        SeatService(sm, _FakeStudentCreator(sm)),
        SchoolAdminService(sm, teacher_creator),
        teacher_creator,
    )


def _client(
    sm: sessionmaker[Session],
    admin_id: uuid.UUID,
    *,
    histories: dict[str, list[PaperRecord]] | None = None,
) -> Iterator[TestClient]:
    seats, admin_service, _ = _services(sm)
    app = create_app()
    app.dependency_overrides[get_seat_service] = lambda: seats
    app.dependency_overrides[get_school_admin_service] = lambda: admin_service
    app.dependency_overrides[get_history_store] = lambda: _StubHistoryStore(histories or {})
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin_id), role=Role.school_admin.value
    )
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


# ── K-01: the overview ────────────────────────────────────────────────────────


def test_overview_counts_staff_classes_and_the_distinct_roll(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    teacher_a = _user(pg_sessionmaker, Role.teacher, "Ms A")
    teacher_b = _user(pg_sessionmaker, Role.teacher, "Mr B")
    _staff(pg_sessionmaker, school, teacher_a)
    _staff(pg_sessionmaker, school, teacher_b)
    student = _user(pg_sessionmaker, Role.student, "Sam")
    other = _user(pg_sessionmaker, Role.student, "Rae")
    # `student` sits in both classes: one student on the roll, not two.
    _class(pg_sessionmaker, school_id=school, teacher_id=teacher_a, name="10A", students=[student])
    _class(
        pg_sessionmaker,
        school_id=school,
        teacher_id=teacher_b,
        name="10B",
        students=[student, other],
    )

    _, service, _ = _services(pg_sessionmaker)
    counts = service.overview(admin)

    assert len(counts) == 1
    assert counts[0].teacher_count == 2
    assert counts[0].class_count == 2
    assert counts[0].enrolled_student_count == 2


def test_overview_average_ignores_quiz_attempts_and_reports_its_denominator(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The K-01 mean is the class mean's rule, and says how many it covered.

    Three students on the roll: one with a paper, one with only a quiz, one with
    nothing. The mean must be the single paper's percentage — not an average of
    two numbers that mean different things — and ``studentsWithAPaper`` must say
    **1**, because "80% across the school" reads very differently when it is one
    student out of three.
    """
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    teacher = _user(pg_sessionmaker, Role.teacher, "Ms A")
    _staff(pg_sessionmaker, school, teacher)
    paper_student = _user(pg_sessionmaker, Role.student, "Paper")
    quiz_student = _user(pg_sessionmaker, Role.student, "Quiz")
    idle_student = _user(pg_sessionmaker, Role.student, "Idle")
    _class(
        pg_sessionmaker,
        school_id=school,
        teacher_id=teacher,
        name="10A",
        students=[paper_student, quiz_student, idle_student],
    )

    histories = {
        str(paper_student): [
            _record(
                student_id=str(paper_student),
                percentage=80.0,
                origin="past_paper",
                recorded_at="2026-08-01T00:00:00+00:00",
            )
        ],
        # A 20% quiz. If it leaked into the mean the answer would be 50.0.
        str(quiz_student): [
            _record(
                student_id=str(quiz_student),
                percentage=20.0,
                origin="quiz",
                recorded_at="2026-08-02T00:00:00+00:00",
            )
        ],
    }
    for client in _client(pg_sessionmaker, admin, histories=histories):
        body = client.get("/api/school/overview").json()

    school_row = body["schools"][0]
    assert school_row["averageLatestPercentage"] == pytest.approx(80.0)
    assert school_row["studentsWithAPaper"] == 1
    assert school_row["enrolledStudentCount"] == 3


def test_overview_average_is_none_rather_than_zero_when_nobody_has_a_paper(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """An unknown average is ``None``. ``0.0`` would read as "everyone failed"."""
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    teacher = _user(pg_sessionmaker, Role.teacher)
    _staff(pg_sessionmaker, school, teacher)
    student = _user(pg_sessionmaker, Role.student)
    _class(pg_sessionmaker, school_id=school, teacher_id=teacher, name="10A", students=[student])

    for client in _client(pg_sessionmaker, admin):
        body = client.get("/api/school/overview").json()

    assert body["schools"][0]["averageLatestPercentage"] is None
    assert body["schools"][0]["studentsWithAPaper"] == 0


def test_overview_is_empty_for_an_admin_who_administers_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    stranger = _user(pg_sessionmaker, Role.school_admin)
    for client in _client(pg_sessionmaker, stranger):
        response = client.get("/api/school/overview")

    assert response.status_code == 200
    assert response.json() == {"schools": []}


# ── K-02: the enriched seat row ───────────────────────────────────────────────


def test_seat_row_carries_the_student_name_school_classes_and_last_attempt(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """And the class list is scoped to this school.

    The independent class below (``school_id=None``, D3.1) belongs to a teacher
    running a class outside any school. It must not appear on a school admin's
    seat row: they administer a school, not a student.
    """
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=5, admin_id=admin)
    teacher = _user(pg_sessionmaker, Role.teacher, "Ms Adeyemi")
    independent = _user(pg_sessionmaker, Role.teacher, "Tutor")
    _staff(pg_sessionmaker, school, teacher)

    seats, _, _ = _services(pg_sessionmaker)
    invited = seats.invite_student(admin, school, "sam@student.local", "pw", display_name="Sam")
    _class(
        pg_sessionmaker,
        school_id=school,
        teacher_id=teacher,
        name="10A",
        students=[invited.user_id],
    )
    _class(
        pg_sessionmaker,
        school_id=None,
        teacher_id=independent,
        name="Private tuition",
        students=[invited.user_id],
    )
    marked_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    _attempt(pg_sessionmaker, invited.user_id, when=marked_at, origin=AttemptOrigin.past_paper)

    usage = seats.seat_usage(admin, school)
    row = usage.seats[0]

    assert row.assigned_display_name == "Sam"
    assert [(c.name, c.teacher_name) for c in row.classes] == [("10A", "Ms Adeyemi")]
    assert row.last_attempt_at == marked_at


def test_seat_row_last_attempt_is_none_for_a_student_who_has_marked_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=5, admin_id=admin)
    seats, _, _ = _services(pg_sessionmaker)
    seats.invite_student(admin, school, "new@student.local", "pw", display_name="New")

    row = seats.seat_usage(admin, school).seats[0]

    assert row.last_attempt_at is None
    assert row.classes == []


# ── K-03: the staff roster ────────────────────────────────────────────────────


def test_teacher_roster_counts_distinct_students_not_summed_rosters(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    teacher = _user(pg_sessionmaker, Role.teacher, "Ms A")
    _staff(pg_sessionmaker, school, teacher)
    shared = _user(pg_sessionmaker, Role.student)
    only_in_b = _user(pg_sessionmaker, Role.student)
    _class(pg_sessionmaker, school_id=school, teacher_id=teacher, name="10A", students=[shared])
    _class(
        pg_sessionmaker,
        school_id=school,
        teacher_id=teacher,
        name="10B",
        students=[shared, only_in_b],
    )

    _, service, _ = _services(pg_sessionmaker)
    roster = service.list_teachers(admin)[0]

    assert roster.teachers[0].class_count == 2
    # Summing the two rosters would say 3. `shared` is one student this teacher
    # is responsible for, not two.
    assert roster.teachers[0].student_count == 2


def test_inviting_a_teacher_consumes_no_seat(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Seats are a student allocation; staff are not billed against the quota."""
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=2, admin_id=admin)
    seats, service, creator = _services(pg_sessionmaker)

    service.invite_teacher(admin, school, "new@teacher.local", "pw", display_name="New Teacher")

    usage = seats.seat_usage(admin, school)
    assert usage.used == 0
    assert usage.available == 2
    assert creator.created == [("new@teacher.local", "pw")]
    assert service.list_teachers(admin)[0].teachers[0].display_name == "New Teacher"


def test_inviting_a_teacher_into_a_school_you_do_not_administer_creates_no_account(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _user(pg_sessionmaker, Role.school_admin)
    stranger = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=5, admin_id=owner)
    _, service, creator = _services(pg_sessionmaker)

    with pytest.raises(SchoolOwnershipError):
        service.invite_teacher(stranger, school, "sneak@teacher.local", "pw")

    assert creator.created == []


def test_removing_a_teacher_who_owns_classes_refuses_without_a_target(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """K-03: reassignment is explicit. The refusal names the count."""
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    leaving = _user(pg_sessionmaker, Role.teacher, "Leaving")
    _staff(pg_sessionmaker, school, leaving)
    _class(pg_sessionmaker, school_id=school, teacher_id=leaving, name="10A")
    _class(pg_sessionmaker, school_id=school, teacher_id=leaving, name="10B")
    _, service, _ = _services(pg_sessionmaker)

    with pytest.raises(ClassesWouldBeOrphanedError) as excinfo:
        service.remove_teacher(admin, school, leaving)

    assert excinfo.value.class_count == 2
    # The refusal wrote nothing: they are still staff, still owning both.
    assert service.list_teachers(admin)[0].teachers[0].class_count == 2


def test_removing_a_teacher_reassigns_their_classes_and_keeps_their_account(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    leaving = _user(pg_sessionmaker, Role.teacher, "Leaving")
    staying = _user(pg_sessionmaker, Role.teacher, "Staying")
    _staff(pg_sessionmaker, school, leaving)
    _staff(pg_sessionmaker, school, staying)
    class_id = _class(pg_sessionmaker, school_id=school, teacher_id=leaving, name="10A")
    _, service, _ = _services(pg_sessionmaker)

    moved = service.remove_teacher(admin, school, leaving, reassign_to=staying)

    assert moved == 1
    roster = service.list_teachers(admin)[0].teachers
    assert [t.display_name for t in roster] == ["Staying"]
    assert roster[0].class_count == 1
    with pg_sessionmaker() as session:
        # The class moved rather than being deleted, and the account survives a
        # staffing change — removing someone from a school is not deleting them.
        assert session.get(SchoolClass, class_id).teacher_id == staying
        assert session.get(User, leaving) is not None


def test_reassigning_to_someone_who_is_not_a_teacher_here_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    other_school = _school(pg_sessionmaker, quota=10, admin_id=admin, name="Elsewhere")
    leaving = _user(pg_sessionmaker, Role.teacher)
    outsider = _user(pg_sessionmaker, Role.teacher)
    _staff(pg_sessionmaker, school, leaving)
    _staff(pg_sessionmaker, other_school, outsider)
    _class(pg_sessionmaker, school_id=school, teacher_id=leaving, name="10A")
    _, service, _ = _services(pg_sessionmaker)

    with pytest.raises(InvalidReassignmentError):
        service.remove_teacher(admin, school, leaving, reassign_to=outsider)


def test_removing_a_teacher_who_is_not_in_this_school_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    unrelated = _user(pg_sessionmaker, Role.teacher)
    _, service, _ = _services(pg_sessionmaker)

    with pytest.raises(TeacherNotFoundError):
        service.remove_teacher(admin, school, unrelated)


# ── HTTP error mapping ────────────────────────────────────────────────────────


def test_remove_teacher_maps_the_orphan_refusal_to_409(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    leaving = _user(pg_sessionmaker, Role.teacher)
    _staff(pg_sessionmaker, school, leaving)
    _class(pg_sessionmaker, school_id=school, teacher_id=leaving, name="10A")

    for client in _client(pg_sessionmaker, admin):
        response = client.post(
            f"/api/school/teachers/{leaving}/remove", json={"schoolId": str(school)}
        )

    assert response.status_code == 409


def test_remove_teacher_maps_a_foreign_school_to_403(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _user(pg_sessionmaker, Role.school_admin)
    stranger = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=owner)
    teacher = _user(pg_sessionmaker, Role.teacher)
    _staff(pg_sessionmaker, school, teacher)

    for client in _client(pg_sessionmaker, stranger):
        response = client.post(
            f"/api/school/teachers/{teacher}/remove", json={"schoolId": str(school)}
        )

    assert response.status_code == 403


def test_remove_teacher_reports_how_many_classes_moved(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=10, admin_id=admin)
    leaving = _user(pg_sessionmaker, Role.teacher)
    staying = _user(pg_sessionmaker, Role.teacher)
    _staff(pg_sessionmaker, school, leaving)
    _staff(pg_sessionmaker, school, staying)
    _class(pg_sessionmaker, school_id=school, teacher_id=leaving, name="10A")

    for client in _client(pg_sessionmaker, admin):
        response = client.post(
            f"/api/school/teachers/{leaving}/remove",
            json={"schoolId": str(school), "reassignToTeacherId": str(staying)},
        )

    assert response.status_code == 200
    assert response.json() == {"classesReassigned": 1}


def test_seat_listing_over_http_carries_the_new_fields(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The wire contract K-02 renders, asserted end to end rather than in Python."""
    admin = _user(pg_sessionmaker, Role.school_admin)
    school = _school(pg_sessionmaker, quota=5, admin_id=admin)
    teacher = _user(pg_sessionmaker, Role.teacher, "Ms Adeyemi")
    _staff(pg_sessionmaker, school, teacher)
    seats, _, _ = _services(pg_sessionmaker)
    invited = seats.invite_student(admin, school, "sam@student.local", "pw", display_name="Sam")
    _class(
        pg_sessionmaker,
        school_id=school,
        teacher_id=teacher,
        name="10A",
        students=[invited.user_id],
    )
    _attempt(
        pg_sessionmaker,
        invited.user_id,
        when=datetime.now(UTC) - timedelta(days=1),
        origin=AttemptOrigin.past_paper,
    )

    for client in _client(pg_sessionmaker, admin):
        row = client.get("/api/school/seats").json()["schools"][0]["seats"][0]

    assert row["assignedDisplayName"] == "Sam"
    assert row["classes"] == [
        {"classId": row["classes"][0]["classId"], "name": "10A", "teacherName": "Ms Adeyemi"}
    ]
    assert row["lastAttemptAt"] is not None
