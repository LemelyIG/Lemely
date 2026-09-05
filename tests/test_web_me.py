"""Route tests for ``/api/me/notification-preferences`` (P3.6 chunk B, G-12).

Self-contained (mirrors ``tests/test_web_quiz.py``) — a throwaway Postgres DB
per test, skipped cleanly when unreachable. Available to every authenticated
role (not gated by ``require_role``), so this file's authz matrix is the
inverse of the role-scoped portal routers': every role reaches both routes,
and only ``atRiskAlert``'s visibility/settability differs by role (teacher
and parent only, per G-12). Proves:

* GET for a caller with no stored row reads as all-defaults.
* PUT then GET round-trips, and a partial PUT leaves other fields untouched.
* ``atRiskAlert`` is null on a student's/school_admin's/platform_admin's GET,
  and a PUT from one of those roles that supplies it (true or false) is 422;
  a teacher's and a parent's PUT setting it succeeds.
* Quiet hours: both-set round-trips; one-set-without-the-other is 422.
* Every route 401s with no bearer token, mirroring
  ``tests/test_web_quiz.py::test_unauthenticated_call_is_401``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.runtime.errors import AuthError, ExternalServiceError
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_notification_prefs_service,
    get_settings,
    get_storage_backend,
    get_user_mirror,
)
from tests.storage_fakes import FakeStorageBackend

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
def prefs_service(pg_sessionmaker: sessionmaker[Session]) -> NotificationPreferencesService:
    return NotificationPreferencesService(pg_sessionmaker)


def _seed_user(
    sm: sessionmaker[Session],
    role: Role,
    display_name: str | None = None,
    email_verified_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a real ``users`` row — ``notification_preferences.user_id`` FKs to it,
    so any test that actually writes a preferences row (not just reads the
    all-defaults value) needs a real user to satisfy the constraint.

    ``display_name`` defaults to ``None`` (unset by every pre-existing caller
    of this helper) so the profile tests can seed the nullable-name case
    without touching any other test in this file. ``email_verified_at``
    defaults to ``None`` for the same reason: an unverified account is what
    every pre-existing caller already meant.
    """
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=role,
                display_name=display_name,
                email_verified_at=email_verified_at,
            )
        )
    return uid


def _use_prefs_service(client: TestClient, service: NotificationPreferencesService) -> None:
    client.app.dependency_overrides[get_notification_prefs_service] = lambda: service  # type: ignore[union-attr]


class _SessionUserMirror:
    """Minimal ``UserMirror`` reading through a throwaway-DB sessionmaker.

    Mirrors ``DbUserMirror.get_by_id`` (``lemely/auth/mirror.py``) exactly,
    but bound to ``pg_sessionmaker`` directly rather than to ``Settings`` —
    the same shape every other test-local repo double in this file's sibling
    tests (``ClassService(sm)`` etc.) uses to avoid touching the process-wide
    database in tests. Only ``get_by_id`` is implemented — the only method
    ``get_profile`` calls.
    """

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        with self._sm() as session:
            user = session.get(User, user_id)
            if user is not None:
                session.expunge(user)
            return user

    def set_avatar_path(self, user_id: uuid.UUID, path: str | None) -> None:
        with self._sm.begin() as session:
            user = session.get(User, user_id)
            if user is not None:
                user.avatar_path = path


def _use_user_mirror(client: TestClient, sm: sessionmaker[Session]) -> None:
    client.app.dependency_overrides[get_user_mirror] = lambda: _SessionUserMirror(sm)  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


# ---------------------------------------------------------------------------
# GET: defaults, no auto-create, atRiskAlert visibility.
# ---------------------------------------------------------------------------


def test_get_defaults_for_a_caller_with_no_stored_row(
    client: TestClient, prefs_service: NotificationPreferencesService
) -> None:
    _use_prefs_service(client, prefs_service)
    _auth_as(client, uuid.uuid4(), Role.student)

    resp = client.get("/api/me/notification-preferences")

    assert resp.status_code == 200
    body = resp.json()
    assert body["gradeReady"] is True
    assert body["announcement"] is True
    assert body["streakWarning"] is True
    assert body["studyPlanReminder"] is True
    assert body["quietHoursStart"] is None
    assert body["quietHoursEnd"] is None


@pytest.mark.parametrize("role", [Role.student, Role.school_admin, Role.platform_admin])
def test_at_risk_alert_is_null_on_a_non_teacher_non_parent_get(
    client: TestClient, prefs_service: NotificationPreferencesService, role: Role
) -> None:
    _use_prefs_service(client, prefs_service)
    _auth_as(client, uuid.uuid4(), role)

    resp = client.get("/api/me/notification-preferences")

    assert resp.status_code == 200
    assert resp.json()["atRiskAlert"] is None


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_at_risk_alert_is_present_on_a_teacher_or_parent_get(
    client: TestClient, prefs_service: NotificationPreferencesService, role: Role
) -> None:
    _use_prefs_service(client, prefs_service)
    _auth_as(client, uuid.uuid4(), role)

    resp = client.get("/api/me/notification-preferences")

    assert resp.status_code == 200
    assert resp.json()["atRiskAlert"] is True


# ---------------------------------------------------------------------------
# PUT then GET: round trip, partial update.
# ---------------------------------------------------------------------------


def test_put_then_get_round_trips(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    prefs_service: NotificationPreferencesService,
) -> None:
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_prefs_service(client, prefs_service)
    _auth_as(client, user, Role.teacher)

    put_resp = client.put(
        "/api/me/notification-preferences",
        json={
            "gradeReady": False,
            "announcement": False,
            "atRiskAlert": False,
            "quietHoursStart": "22:00:00",
            "quietHoursEnd": "07:00:00",
        },
    )
    assert put_resp.status_code == 200
    put_body = put_resp.json()
    assert put_body["gradeReady"] is False
    assert put_body["announcement"] is False
    assert put_body["atRiskAlert"] is False
    assert put_body["quietHoursStart"] == "22:00:00"
    assert put_body["quietHoursEnd"] == "07:00:00"
    # Unmentioned fields land at their documented default on first write.
    assert put_body["streakWarning"] is True
    assert put_body["studyPlanReminder"] is True

    get_resp = client.get("/api/me/notification-preferences")
    assert get_resp.status_code == 200
    assert get_resp.json() == put_body


def test_partial_put_leaves_other_fields_untouched(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    prefs_service: NotificationPreferencesService,
) -> None:
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_prefs_service(client, prefs_service)
    _auth_as(client, user, Role.teacher)

    client.put(
        "/api/me/notification-preferences",
        json={"gradeReady": False, "announcement": False, "atRiskAlert": False},
    )
    second = client.put("/api/me/notification-preferences", json={"gradeReady": True})

    assert second.status_code == 200
    body = second.json()
    assert body["gradeReady"] is True
    # Untouched by the second PUT — must still reflect the first.
    assert body["announcement"] is False
    assert body["atRiskAlert"] is False
    assert body["streakWarning"] is True
    assert body["studyPlanReminder"] is True


def test_put_empty_body_leaves_every_field_untouched(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    prefs_service: NotificationPreferencesService,
) -> None:
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_prefs_service(client, prefs_service)
    _auth_as(client, user, Role.teacher)

    client.put("/api/me/notification-preferences", json={"streakWarning": False})
    second = client.put("/api/me/notification-preferences", json={})

    assert second.status_code == 200
    assert second.json()["streakWarning"] is False


@pytest.mark.parametrize(
    "field",
    ["gradeReady", "announcement", "streakWarning", "studyPlanReminder"],
)
def test_put_explicit_null_on_a_toggle_is_422_not_a_silent_reset(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    prefs_service: NotificationPreferencesService,
    field: str,
) -> None:
    """An explicit ``null`` on a toggle is invalid input, not "clear this field".

    Every toggle column is ``NOT NULL``, so there is no state a ``null``
    could mean. The DTO types them ``bool | None`` purely so
    ``model_fields_set`` can tell *omitted* from *sent*; the route must
    therefore reject a sent ``null`` rather than coerce it to the default,
    which would silently re-enable a notification the user had turned off.
    The quiet-hours pair is the deliberate exception — there ``null`` really
    does clear the bound.
    """
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_prefs_service(client, prefs_service)
    _auth_as(client, user, Role.student)
    assert client.put("/api/me/notification-preferences", json={field: False}).status_code == 200

    resp = client.put("/api/me/notification-preferences", json={field: None})

    assert resp.status_code == 422
    # The rejected write left the stored value alone.
    assert client.get("/api/me/notification-preferences").json()[field] is False


# ---------------------------------------------------------------------------
# atRiskAlert: role gating on PUT.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.student, Role.school_admin, Role.platform_admin])
def test_put_at_risk_alert_from_a_disallowed_role_is_422(
    client: TestClient, prefs_service: NotificationPreferencesService, role: Role
) -> None:
    _use_prefs_service(client, prefs_service)
    _auth_as(client, uuid.uuid4(), role)

    resp = client.put("/api/me/notification-preferences", json={"atRiskAlert": True})

    assert resp.status_code == 422


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_put_at_risk_alert_from_teacher_or_parent_succeeds(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    prefs_service: NotificationPreferencesService,
    role: Role,
) -> None:
    user = _seed_user(pg_sessionmaker, role)
    _use_prefs_service(client, prefs_service)
    _auth_as(client, user, role)

    resp = client.put("/api/me/notification-preferences", json={"atRiskAlert": False})

    assert resp.status_code == 200
    assert resp.json()["atRiskAlert"] is False


def test_put_at_risk_alert_disallowed_role_does_not_change_other_fields(
    client: TestClient, prefs_service: NotificationPreferencesService
) -> None:
    user = uuid.uuid4()
    _use_prefs_service(client, prefs_service)
    _auth_as(client, user, Role.student)

    rejected = client.put(
        "/api/me/notification-preferences",
        json={"gradeReady": False, "atRiskAlert": True},
    )
    assert rejected.status_code == 422

    # The whole request must have been rejected, not applied partially.
    get_resp = client.get("/api/me/notification-preferences")
    assert get_resp.json()["gradeReady"] is True


# ---------------------------------------------------------------------------
# Quiet hours: pair validation on PUT.
# ---------------------------------------------------------------------------


def test_quiet_hours_both_set_round_trips(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    prefs_service: NotificationPreferencesService,
) -> None:
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_prefs_service(client, prefs_service)
    _auth_as(client, user, Role.student)

    resp = client.put(
        "/api/me/notification-preferences",
        json={"quietHoursStart": "21:30:00", "quietHoursEnd": "06:15:00"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["quietHoursStart"] == "21:30:00"
    assert body["quietHoursEnd"] == "06:15:00"


def test_quiet_hours_start_without_end_is_422(
    client: TestClient, prefs_service: NotificationPreferencesService
) -> None:
    _use_prefs_service(client, prefs_service)
    _auth_as(client, uuid.uuid4(), Role.student)

    resp = client.put("/api/me/notification-preferences", json={"quietHoursStart": "21:30:00"})

    assert resp.status_code == 422


def test_quiet_hours_end_without_start_is_422(
    client: TestClient, prefs_service: NotificationPreferencesService
) -> None:
    _use_prefs_service(client, prefs_service)
    _auth_as(client, uuid.uuid4(), Role.student)

    resp = client.put("/api/me/notification-preferences", json={"quietHoursEnd": "06:15:00"})

    assert resp.status_code == 422


def test_clearing_only_one_bound_of_an_existing_pair_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    prefs_service: NotificationPreferencesService,
) -> None:
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_prefs_service(client, prefs_service)
    _auth_as(client, user, Role.student)
    client.put(
        "/api/me/notification-preferences",
        json={"quietHoursStart": "21:30:00", "quietHoursEnd": "06:15:00"},
    )

    resp = client.put("/api/me/notification-preferences", json={"quietHoursStart": None})

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/me/profile (P3.7 chunk B) — real identity, never a fabricated one.
# ---------------------------------------------------------------------------


def test_profile_returns_the_real_display_name_email_and_role(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    user = _seed_user(pg_sessionmaker, Role.teacher, display_name="Nour El-Sayed")
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)

    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["displayName"] == "Nour El-Sayed"
    assert body["email"] == f"{user}@example.com"
    assert body["role"] == "teacher"


def test_profile_display_name_is_null_when_unset_not_fabricated(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A user who never set a display name gets ``null``, never a made-up one.

    ``User.display_name`` is nullable; the route must pass that absence
    through honestly rather than substituting the email or a placeholder —
    the caller (the teacher-portal sidebar) decides how to render it.
    """
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)

    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    assert resp.json()["displayName"] is None


def test_profile_reports_an_unverified_email_as_unverified(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """D7.5's gate reads ``email_verified_at``; nothing published it until now.

    Without this field the app cannot tell a reader their address is
    unverified before ``POST /student/correct`` refuses the run, which is the
    whole reason the verify-email banner exists.
    """
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)

    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    assert resp.json()["emailVerified"] is False


def test_profile_reports_a_verified_email_as_verified(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A boolean, never the timestamp: the client only asks the yes/no question."""
    user = _seed_user(
        pg_sessionmaker,
        Role.student,
        email_verified_at=datetime(2026, 3, 3, 12, 0, tzinfo=UTC),
    )
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)

    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["emailVerified"] is True
    # The date itself is deliberately not published. Shipping it would invite a
    # screen to render "verified on 3 March", which nobody asked for and which
    # would then have to be maintained as a user-facing fact.
    assert "emailVerifiedAt" not in body


@pytest.mark.parametrize(
    "role", [Role.student, Role.parent, Role.school_admin, Role.platform_admin]
)
def test_profile_is_reachable_by_every_role(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    """Unlike the role-scoped portal routers, ``/api/me`` reaches every role (G-12's pattern)."""
    user = _seed_user(pg_sessionmaker, role)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, role)

    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    assert resp.json()["role"] == role.value


def test_profile_for_a_token_with_no_mirrored_row_is_404_not_500(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, uuid.uuid4(), Role.teacher)

    resp = client.get("/api/me/profile")

    assert resp.status_code == 404


def test_unauthenticated_profile_get_is_401(client: TestClient) -> None:
    resp = client.get("/api/me/profile")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Unauthenticated: 401 on both routes.
# ---------------------------------------------------------------------------


def test_unauthenticated_get_is_401(client: TestClient) -> None:
    resp = client.get("/api/me/notification-preferences")
    assert resp.status_code == 401


def test_unauthenticated_put_is_401(client: TestClient) -> None:
    resp = client.put("/api/me/notification-preferences", json={"gradeReady": False})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST/DELETE /api/me/avatar — profile picture, any authenticated role.
# ---------------------------------------------------------------------------


def _png_bytes(size: tuple[int, int] = (4, 4)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _use_storage_backend(client: TestClient, backend: FakeStorageBackend) -> None:
    client.app.dependency_overrides[get_storage_backend] = lambda: backend  # type: ignore[union-attr]


def _settings_with(**storage_overrides: object) -> Settings:
    """A ``Settings`` copy with ``[storage]`` fields overridden (see ``test_web_classes.py``)."""
    base = load_settings()
    data = base.model_dump()
    data["storage"] = {**data["storage"], **storage_overrides}
    return Settings.model_validate(data)


def _use_settings(client: TestClient, settings: Settings) -> None:
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[union-attr]


def test_avatar_upload_sets_signed_url_and_stores_object(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)
    backend = FakeStorageBackend()
    _use_storage_backend(client, backend)

    resp = client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["avatarUrl"] is not None
    assert body["avatarUrl"].startswith("fake://avatars/")
    assert f"avatars/{user}/" in body["avatarUrl"]

    # The object actually landed in storage under the caller's own namespace,
    # inside the avatars bucket (the object path itself does not repeat the
    # bucket name — that would double it to "avatars/avatars/...").
    stored_paths = [path for (bucket, path) in backend._objects if bucket == "avatars"]
    assert len(stored_paths) == 1
    assert stored_paths[0].startswith(f"{user}/")
    assert stored_paths[0].endswith(".png")

    # GET reflects the upload.
    get_resp = client.get("/api/me/profile")
    assert get_resp.status_code == 200
    assert get_resp.json()["avatarUrl"] == body["avatarUrl"]


@pytest.mark.parametrize(
    "role",
    [Role.student, Role.teacher, Role.parent, Role.school_admin, Role.platform_admin],
)
def test_avatar_upload_is_reachable_by_every_role(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    user = _seed_user(pg_sessionmaker, role)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, role)
    _use_storage_backend(client, FakeStorageBackend())

    resp = client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert resp.status_code == 200
    assert resp.json()["role"] == role.value


def test_avatar_upload_wrong_content_type_is_415(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)
    _use_storage_backend(client, FakeStorageBackend())

    resp = client.post(
        "/api/me/avatar",
        files={"image": ("scan.pdf", b"%PDF-1.4 not really an image", "application/pdf")},
    )

    assert resp.status_code == 415


def test_avatar_upload_oversize_is_413(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)
    _use_storage_backend(client, FakeStorageBackend())
    _use_settings(client, _settings_with(avatar_max_bytes=16))

    resp = client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert resp.status_code == 413


def test_avatar_upload_decompression_bomb_is_422_not_500(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A tiny-on-disk, huge-in-memory PNG must 422, not crash with an unhandled 500.

    ``PIL.Image.DecompressionBombError`` subclasses ``Exception`` directly
    (neither ``OSError`` nor ``ValueError``), so a route that only catches
    those two lets this one propagate as an internal server error.
    """
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)
    _use_storage_backend(client, FakeStorageBackend())

    buf = BytesIO()
    Image.new("L", (20000, 20000)).save(buf, format="PNG")
    bomb_bytes = buf.getvalue()

    resp = client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", bomb_bytes, "image/png")},
    )

    assert resp.status_code == 422
    # Nothing was written to storage or the mirror.
    assert client.get("/api/me/profile").json()["avatarUrl"] is None


def test_avatar_upload_format_mismatching_declared_content_type_is_415(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """Real GIF bytes declared as ``image/png`` must not be stored as a ``.png``.

    The upload decodes cleanly with Pillow, so the "is this a valid image at
    all" check alone would accept it — the format the bytes actually sniff as
    must also match the declared content type.
    """
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)
    _use_storage_backend(client, FakeStorageBackend())

    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(1, 2, 3)).save(buf, format="GIF")
    gif_bytes = buf.getvalue()

    resp = client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", gif_bytes, "image/png")},
    )

    assert resp.status_code == 415
    assert client.get("/api/me/profile").json()["avatarUrl"] is None


def test_avatar_upload_garbage_bytes_with_image_content_type_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A caller lying about the content type does not get an image accepted."""
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)
    _use_storage_backend(client, FakeStorageBackend())

    resp = client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", b"not actually a png", "image/png")},
    )

    assert resp.status_code == 422
    # Nothing was written to storage or the mirror.
    assert client.get("/api/me/profile").json()["avatarUrl"] is None


def test_avatar_delete_clears_avatar_url(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)
    _use_storage_backend(client, FakeStorageBackend())
    upload_resp = client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )
    assert upload_resp.json()["avatarUrl"] is not None

    resp = client.delete("/api/me/avatar")

    assert resp.status_code == 200
    assert resp.json()["avatarUrl"] is None
    assert client.get("/api/me/profile").json()["avatarUrl"] is None


def test_unauthenticated_avatar_post_is_401(client: TestClient) -> None:
    resp = client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 401


def test_unauthenticated_avatar_delete_is_401(client: TestClient) -> None:
    resp = client.delete("/api/me/avatar")
    assert resp.status_code == 401


class _SigningFailsStorageBackend(FakeStorageBackend):
    """A storage double whose signing always fails, like a down storage backend."""

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        raise ExternalServiceError("storage is unreachable")


def test_profile_get_avatar_url_is_null_when_signing_fails_not_500(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """The sidebar must render even when storage cannot sign a URL (D5.9-style rule)."""
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)
    _use_storage_backend(client, FakeStorageBackend())
    client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    _use_storage_backend(client, _SigningFailsStorageBackend())
    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    assert resp.json()["avatarUrl"] is None


class _AuthErrorStorageBackend(FakeStorageBackend):
    """A storage double raising ``AuthError``, like an unconfigured service-role key."""

    def create_signed_url(self, bucket: str, object_path: str, expires_in: int) -> str:
        raise AuthError("Supabase service-role key is not configured.")


def test_profile_get_avatar_url_is_null_when_signing_raises_auth_error_not_500(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A missing service-role key (``AuthError``) must not 500 the profile read either.

    ``_avatar_url_for``'s contract is "never fail the profile read" for any
    storage failure, not only :class:`~lemely.runtime.errors.ExternalServiceError`
    — an unconfigured Supabase key, or a google-auth error on the GCS backend,
    are equally not this route's problem.
    """
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)
    _use_storage_backend(client, FakeStorageBackend())
    client.post(
        "/api/me/avatar",
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    _use_storage_backend(client, _AuthErrorStorageBackend())
    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    assert resp.json()["avatarUrl"] is None
