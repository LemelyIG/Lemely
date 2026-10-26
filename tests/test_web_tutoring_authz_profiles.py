"""Object-level rules for profiles and the directory (SPEC §c.3 O1, O11 directory half, O21).

PLAN §1.4 #3: one ``tests/test_web_tutoring_authz_<area>.py`` file per task. Each
rule has a passing case and a case that must go red without its check (the
mutation proofs are recorded in the task's return).
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import TYPE_CHECKING

import pytest

from lemely.core.keyset import encode_cursor
from lemely.db.models.enums import Role
from lemely.web.routers import tutor_profile
from tests.test_tutor_directory_repo import (
    add_block,
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)
from tests.test_web_tutoring_public import act_as, anonymous, tutoring_client
from tests.tutoring_app import flatten_routes

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = tutoring_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def _token(payload: object) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# ---------------------------------------------------------------------------
# O1: tutor routes act only on the caller's own profile
# ---------------------------------------------------------------------------


def test_o1_tutor_routes_take_no_tutor_id() -> None:
    routes = flatten_routes(tutor_profile.router)
    assert len(routes) == 5  # T1-T5
    for route in routes:
        assert "{" not in route.path, route.path
        assert not route.dependant.query_params, route.path


def test_o1_each_teacher_reads_and_edits_only_their_own_profile(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    subject = add_subject(sm)
    alice = add_tutor(sm, first_name="Alia", subjects=(subject,))
    bob = add_tutor(sm, first_name="Basma", subjects=(subject,))

    act_as(client, bob.user_id, Role.teacher)
    assert client.get("/api/tutor/profile").json()["tutorId"] == str(bob.profile_id)
    edited = client.patch("/api/tutor/profile", json={"indexable": False})
    assert edited.json()["tutorId"] == str(bob.profile_id)

    act_as(client, alice.user_id, Role.teacher)
    mine = client.get("/api/tutor/profile").json()
    assert mine["tutorId"] == str(alice.profile_id)
    assert mine["publicName"] == "Alia M."
    assert mine["indexable"] is True


# ---------------------------------------------------------------------------
# O11 (directory half): listed and not paused, blocked pairs hidden
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.student, Role.parent])
def test_o11_sp2_404_unless_listed_and_not_paused(
    client: TestClient, sm: sessionmaker[Session], role: Role
) -> None:
    act_as(client, add_user(sm, role), role)
    listed = add_tutor(sm, subjects=(add_subject(sm),))
    ok = client.get(f"/api/tutors/{listed.profile_id}")
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == "private, no-store"
    unknown = client.get(f"/api/tutors/{uuid.uuid4()}")
    assert unknown.status_code == 404
    for hidden in [
        add_tutor(sm, paused=True),
        *(
            add_tutor(sm, state=s)
            for s in ("draft", "pending_review", "rejected", "suspended", "closed")
        ),
    ]:
        response = client.get(f"/api/tutors/{hidden.profile_id}")
        assert response.status_code == 404
        assert response.content == unknown.content
    page = client.get("/api/tutors").json()
    assert [item["tutorId"] for item in page["items"]] == [str(listed.profile_id)]


@pytest.mark.parametrize("direction", ["student_blocks_tutor", "tutor_blocks_student"])
def test_o11_blocked_pair_hidden_on_sp1_and_sp2(
    client: TestClient, sm: sessionmaker[Session], direction: str
) -> None:
    student = add_user(sm)
    blocked, free = add_tutor(sm), add_tutor(sm)
    if direction == "student_blocks_tutor":
        add_block(sm, student, blocked.user_id)
    else:
        add_block(sm, blocked.user_id, student)
    act_as(client, student, Role.student)

    listed = {item["tutorId"] for item in client.get("/api/tutors").json()["items"]}
    assert listed == {str(free.profile_id)}
    hidden = client.get(f"/api/tutors/{blocked.profile_id}")
    assert hidden.status_code == 404
    assert hidden.content == client.get(f"/api/tutors/{uuid.uuid4()}").content
    assert client.get(f"/api/tutors/{free.profile_id}").status_code == 200

    # A parent holds no blocks (SPEC §b.2 SP1): the tutor stays visible to them.
    act_as(client, add_user(sm, Role.parent), Role.parent)
    assert client.get(f"/api/tutors/{blocked.profile_id}").status_code == 200


def test_sp2_requires_verified_email_403(client: TestClient, sm: sessionmaker[Session]) -> None:
    listed = add_tutor(sm)
    act_as(client, add_user(sm, verified=False), Role.student)
    response = client.get(f"/api/tutors/{listed.profile_id}")
    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "email_unverified"}
    assert response.headers["cache-control"] == "private, no-store"
    # SP1 carries no V mark.
    assert client.get("/api/tutors").status_code == 200


def test_sp2_serves_the_logged_in_profile(client: TestClient, sm: sessionmaker[Session]) -> None:
    subject = add_subject(sm, name="Biology")
    seeded = add_tutor(
        sm,
        subjects=(subject,),
        bio="Ten years.",
        modes=("virtual", "other"),
        other_mode_note="Small groups",
        rules=((4, 1020, 1200),),
        documents_seen=True,
    )
    act_as(client, add_user(sm), Role.student)
    body = client.get(f"/api/tutors/{seeded.profile_id}").json()
    assert body["bio"] == "Ten years."
    assert body["otherModeNote"] == "Small groups"
    assert body["documentsSeen"] is True
    assert body["availability"] == [{"isoWeekday": 4, "startMinute": 1020, "endMinute": 1200}]
    assert body["zoneLabel"] == "Cairo time"
    assert len(body["listedSince"]) == 7  # "YYYY-MM"
    assert "indexable" not in body  # O31
    assert str(seeded.user_id) not in json.dumps(body)  # O29


def test_sp1_availability_filters(client: TestClient, sm: sessionmaker[Session]) -> None:
    evening = add_tutor(sm, rules=((4, 1020, 1200),))
    morning = add_tutor(sm, rules=((1, 540, 660),))
    act_as(client, add_user(sm, Role.parent), Role.parent)

    def ids(query: str) -> set[str]:
        response = client.get(f"/api/tutors?{query}")
        assert response.status_code == 200, response.text
        return {item["tutorId"] for item in response.json()["items"]}

    assert ids("") == {str(evening.profile_id), str(morning.profile_id)}
    assert ids("day=4&timeOfDay=evening") == {str(evening.profile_id)}
    assert ids("timeOfDay=morning&timeOfDay=afternoon") == {str(morning.profile_id)}
    assert ids("day=2") == set()
    for bad in ("day=0", "day=8", "day=x", "timeOfDay=night", "minRating=4.3", "area=atlantis"):
        assert client.get(f"/api/tutors?{bad}").status_code == 422, bad


@pytest.mark.parametrize("role", [Role.teacher, Role.school_admin, Role.platform_admin])
def test_sp1_sp2_refuse_other_roles_403(
    client: TestClient, sm: sessionmaker[Session], role: Role
) -> None:
    listed = add_tutor(sm)
    act_as(client, add_user(sm, role), role)
    for path in ("/api/tutors", f"/api/tutors/{listed.profile_id}"):
        response = client.get(path)
        assert response.status_code == 403, path
        assert response.headers["cache-control"] == "private, no-store"
    anonymous(client)
    assert client.get("/api/tutors").status_code == 401


# ---------------------------------------------------------------------------
# O21: cursors are tagged and typed
# ---------------------------------------------------------------------------


def test_idor_cursor_from_other_endpoint_422(client: TestClient, sm: sessionmaker[Session]) -> None:
    for n in range(3):
        add_tutor(sm, first_name=f"Tutor{'abc'[n]}")
    act_as(client, add_user(sm), Role.student)

    public_cursor = client.get("/api/public/tutors?limit=1").json()["nextCursor"]
    logged_in_cursor = client.get("/api/tutors?limit=1").json()["nextCursor"]
    assert public_cursor and logged_in_cursor
    # Each works on its own list...
    assert client.get(f"/api/public/tutors?limit=1&cursor={public_cursor}").status_code == 200
    assert client.get(f"/api/tutors?limit=1&cursor={logged_in_cursor}").status_code == 200
    # ...and neither on the other one.
    crossed = client.get(f"/api/tutors?limit=1&cursor={public_cursor}")
    assert crossed.status_code == 422
    assert crossed.json()["detail"]["code"] == "invalid_cursor"
    assert crossed.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/public/tutors?limit=1&cursor={logged_in_cursor}").status_code == 422
    # A cursor minted for an unrelated list (another endpoint's tag) is refused too.
    foreign = encode_cursor("student_bookings", ["4.000000", False, "2026-01-01T00:00:00+00:00"])
    assert client.get(f"/api/tutors?cursor={foreign}").status_code == 422


_INJECTIONS = [
    # Decimal slot carrying SQL.
    {
        "e": "{tag}",
        "k": ["4.0; DROP TABLE tutor_profiles; --", False, "2026-01-01T00:00:00+00:00", "{id}"],
    },
    # Exponent and NaN forms are never written by the codec.
    {"e": "{tag}", "k": ["1e999999", False, "2026-01-01T00:00:00+00:00", "{id}"]},
    {"e": "{tag}", "k": ["NaN", False, "2026-01-01T00:00:00+00:00", "{id}"]},
    # UUID slot carrying SQL, and a non-canonical UUID.
    {"e": "{tag}", "k": ["4.000000", False, "2026-01-01T00:00:00+00:00", "' OR '1'='1"]},
    {"e": "{tag}", "k": ["4.000000", False, "2026-01-01T00:00:00+00:00", "{{{id}}}"]},
    # Naive instant, wrong type in the flag slot, wrong arity, extra keys.
    {"e": "{tag}", "k": ["4.000000", False, "2026-01-01T00:00:00", "{id}"]},
    {"e": "{tag}", "k": ["4.000000", "false", "2026-01-01T00:00:00+00:00", "{id}"]},
    {"e": "{tag}", "k": ["4.000000", "{id}"]},
    {"e": "{tag}", "k": ["4.000000", False, "2026-01-01T00:00:00+00:00", "{id}"], "x": 1},
]


@pytest.mark.parametrize("path", ["/api/public/tutors", "/api/tutors"])
def test_idor_cursor_typed_decode_rejects_injection(
    client: TestClient, sm: sessionmaker[Session], path: str
) -> None:
    add_tutor(sm)
    act_as(client, add_user(sm), Role.student)
    tag = "public_tutors" if path.startswith("/api/public") else "tutors"
    tid = str(uuid.uuid4())
    for template in _INJECTIONS:
        payload = json.loads(json.dumps(template).replace("{tag}", tag).replace("{id}", tid))
        response = client.get(path, params={"cursor": _token(payload)})
        assert response.status_code == 422, payload
        assert response.json()["detail"]["code"] == "invalid_cursor", payload
    for garbage in ["%%%", "a" * 600, _token(["not", "an", "object"])]:
        assert client.get(path, params={"cursor": garbage}).status_code == 422, garbage
    # The table is intact and the list still answers.
    assert len(client.get(path).json()["items"]) == 1
    assert len(_INJECTIONS) == 9
