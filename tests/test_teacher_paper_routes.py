"""HTTP surface of teacher-console paper deletion (``/api/papers/...``, Task 17, R2).

Mirrors ``tests/test_student_deletion_routes.py``: real Postgres through the
``TestClient`` (throwaway database), papers seeded straight through the ORM
rather than through the upload/grading pipeline, since this file's whole
subject is the routes' status mapping and the console list's own honesty
about what it still shows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.deletion import RETENTION_DAYS
from lemely.db.base import Base
from lemely.db.deletion_repo import TeacherPaperDeletionService
from lemely.db.models import TeacherPaper, User
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.session import INCLUDE_DELETED
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_teacher_paper_deletion_service,
    get_teacher_paper_repo,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ── DB fixture (self-contained — mirrors test_class_unshare.py's own copy) ──


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


# ── seeding helpers ──────────────────────────────────────────────────────────


def _user(sm: sessionmaker[Session], role: Role = Role.teacher) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _paper(sm: sessionmaker[Session], owner: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid4()
    prefix = f"teacher/{owner}/{pid.hex}"
    with sm.begin() as session:
        session.add(
            TeacherPaper(
                id=pid,
                uploaded_by=owner,
                storage_path=f"{prefix}/scan.pdf",
                original_filename="scan.pdf",
                status=UploadStatus.failed,
                error="no marks yet — seeded directly for this route test",
            )
        )
    return pid


def _make_client(sm: sessionmaker[Session], user_id: uuid.UUID, role: Role) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(user_id), role=role.value
    )
    app.dependency_overrides[get_teacher_paper_deletion_service] = lambda: (
        TeacherPaperDeletionService(sm)
    )
    app.dependency_overrides[get_teacher_paper_repo] = lambda: TeacherPaperRepository(
        sm, stale_after=timedelta(minutes=10)
    )
    return TestClient(app)


@pytest.fixture
def owner(pg_sessionmaker: sessionmaker[Session]) -> uuid.UUID:
    return _user(pg_sessionmaker, Role.teacher)


@pytest.fixture
def other_teacher(pg_sessionmaker: sessionmaker[Session]) -> uuid.UUID:
    return _user(pg_sessionmaker, Role.teacher)


@pytest.fixture
def student(pg_sessionmaker: sessionmaker[Session]) -> uuid.UUID:
    return _user(pg_sessionmaker, Role.student)


@pytest.fixture
def client(pg_sessionmaker: sessionmaker[Session], owner: uuid.UUID) -> TestClient:
    return _make_client(pg_sessionmaker, owner, Role.teacher)


@pytest.fixture
def other_teacher_client(
    pg_sessionmaker: sessionmaker[Session], other_teacher: uuid.UUID
) -> TestClient:
    return _make_client(pg_sessionmaker, other_teacher, Role.teacher)


@pytest.fixture
def student_client(pg_sessionmaker: sessionmaker[Session], student: uuid.UUID) -> TestClient:
    return _make_client(pg_sessionmaker, student, Role.student)


@pytest.fixture
def paper(pg_sessionmaker: sessionmaker[Session], owner: uuid.UUID) -> uuid.UUID:
    return _paper(pg_sessionmaker, owner)


# ── /papers/{paper_id} DELETE / restore ──────────────────────────────────────


def test_delete_returns_204_and_hides_the_paper_from_the_console_list(
    client: TestClient, paper: uuid.UUID
) -> None:
    assert any(p["id"] == str(paper) for p in client.get("/api/papers").json()["papers"])
    assert client.delete(f"/api/papers/{paper}").status_code == 204
    assert not any(p["id"] == str(paper) for p in client.get("/api/papers").json()["papers"])


def test_the_console_list_hides_a_deleted_paper(client: TestClient, paper: uuid.UUID) -> None:
    """Moved from Task 16 by the review amendments: proven against ``GET /papers`` directly."""
    client.delete(f"/api/papers/{paper}")
    body = client.get("/api/papers").json()
    assert str(paper) not in {p["id"] for p in body["papers"]}


def test_deleting_another_teachers_paper_is_404_with_the_fixed_body(
    other_teacher_client: TestClient, paper: uuid.UUID
) -> None:
    response = other_teacher_client.delete(f"/api/papers/{paper}")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_a_student_cannot_delete_a_console_paper(
    student_client: TestClient, paper: uuid.UUID
) -> None:
    assert student_client.delete(f"/api/papers/{paper}").status_code == 403


def test_a_bad_id_is_the_same_fixed_404(client: TestClient) -> None:
    response = client.delete("/api/papers/not-a-uuid")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_restore_returns_204_and_the_paper_comes_back(client: TestClient, paper: uuid.UUID) -> None:
    client.delete(f"/api/papers/{paper}")
    assert client.post(f"/api/papers/{paper}/restore").status_code == 204
    assert any(p["id"] == str(paper) for p in client.get("/api/papers").json()["papers"])


def test_restoring_another_teachers_paper_is_404(
    client: TestClient, other_teacher_client: TestClient, paper: uuid.UUID
) -> None:
    client.delete(f"/api/papers/{paper}")
    response = other_teacher_client.post(f"/api/papers/{paper}/restore")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_restoring_a_never_deleted_paper_is_404(client: TestClient, paper: uuid.UUID) -> None:
    response = client.post(f"/api/papers/{paper}/restore")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_restore_past_the_window_is_410(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], paper: uuid.UUID
) -> None:
    client.delete(f"/api/papers/{paper}")
    expired = datetime.now(UTC) - timedelta(days=RETENTION_DAYS + 1)
    with pg_sessionmaker.begin() as session:
        row = session.scalars(
            select(TeacherPaper)
            .where(TeacherPaper.id == paper)
            .execution_options(**{INCLUDE_DELETED: True})
        ).one()
        row.deleted_at = expired

    response = client.post(f"/api/papers/{paper}/restore")
    assert response.status_code == 410


def test_a_student_cannot_restore_a_console_paper(
    student_client: TestClient, paper: uuid.UUID
) -> None:
    assert student_client.post(f"/api/papers/{paper}/restore").status_code == 403


# ── GET /papers/deleted ──────────────────────────────────────────────────────


def test_deleted_list_is_scoped_to_the_caller(
    client: TestClient, other_teacher_client: TestClient, paper: uuid.UUID
) -> None:
    client.delete(f"/api/papers/{paper}")
    assert len(client.get("/api/papers/deleted").json()["papers"]) == 1
    assert other_teacher_client.get("/api/papers/deleted").json()["papers"] == []


def test_deleted_list_includes_retention_days_and_the_row_shape(
    client: TestClient, paper: uuid.UUID
) -> None:
    client.delete(f"/api/papers/{paper}")
    body = client.get("/api/papers/deleted").json()
    assert body["retentionDays"] == RETENTION_DAYS
    row = body["papers"][0]
    assert set(row) == {"paperId", "label", "deletedAt", "restoreDeadline"}
    assert row["paperId"] == str(paper)


def test_deleted_is_declared_above_paper_id_and_is_never_captured_as_one(
    client: TestClient,
) -> None:
    """``GET /papers/deleted`` must answer the list, never the ``get_paper`` 404."""
    response = client.get("/api/papers/deleted")
    assert response.status_code == 200
    assert response.json() == {"papers": [], "retentionDays": RETENTION_DAYS}


def test_a_student_cannot_read_the_deleted_list(student_client: TestClient) -> None:
    assert student_client.get("/api/papers/deleted").status_code == 403


def test_the_delete_route_is_declared_above_get_paper_in_source() -> None:
    """Static proof to match the review amendment's ordering requirement.

    ``GET /papers/deleted`` (declared just above ``get_paper``) must appear
    earlier in the file than ``get_paper`` itself — a route reordering that
    silently moved ``deleted`` below ``{paper_id}`` would make it fail the
    same way ``deleted`` colliding with ``attempt_id`` did for the student
    router, without a request-level test necessarily catching every possible
    reordering.
    """
    import inspect

    from lemely.web.routers import teacher as teacher_module

    source = inspect.getsource(teacher_module)
    deleted_idx = source.index('@router.get("/papers/deleted"')
    get_paper_idx = source.index('@router.get("/papers/{paper_id}", response_model=PaperDetailDTO)')
    assert deleted_idx < get_paper_idx
