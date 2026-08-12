"""Route tests for ``/api/student/friends`` (P5.4 chunk B).

Self-contained (mirrors ``tests/test_web_leaderboard.py``) — a throwaway
Postgres DB per test, skipped cleanly when unreachable. This file tests the
HTTP layer (DTO shape, code normalisation, status-code mapping), not
``FriendService`` itself, which already has its own suite
(``tests/test_friend_repo.py``).

Covers every route's happy path, the full error-mapping table from the P5.4
chunk B brief by status code, the authz matrix (non-student roles rejected
on every route), lowercase-friend-code normalisation, the crossed-requests
response body, a non-party ``DELETE`` leaving the row intact, the D5.5
no-``@``-leak regression extended to this surface, ``scope=friends`` being
reachable over HTTP on the leaderboard route, and the friend code being
stable across repeated ``GET`` calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.friend_repo import FriendService
from lemely.db.leaderboard_repo import LeaderboardService
from lemely.db.models.enums import Role
from lemely.db.models.users import Friendship, User
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_friend_service,
    get_leaderboard_service,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_NOON_UTC = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


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
def friend_service(pg_sessionmaker: sessionmaker[Session]) -> FriendService:
    return FriendService(pg_sessionmaker, now=lambda: _NOON_UTC)


@pytest.fixture
def leaderboard_service(pg_sessionmaker: sessionmaker[Session]) -> LeaderboardService:
    return LeaderboardService(pg_sessionmaker, now=lambda: _NOON_UTC)


def _use_services(
    client: TestClient,
    friend_service: FriendService,
    leaderboard_service: LeaderboardService | None = None,
) -> None:
    client.app.dependency_overrides[get_friend_service] = lambda: friend_service  # type: ignore[union-attr]
    if leaderboard_service is not None:
        client.app.dependency_overrides[get_leaderboard_service] = lambda: leaderboard_service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(
    sm: sessionmaker[Session], role: Role = Role.student, *, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


# ---------------------------------------------------------------------------
# GET "" — happy path.
# ---------------------------------------------------------------------------


def test_get_friends_mints_code_and_returns_full_page(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    viewer = _seed_user(pg_sessionmaker, display_name="Viewer")
    _auth_as(client, viewer, Role.student)

    resp = client.get("/api/student/friends")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["friendCode"]) == 8
    assert body["friends"] == []
    assert body["incoming"] == []
    assert body["outgoing"] == []


def test_friend_code_is_stable_across_two_get_calls(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    viewer = _seed_user(pg_sessionmaker)
    _auth_as(client, viewer, Role.student)

    first = client.get("/api/student/friends").json()["friendCode"]
    second = client.get("/api/student/friends").json()["friendCode"]

    assert first == second


def test_get_friends_shows_accepted_friend_and_pending_requests(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker, display_name="A")
    b = _seed_user(pg_sessionmaker, display_name="B")
    c = _seed_user(pg_sessionmaker, display_name="C")

    friendship_ab = friend_service.request(a, friend_service.friend_code_for(b))
    friend_service.accept(b, friendship_ab.id)
    friend_service.request(a, friend_service.friend_code_for(c))  # a -> c pending

    _auth_as(client, a, Role.student)
    body = client.get("/api/student/friends").json()

    assert [f["userId"] for f in body["friends"]] == [str(b)]
    assert body["friends"][0]["optedOut"] is False
    assert [r["userId"] for r in body["outgoing"]] == [str(c)]
    assert body["incoming"] == []


# ---------------------------------------------------------------------------
# POST /requests
# ---------------------------------------------------------------------------


def test_create_request_happy_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker, display_name="B")
    code_b = friend_service.friend_code_for(b)
    _auth_as(client, a, Role.student)

    resp = client.post("/api/student/friends/requests", json={"friendCode": code_b})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["userId"] == str(b)
    assert body["displayName"] == "B"
    assert body["status"] == "pending"


def test_lowercase_friend_code_is_normalised_and_succeeds(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    """A student typing a friend's code off a screenshot in lowercase must
    not get "no such code" — the router normalises with ``.strip().upper()``
    before calling the service."""
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker)
    code_b = friend_service.friend_code_for(b)
    _auth_as(client, a, Role.student)

    resp = client.post(
        "/api/student/friends/requests", json={"friendCode": f"  {code_b.lower()}  "}
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["userId"] == str(b)


def test_crossed_requests_second_caller_gets_accepted_status_in_body(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    """Both students ask before seeing the other's request -> the second
    caller's response body must say ``status="accepted"``, not ``"pending"``
    -- the client must never be left inferring this."""
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker, display_name="A")
    b = _seed_user(pg_sessionmaker, display_name="B")
    code_a = friend_service.friend_code_for(a)
    code_b = friend_service.friend_code_for(b)

    _auth_as(client, a, Role.student)
    first = client.post("/api/student/friends/requests", json={"friendCode": code_b})
    assert first.status_code == 201
    assert first.json()["status"] == "pending"

    _auth_as(client, b, Role.student)
    second = client.post("/api/student/friends/requests", json={"friendCode": code_a})
    assert second.status_code == 201
    body = second.json()
    assert body["status"] == "accepted"
    assert body["friendshipId"] == first.json()["friendshipId"]

    # The returned party must be the OTHER student, never the caller. The row
    # accepted here was created by A, so its ``addressee_id`` is B -- the
    # caller -- and reading the party straight off that column shipped a DTO
    # that id'd the caller while carrying A's display name. A client
    # rendering "you are now friends with ..." would have linked to the
    # caller's own profile. Both halves are asserted because the id and the
    # name came from different code paths and only one of them was wrong.
    assert body["userId"] == str(a)
    assert body["displayName"] == "A"


# ---------------------------------------------------------------------------
# Error mapping — POST /requests.
# ---------------------------------------------------------------------------


def test_create_request_unknown_code_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    _auth_as(client, a, Role.student)

    resp = client.post("/api/student/friends/requests", json={"friendCode": "ZZZZZZZZ"})

    assert resp.status_code == 404


def test_create_request_self_code_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    code_a = friend_service.friend_code_for(a)
    _auth_as(client, a, Role.student)

    resp = client.post("/api/student/friends/requests", json={"friendCode": code_a})

    assert resp.status_code == 422


def test_create_request_duplicate_is_409(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker)
    code_b = friend_service.friend_code_for(b)
    _auth_as(client, a, Role.student)
    client.post("/api/student/friends/requests", json={"friendCode": code_b})

    resp = client.post("/api/student/friends/requests", json={"friendCode": code_b})

    assert resp.status_code == 409


def test_create_request_viewer_id_with_no_user_row_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    _use_services(client, friend_service)
    b = _seed_user(pg_sessionmaker)
    code_b = friend_service.friend_code_for(b)
    _auth_as(client, uuid.uuid4(), Role.student)  # never seeded

    resp = client.post("/api/student/friends/requests", json={"friendCode": code_b})

    assert resp.status_code == 404


def test_create_request_ineligible_db_role_is_403(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    """Defence in depth (D5.1 §10): the token claims student, but the
    persisted row is a teacher."""
    _use_services(client, friend_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    b = _seed_user(pg_sessionmaker)
    code_b = friend_service.friend_code_for(b)
    _auth_as(client, teacher, Role.student)  # token lies about the role

    resp = client.post("/api/student/friends/requests", json={"friendCode": code_b})

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /{friendship_id}/accept
# ---------------------------------------------------------------------------


def test_accept_happy_path_returns_enriched_friend(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker, display_name="A")
    b = _seed_user(pg_sessionmaker)
    friendship = friend_service.request(a, friend_service.friend_code_for(b))
    _auth_as(client, b, Role.student)

    resp = client.post(f"/api/student/friends/{friendship.id}/accept")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["userId"] == str(a)
    assert body["displayName"] == "A"
    assert body["optedOut"] is False


def test_accept_accepts_a_non_canonical_uuid_spelling(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    """An uppercase / braced UUID must return the friend, not a 500.

    ``uuid.UUID`` happily parses ``{ABCD-...}``, so the service accepts the
    request; the route then has to find the resulting row. Matching on the raw
    path string instead of the parsed id would succeed at accepting and *then*
    fall through to the route's "unreachable" 500 -- a friendship silently
    created behind an error response.
    """
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker, display_name="A")
    b = _seed_user(pg_sessionmaker)
    friendship = friend_service.request(a, friend_service.friend_code_for(b))
    _auth_as(client, b, Role.student)

    resp = client.post(f"/api/student/friends/{{{str(friendship.id).upper()}}}/accept")

    assert resp.status_code == 200, resp.text
    assert resp.json()["userId"] == str(a)


def test_accept_unknown_friendship_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    _use_services(client, friend_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.post(f"/api/student/friends/{uuid.uuid4()}/accept")

    assert resp.status_code == 404


def test_accept_by_non_addressee_is_404_same_as_unknown(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    """Requester or stranger accepting -> 404, indistinguishable from an
    unknown friendship (D5.6 §4 no-existence-oracle)."""
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker)
    friendship = friend_service.request(a, friend_service.friend_code_for(b))
    _auth_as(client, a, Role.student)  # requester, not addressee

    resp = client.post(f"/api/student/friends/{friendship.id}/accept")

    assert resp.status_code == 404


def test_accept_already_accepted_is_409(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker)
    friendship = friend_service.request(a, friend_service.friend_code_for(b))
    friend_service.accept(b, friendship.id)
    _auth_as(client, b, Role.student)

    resp = client.post(f"/api/student/friends/{friendship.id}/accept")

    assert resp.status_code == 409


def test_accept_malformed_id_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    _use_services(client, friend_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.post("/api/student/friends/not-a-uuid/accept")

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /{friendship_id}
# ---------------------------------------------------------------------------


def test_delete_pending_by_addressee_declines(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker)
    friendship = friend_service.request(a, friend_service.friend_code_for(b))
    _auth_as(client, b, Role.student)

    resp = client.delete(f"/api/student/friends/{friendship.id}")

    assert resp.status_code == 204
    assert resp.content == b""
    with pg_sessionmaker() as session:
        assert session.get(Friendship, friendship.id) is None


def test_delete_accepted_by_either_party_unfriends(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker)
    friendship = friend_service.request(a, friend_service.friend_code_for(b))
    friend_service.accept(b, friendship.id)
    _auth_as(client, a, Role.student)

    resp = client.delete(f"/api/student/friends/{friendship.id}")

    assert resp.status_code == 204
    with pg_sessionmaker() as session:
        assert session.get(Friendship, friendship.id) is None


def test_delete_by_non_party_is_404_and_friendship_still_exists(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker)
    stranger = _seed_user(pg_sessionmaker)
    friendship = friend_service.request(a, friend_service.friend_code_for(b))
    _auth_as(client, stranger, Role.student)

    resp = client.delete(f"/api/student/friends/{friendship.id}")

    assert resp.status_code == 404
    # The DB state, not just the status code: the row must survive untouched.
    with pg_sessionmaker() as session:
        row = session.get(Friendship, friendship.id)
        assert row is not None
        assert row.requester_id == a
        assert row.addressee_id == b


def test_delete_malformed_id_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], friend_service: FriendService
) -> None:
    _use_services(client, friend_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.delete("/api/student/friends/not-a-uuid")

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Authz matrix.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.teacher, Role.parent, Role.school_admin])
def test_non_student_roles_are_rejected_on_every_route(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
    role: Role,
) -> None:
    _use_services(client, friend_service)
    non_student = _seed_user(pg_sessionmaker, role)
    student = _seed_user(pg_sessionmaker)
    code_student = friend_service.friend_code_for(student)
    fake_friendship_id = uuid.uuid4()
    _auth_as(client, non_student, role)

    assert client.get("/api/student/friends").status_code == 403
    assert (
        client.post("/api/student/friends/requests", json={"friendCode": code_student}).status_code
        == 403
    )
    assert client.post(f"/api/student/friends/{fake_friendship_id}/accept").status_code == 403
    assert client.delete(f"/api/student/friends/{fake_friendship_id}").status_code == 403

    # Inverse: the identical route, as a student, is reachable (not 403).
    _auth_as(client, student, Role.student)
    assert client.get("/api/student/friends").status_code == 200


# ---------------------------------------------------------------------------
# D5.5 regression: no email leaks through a display name.
# ---------------------------------------------------------------------------


def test_no_at_sign_anywhere_in_friends_page_response(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker, display_name=None)  # unnamed
    b = _seed_user(pg_sessionmaker, display_name=None)  # unnamed
    c = _seed_user(pg_sessionmaker, display_name=None)  # unnamed
    friendship = friend_service.request(a, friend_service.friend_code_for(b))
    friend_service.accept(b, friendship.id)
    friend_service.request(a, friend_service.friend_code_for(c))
    _auth_as(client, a, Role.student)

    resp = client.get("/api/student/friends")

    assert resp.status_code == 200
    assert "@" not in resp.text


def test_no_at_sign_in_create_request_response(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    a = _seed_user(pg_sessionmaker)
    b = _seed_user(pg_sessionmaker, display_name=None)  # unnamed
    code_b = friend_service.friend_code_for(b)
    _auth_as(client, a, Role.student)

    resp = client.post("/api/student/friends/requests", json={"friendCode": code_b})

    assert resp.status_code == 201
    assert "@" not in resp.text


# ---------------------------------------------------------------------------
# scope=friends reachable over HTTP on the leaderboard route (chunk A could
# not prove this — the router did not exist yet).
# ---------------------------------------------------------------------------


def test_leaderboard_friends_scope_is_reachable_over_http(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
    leaderboard_service: LeaderboardService,
) -> None:
    from lemely.db.models.engagement import XpEvent
    from lemely.db.models.enums import XpSource

    _use_services(client, friend_service, leaderboard_service)
    viewer = _seed_user(pg_sessionmaker, display_name="Viewer")
    accepted_friend = _seed_user(pg_sessionmaker, display_name="Friend")
    non_friend = _seed_user(pg_sessionmaker, display_name="Stranger")

    friendship = friend_service.request(viewer, friend_service.friend_code_for(accepted_friend))
    friend_service.accept(accepted_friend, friendship.id)

    with pg_sessionmaker.begin() as session:
        session.add_all(
            [
                XpEvent(
                    user_id=viewer,
                    source=XpSource.flashcard_reviewed,
                    amount=10,
                    awarded_on=_NOON_UTC.date(),
                    dedupe_key=f"dk-{uuid.uuid4()}",
                ),
                XpEvent(
                    user_id=accepted_friend,
                    source=XpSource.flashcard_reviewed,
                    amount=20,
                    awarded_on=_NOON_UTC.date(),
                    dedupe_key=f"dk-{uuid.uuid4()}",
                ),
                XpEvent(
                    user_id=non_friend,
                    source=XpSource.flashcard_reviewed,
                    amount=999,
                    awarded_on=_NOON_UTC.date(),
                    dedupe_key=f"dk-{uuid.uuid4()}",
                ),
            ]
        )

    _auth_as(client, viewer, Role.student)
    resp = client.get("/api/student/leaderboard", params={"scope": "friends"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {row["userId"] for row in body["rows"]}
    assert str(viewer) in ids
    assert str(accepted_friend) in ids
    assert str(non_friend) not in ids


# ---------------------------------------------------------------------------
# Sanity: the friend code minted for the DB row matches what the DB stores.
# ---------------------------------------------------------------------------


def test_minted_friend_code_matches_persisted_column(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    friend_service: FriendService,
) -> None:
    _use_services(client, friend_service)
    viewer = _seed_user(pg_sessionmaker)
    _auth_as(client, viewer, Role.student)

    body = client.get("/api/student/friends").json()

    with pg_sessionmaker() as session:
        row = session.scalar(select(User).where(User.id == viewer))
        assert row is not None
        assert row.friend_code == body["friendCode"]
