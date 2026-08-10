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
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import NotificationType, Role
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.upload_repo import StudentUploadRepository
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_attempt_repo,
    get_auth_context,
    get_gemini_client,
    get_notification_service,
    get_push_transport,
    get_settings,
    get_storage_backend,
    get_student_upload_repo,
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
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


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
    _upload_and_correct(api)

    row = _inbox(notifications, student_id, NotificationType.grade_ready)[0]
    text = f"{row.title} {row.body} {row.payload}".lower()
    # "2/3" is the awarded total, "67" its percentage; "out of"/"scored"/"%"
    # are the shapes a well-meaning future edit would reach for. The word
    # "marked" is fine and deliberately not forbidden — that a paper *has
    # been marked* is the event, and saying so reveals nothing.
    for forbidden in ("2/3", "67", "%", "scored", "out of", "grade"):
        assert forbidden not in text
    assert set(row.payload) == {"uploadId"}


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
