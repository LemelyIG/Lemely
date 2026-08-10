"""Route tests for ``/api/student/exam-calendar`` (P5.5 chunk C, D5.8).

Self-contained (mirrors ``tests/test_web_friends.py``) — a throwaway Postgres
DB per test, skipped cleanly when unreachable. This file tests the HTTP layer
(DTO shape, the three availability states reaching the wire intact, authz),
not :class:`~lemely.db.exam_calendar_repo.ExamCalendarService`, which has its
own suite (``tests/test_exam_calendar_repo.py``).

The state this build ships in — an onboarded student, an empty table, a
``no_timetable`` response — is pinned as a **test of intended behaviour**, not
tolerated as a gap. Nothing here may start returning a date that no official
timetable supplied.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.exam_calendar_repo import ExamCalendarService, TimetableEntry
from lemely.db.models.academic import Subject
from lemely.db.models.enums import Role, SessionMonth
from lemely.db.models.profiles import StudentEnrolmentPaper, StudentSubjectEnrolment
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_exam_calendar_service
from lemely.web.schemas_exam_calendar import (
    ExamDateDTO,
    StudentExamCalendarDTO,
    StudentExamEntryDTO,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_SOURCE = "CAIE June 2026 final timetable (Zone 3)"


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
def exam_calendar_service(pg_sessionmaker: sessionmaker[Session]) -> ExamCalendarService:
    return ExamCalendarService(pg_sessionmaker)


def _use_service(client: TestClient, service: ExamCalendarService) -> None:
    client.app.dependency_overrides[get_exam_calendar_service] = lambda: service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _declare(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    session_month: SessionMonth | None = SessionMonth.may_june,
    session_year: int | None = 2026,
) -> None:
    with sm.begin() as session:
        if session.scalar(select(Subject).where(Subject.code == "0625")) is None:
            session.add(Subject(code="0625", name="Physics"))
        enrolment = StudentSubjectEnrolment(
            user_id=student_id,
            subject_code="0625",
            session_month=session_month,
            session_year=session_year,
        )
        session.add(enrolment)
        session.flush()
        session.add(StudentEnrolmentPaper(enrolment_id=enrolment.id, paper_number=2))


# ---------------------------------------------------------------------------
# The three availability states, over HTTP.
# ---------------------------------------------------------------------------


def test_an_onboarded_student_with_an_empty_table_gets_no_timetable_and_a_200(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    exam_calendar_service: ExamCalendarService,
) -> None:
    """The state this build actually ships in, asserted as intended (D5.8).

    A 200 with a named cause, never a 404: "there is no calendar for you" is
    false — we know exactly which paper they are sitting and simply do not
    hold the official date.
    """
    _use_service(client, exam_calendar_service)
    student = _seed_user(pg_sessionmaker)
    _declare(pg_sessionmaker, student)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/exam-calendar")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["availability"] == "no_timetable"
    (entry,) = body["entries"]
    assert entry["subjectCode"] == "0625"
    assert entry["paperNumber"] == 2
    assert entry["availability"] == "no_timetable"
    assert entry["dates"] == []


def test_a_student_who_has_not_onboarded_gets_no_enrolment(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    exam_calendar_service: ExamCalendarService,
) -> None:
    _use_service(client, exam_calendar_service)
    _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

    resp = client.get("/api/student/exam-calendar")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"availability": "no_enrolment", "entries": []}


def test_a_paper_with_no_declared_session_reports_no_session(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    exam_calendar_service: ExamCalendarService,
) -> None:
    _use_service(client, exam_calendar_service)
    student = _seed_user(pg_sessionmaker)
    _declare(pg_sessionmaker, student, session_month=None, session_year=None)
    _auth_as(client, student, Role.student)

    (entry,) = client.get("/api/student/exam-calendar").json()["entries"]

    assert entry["availability"] == "no_session"
    assert entry["sessionMonth"] is None
    assert entry["sessionYear"] is None


def test_an_ingested_date_reaches_the_wire_with_its_provenance(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    exam_calendar_service: ExamCalendarService,
) -> None:
    """``source`` is on the response, not just in the database.

    Someone who believes a date is wrong can name the document rather than
    argue with the app.
    """
    _use_service(client, exam_calendar_service)
    student = _seed_user(pg_sessionmaker)
    _declare(pg_sessionmaker, student)
    exam_calendar_service.ingest(
        [
            TimetableEntry(
                subject_code="0625",
                session_month=SessionMonth.may_june,
                session_year=2026,
                paper_number=2,
                paper_variant="22",
                exam_date=date(2026, 5, 12),
                starts_at_local="09:00",
                duration_minutes=45,
            )
        ],
        source=_SOURCE,
    )
    _auth_as(client, student, Role.student)

    body = client.get("/api/student/exam-calendar").json()

    assert body["availability"] == "available"
    (entry,) = body["entries"]
    assert entry["availability"] == "dated"
    assert entry["sessionMonth"] == "may_june"
    (dated,) = entry["dates"]
    assert dated == {
        "paperVariant": "22",
        "examDate": "2026-05-12",
        "startsAtLocal": "09:00",
        "durationMinutes": 45,
        "source": _SOURCE,
    }


def test_a_timetable_with_no_stated_time_reports_null_not_midnight(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    exam_calendar_service: ExamCalendarService,
) -> None:
    _use_service(client, exam_calendar_service)
    student = _seed_user(pg_sessionmaker)
    _declare(pg_sessionmaker, student)
    exam_calendar_service.ingest(
        [
            TimetableEntry(
                subject_code="0625",
                session_month=SessionMonth.may_june,
                session_year=2026,
                paper_number=2,
                paper_variant="22",
                exam_date=date(2026, 5, 12),
            )
        ],
        source=_SOURCE,
    )
    _auth_as(client, student, Role.student)

    (dated,) = client.get("/api/student/exam-calendar").json()["entries"][0]["dates"]

    assert dated["startsAtLocal"] is None
    assert dated["durationMinutes"] is None


# ---------------------------------------------------------------------------
# There is no ingestion route, and no non-student may read.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.teacher, Role.parent, Role.school_admin])
def test_non_students_are_rejected(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    exam_calendar_service: ExamCalendarService,
    role: Role,
) -> None:
    _use_service(client, exam_calendar_service)
    _auth_as(client, _seed_user(pg_sessionmaker, role), role)

    assert client.get("/api/student/exam-calendar").status_code == 403


def test_the_router_exposes_exactly_one_read_route_and_no_write(
    client: TestClient,
) -> None:
    """Ingestion must not be reachable over HTTP (D5.8).

    Loading a timetable is an operator act against a published document. A
    route for it would put the only write path capable of publishing a wrong
    exam date behind nothing but a role check.
    """
    # Read the OpenAPI schema rather than ``app.routes``: this FastAPI version
    # wraps an included router in an opaque ``_IncludedRouter`` with no
    # ``.path``, so walking ``app.routes`` silently finds nothing and the
    # assertion would pass for the wrong reason on an empty list.
    paths = client.app.openapi()["paths"]  # type: ignore[union-attr]
    calendar_paths = {
        path: sorted(operations)
        for path, operations in paths.items()
        if path.startswith("/api/student/exam-calendar")
    }

    assert calendar_paths == {"/api/student/exam-calendar": ["get"]}


# ---------------------------------------------------------------------------
# D5.1 §0: the DTOs cannot carry a mark.
# ---------------------------------------------------------------------------


_FORBIDDEN_SUBSTRINGS = ("mark", "percent", "grade", "accuracy", "score", "confidence")


class TestNoMarkShapedFields:
    def test_field_sets_are_exactly_the_calendar_contract(self) -> None:
        assert set(StudentExamCalendarDTO.model_fields) == {"availability", "entries"}
        assert set(StudentExamEntryDTO.model_fields) == {
            "subjectCode",
            "sessionMonth",
            "sessionYear",
            "paperNumber",
            "availability",
            "dates",
        }
        assert set(ExamDateDTO.model_fields) == {
            "paperVariant",
            "examDate",
            "startsAtLocal",
            "durationMinutes",
            "source",
        }

    def test_no_dto_has_a_field_matching_a_forbidden_substring(self) -> None:
        for model in (StudentExamCalendarDTO, StudentExamEntryDTO, ExamDateDTO):
            lowered = {name.lower() for name in model.model_fields}
            for forbidden in _FORBIDDEN_SUBSTRINGS:
                matches = [name for name in lowered if forbidden in name]
                assert not matches, f"{model.__name__}: {forbidden!r} in {matches}"
