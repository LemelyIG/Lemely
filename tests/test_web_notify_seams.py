"""Route tests for the notification seams (P5.6 chunk C2, D5.9).

Chunk C1 built the inbox routes and :func:`~lemely.web.notify.notify_safely`;
this file covers the *seams* — the places in the product where something
actually happens and a notification is produced. Each seam is tested through
the real HTTP surface with a real ``NotificationService`` on a throwaway
Postgres database and a :class:`~lemely.web.push.RecordingPushTransport` (the
headless push mock MISSION §4's Phase-5 acceptance names), because the
properties worth proving are exactly the ones a unit test of the helper cannot
see: which recipient the router derived, which key it deduped on, and whether
the action survives the notification failing.

Seam 1 — ``grade_ready`` at ``POST /api/student/correct``. What it pins:

* The happy path: one row, addressed to the student, pushed to their device.
* **The dedupe key is the upload, never the attempt** (D5.9 §6 / D5.3).
  ``persist_correction`` mints a fresh ``Attempt`` on every run, so an
  attempt-keyed notification re-fires on every re-correction of one PDF. The
  re-correction test asserts two attempts exist, so it cannot pass by the
  pipeline having declined to run.
* **The row carries no mark and no grade** (D5.9 §2, UI spec §1.4). A pointer
  is what makes the preference gate lossless and what keeps a grade off a
  push service.
* The learning wins (D5.9 §1): a *failing* notification service still leaves
  the correction a normal, successful SSE stream.
* The preference gate is live at the seam, not merely inside the service: a
  student who turned ``grade_ready`` off gets no row at all.

Seam 2 — ``announcement`` at ``POST /api/teacher/announcements``. Here the
composer and the recipients are *different people*, which is what the seam has
to get right. What it pins:

* Every enrolled student is notified, not just the first — the dedupe key
  carries the recipient as well as the announcement (D5.9 §6).
* A school-wide post reaches students through ``Seat``, never
  ``SchoolMembership`` (D5.4), and a revoked seat is not in the audience: a
  notification pointing at a row the reader cannot open is worse than none.
* A scheduled (future ``publishAt``) post notifies nobody yet, because
  ``list_for_student`` still hides it.
* The composer survives a failing inbox, and one student's opt-out does not
  silence their classmates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord, StudentHistory
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExamMetadata, ExtractedAnswer, ExtractedAnswers
from lemely.db.announcement_repo import AnnouncementService
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import School, SchoolMembership, User
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import MembershipRole, NotificationType, Role, SeatStatus
from lemely.db.models.orgs import ClassEnrollment, Seat
from lemely.db.models.users import ParentChildLink
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.upload_repo import StudentUploadRepository
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_announcement_service,
    get_attempt_repo,
    get_auth_context,
    get_class_service,
    get_gemini_client,
    get_history_store,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
    get_settings,
    get_storage_backend,
    get_student_profile_service,
    get_student_upload_repo,
    get_user_mirror,
    get_xp_service,
)
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import student as student_router_module
from tests.storage_fakes import FakeStorageBackend

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from lemely.db.notification_repo import CreateResult, NotificationRow


# ---------------------------------------------------------------------------
# Shared fixtures (the throwaway-Postgres shape used by every P5 route test).
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
def prefs(pg_sessionmaker: sessionmaker[Session]) -> NotificationPreferencesService:
    return NotificationPreferencesService(pg_sessionmaker)


@pytest.fixture
def notifications(
    pg_sessionmaker: sessionmaker[Session],
    prefs: NotificationPreferencesService,
) -> NotificationService:
    return NotificationService(pg_sessionmaker, prefs)


@pytest.fixture
def transport() -> RecordingPushTransport:
    return RecordingPushTransport()


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        # Issue #10 / D7.5: `POST /student/correct` (Seam 1's own `grade_ready`
        # trigger) now soft-gates on a verified email. Every seeded user is
        # pre-verified so this file keeps testing notification seams, not
        # verification.
        session.add(
            User(id=uid, email=f"{uid}@example.com", role=role, email_verified_at=datetime.now(UTC))
        )
    return uid


class _PgUserMirror:
    """Minimal ``UserMirror`` bound to this file's throwaway sessionmaker.

    ``require_verified_email`` (issue #10) reads the mirror directly; without
    this override the ``/correct`` seam would fall back to the real,
    unoverridden ``DbUserMirror`` against the default configured database —
    not the throwaway one every seeded user here actually lives in — and see
    nothing, gating every request in this file at 403. Only ``get_by_id`` is
    exercised by that dependency; the rest raise so an unexpected call
    surfaces immediately.
    """

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        with self._sm() as session:
            user = session.get(User, user_id)
            if user is not None:
                session.expunge(user)
            return user

    def get_by_phone(self, phone: str) -> User | None:  # pragma: no cover - unused here
        raise NotImplementedError

    def get_by_email(self, email: str) -> User | None:  # pragma: no cover - unused here
        raise NotImplementedError

    def upsert(self, *args: object, **kwargs: object) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    def mark_email_verified(
        self, user_id: uuid.UUID, *, verified_at: datetime
    ) -> None:  # pragma: no cover - unused here
        raise NotImplementedError


def _inbox(
    service: NotificationService,
    user_id: uuid.UUID,
    type: NotificationType,
) -> list[NotificationRow]:
    return [row for row in service.list_for_user(user_id) if row.type is type]


class _FailingNotificationService:
    """A double whose ``create`` always raises — proves D5.9 §1's fail-open rule.

    Duck-typed rather than a subclass, mirroring ``_FailingXpService`` in
    ``tests/test_web_xp_awards.py``: the only contract ``notify_safely``
    relies on is a callable ``create``, and a raising stand-in is the simplest
    way to prove the *caller* survives it.
    """

    def create(self, *args: object, **kwargs: object) -> CreateResult:
        raise RuntimeError("simulated notification infrastructure failure")


class _NoopXpService:
    """Stands in for ``XpService`` at the seams this file exercises.

    ``/student/correct`` awards XP as well as notifying, and the default
    dependency points at the *real* configured database, where these tests'
    throwaway-DB student does not exist. ``award_xp_safely`` swallows the
    resulting error correctly — but it logs a full traceback into every run
    here, which reads like a failure in a file about something else. XP at
    this seam is ``tests/test_web_xp_awards.py``'s subject, not this file's.
    """

    def award(self, *args: object, **kwargs: object) -> None:
        return None


# ---------------------------------------------------------------------------
# Seam 1 — grade_ready (POST /api/student/correct).
# ---------------------------------------------------------------------------


def _mcq_scheme() -> MarkScheme:
    """A 3-mark Paper 4 Variant 1 — every small integer in it is distinct.

    Deliberately *not* the 2-mark Paper 1 Variant 2 of
    ``tests/test_web_xp_awards.py``: the no-mark-on-the-wire assertion below
    is only meaningful if the awarded mark and the maximum are numbers that do
    not also appear as the paper number or the variant.
    """
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 4,
                "paper_variant": 1,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 3,
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
                {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "B"},
                {"id": "3", "marks": 1, "type": "mcq", "mcq_answer": "C"},
            ],
        }
    )


def _extracted() -> ExtractedAnswers:
    """Two right, one blank — an awarded total of 2 out of 3."""
    return ExtractedAnswers(
        paper_id="paper",
        source_scan="scan.pdf",
        answers=[
            ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
            ExtractedAnswer(question_id="2", answer="B", confidence=0.99),
            ExtractedAnswer(question_id="3", answer="", confidence=0.0),
        ],
    )


@pytest.fixture
def correct_settings(tmp_path: Path) -> Settings:
    base = load_settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    data["gemini_api_key"] = None
    return Settings.model_validate(data)


@pytest.fixture
def correct_client(
    correct_settings: Settings,
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, uuid.UUID]]:
    """An authenticated student with one uploadable paper and a live inbox."""
    student_id = _seed_user(pg_sessionmaker, Role.student)
    upload_repo = StudentUploadRepository(pg_sessionmaker)
    attempt_repo = AttemptRepository(pg_sessionmaker)
    storage_backend = FakeStorageBackend()

    monkeypatch.setattr(student_router_module, "resolve_mark_scheme", lambda *a, **k: _mcq_scheme())
    monkeypatch.setattr(student_router_module, "extract_answers", lambda *a, **k: _extracted())

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: correct_settings
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    app.dependency_overrides[get_attempt_repo] = lambda: attempt_repo
    app.dependency_overrides[get_student_upload_repo] = lambda: upload_repo
    app.dependency_overrides[get_storage_backend] = lambda: storage_backend
    app.dependency_overrides[get_notification_service] = lambda: notifications
    app.dependency_overrides[get_push_transport] = lambda: transport
    app.dependency_overrides[get_xp_service] = _NoopXpService
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(student_id), role="student"
    )
    # Issue #10 / D7.5: see `_PgUserMirror`'s own docstring above.
    app.dependency_overrides[get_user_mirror] = lambda: _PgUserMirror(pg_sessionmaker)
    yield TestClient(app), student_id
    app.dependency_overrides.clear()


def _upload(client: TestClient) -> str:
    up = client.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert up.status_code == 200, up.text
    return str(up.json()["paperId"])


def _correct(client: TestClient, paper_id: str) -> None:
    resp = client.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200, resp.text
    assert "[DONE]" in resp.text


def _upload_and_correct(client: TestClient) -> str:
    paper_id = _upload(client)
    _correct(client, paper_id)
    return paper_id


def test_correcting_a_paper_notifies_the_student(
    correct_client: tuple[TestClient, uuid.UUID],
    notifications: NotificationService,
) -> None:
    api, student_id = correct_client
    paper_id = _upload_and_correct(api)

    rows = _inbox(notifications, student_id, NotificationType.grade_ready)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == student_id
    assert row.title == "Your paper has been marked"
    assert row.body == "0625 Paper 4 Variant 1 is ready to review."
    # The one identifier the screen needs to link somewhere, and nothing else.
    assert row.payload == {"uploadId": paper_id}


def test_the_notification_is_pushed_to_the_students_devices(
    correct_client: tuple[TestClient, uuid.UUID],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """The seam reaches delivery, not just the inbox write."""
    api, student_id = correct_client
    notifications.subscribe(student_id, "https://push.example/ep-1", "p256dh-key", "auth-secret")

    _upload_and_correct(api)

    assert transport.endpoints == ["https://push.example/ep-1"]


def test_re_correcting_the_same_paper_does_not_re_notify(
    correct_client: tuple[TestClient, uuid.UUID],
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
) -> None:
    """D5.9 §6, which is D5.3 written down before it could recur.

    Re-running ``/student/correct`` on one upload is an ordinary, legitimate
    act. It succeeds, mints a *second* ``Attempt``, and must not tell the
    student twice that the same paper is ready. This is the test that fails if
    the dedupe key is ever keyed on the attempt instead of the upload.
    """
    api, student_id = correct_client
    paper_id = _upload_and_correct(api)
    _correct(api, paper_id)

    # The re-correction genuinely ran — so the second notification was
    # suppressed by the dedupe key, not by the pipeline having refused.
    with pg_sessionmaker() as session:
        assert len(list(session.scalars(select(Attempt)))) == 2

    rows = _inbox(notifications, student_id, NotificationType.grade_ready)
    assert len(rows) == 1


def test_the_notification_carries_no_mark_and_no_grade(
    correct_client: tuple[TestClient, uuid.UUID],
    notifications: NotificationService,
) -> None:
    """D5.9 §2 and UI spec §1.4 — a notification is a pointer, never the data.

    The paper is marked 2 out of 3 and predicted at some grade; none of that
    may reach a row that a push service is told about and that a lock screen
    renders. Asserted over the whole serialised row rather than field by
    field, so a future seam that adds a helpful "you scored…" line fails here.
    """
    api, student_id = correct_client
    paper_id = _upload_and_correct(api)

    row = _inbox(notifications, student_id, NotificationType.grade_ready)[0]
    # The human-readable half: "2/3" is the awarded total, "67" its
    # percentage; "out of"/"scored"/"%" are the shapes a well-meaning future
    # edit would reach for. The word "marked" is fine and deliberately not
    # forbidden — that a paper *has been marked* is the event, and saying so
    # reveals nothing.
    text = f"{row.title} {row.body}".lower()
    for forbidden in ("2/3", "67", "%", "scored", "out of", "grade"):
        assert forbidden not in text
    # The payload is checked structurally rather than by substring: it holds
    # an id, and a UUID contains arbitrary hex, so "67" appears in one about
    # a third of the time. A substring scan over it is a test that fails on
    # the seed rather than on the code — which is exactly what it did.
    assert set(row.payload) == {"uploadId"}
    assert row.payload["uploadId"] == paper_id


def test_a_notification_failure_does_not_fail_the_correction(
    correct_client: tuple[TestClient, uuid.UUID],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D5.9 §1: the paper is already marked and stays marked.

    The attempt is persisted and the upload completed *before* this seam runs,
    so an inbox outage must cost the student a nudge and nothing else.
    """
    api, _student_id = correct_client
    api.app.dependency_overrides[get_notification_service] = _FailingNotificationService  # type: ignore[union-attr]

    paper_id = _upload(api)
    resp = api.post("/api/student/correct", json={"paperId": paper_id})

    assert resp.status_code == 200, resp.text
    assert "[DONE]" in resp.text
    assert "error" not in resp.text.lower()
    with pg_sessionmaker() as session:
        assert len(list(session.scalars(select(Attempt)))) == 1


def test_a_student_who_turned_grade_ready_off_gets_no_row(
    correct_client: tuple[TestClient, uuid.UUID],
    notifications: NotificationService,
    prefs: NotificationPreferencesService,
    transport: RecordingPushTransport,
) -> None:
    """The preference gate is live *at the seam*, not only inside the service.

    ``grade_ready`` off is a content preference, so the row is suppressed too
    (D5.9 §2) — safe precisely because the row was never the result, only a
    pointer to it. The correction itself is unaffected.
    """
    api, student_id = correct_client
    notifications.subscribe(student_id, "https://push.example/ep-1", "p256dh-key", "auth-secret")
    prefs.set(student_id, grade_ready=False)

    _upload_and_correct(api)

    assert _inbox(notifications, student_id, NotificationType.grade_ready) == []
    assert transport.endpoints == []


# ---------------------------------------------------------------------------
# Seam 2 — announcement (POST /api/teacher/announcements).
# ---------------------------------------------------------------------------


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def announcements(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> AnnouncementService:
    return AnnouncementService(pg_sessionmaker, class_service)


@pytest.fixture
def compose_client(
    announcements: AnnouncementService,
    class_service: ClassService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> Iterator[TestClient]:
    """A ``TestClient`` for the composer with a live inbox behind it.

    Auth is set per test via :func:`_auth_as`, because this seam's whole point
    is that the *composer* and the *recipients* are different people.
    """
    app = create_app()
    app.dependency_overrides[get_announcement_service] = lambda: announcements
    app.dependency_overrides[get_class_service] = lambda: class_service
    app.dependency_overrides[get_notification_service] = lambda: notifications
    app.dependency_overrides[get_push_transport] = lambda: transport
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_school(sm: sessionmaker[Session], admin_id: uuid.UUID) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Test School", seat_quota=10))
        session.add(
            SchoolMembership(
                school_id=school_id,
                user_id=admin_id,
                membership_role=MembershipRole.school_admin,
            )
        )
    return school_id


def _enroll(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def _seat(
    sm: sessionmaker[Session],
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    status: SeatStatus = SeatStatus.assigned,
) -> None:
    with sm.begin() as session:
        session.add(Seat(school_id=school_id, assigned_user_id=student_id, status=status))


def _post(client: TestClient, **body: object) -> dict[str, object]:
    resp = client.post("/api/teacher/announcements", json=body)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def test_a_class_announcement_notifies_every_enrolled_student(
    compose_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    notifications: NotificationService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    alice = _seed_user(pg_sessionmaker)
    bob = _seed_user(pg_sessionmaker)
    _enroll(pg_sessionmaker, cls.class_id, alice)
    _enroll(pg_sessionmaker, cls.class_id, bob)
    _auth_as(compose_client, teacher, Role.teacher)

    payload = _post(
        compose_client,
        title="Test on Friday",
        body="Bring calculators.",
        classIds=[str(cls.class_id)],
    )
    announcement_id = payload["announcements"][0]["announcementId"]  # type: ignore[index]

    # **Both** students. D5.9 §6 makes this seam idempotent on the pair
    # (announcement_id, user_id), and it is the unique index — already
    # (user_id, type, dedupe_key) — that supplies the user half, so one
    # announcement-id key per recipient is one row each, not one row total.
    for student in (alice, bob):
        rows = _inbox(notifications, student, NotificationType.announcement)
        assert len(rows) == 1
        assert rows[0].title == "New announcement"
        assert rows[0].body == "Test on Friday"
        assert rows[0].payload == {"announcementId": announcement_id}

    # The composing teacher is not in their own audience.
    assert _inbox(notifications, teacher, NotificationType.announcement) == []


def test_a_school_wide_announcement_notifies_seated_students(
    compose_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
) -> None:
    """D5.4's guard, in the delivery direction.

    Students reach a school through ``Seat``, never ``SchoolMembership`` —
    that table's role vocabulary is staff-only. Resolving the audience the
    wrong way returns nobody and reads as "the school has no students"
    rather than as a bug, which is why this test exists as well as
    ``test_announcement_student_read.py``'s read-side twin.
    """
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school_id = _seed_school(pg_sessionmaker, admin)
    seated = _seed_user(pg_sessionmaker)
    _seat(pg_sessionmaker, school_id, seated)
    _auth_as(compose_client, admin, Role.school_admin)

    _post(
        compose_client,
        title="Half term",
        body="School closed Monday.",
        schoolWide=True,
        schoolId=str(school_id),
    )

    assert len(_inbox(notifications, seated, NotificationType.announcement)) == 1


def test_a_revoked_seat_is_not_notified(
    compose_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
) -> None:
    """Someone whose seat was revoked cannot read the post, so must not be told about it.

    The audience reader and ``list_for_student`` share this predicate for
    exactly this reason: a notification pointing at a row the recipient is
    not allowed to open is worse than no notification.
    """
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school_id = _seed_school(pg_sessionmaker, admin)
    revoked = _seed_user(pg_sessionmaker)
    _seat(pg_sessionmaker, school_id, revoked, SeatStatus.revoked)
    _auth_as(compose_client, admin, Role.school_admin)

    _post(
        compose_client,
        title="Half term",
        body="School closed Monday.",
        schoolWide=True,
        schoolId=str(school_id),
    )

    assert _inbox(notifications, revoked, NotificationType.announcement) == []


def test_a_scheduled_announcement_notifies_nobody_yet(
    compose_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    notifications: NotificationService,
) -> None:
    """A future ``publishAt`` is invisible to students, so it must be silent.

    Notifying now would push a student at a post ``list_for_student`` still
    hides — a pointer to nothing. The honest cost, recorded rather than
    hidden: with no scheduler in this build (D5.9 §5), a scheduled
    announcement is never notified about at all; it simply appears in the
    student's list when its time comes.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    student = _seed_user(pg_sessionmaker)
    _enroll(pg_sessionmaker, cls.class_id, student)
    _auth_as(compose_client, teacher, Role.teacher)

    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    _post(
        compose_client,
        title="Next week",
        body="Later.",
        classIds=[str(cls.class_id)],
        publishAt=future,
    )

    assert _inbox(notifications, student, NotificationType.announcement) == []


def test_a_notification_failure_does_not_fail_the_compose(
    compose_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    """D5.9 §1: the announcement is written and stays written.

    The teacher's post succeeded before this seam ran; an inbox outage costs
    the class a nudge, and must not cost the teacher their announcement or
    show them a 500 for work that landed.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, _seed_user(pg_sessionmaker))
    _auth_as(compose_client, teacher, Role.teacher)
    compose_client.app.dependency_overrides[get_notification_service] = _FailingNotificationService  # type: ignore[union-attr]

    resp = compose_client.post(
        "/api/teacher/announcements",
        json={"title": "Test", "body": "Body", "classIds": [str(cls.class_id)]},
    )

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["announcements"]) == 1


def test_a_student_who_turned_announcements_off_gets_no_row(
    compose_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    notifications: NotificationService,
    prefs: NotificationPreferencesService,
) -> None:
    """One student opting out does not silence their classmates."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    quiet = _seed_user(pg_sessionmaker)
    loud = _seed_user(pg_sessionmaker)
    _enroll(pg_sessionmaker, cls.class_id, quiet)
    _enroll(pg_sessionmaker, cls.class_id, loud)
    prefs.set(quiet, announcement=False)
    _auth_as(compose_client, teacher, Role.teacher)

    _post(compose_client, title="Test", body="Body", classIds=[str(cls.class_id)])

    assert _inbox(notifications, quiet, NotificationType.announcement) == []
    assert len(_inbox(notifications, loud, NotificationType.announcement)) == 1


# ---------------------------------------------------------------------------
# Seam 3 — at_risk_alert (also POST /api/student/correct).
# ---------------------------------------------------------------------------


def _at_risk_record(percentage: float) -> PaperRecord:
    return PaperRecord(
        student_id="student",
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=4,
            paper_variant=1,
            session_month="May/June",
            session_year=2020,
        ),
        awarded_marks=int(percentage * 80 / 100),
        maximum_marks=80,
        percentage=percentage,
        grade="D",
        weak_areas=[],
        recorded_at=datetime.now(UTC).isoformat(),
        origin="past_paper",
    )


class _StubHistoryStore:
    """Returns one fixed history for every student.

    The at-risk *rules* are ``tests/test_at_risk.py``'s subject and are not
    re-tested here; what this file has to pin is the **seam** — who gets told,
    on what key, and gated by whose preferences. Driving the assessment from a
    fixed declining history makes those properties deterministic instead of a
    consequence of whatever grade the mocked pipeline happens to predict.
    """

    def __init__(self, history: StudentHistory) -> None:
        self._history = history

    def load(self, student_id: str) -> StudentHistory:
        return StudentHistory(student_id=student_id, records=list(self._history.records))


#: 72% → 65% → 58%: strictly decreasing over the 3-paper window with a 14pp
#: drop, so rule 1 fires. Rule 2 stays not-evaluable (no target is seeded) and
#: rule 3 cannot fire at this seam at all (D5.11 §2).
_DECLINING = StudentHistory(
    student_id="student",
    records=[_at_risk_record(72.0), _at_risk_record(65.0), _at_risk_record(58.0)],
)
_STEADY = StudentHistory(
    student_id="student",
    records=[_at_risk_record(72.0), _at_risk_record(74.0), _at_risk_record(73.0)],
)


@pytest.fixture
def at_risk_client(
    correct_client: tuple[TestClient, uuid.UUID],
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A declining student with one teacher and one linked parent.

    Returns ``(client, student, teacher, parent)``.
    """
    api, student_id = correct_client
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student_id)

    parent = _seed_user(pg_sessionmaker, Role.parent)
    with pg_sessionmaker.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=student_id))

    api.app.dependency_overrides[get_class_service] = lambda: class_service  # type: ignore[union-attr]
    api.app.dependency_overrides[get_parent_link_service] = lambda: ParentLinkService(  # type: ignore[union-attr]
        pg_sessionmaker
    )
    api.app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(  # type: ignore[union-attr]
        pg_sessionmaker
    )
    api.app.dependency_overrides[get_history_store] = lambda: _StubHistoryStore(_DECLINING)  # type: ignore[union-attr]
    return api, student_id, teacher, parent


def test_a_declining_students_teacher_and_parent_are_both_alerted(
    at_risk_client: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
    notifications: NotificationService,
) -> None:
    api, student_id, teacher, parent = at_risk_client

    _upload_and_correct(api)

    for staff in (teacher, parent):
        rows = _inbox(notifications, staff, NotificationType.at_risk_alert)
        assert len(rows) == 1
        assert rows[0].payload == {"studentId": str(student_id), "reason": "declining_trend"}
        # The reason, not the evidence: no percentage, no predicted grade.
        assert rows[0].body == "Recent papers show a declining trend."
        assert "%" not in rows[0].title + (rows[0].body or "")

    # The student is not told they are at risk by this seam — the alert is
    # addressed to the people who can act on it.
    assert _inbox(notifications, student_id, NotificationType.at_risk_alert) == []


def test_a_second_paper_the_same_day_does_not_re_alert(
    at_risk_client: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
    notifications: NotificationService,
) -> None:
    """D5.11 §3: at-risk is a state, not an event.

    An upload-keyed alert would send a teacher of thirty students one
    notification per upload per student. The key is
    ``(student, reason, Cairo civil date)``, so a second paper the same day is
    the same standing concern and says nothing new.
    """
    api, _student_id, teacher, _parent = at_risk_client

    _upload_and_correct(api)
    _upload_and_correct(api)

    assert len(_inbox(notifications, teacher, NotificationType.at_risk_alert)) == 1


def test_a_student_who_is_not_at_risk_alerts_nobody(
    correct_client: tuple[TestClient, uuid.UUID],
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    notifications: NotificationService,
) -> None:
    """No flag, no notification — the alert is a signal, so it must stay rare."""
    api, student_id = correct_client
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student_id)
    api.app.dependency_overrides[get_class_service] = lambda: class_service  # type: ignore[union-attr]
    api.app.dependency_overrides[get_parent_link_service] = lambda: ParentLinkService(  # type: ignore[union-attr]
        pg_sessionmaker
    )
    api.app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(  # type: ignore[union-attr]
        pg_sessionmaker
    )
    api.app.dependency_overrides[get_history_store] = lambda: _StubHistoryStore(_STEADY)  # type: ignore[union-attr]

    _upload_and_correct(api)

    assert _inbox(notifications, teacher, NotificationType.at_risk_alert) == []


def test_the_student_cannot_silence_alerts_about_themselves(
    at_risk_client: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
    notifications: NotificationService,
    prefs: NotificationPreferencesService,
) -> None:
    """D5.9 §3, the property this seam most needs pinned.

    The gate reads the **recipient's** preferences, never the subject's. A
    student turning ``at_risk_alert`` off silences alerts *addressed to them*
    — of which this seam sends none — and must not silence the ones addressed
    to their teacher and their parent. The parent's own row is what gates the
    parent's alert, and MISSION §4's opt-in for parent alerts is the parent's.
    """
    api, student_id, teacher, parent = at_risk_client
    prefs.set(student_id, at_risk_alert=False)

    _upload_and_correct(api)

    assert len(_inbox(notifications, teacher, NotificationType.at_risk_alert)) == 1
    assert len(_inbox(notifications, parent, NotificationType.at_risk_alert)) == 1


def test_a_parent_who_opted_out_is_not_alerted_but_the_teacher_still_is(
    at_risk_client: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
    notifications: NotificationService,
    prefs: NotificationPreferencesService,
) -> None:
    """The other half of D5.9 §3: the parent's own row governs the parent's alert."""
    api, _student_id, teacher, parent = at_risk_client
    prefs.set(parent, at_risk_alert=False)

    _upload_and_correct(api)

    assert _inbox(notifications, parent, NotificationType.at_risk_alert) == []
    assert len(_inbox(notifications, teacher, NotificationType.at_risk_alert)) == 1


def test_an_at_risk_failure_does_not_fail_the_correction(
    at_risk_client: tuple[TestClient, uuid.UUID, uuid.UUID, uuid.UUID],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D5.9 §1 again, and here it needs its own guard.

    The assessment and both recipient lookups are queries of *ours* and sit
    outside ``notify_safely``, so unlike the other two seams this one is not
    covered by that helper's own try/except. A raising history store stands in
    for any of them failing.
    """

    class _ExplodingHistoryStore:
        def load(self, student_id: str) -> StudentHistory:
            raise RuntimeError("simulated history-store failure")

    api, _student_id, _teacher, _parent = at_risk_client
    api.app.dependency_overrides[get_history_store] = _ExplodingHistoryStore  # type: ignore[union-attr]

    paper_id = _upload(api)
    resp = api.post("/api/student/correct", json={"paperId": paper_id})

    assert resp.status_code == 200, resp.text
    assert "[DONE]" in resp.text
    with pg_sessionmaker() as session:
        assert len(list(session.scalars(select(Attempt)))) == 1
