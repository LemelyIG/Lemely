"""HTTP surface of student paper deletion (``/api/student/attempts/...``, Task 8).

Real Postgres through the TestClient (throwaway database), no Gemini
involvement at all — deletion touches no marking. Every dependency this
router or ``/api/student/overview`` needs is overridden onto the same
throwaway ``sessionmaker``; none is left to resolve
:func:`lemely.web.deps.get_sessionmaker`'s ambient dev database.

Attempts are seeded straight through the ORM (mirroring
``tests/test_deletion_repo.py``'s helpers), not through the upload/correct
endpoints — this file's whole subject is the routes' status mapping and
non-leak proof, not the marking pipeline.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lemely.core.deletion import RETENTION_DAYS
from lemely.db.deletion_repo import PaperDeletionService
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models.attempts import Attempt, QuestionResult, Upload
from lemely.db.models.enums import (
    AttemptOrigin,
    ConfidenceBand,
    MarkerSource,
    Role,
)
from lemely.db.session import INCLUDE_DELETED
from lemely.db.student_profile_repo import StudentProfileService
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_history_store,
    get_paper_deletion_service,
    get_student_profile_service,
    get_user_mirror,
)
from tests import test_student_correct as _student_correct
from tests._integrity_leak import leaks_to_student

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

# Re-exported by attribute, not by `from ... import`: a plain import makes
# every fixture/parameter named `pg_sessionmaker` an F811 redefinition (see
# tests/test_student_self_review_web.py's module docstring, which hit the
# same thing first). Assignment binds the same fixture object and keeps the
# rule live for genuine duplicate-name mistakes elsewhere in this file.
pg_sessionmaker = _student_correct.pg_sessionmaker
_PgUserMirror = _student_correct._PgUserMirror
_seed_user = _student_correct._seed_user


# ── seeding helpers (mirroring tests/test_deletion_repo.py) ────────────────


def _seed_upload(sm: sessionmaker[Session], owner: str) -> uuid.UUID:
    upload_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Upload(
                id=upload_id,
                user_id=uuid.UUID(owner),
                storage_path=f"uploads/{upload_id}.pdf",
                idempotency_key=f"scan-{upload_id}",
            )
        )
    return upload_id


def _seed_attempt(
    sm: sessionmaker[Session],
    owner: str,
    upload_id: uuid.UUID | None,
    *,
    origin: AttemptOrigin = AttemptOrigin.past_paper,
) -> str:
    attempt_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Attempt(
                id=attempt_id,
                user_id=uuid.UUID(owner),
                upload_id=upload_id,
                subject_code="0625",
                paper_number=4,
                paper_variant=2,
                awarded_marks=30,
                maximum_marks=40,
                percentage=75.0,
                grade="B",
                recorded_at=datetime.now(UTC),
                origin=origin,
            )
        )
    return str(attempt_id)


def _seed_flagged_attempt(sm: sessionmaker[Session], owner: str) -> str:
    """A past-paper attempt with a plagiarism-flagged question: inside the D8 hold."""
    upload_id = _seed_upload(sm, owner)
    attempt_id = _seed_attempt(sm, owner, upload_id)
    with sm.begin() as session:
        session.add(
            QuestionResult(
                id=uuid.uuid4(),
                attempt_id=uuid.UUID(attempt_id),
                question_id="1",
                awarded_marks=2,
                maximum_marks=4,
                confidence_band=ConfidenceBand.low,
                confidence_score=0.4,
                marker_source=MarkerSource.ai,
                plagiarism_flagged=True,
            )
        )
    return attempt_id


# ── app / client fixtures ───────────────────────────────────────────────────


def _make_client(sm: sessionmaker[Session], user_id: str, role: str) -> TestClient:
    """A ``TestClient`` authenticated as ``user_id``/``role``, wired to ``sm``.

    Not entered as a context manager (bare ``TestClient(app)``): per
    ``lemely/web/app.py``'s ``_lifespan`` docstring, that is what keeps the
    notification sweeper from ever starting for this file.
    """
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=user_id, role=role)
    app.dependency_overrides[get_paper_deletion_service] = lambda: PaperDeletionService(sm)
    app.dependency_overrides[get_history_store] = lambda: DbHistoryStore(sm)
    app.dependency_overrides[get_user_mirror] = lambda: _PgUserMirror(sm)
    app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(sm)
    return TestClient(app)


@pytest.fixture
def owner(pg_sessionmaker: sessionmaker[Session]) -> str:
    return _seed_user(pg_sessionmaker, Role.student)


@pytest.fixture
def stranger(pg_sessionmaker: sessionmaker[Session]) -> str:
    return _seed_user(pg_sessionmaker, Role.student)


@pytest.fixture
def teacher(pg_sessionmaker: sessionmaker[Session]) -> str:
    return _seed_user(pg_sessionmaker, Role.teacher)


@pytest.fixture
def client(pg_sessionmaker: sessionmaker[Session], owner: str) -> TestClient:
    return _make_client(pg_sessionmaker, owner, "student")


@pytest.fixture
def client_as_stranger(pg_sessionmaker: sessionmaker[Session], stranger: str) -> TestClient:
    return _make_client(pg_sessionmaker, stranger, "student")


@pytest.fixture
def teacher_client(pg_sessionmaker: sessionmaker[Session], teacher: str) -> TestClient:
    return _make_client(pg_sessionmaker, teacher, "teacher")


@pytest.fixture
def attempt(pg_sessionmaker: sessionmaker[Session], owner: str) -> str:
    return _seed_attempt(pg_sessionmaker, owner, _seed_upload(pg_sessionmaker, owner))


@pytest.fixture
def flagged_attempt(pg_sessionmaker: sessionmaker[Session], owner: str) -> str:
    return _seed_flagged_attempt(pg_sessionmaker, owner)


@pytest.fixture
def quiz_attempt(pg_sessionmaker: sessionmaker[Session], owner: str) -> str:
    return _seed_attempt(pg_sessionmaker, owner, None, origin=AttemptOrigin.quiz)


# ── tests ────────────────────────────────────────────────────────────────────


def test_delete_returns_204_and_hides_the_paper(client: TestClient, attempt: str) -> None:
    assert client.get("/api/student/overview").json()["subjects"] != []
    assert client.delete(f"/api/student/attempts/{attempt}").status_code == 204
    assert client.get("/api/student/overview").json()["subjects"] == []


def test_deleting_another_students_paper_is_404_with_the_fixed_body(
    client_as_stranger: TestClient, attempt: str
) -> None:
    response = client_as_stranger.delete(f"/api/student/attempts/{attempt}")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_a_bad_id_is_the_same_fixed_404_never_a_422(client: TestClient) -> None:
    """A malformed id must not distinguish "not a UUID" from "not yours"."""
    response = client.delete("/api/student/attempts/not-a-uuid")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_the_literal_deleted_on_delete_is_the_same_fixed_404(client: TestClient) -> None:
    """``DELETE .../deleted`` is not a UUID either — the collision that made
    ``GET /deleted`` worth declaring ahead of ``/{attempt_id}`` in the first
    place, proven from the DELETE side too."""
    response = client.delete("/api/student/attempts/deleted")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_a_teacher_cannot_delete_a_students_paper(teacher_client: TestClient, attempt: str) -> None:
    assert teacher_client.delete(f"/api/student/attempts/{attempt}").status_code == 403


def test_integrity_hold_is_409_with_a_date_and_no_reason(
    client: TestClient, flagged_attempt: str
) -> None:
    response = client.delete(f"/api/student/attempts/{flagged_attempt}")
    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "This paper can't be deleted yet."
    assert body["deletableFrom"].startswith(f"{datetime.now(UTC).year}-")


def test_the_409_body_leaks_no_integrity_language(client: TestClient, flagged_attempt: str) -> None:
    """Neither an integrity word nor "review" — a hold must not out-narrate itself."""
    response = client.delete(f"/api/student/attempts/{flagged_attempt}")
    assert leaks_to_student(response.json()) is False


def test_the_leak_detector_actually_detects() -> None:
    """A leak test whose detector has never detected is a test that cannot fail."""
    assert leaks_to_student({"detail": "flagged for plagiarism (score 0.94)"}) is True
    # "review" alone, no integrity word: still a leak on a route that must
    # never even concede a review happened.
    assert leaks_to_student({"detail": "This is under review."}) is True
    assert leaks_to_student({"detail": "This paper can't be deleted yet."}) is False


def test_a_quiz_attempt_is_409_with_its_own_copy(client: TestClient, quiz_attempt: str) -> None:
    response = client.delete(f"/api/student/attempts/{quiz_attempt}")
    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Only uploaded papers can be deleted."
    assert "deletableFrom" not in body
    assert leaks_to_student(body) is False


def test_restore_returns_204_and_the_paper_comes_back(client: TestClient, attempt: str) -> None:
    client.delete(f"/api/student/attempts/{attempt}")
    assert client.post(f"/api/student/attempts/{attempt}/restore").status_code == 204
    assert client.get("/api/student/overview").json()["subjects"] != []


def test_restore_past_the_window_is_410(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], attempt: str
) -> None:
    client.delete(f"/api/student/attempts/{attempt}")
    # Force both the attempt and its upload past the retention window,
    # keeping their `deleted_at` equal (restore matches on that equality).
    expired = datetime.now(UTC) - timedelta(days=RETENTION_DAYS + 1)
    with pg_sessionmaker.begin() as session:
        att = session.scalars(
            select(Attempt)
            .where(Attempt.id == uuid.UUID(attempt))
            .execution_options(**{INCLUDE_DELETED: True})
        ).one()
        upload = session.scalars(
            select(Upload)
            .where(Upload.id == att.upload_id)
            .execution_options(**{INCLUDE_DELETED: True})
        ).one()
        att.deleted_at = expired
        upload.deleted_at = expired

    response = client.post(f"/api/student/attempts/{attempt}/restore")
    assert response.status_code == 410


def test_restoring_an_attempt_not_deleted_with_its_upload_is_410(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], owner: str, attempt: str
) -> None:
    """The defensive 410 cause: an attempt stamped at another instant than its upload."""
    earlier_id = _seed_attempt(pg_sessionmaker, owner, None)
    # Attach it to the same upload as `attempt`, then stamp it deleted at an
    # instant of its own — never the upload's, which `delete` below will set.
    with pg_sessionmaker.begin() as session:
        att = session.scalars(select(Attempt).where(Attempt.id == uuid.UUID(attempt))).one()
        earlier = session.scalars(select(Attempt).where(Attempt.id == uuid.UUID(earlier_id))).one()
        earlier.upload_id = att.upload_id
        earlier.deleted_at = datetime.now(UTC) - timedelta(days=2)

    client.delete(f"/api/student/attempts/{attempt}")

    response = client.post(f"/api/student/attempts/{earlier_id}/restore")
    assert response.status_code == 410


def test_restoring_a_never_deleted_attempt_is_404(client: TestClient, attempt: str) -> None:
    response = client.post(f"/api/student/attempts/{attempt}/restore")
    assert response.status_code == 404
    assert response.json()["detail"] == "No such paper"


def test_deleted_list_is_scoped_to_the_caller(
    client: TestClient, client_as_stranger: TestClient, attempt: str
) -> None:
    client.delete(f"/api/student/attempts/{attempt}")
    assert len(client.get("/api/student/attempts/deleted").json()["papers"]) == 1
    assert client_as_stranger.get("/api/student/attempts/deleted").json()["papers"] == []


def test_deleted_list_includes_retention_days_and_the_row_shape(
    client: TestClient, attempt: str
) -> None:
    client.delete(f"/api/student/attempts/{attempt}")
    body = client.get("/api/student/attempts/deleted").json()
    assert body["retentionDays"] == 30
    row = body["papers"][0]
    assert set(row) == {"attemptId", "paperLabel", "subjectCode", "deletedAt", "restoreDeadline"}
    assert row["attemptId"] == attempt
    assert row["subjectCode"] == "0625"


def test_deleted_is_never_captured_as_an_attempt_id(client: TestClient) -> None:
    """GET /deleted must answer the list, never a 404 that treats "deleted" as an id."""
    response = client.get("/api/student/attempts/deleted")
    assert response.status_code == 200
    assert response.json() == {"papers": [], "retentionDays": 30}


def test_the_history_row_does_not_pre_signal_deletability(
    client: TestClient, flagged_attempt: str
) -> None:
    """Design §8: no screen marks one paper as different before the student acts."""
    body = client.get("/api/student/overview").json()
    serialised = json.dumps(body)
    assert "canDelete" not in serialised
    assert "deletableFrom" not in serialised
