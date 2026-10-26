"""Object-level rules for reviews and moderation (SPEC §c.3 O10, O11 SP3, O21, O27, SC-12).

PLAN §1.4 #3: one ``tests/test_web_tutoring_authz_<area>.py`` file per task. Each
rule has a passing case and a case that must go red without its check (the
mutation proofs are recorded in the task's return).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from lemely.db.models.enums import Role
from lemely.web.routers import (
    admin_tutoring_moderation,
    student_reviews,
    tutor_reviews,
    tutoring_reviews,
)
from tests.test_tutor_review_repo import (
    add_booking,
    add_reply_row,
    add_review_row,
    add_student,
    review_row,
)
from tests.test_web_tutor_reviews import NO_STORE, Setup, review_client
from tests.tutoring_app import flatten_routes
from tests.tutoring_db import (
    act_as,
    add_block,
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.dependencies.models import Dependant
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

SPEC = Path(__file__).resolve().parent.parent / "docs" / "tutoring" / "SPEC.md"


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = review_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.fixture
def s(sm: sessionmaker[Session]) -> Setup:
    return Setup(sm)


# ---------------------------------------------------------------------------
# The route set and its guards, read from SPEC §c.1 (not restated here)
# ---------------------------------------------------------------------------

_SPEC_GUARDS = {
    "STUDENT": frozenset({"student"}),
    "STUDENT_OR_PARENT": frozenset({"student", "parent"}),
    "TEACHER": frozenset({"teacher"}),
    "PLATFORM_ADMIN": frozenset({"platform_admin"}),
}
_SPEC_ROW = re.compile(r'^\s*\("(GET|POST|PATCH|PUT|DELETE)", "([^"]+)"\): ([A-Z_]+),\s*$')


def _spec_review_routes() -> dict[tuple[str, str], frozenset[str]]:
    rows: dict[tuple[str, str], frozenset[str]] = {}
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        match = _SPEC_ROW.match(line)
        if match is None:
            continue
        method, path, guard = match.groups()
        if re.search(r"/reviews|/review$|moderat", path):
            rows[(method, path)] = _SPEC_GUARDS[guard]
    return rows


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


def _wired_roles(route: APIRoute) -> frozenset[str] | None:
    roles: set[str] | None = None
    for dependant in _walk(route.dependant):
        call = dependant.call
        if call is None or getattr(call, "__name__", "") != "_guard" or not call.__closure__:
            continue
        cells = dict(zip(call.__code__.co_freevars, call.__closure__, strict=True))
        allowed = set(cells["allowed_values"].cell_contents)
        roles = allowed if roles is None else roles & allowed
    return None if roles is None else frozenset(roles)


def test_the_four_routers_serve_exactly_the_spec_routes_with_the_spec_guards() -> None:
    expected = _spec_review_routes()
    assert len(expected) == 8  # SP3, S6, S7, T18, T21, A6, A7, A8
    served: dict[tuple[str, str], frozenset[str] | None] = {}
    for module in (
        tutoring_reviews,
        student_reviews,
        tutor_reviews,
        admin_tutoring_moderation,
    ):
        for route in flatten_routes(module.router):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                served[(method, route.path)] = _wired_roles(route)
    assert served == expected


# ---------------------------------------------------------------------------
# O11 for SP3: listed and not paused, blocked pairs get nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.student, Role.parent])
def test_sp3_404_for_unlisted_paused_or_blocked_tutor(
    client: TestClient, sm: sessionmaker[Session], role: Role
) -> None:
    subject = add_subject(sm)
    viewer = add_user(sm, role)
    act_as(client, viewer, role)

    def with_a_review(**kwargs: object) -> uuid.UUID:
        tutor = add_tutor(sm, subjects=(subject,), **kwargs)  # type: ignore[arg-type]
        student = add_student(sm)
        add_review_row(
            sm,
            booking=add_booking(sm, student=student, tutor=tutor, subject=subject),
            tutor_id=tutor.profile_id,
            student=student,
        )
        return tutor.profile_id

    listed = with_a_review()
    ok = client.get(f"/api/tutors/{listed}/reviews")
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == NO_STORE
    assert len(ok.json()["items"]) == 1

    unknown = client.get(f"/api/tutors/{uuid.uuid4()}/reviews")
    assert unknown.status_code == 404
    hidden = [with_a_review(paused=True)] + [
        with_a_review(state=state)
        for state in ("draft", "pending_review", "rejected", "suspended", "closed")
    ]
    for tutor_id in hidden:
        response = client.get(f"/api/tutors/{tutor_id}/reviews")
        assert response.status_code == 404, tutor_id
        assert response.content == unknown.content
        assert response.headers["cache-control"] == NO_STORE


@pytest.mark.parametrize("direction", ["student_blocks_tutor", "tutor_blocks_student"])
def test_sp3_blocked_pair_gets_404_but_a_parent_holds_no_blocks(
    client: TestClient, sm: sessionmaker[Session], direction: str
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(sm, subjects=(subject,))
    author = add_student(sm)
    add_review_row(
        sm,
        booking=add_booking(sm, student=author, tutor=tutor, subject=subject),
        tutor_id=tutor.profile_id,
        student=author,
    )
    student = add_user(sm, Role.student)
    parent = add_user(sm, Role.parent)
    if direction == "student_blocks_tutor":
        add_block(sm, student, tutor.user_id)
    else:
        add_block(sm, tutor.user_id, student)
    url = f"/api/tutors/{tutor.profile_id}/reviews"

    act_as(client, student, Role.student)
    blocked = client.get(url)
    assert blocked.status_code == 404
    assert blocked.content == client.get(f"/api/tutors/{uuid.uuid4()}/reviews").content

    act_as(client, parent, Role.parent)
    assert client.get(url).status_code == 200


# ---------------------------------------------------------------------------
# O10: only the booking's student, parents refused by the guard
# ---------------------------------------------------------------------------


def test_o10_only_the_bookings_student_may_review(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    booking = s.booking()
    stranger = add_student(sm)
    act_as(client, stranger, Role.student)
    refused = client.post(f"/api/student/bookings/{booking}/review", json={"stars": 1})
    assert refused.status_code == 404
    assert refused.json()["detail"]["code"] == "not_found"
    with sm() as session:
        assert session.execute(sa.text("SELECT count(*) FROM tutor_reviews")).scalar_one() == 0
        assert (
            session.execute(
                sa.text("SELECT rating_count FROM tutor_profiles WHERE id = :t"),
                {"t": s.tutor.profile_id},
            ).scalar_one()
            == 0
        )

    act_as(client, s.student, Role.student)
    assert (
        client.post(f"/api/student/bookings/{booking}/review", json={"stars": 1}).status_code == 201
    )


@pytest.mark.parametrize(
    "role", [Role.parent, Role.teacher, Role.school_admin, Role.platform_admin]
)
def test_o10_parents_and_every_other_role_are_refused_by_the_guard(
    client: TestClient, sm: sessionmaker[Session], s: Setup, role: Role
) -> None:
    review = s.seeded_review(stars=4)
    act_as(client, add_user(sm, role), role)
    post = client.post(f"/api/student/bookings/{s.booking()}/review", json={"stars": 5})
    patch = client.patch(f"/api/student/reviews/{review}", json={"stars": 1})
    assert (post.status_code, patch.status_code) == (403, 403)
    assert review_row(sm, review).stars == 4
    with sm() as session:
        assert session.execute(sa.text("SELECT count(*) FROM tutor_reviews")).scalar_one() == 1


def test_o10_one_review_per_booking_is_a_database_rule_too(
    sm: sessionmaker[Session], s: Setup
) -> None:
    booking = s.booking()
    add_review_row(sm, booking=booking, tutor_id=s.tutor.profile_id, student=s.student)
    with pytest.raises(IntegrityError, match="uq_tutor_reviews_booking_id"):
        add_review_row(sm, booking=booking, tutor_id=s.tutor.profile_id, student=s.student)


# ---------------------------------------------------------------------------
# IDOR on S7, T18 and the moderation ids
# ---------------------------------------------------------------------------


def test_idor_s7_cannot_edit_another_students_review(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    review = add_review_row(
        sm,
        booking=s.booking(),
        tutor_id=s.tutor.profile_id,
        student=s.student,
        stars=4,
        text="Mine.",
        text_state="approved",
    )
    act_as(client, add_student(sm), Role.student)
    refused = client.patch(f"/api/student/reviews/{review}", json={"stars": 1, "text": "Hijacked"})
    unknown = client.patch(f"/api/student/reviews/{uuid.uuid4()}", json={"stars": 1})
    assert refused.status_code == 404
    assert refused.json() == unknown.json()
    row = review_row(sm, review)
    assert (row.stars, row.body, row.text_state) == (4, "Mine.", "approved")

    act_as(client, s.student, Role.student)  # positive control: the author can
    assert client.patch(f"/api/student/reviews/{review}", json={"stars": 2}).status_code == 200
    assert review_row(sm, review).stars == 2


def test_idor_t18_cannot_reply_to_another_tutors_review(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    review = s.seeded_review()
    rival = add_tutor(sm, subjects=(s.subject,))
    act_as(client, rival.user_id, Role.teacher)
    refused = client.post(f"/api/tutor/reviews/{review}/reply", json={"body": "Mine now"})
    unknown = client.post(f"/api/tutor/reviews/{uuid.uuid4()}/reply", json={"body": "Mine now"})
    assert refused.status_code == 404
    assert refused.json() == unknown.json()
    with sm() as session:
        assert (
            session.execute(sa.text("SELECT count(*) FROM tutor_review_replies")).scalar_one() == 0
        )
    act_as(client, s.tutor.user_id, Role.teacher)
    assert (
        client.post(f"/api/tutor/reviews/{review}/reply", json={"body": "Thank you"}).status_code
        == 201
    )


def test_o1_tutor_review_routes_take_no_tutor_id() -> None:
    routes = flatten_routes(tutor_reviews.router)
    assert {(m, r.path) for r in routes for m in r.methods} == {
        ("GET", "/api/tutor/reviews"),
        ("POST", "/api/tutor/reviews/{review_id}/reply"),
    }
    for route in routes:
        assert "tutor_id" not in route.path
        assert not [p for p in route.dependant.query_params if "tutor" in p.name.lower()], (
            route.path
        )


def test_a7_a8_ids_are_not_interchangeable(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    review = s.seeded_review(text="text", text_state="pending")
    reply = add_reply_row(sm, review=review, tutor_id=s.tutor.profile_id)
    act_as(client, s.admin, Role.platform_admin)
    assert (
        client.post(
            f"/api/admin/tutoring/replies/{review}/moderate", json={"decision": "approved"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/admin/tutoring/reviews/{reply}/moderate", json={"decision": "approved"}
        ).status_code
        == 404
    )
    assert review_row(sm, review).text_state == "pending"
    # Positive controls: each id works on its own path.
    assert (
        client.post(
            f"/api/admin/tutoring/reviews/{review}/moderate", json={"decision": "approved"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/admin/tutoring/replies/{reply}/moderate", json={"decision": "approved"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("role", [Role.student, Role.parent, Role.teacher, Role.school_admin])
def test_moderation_is_platform_admin_only(
    client: TestClient, sm: sessionmaker[Session], s: Setup, role: Role
) -> None:
    review = s.seeded_review(text="text", text_state="pending")
    reply = add_reply_row(sm, review=review, tutor_id=s.tutor.profile_id)
    act_as(client, add_user(sm, role), role)
    responses = [
        client.get("/api/admin/tutoring/moderation"),
        client.post(
            f"/api/admin/tutoring/reviews/{review}/moderate", json={"decision": "approved"}
        ),
        client.post(f"/api/admin/tutoring/replies/{reply}/moderate", json={"decision": "approved"}),
    ]
    assert [r.status_code for r in responses] == [403, 403, 403]
    assert review_row(sm, review).text_state == "pending"


# ---------------------------------------------------------------------------
# O27: T21 returns only the caller's reviews
# ---------------------------------------------------------------------------


def test_o27_t21_returns_only_reviews_of_the_callers_profile(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    mine = [
        s.seeded_review(stars=5),
        s.seeded_review(stars=4, text="mine, approved", text_state="approved"),
    ]
    other_subject = add_subject(sm)
    rival = add_tutor(sm, subjects=(other_subject,))
    other_student = add_student(sm)
    theirs = add_review_row(
        sm,
        booking=add_booking(sm, student=other_student, tutor=rival, subject=other_subject),
        tutor_id=rival.profile_id,
        student=other_student,
        stars=1,
        text="theirs, approved",
        text_state="approved",
    )

    act_as(client, s.tutor.user_id, Role.teacher)
    page = client.get("/api/tutor/reviews").json()
    assert {item["reviewId"] for item in page["items"]} == {str(x) for x in mine}
    assert str(theirs) not in str(page)
    assert "theirs" not in str(page)

    act_as(client, rival.user_id, Role.teacher)
    assert [item["reviewId"] for item in client.get("/api/tutor/reviews").json()["items"]] == [
        str(theirs)
    ]


# ---------------------------------------------------------------------------
# O21: a cursor is bound to its list
# ---------------------------------------------------------------------------


def test_o21_cursors_are_not_interchangeable_between_lists(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    now = datetime.now(UTC)
    for days in (1, 2, 3):
        s.seeded_review(
            text=f"text {days}", text_state="pending", created_at=now - timedelta(days=days)
        )
    public_url = f"/api/tutors/{s.tutor.profile_id}/reviews"

    act_as(client, s.viewer, Role.student)
    public_cursor = client.get(public_url, params={"limit": 1}).json()["nextCursor"]
    assert public_cursor is not None

    act_as(client, s.tutor.user_id, Role.teacher)
    own_cursor = client.get("/api/tutor/reviews", params={"limit": 1}).json()["nextCursor"]
    assert own_cursor is not None
    assert client.get("/api/tutor/reviews", params={"cursor": own_cursor}).status_code == 200
    assert client.get("/api/tutor/reviews", params={"cursor": public_cursor}).status_code == 422

    act_as(client, s.admin, Role.platform_admin)
    queue_cursor = client.get("/api/admin/tutoring/moderation", params={"limit": 1}).json()[
        "nextCursor"
    ]
    assert queue_cursor is not None
    assert (
        client.get("/api/admin/tutoring/moderation", params={"cursor": public_cursor}).status_code
        == 422
    )

    act_as(client, s.viewer, Role.student)
    assert client.get(public_url, params={"cursor": public_cursor}).status_code == 200
    for foreign in (own_cursor, queue_cursor):
        refused = client.get(public_url, params={"cursor": foreign})
        assert refused.status_code == 422, foreign
        assert refused.headers["cache-control"] == NO_STORE


# ---------------------------------------------------------------------------
# SC-12: nothing that identifies the reviewer
# ---------------------------------------------------------------------------


def test_sc12_public_and_tutor_views_carry_no_reviewer_or_booking_reference(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    review = s.seeded_review(stars=5, text="Great.", text_state="approved")
    with sm() as session:
        student_id, booking_id = (
            str(value)
            for value in session.execute(
                sa.text("SELECT student_id, booking_id FROM tutor_reviews WHERE id = :r"),
                {"r": review},
            ).one()
        )
    act_as(client, s.viewer, Role.student)
    public = client.get(f"/api/tutors/{s.tutor.profile_id}/reviews")
    act_as(client, s.tutor.user_id, Role.teacher)
    own = client.get("/api/tutor/reviews")
    act_as(client, s.admin, Role.platform_admin)
    admin = client.post(
        f"/api/admin/tutoring/reviews/{review}/moderate", json={"decision": "approved"}
    )
    for response in (public, own):
        assert response.status_code == 200
        assert student_id not in response.text
        assert booking_id not in response.text
    assert student_id not in admin.text
    assert booking_id not in admin.text
