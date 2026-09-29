"""Teacher notification when a deletion withdraws their open review item (Task 9, D10).

Real Postgres through the TestClient, mirroring ``tests/test_student_deletion_routes.py``'s
seeding style: attempts and review-queue rows are written straight through the
ORM, never through the marking pipeline. Unlike that file, ``NotificationService``
here is bound to the *same* throwaway database as everything else — the Task 6
review finding this file exists to close: an unoverridden
``get_notification_service`` resolves to the ambient dev database, so a test
that only checked "the request didn't raise" could pass while writing nothing
at all. Every test here reads the row back through
:meth:`~lemely.db.notification_repo.NotificationService.list_for_user`, not
just the response status, so presence is the thing actually proven.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lemely.core.deletion import RETENTION_DAYS
from lemely.db.class_repo import ClassService
from lemely.db.deletion_repo import PaperDeletionService
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import (
    ConfidenceBand,
    MarkerSource,
    NotificationType,
    ReviewReason,
    ReviewStatus,
    Role,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.models.orgs import ClassEnrollment, SchoolClass
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.session import INCLUDE_DELETED
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_class_service,
    get_notification_service,
    get_paper_deletion_service,
    get_push_transport,
)
from lemely.web.push import RecordingPushTransport
from tests import test_student_correct as _student_correct
from tests import test_student_deletion_routes as _deletion_routes
from tests._integrity_leak import leaks_integrity

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

# Re-exported by attribute for the same F811 reason
# ``test_student_deletion_routes.py`` documents on its own re-exports.
pg_sessionmaker = _student_correct.pg_sessionmaker
_seed_user = _student_correct._seed_user
_seed_upload = _deletion_routes._seed_upload
_seed_attempt = _deletion_routes._seed_attempt

#: Comfortably outside the D8 integrity-hold window (``RETENTION_DAYS``), so a
#: seeded ``QuestionResult.plagiarism_flagged=True`` row proves the *copy*
#: never leaks the finding without also tripping the 409 hold that a
#: within-window flag would raise instead of letting the delete succeed.
_PAST_HOLD_WINDOW = timedelta(days=RETENTION_DAYS + 5)


class _BrokenNotificationService:
    """A double whose ``create`` always raises — ``notify_safely`` must swallow it."""

    def create(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("notification backend unavailable")


def _seed_review_item(
    sm: sessionmaker[Session],
    attempt_id: str,
    *,
    reason: ReviewReason = ReviewReason.low_confidence,
    assigned_teacher_id: str | None = None,
    status: ReviewStatus = ReviewStatus.open,
) -> uuid.UUID:
    item_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            ReviewQueueItem(
                id=item_id,
                attempt_id=uuid.UUID(attempt_id),
                reason=reason,
                status=status,
                assigned_teacher_id=(
                    uuid.UUID(assigned_teacher_id) if assigned_teacher_id is not None else None
                ),
            )
        )
    return item_id


def _seed_flagged_review_item(
    sm: sessionmaker[Session],
    owner: str,
    *,
    assigned_teacher_id: str,
) -> str:
    """A past-paper attempt with a plagiarism-flagged question, outside the D8 window.

    Deletable (the hold has lapsed), so this exercises the notification copy
    against a real integrity finding without the 409 that a fresh one raises.
    """
    upload_id = _seed_upload(sm, owner)
    attempt_id = uuid.uuid4()
    recorded_at = datetime.now(UTC) - _PAST_HOLD_WINDOW
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
                recorded_at=recorded_at,
            )
        )
        qr_id = uuid.uuid4()
        session.add(
            QuestionResult(
                id=qr_id,
                attempt_id=attempt_id,
                question_id="1",
                awarded_marks=2,
                maximum_marks=4,
                confidence_band=ConfidenceBand.low,
                confidence_score=0.4,
                marker_source=MarkerSource.ai,
                plagiarism_flagged=True,
            )
        )
        session.add(
            ReviewQueueItem(
                id=uuid.uuid4(),
                attempt_id=attempt_id,
                question_result_id=qr_id,
                reason=ReviewReason.plagiarism_flag,
                status=ReviewStatus.open,
                assigned_teacher_id=uuid.UUID(assigned_teacher_id),
            )
        )
    return str(attempt_id)


def _seed_class(sm: sessionmaker[Session], teacher_id: str, student_id: str) -> None:
    class_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            SchoolClass(id=class_id, teacher_id=uuid.UUID(teacher_id), name="9A", join_code=None)
        )
        session.add(
            ClassEnrollment(id=uuid.uuid4(), class_id=class_id, student_id=uuid.UUID(student_id))
        )


def _make_client(
    sm: sessionmaker[Session], user_id: str, role: str, *, notifications: NotificationService
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=user_id, role=role)
    app.dependency_overrides[get_paper_deletion_service] = lambda: PaperDeletionService(sm)
    app.dependency_overrides[get_notification_service] = lambda: notifications
    app.dependency_overrides[get_push_transport] = RecordingPushTransport
    app.dependency_overrides[get_class_service] = lambda: ClassService(sm)
    return TestClient(app)


@pytest.fixture
def owner(pg_sessionmaker: sessionmaker[Session]) -> str:
    return _seed_user(pg_sessionmaker, Role.student)


@pytest.fixture
def teacher(pg_sessionmaker: sessionmaker[Session]) -> str:
    return _seed_user(pg_sessionmaker, Role.teacher)


@pytest.fixture
def notifications(pg_sessionmaker: sessionmaker[Session]) -> NotificationService:
    """The real service, bound to *this test's* database — never the ambient one."""
    return NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))


@pytest.fixture
def broken_notifications() -> _BrokenNotificationService:
    return _BrokenNotificationService()


@pytest.fixture
def client(
    pg_sessionmaker: sessionmaker[Session], owner: str, notifications: NotificationService
) -> TestClient:
    return _make_client(pg_sessionmaker, owner, "student", notifications=notifications)


@pytest.fixture
def broken_client(
    pg_sessionmaker: sessionmaker[Session],
    owner: str,
    broken_notifications: _BrokenNotificationService,
) -> TestClient:
    # `_BrokenNotificationService` is intentionally not a `NotificationService`
    # subclass — just enough of its shape for `notify_safely` to call, per
    # `tests/test_web_notify.py`'s `FakeNotificationService` convention.
    return _make_client(
        pg_sessionmaker,
        owner,
        "student",
        notifications=broken_notifications,  # type: ignore[arg-type]
    )


@pytest.fixture
def attempt(pg_sessionmaker: sessionmaker[Session], owner: str) -> str:
    return _seed_attempt(pg_sessionmaker, owner, _seed_upload(pg_sessionmaker, owner))


@pytest.fixture
def item_assigned_to_teacher(
    pg_sessionmaker: sessionmaker[Session], attempt: str, teacher: str
) -> uuid.UUID:
    return _seed_review_item(pg_sessionmaker, attempt, assigned_teacher_id=teacher)


# Alias matching the brief's illustrative parameter name.
@pytest.fixture
def open_item(pg_sessionmaker: sessionmaker[Session], attempt: str, teacher: str) -> uuid.UUID:
    return _seed_review_item(pg_sessionmaker, attempt, assigned_teacher_id=teacher)


# ── tests ────────────────────────────────────────────────────────────────────


def test_the_assigned_teacher_is_told_when_their_item_is_withdrawn(
    client: TestClient,
    notifications: NotificationService,
    attempt: str,
    item_assigned_to_teacher: uuid.UUID,
    teacher: str,
) -> None:
    assert client.delete(f"/api/student/attempts/{attempt}").status_code == 204
    rows = notifications.list_for_user(teacher)
    assert [r.type for r in rows] == [NotificationType.review_withdrawn]
    assert rows[0].payload["reviewItemId"] == str(item_assigned_to_teacher)


def test_the_notification_never_says_why(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    owner: str,
    teacher: str,
) -> None:
    """Neither an integrity word nor a "flagged for plagiarism" hint reaches the copy."""
    attempt_id = _seed_flagged_review_item(pg_sessionmaker, owner, assigned_teacher_id=teacher)
    assert client.delete(f"/api/student/attempts/{attempt_id}").status_code == 204
    row = notifications.list_for_user(teacher)[0]
    assert leaks_integrity({"title": row.title, "body": row.body}) is False


def test_the_leak_detector_actually_detects() -> None:
    """A leak test whose detector has never detected is a test that cannot fail."""
    assert leaks_integrity({"body": "flagged for plagiarism (score 0.94)"}) is True
    assert leaks_integrity({"body": "so the question you had to review is gone"}) is False


def test_delete_restore_delete_notifies_twice(
    client: TestClient,
    notifications: NotificationService,
    attempt: str,
    open_item: uuid.UUID,
    teacher: str,
) -> None:
    """The dedupe key carries ``deleted_at``, so a second real deletion is a second notice."""
    client.delete(f"/api/student/attempts/{attempt}")
    client.post(f"/api/student/attempts/{attempt}/restore")
    client.delete(f"/api/student/attempts/{attempt}")
    assert len(notifications.list_for_user(teacher)) == 2


def test_a_paper_with_no_open_item_notifies_nobody(
    client: TestClient, notifications: NotificationService, attempt: str, teacher: str
) -> None:
    client.delete(f"/api/student/attempts/{attempt}")
    assert notifications.list_for_user(teacher) == []


def test_an_unassigned_item_notifies_every_teacher_of_the_student(
    pg_sessionmaker: sessionmaker[Session],
    client: TestClient,
    notifications: NotificationService,
    owner: str,
    attempt: str,
) -> None:
    """No ``assigned_teacher_id`` falls back to every teacher the student has (R7-R10)."""
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_class(pg_sessionmaker, teacher_a, owner)
    _seed_class(pg_sessionmaker, teacher_b, owner)
    _seed_review_item(pg_sessionmaker, attempt, assigned_teacher_id=None)

    assert client.delete(f"/api/student/attempts/{attempt}").status_code == 204

    assert [r.type for r in notifications.list_for_user(teacher_a)] == [
        NotificationType.review_withdrawn
    ]
    assert [r.type for r in notifications.list_for_user(teacher_b)] == [
        NotificationType.review_withdrawn
    ]


def test_a_notification_failure_does_not_undo_the_deletion(
    broken_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    attempt: str,
    open_item: uuid.UUID,
) -> None:
    assert broken_client.delete(f"/api/student/attempts/{attempt}").status_code == 204
    with pg_sessionmaker() as session:
        row = session.scalars(
            select(Attempt)
            .where(Attempt.id == uuid.UUID(attempt))
            .execution_options(**{INCLUDE_DELETED: True})
        ).one()
    assert row.deleted_at is not None
