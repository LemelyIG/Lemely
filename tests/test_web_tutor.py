"""Tutor profile routes T1-T5 (SPEC §b.2 "Tutor", §a.3, §a.4b CB-7, ADR-T01, SC-7, row 17).

Cross-cutting obligations of PLAN "Global constraints" for these five routes:
(a) ``no-store`` on each success path, (b) SC-7 for every free-text field they
accept, (c) ``email_unverified`` on the one **V** route (T4), (d)
``tutor_suspended``/``tutor_closed`` on every write route (T3, T4, T5), and (f)
``no_tutor_profile`` 404 on every route except T2 (ADR-T01 action 3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.enums import Role
from tests.test_tutor_directory_repo import (
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)
from tests.test_web_tutoring_public import act_as, anonymous, tutoring_client

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


def create_body(subject: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "publicFirstName": "Sara",
        "publicLastInitial": "M",
        "headline": "IGCSE Mathematics, exam focused",
        "subjectCodes": [subject],
        "offersVirtual": True,
        "offersInPerson": False,
        "offersOther": True,
        "otherModeNote": "Small groups",
        "areaCode": "cairo",
    }
    body.update(overrides)
    return body


def _profile_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.execute(sa.text("SELECT count(*) FROM tutor_profiles")).scalar_one())


# ---------------------------------------------------------------------------
# T2 create, T1 read
# ---------------------------------------------------------------------------


def test_t2_creates_a_draft_and_t1_reads_it(client: TestClient, sm: sessionmaker[Session]) -> None:
    subject = add_subject(sm, name="Mathematics")
    teacher = add_user(sm, Role.teacher)
    act_as(client, teacher, Role.teacher)

    created = client.post("/api/tutor/profile", json=create_body(subject, bio="Ten years."))
    assert created.status_code == 201, created.text
    assert created.headers["cache-control"] == "private, no-store"
    body = created.json()
    assert body["listingState"] == "draft"
    assert body["publicName"] == "Sara M."
    assert body["subjects"] == [{"code": subject, "name": "Mathematics"}]
    assert body["modes"] == ["virtual", "other"]
    assert body["area"] == {"code": "cairo", "name": "Cairo"}
    assert body["rating"] == {"state": "new", "average": None, "count": 0}
    assert body["listedSince"] is None
    assert body["zone"] == "Africa/Cairo"
    assert body["zoneLabel"] == "Cairo time"
    assert body["paused"] is False
    assert body["evidence"] == []
    assert body["reviewNote"] is None
    assert body["reReviewRequired"] is False
    assert body["availability"] == []
    assert body["tutorId"] != str(teacher)

    read = client.get("/api/tutor/profile")
    assert read.status_code == 200
    assert read.headers["cache-control"] == "private, no-store"
    assert read.json() == body


def test_t2_profile_exists_409(client: TestClient, sm: sessionmaker[Session]) -> None:
    subject = add_subject(sm)
    teacher = add_user(sm, Role.teacher)
    act_as(client, teacher, Role.teacher)
    assert client.post("/api/tutor/profile", json=create_body(subject)).status_code == 201
    again = client.post("/api/tutor/profile", json=create_body(subject))
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "profile_exists"
    assert again.headers["cache-control"] == "private, no-store"
    assert _profile_count(sm) == 1


def test_t2_name_charset_422(client: TestClient, sm: sessionmaker[Session]) -> None:
    subject = add_subject(sm)
    act_as(client, add_user(sm, Role.teacher), Role.teacher)
    for name in ("Sara1", "sara@x", "Sara‮", "www.sara"):
        response = client.post(
            "/api/tutor/profile", json=create_body(subject, publicFirstName=name)
        )
        assert response.status_code == 422, name
        assert response.json()["detail"]["code"] == "invalid_public_name", name
    assert (
        client.post(
            "/api/tutor/profile", json=create_body(subject, publicFirstName="سارة")
        ).status_code
        == 201
    )


def test_indexable_defaults_true_and_tutor_can_opt_out(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    subject = add_subject(sm)
    teacher = add_user(sm, Role.teacher)
    act_as(client, teacher, Role.teacher)
    created = client.post("/api/tutor/profile", json=create_body(subject)).json()
    assert created["indexable"] is True

    # Approve it the way A3 will (T10), so P2 can read it.
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE tutor_profiles SET listing_state = 'listed', first_listed_at = now(), "
                "listed_at = now() WHERE user_id = :u"
            ),
            {"u": teacher},
        )
    tutor_id = created["tutorId"]
    assert client.get(f"/api/public/tutors/{tutor_id}").json()["indexable"] is True

    opted_out = client.patch("/api/tutor/profile", json={"indexable": False})
    assert opted_out.status_code == 200
    assert opted_out.json()["indexable"] is False
    assert opted_out.json()["listingState"] == "listed"
    assert client.get("/api/tutor/profile").json()["indexable"] is False
    assert client.get(f"/api/public/tutors/{tutor_id}").json()["indexable"] is False


def test_indexable_change_does_not_send_profile_back_to_review(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    act_as(client, tutor.user_id, Role.teacher)
    for body in ({"indexable": False}, {"indexable": True}, {"paused": True}, {"paused": False}):
        response = client.patch("/api/tutor/profile", json=body)
        assert response.status_code == 200, body
        assert response.json()["reReviewRequired"] is False, body
        assert response.json()["listingState"] == "listed", body


def test_t3_moderated_edit_reports_re_review(client: TestClient, sm: sessionmaker[Session]) -> None:
    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    act_as(client, tutor.user_id, Role.teacher)
    response = client.patch("/api/tutor/profile", json={"headline": "A sharper headline"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["reReviewRequired"] is True
    assert response.json()["listingState"] == "pending_review"
    assert client.get(f"/api/public/tutors/{tutor.profile_id}").status_code == 404
    # A later read is a plain read again.
    assert client.get("/api/tutor/profile").json()["reReviewRequired"] is False


def test_t3_null_for_a_required_field_422(client: TestClient, sm: sessionmaker[Session]) -> None:
    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    act_as(client, tutor.user_id, Role.teacher)
    for body in ({"headline": None}, {"subjectCodes": None}, {"areaCode": None}):
        assert client.patch("/api/tutor/profile", json=body).status_code == 422, body
    assert client.patch("/api/tutor/profile", json={"unknownField": 1}).status_code == 422


# ---------------------------------------------------------------------------
# SC-7: every free-text profile field (b)
# ---------------------------------------------------------------------------

_CONTACTS = ["Call 0101 234 5678", "sara@example.com", "https://wa.me/201012345678", "@sara_tutor"]
_FREE_TEXT = ["headline", "bio", "qualificationNote", "otherModeNote"]


@pytest.mark.parametrize("field", _FREE_TEXT)
@pytest.mark.parametrize("route", ["T2", "T3"])
def test_free_text_fields_reject_contact_details(
    client: TestClient, sm: sessionmaker[Session], field: str, route: str
) -> None:
    subject = add_subject(sm)
    if route == "T2":
        actor = add_user(sm, Role.teacher)
    else:
        actor = add_tutor(sm, subjects=(subject,), modes=("virtual", "other")).user_id
    act_as(client, actor, Role.teacher)
    for contact in _CONTACTS:
        text = f"Lessons online. {contact}"
        if route == "T2":
            response = client.post("/api/tutor/profile", json=create_body(subject, **{field: text}))
        else:
            response = client.patch("/api/tutor/profile", json={field: text})
        assert response.status_code == 422, (field, contact)
        assert response.json()["detail"]["code"] == "contact_details_not_allowed", (field, contact)
    with sm() as session:
        stored = session.execute(
            sa.text("SELECT headline, bio, qualification_note, other_mode_note FROM tutor_profiles")
        ).all()
    assert all("Lessons online" not in str(value) for row in stored for value in row)


# ---------------------------------------------------------------------------
# No profile (f), suspended/closed (d), verified email (c)
# ---------------------------------------------------------------------------

_NEEDS_PROFILE = [
    ("GET", "/api/tutor/profile", None),
    ("PATCH", "/api/tutor/profile", {"indexable": False}),
    ("POST", "/api/tutor/profile/submit", None),
    ("PUT", "/api/tutor/profile/availability", {"rules": []}),
]


def test_t1_without_profile_404_no_tutor_profile(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    act_as(client, add_user(sm, Role.teacher), Role.teacher)
    response = client.get("/api/tutor/profile")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_tutor_profile"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(("method", "path", "json_body"), _NEEDS_PROFILE[1:])
def test_t3_t4_t5_404_no_tutor_profile(
    client: TestClient, sm: sessionmaker[Session], method: str, path: str, json_body: object
) -> None:
    # Verified, so T4's email gate cannot be what answers.
    act_as(client, add_user(sm, Role.teacher, verified=True), Role.teacher)
    response = client.request(method, path, json=json_body)
    assert response.status_code == 404, path
    assert response.json()["detail"]["code"] == "no_tutor_profile", path
    assert response.headers["cache-control"] == "private, no-store"


def test_another_teachers_profile_is_never_reached(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    add_tutor(sm, subjects=(add_subject(sm),))
    act_as(client, add_user(sm, Role.teacher), Role.teacher)
    for method, path, json_body in _NEEDS_PROFILE:
        assert client.request(method, path, json=json_body).status_code == 404, path


@pytest.mark.parametrize(
    ("state", "code"), [("suspended", "tutor_suspended"), ("closed", "tutor_closed")]
)
@pytest.mark.parametrize(("method", "path", "json_body"), _NEEDS_PROFILE[1:])
def test_t3_t4_t5_suspended_or_closed_409(
    client: TestClient,
    sm: sessionmaker[Session],
    state: str,
    code: str,
    method: str,
    path: str,
    json_body: object,
) -> None:
    tutor = add_tutor(sm, state=state, subjects=(add_subject(sm),))
    act_as(client, tutor.user_id, Role.teacher)
    response = client.request(method, path, json=json_body)
    assert response.status_code == 409, path
    assert response.json()["detail"]["code"] == code, path
    assert response.headers["cache-control"] == "private, no-store"
    # The tutor can still read their own profile (T1 is not a write route).
    assert client.get("/api/tutor/profile").json()["listingState"] == state


def test_t4_requires_verified_email_403(client: TestClient, sm: sessionmaker[Session]) -> None:
    tutor = add_tutor(sm, state="draft", subjects=(add_subject(sm),), verified=False)
    act_as(client, tutor.user_id, Role.teacher)
    response = client.post("/api/tutor/profile/submit")
    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "email_unverified"}
    assert response.headers["cache-control"] == "private, no-store"


def test_t4_submit_flow(client: TestClient, sm: sessionmaker[Session]) -> None:
    tutor = add_tutor(sm, state="draft", subjects=(), rules=())
    act_as(client, tutor.user_id, Role.teacher)
    incomplete = client.post("/api/tutor/profile/submit")
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"]["code"] == "incomplete_profile"

    subject = add_subject(sm)
    assert client.patch("/api/tutor/profile", json={"subjectCodes": [subject]}).status_code == 200
    rules = {"rules": [{"isoWeekday": 4, "startMinute": 1020, "endMinute": 1200}]}
    assert client.put("/api/tutor/profile/availability", json=rules).status_code == 200
    submitted = client.post("/api/tutor/profile/submit")
    assert submitted.status_code == 200
    assert submitted.headers["cache-control"] == "private, no-store"
    assert submitted.json()["listingState"] == "pending_review"
    assert submitted.json()["submittedAt"] is not None

    again = client.post("/api/tutor/profile/submit")
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "illegal_transition"


# ---------------------------------------------------------------------------
# T5 availability
# ---------------------------------------------------------------------------


def test_t5_replaces_rules_and_maps_overlap_to_422(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    act_as(client, tutor.user_id, Role.teacher)
    overlapping = {
        "rules": [
            {"isoWeekday": 1, "startMinute": 600, "endMinute": 720},
            {"isoWeekday": 1, "startMinute": 660, "endMinute": 780},
        ]
    }
    refused = client.put("/api/tutor/profile/availability", json=overlapping)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "overlapping_rules"
    assert refused.headers["cache-control"] == "private, no-store"

    replaced = client.put(
        "/api/tutor/profile/availability",
        json={
            "rules": [
                {"isoWeekday": 3, "startMinute": 600, "endMinute": 720},
                {"isoWeekday": 1, "startMinute": 600, "endMinute": 720},
            ]
        },
    )
    assert replaced.status_code == 200
    assert replaced.headers["cache-control"] == "private, no-store"
    assert replaced.json() == [
        {"isoWeekday": 1, "startMinute": 600, "endMinute": 720},
        {"isoWeekday": 3, "startMinute": 600, "endMinute": 720},
    ]
    assert client.get("/api/tutor/profile").json()["availability"] == replaced.json()
    # Availability is not moderated: the listing stays up.
    assert client.get("/api/tutor/profile").json()["listingState"] == "listed"


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [Role.student, Role.parent, Role.school_admin, Role.platform_admin]
)
def test_tutor_routes_refuse_other_roles_403(
    client: TestClient, sm: sessionmaker[Session], role: Role
) -> None:
    act_as(client, add_user(sm, role), role)
    for method, path, json_body in [*_NEEDS_PROFILE, ("POST", "/api/tutor/profile", {})]:
        response = client.request(method, path, json=json_body)
        assert response.status_code == 403, (role, path)
        assert response.headers["cache-control"] == "private, no-store"


def test_tutor_routes_unauthenticated_401(client: TestClient) -> None:
    anonymous(client)
    for method, path, json_body in [*_NEEDS_PROFILE, ("POST", "/api/tutor/profile", {})]:
        response = client.request(method, path, json=json_body)
        assert response.status_code == 401, path
        assert response.headers["cache-control"] == "private, no-store"
