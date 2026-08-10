"""Route tests for ``/api/notifications`` (P5.6 chunk C).

Self-contained (mirrors ``tests/test_web_exam_calendar.py``) — a throwaway
Postgres DB per test, skipped cleanly when unreachable. This file tests the
HTTP layer: DTO shape, idempotency across the wire, the role-agnostic gate,
and the ownership properties that are structural rather than checked.
:class:`~lemely.db.notification_repo.NotificationService` has its own suite.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.enums import NotificationType, Role
from lemely.db.models.users import User
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.runtime.config import DatabaseSettings, PushSettings, Settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_notification_service,
    get_push_transport,
    get_settings,
)
from lemely.web.push import RecordingPushTransport, VapidPushTransport
from lemely.web.schemas_notifications import (
    NotificationCountsDTO,
    NotificationDTO,
    PushConfigDTO,
    PushSubscriptionDTO,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


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
def service(pg_sessionmaker: sessionmaker[Session]) -> NotificationService:
    return NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))


def _use_service(client: TestClient, service: NotificationService) -> None:
    client.app.dependency_overrides[get_notification_service] = lambda: service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role = Role.student) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


@pytest.fixture
def student(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    service: NotificationService,
) -> uuid.UUID:
    """A seeded, authenticated student with the service wired to their DB."""
    uid = _seed_user(pg_sessionmaker)
    _use_service(client, service)
    _auth_as(client, uid)
    return uid


# -- Reading the inbox -----------------------------------------------------


def test_an_empty_inbox_is_a_successful_empty_list(client: TestClient, student: uuid.UUID) -> None:
    """Nothing having happened yet is not an error and not a 404."""
    response = client.get("/api/notifications")

    assert response.status_code == 200
    assert response.json() == {"notifications": []}


def test_notifications_come_back_newest_first(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    service.create(student, NotificationType.grade_ready, "first")
    service.create(student, NotificationType.announcement, "second")

    titles = [n["title"] for n in client.get("/api/notifications").json()["notifications"]]

    assert titles == ["second", "first"]


def test_the_dto_carries_the_type_name_and_the_payload(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    service.create(
        student,
        NotificationType.grade_ready,
        "Your paper has been marked",
        body="Physics 0625 Paper 41",
        payload={"uploadId": "abc-123"},
    )

    row = client.get("/api/notifications").json()["notifications"][0]

    assert row["type"] == "grade_ready"
    assert row["title"] == "Your paper has been marked"
    assert row["body"] == "Physics 0625 Paper 41"
    assert row["payload"] == {"uploadId": "abc-123"}
    assert row["readAt"] is None


def test_a_non_string_payload_value_is_stringified_not_a_500(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    """A whole inbox that 500s over one odd row is worse than a coerced id."""
    service.create(student, NotificationType.grade_ready, "t", payload={"count": 3})

    response = client.get("/api/notifications")

    assert response.status_code == 200
    assert response.json()["notifications"][0]["payload"] == {"count": "3"}


def test_unread_only_filters(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    read = service.create(student, NotificationType.grade_ready, "read one")
    service.create(student, NotificationType.announcement, "unread one")
    assert read.row is not None
    service.mark_read(student, read.row.id)

    titles = [
        n["title"]
        for n in client.get("/api/notifications", params={"unreadOnly": True}).json()[
            "notifications"
        ]
    ]

    assert titles == ["unread one"]


def test_one_student_never_sees_anothers_notifications(
    client: TestClient,
    student: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    service: NotificationService,
) -> None:
    other = _seed_user(pg_sessionmaker)
    service.create(other, NotificationType.grade_ready, "not yours")

    assert client.get("/api/notifications").json() == {"notifications": []}


def test_counts_report_the_whole_inbox_not_the_page(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    """A badge derived from a LIMIT-ed page under-reports; this one cannot."""
    read = service.create(student, NotificationType.grade_ready, "a")
    service.create(student, NotificationType.announcement, "b")
    service.create(student, NotificationType.announcement, "c")
    assert read.row is not None
    service.mark_read(student, read.row.id)

    counts = client.get("/api/notifications/counts").json()

    assert counts == {"unread": 2, "total": 3, "unreadByType": {"announcement": 2}}


# -- Marking read ----------------------------------------------------------


def test_marking_read_echoes_the_canonical_id(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    """``uuid.UUID`` accepts braces, uppercase and ``urn:uuid:`` forms, which
    normalise differently. Echoing the raw path hands back an id that never
    matches the list response — P5.4 chunk B's defect, then P5.5's, not a third
    time."""
    result = service.create(student, NotificationType.grade_ready, "t")
    assert result.row is not None
    weird = f"urn:uuid:{str(result.row.id).upper()}"

    response = client.post(f"/api/notifications/{weird}/read")

    assert response.status_code == 200
    assert response.json()["notificationId"] == str(result.row.id)


def test_marking_read_twice_keeps_the_first_read_time(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    result = service.create(student, NotificationType.grade_ready, "t")
    assert result.row is not None

    first = client.post(f"/api/notifications/{result.row.id}/read").json()
    second = client.post(f"/api/notifications/{result.row.id}/read").json()

    assert second["readAt"] == first["readAt"]


def test_marking_someone_elses_notification_is_the_same_404_as_a_missing_one(
    client: TestClient,
    student: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    service: NotificationService,
) -> None:
    """One response for both, so nobody can probe for another user's ids."""
    other = _seed_user(pg_sessionmaker)
    theirs = service.create(other, NotificationType.grade_ready, "not yours")
    assert theirs.row is not None

    not_mine = client.post(f"/api/notifications/{theirs.row.id}/read")
    missing = client.post(f"/api/notifications/{uuid.uuid4()}/read")

    assert not_mine.status_code == 404
    assert missing.status_code == 404
    assert not_mine.json() == missing.json()


def test_a_malformed_notification_id_is_422(client: TestClient, student: uuid.UUID) -> None:
    assert client.post("/api/notifications/not-a-uuid/read").status_code == 422


def test_read_all_clears_the_inbox_and_is_idempotent(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    service.create(student, NotificationType.grade_ready, "a")
    service.create(student, NotificationType.announcement, "b")

    first = client.post("/api/notifications/read-all").json()
    second = client.post("/api/notifications/read-all").json()

    assert first == {"markedRead": 2}
    assert second == {"markedRead": 0}, "a second call reports 0, it does not re-stamp"


# -- The inbox belongs to every role --------------------------------------


@pytest.mark.parametrize("role", [Role.student, Role.teacher, Role.parent, Role.school_admin])
def test_every_role_can_open_its_own_inbox(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    service: NotificationService,
    role: Role,
) -> None:
    """``at_risk_alert`` is addressed to a teacher and a parent. A
    student-only router would have built an inbox two of its three intended
    readers cannot open."""
    uid = _seed_user(pg_sessionmaker, role)
    _use_service(client, service)
    _auth_as(client, uid, role)
    service.create(uid, NotificationType.at_risk_alert, "needs attention")

    response = client.get("/api/notifications")

    assert response.status_code == 200
    assert len(response.json()["notifications"]) == 1


def test_an_unauthenticated_caller_gets_401(client: TestClient) -> None:
    assert client.get("/api/notifications").status_code == 401


# -- Push subscriptions ----------------------------------------------------


def _subscribe(client: TestClient, endpoint: str) -> httpx.Response:
    return client.post(
        "/api/notifications/push/subscribe",
        json={"endpoint": endpoint, "keys": {"p256dh": "pk", "auth": "ak"}},
    )


def test_subscribing_stores_the_endpoint_and_is_idempotent(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    first = _subscribe(client, "https://push.test/a")
    second = _subscribe(client, "https://push.test/a")

    assert first.status_code == 200
    assert second.status_code == 200
    assert [s.endpoint for s in service.subscriptions_for(student)] == ["https://push.test/a"]


def test_subscribing_is_accepted_with_no_vapid_keys_configured(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    """A subscription is a durable fact about a browser. Refusing to record it
    on an unconfigured server would force every user to re-subscribe the day
    keys were added."""
    client.app.dependency_overrides[get_push_transport] = lambda: VapidPushTransport(  # type: ignore[union-attr]
        PushSettings()
    )

    assert _subscribe(client, "https://push.test/a").status_code == 200
    assert len(service.subscriptions_for(student)) == 1


def test_the_subscribe_response_carries_no_key_material(
    client: TestClient, student: uuid.UUID
) -> None:
    body = _subscribe(client, "https://push.test/a").json()

    assert set(body) == {"endpoint", "createdAt"}
    assert "pk" not in str(body)
    assert "ak" not in str(body)


def test_a_malformed_subscription_body_is_422(client: TestClient, student: uuid.UUID) -> None:
    response = client.post(
        "/api/notifications/push/subscribe",
        json={"endpoint": "https://push.test/a"},
    )

    assert response.status_code == 422


def test_unsubscribing_removes_the_caller_s_endpoint(
    client: TestClient, student: uuid.UUID, service: NotificationService
) -> None:
    _subscribe(client, "https://push.test/a")

    response = client.post(
        "/api/notifications/push/unsubscribe", json={"endpoint": "https://push.test/a"}
    )

    assert response.json() == {"removed": True}
    assert service.subscriptions_for(student) == []


def test_unsubscribing_someone_elses_endpoint_is_a_successful_false(
    client: TestClient,
    student: uuid.UUID,
    pg_sessionmaker: sessionmaker[Session],
    service: NotificationService,
) -> None:
    """The postcondition holds either way. A 404 would tell the caller whether
    some endpoint string belongs to somebody else."""
    other = _seed_user(pg_sessionmaker)
    service.subscribe(other, "https://push.test/theirs", "pk", "ak")

    response = client.post(
        "/api/notifications/push/unsubscribe", json={"endpoint": "https://push.test/theirs"}
    )

    assert response.status_code == 200
    assert response.json() == {"removed": False}
    assert len(service.subscriptions_for(other)) == 1, "their subscription survives"


# -- Push configuration ----------------------------------------------------


def test_push_config_is_honestly_unavailable_with_no_keys(
    client: TestClient, student: uuid.UUID
) -> None:
    """The state this build actually ships in."""
    client.app.dependency_overrides[get_push_transport] = lambda: VapidPushTransport(  # type: ignore[union-attr]
        PushSettings()
    )

    body = client.get("/api/notifications/push/config").json()

    assert body == {"available": False, "publicKey": None}


def test_push_config_publishes_the_public_key_when_configured(
    client: TestClient, student: uuid.UUID
) -> None:
    push = PushSettings(
        vapid_public_key="BPublicKeyMaterial",
        vapid_private_key="cHJpdmF0ZQ",
        vapid_subject="mailto:build@lemely.test",
    )
    client.app.dependency_overrides[get_settings] = lambda: Settings(push=push)  # type: ignore[union-attr]
    client.app.dependency_overrides[get_push_transport] = lambda: VapidPushTransport(push)  # type: ignore[union-attr]

    body = client.get("/api/notifications/push/config").json()

    assert body == {"available": True, "publicKey": "BPublicKeyMaterial"}


def test_a_recording_transport_can_stand_in_for_the_real_one(
    client: TestClient, student: uuid.UUID
) -> None:
    """MISSION §4's headless push mock, reachable through ``deps``."""
    client.app.dependency_overrides[get_push_transport] = RecordingPushTransport  # type: ignore[union-attr]

    assert client.get("/api/notifications/push/config").json()["available"] is True


# -- The routes exist, read from the OpenAPI schema ------------------------


def test_every_notification_route_is_mounted() -> None:
    """Read ``app.openapi()``, never ``app.routes``: this FastAPI version wraps
    included routers in an opaque ``_IncludedRouter`` with no ``.path``, so a
    route-introspection test over ``app.routes`` finds nothing and passes for
    the wrong reason (P5.5 chunk C's trap, not re-sprung)."""
    paths = set(create_app().openapi()["paths"])

    assert {
        "/api/notifications",
        "/api/notifications/counts",
        "/api/notifications/{notification_id}/read",
        "/api/notifications/read-all",
        "/api/notifications/push/config",
        "/api/notifications/push/subscribe",
        "/api/notifications/push/unsubscribe",
    } <= paths


# -- Structurally answer-only (D5.1 §0, MISSION §3) ------------------------


@pytest.mark.parametrize(
    "model",
    [NotificationDTO, NotificationCountsDTO, PushConfigDTO, PushSubscriptionDTO],
)
def test_no_notification_dto_carries_anything_shaped_like_a_mark(model: type) -> None:
    """An addition fails here rather than silently reaching the wire."""
    # "total" is deliberately absent: NotificationCountsDTO.total is a count of
    # rows, not a mark out of a maximum, and banning the word would make the
    # guard cry wolf on the one honest use of it here.
    banned = {"mark", "marks", "score", "grade", "percentage", "percent", "accuracy"}
    names = {name.lower() for name in model.model_fields}

    assert not (names & banned), f"{model.__name__} grew a grade-shaped field"
