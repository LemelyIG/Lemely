"""B1-B3 at the route (PLAN T21; SPEC §b.2 "Safety", §a.2, §a.4b, §i.8; O13, O28, SC-11, SC-19).

Route-level, through ``tests.test_tutoring_sweeps.safety_client`` (a lane never edits
``lemely/web/app.py``), on a throwaway ``create_all`` database.

* **IDOR (SC-19, O13, O28).** A student names a tutor by profile id, never by ``users.id``; a
  tutor names a student by id and may block only a student who booked or granted them. B3
  resolves the id by the caller's role and only within the caller's own rows.
* **No oracle (SC-11).** Every B2/B3/B1 answer is the same whether or not the other side had
  already blocked the caller.
* **SPEC §i.8 pin.** B2 twice, before and after the note window closes: the tutor's
  ``notesFrozen`` stays true, because the second request writes nothing.
* **Notices after commit (SPEC §b.4, §i.8 (c)).** A tutor's block tells the student "can no
  longer see your progress", word for word the notice a suspension sends; a student's block
  tells the tutor only that access ended. A failing inbox never undoes the block (D5.9 §1).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
import structlog.testing

from lemely.core.tutor_directory import student_label
from lemely.db.models.enums import Role
from lemely.web.tutoring_http import iso_instant, tutor_not_found
from tests.test_booking_repo import (
    add_booking,
    add_parent,
    add_student,
    make_world,
    set_listing,
)
from tests.test_tutor_grant_repo import add_grant
from tests.test_tutoring_sweeps import (
    SIDES,
    Side,
    block,
    block_count,
    block_row,
    grant_state,
    pair,
    safety_client,
)
from tests.tutoring_db import act_as, add_tutor, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from tests.test_booking_repo import World

B = "/api/tutoring/blocks"
NO_STORE = "private, no-store"
TUTOR_NOT_FOUND = {"detail": tutor_not_found().detail}


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = safety_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def related_world(sm: sessionmaker[Session]) -> World:
    """A listed tutor and a student with a past session (so either side may block, O13)."""
    w = make_world(sm)
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=12))
    return w


def as_side(client: TestClient, w: World, by: Side) -> dict[str, str]:
    """Act as ``by`` and return the B2 body that names the other side."""
    if by == "student":
        act_as(client, w.student, Role.student)
        return {"tutorId": str(w.tutor.profile_id)}
    act_as(client, w.tutor.user_id, Role.teacher)
    return {"studentId": str(w.student)}


def counterpart_of(w: World, by: Side) -> uuid.UUID:
    return w.tutor.profile_id if by == "student" else w.student


def inbox(sm: sessionmaker[Session], user: uuid.UUID) -> list[tuple[str, str, str | None, str]]:
    """``(type, title, body, dedupe_key)`` of the user's inbox rows, oldest first."""
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT type::text, title, body, dedupe_key FROM notifications "
                "WHERE user_id = :u ORDER BY created_at, id"
            ),
            {"u": user},
        ).all()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


# ---------------------------------------------------------------------------
# IDOR and object rules (SC-19, O13, O28)
# ---------------------------------------------------------------------------


def test_idor_b2_student_blocks_by_tutor_id(sm: sessionmaker[Session], client: TestClient) -> None:
    """SC-19: the student names the tutor by profile id; the row is keyed on the tutor's
    ``users.id``; no response ever carries that ``users.id``."""
    w = make_world(sm)
    act_as(client, w.student, Role.student)

    by_user_id = client.post(B, json={"tutorId": str(w.tutor.user_id)})
    assert by_user_id.status_code == 404
    assert by_user_id.json() == TUTOR_NOT_FOUND
    assert block_count(sm) == 0

    made = client.post(B, json={"tutorId": str(w.tutor.profile_id)})
    assert made.status_code == 201, made.text
    assert made.json()["counterpartId"] == str(w.tutor.profile_id)
    assert made.json()["displayName"] == "Sara M."
    assert block_row(sm, w.student, w.tutor.user_id) is not None
    listed = client.get(B)
    assert [item["counterpartId"] for item in listed.json()["items"]] == [str(w.tutor.profile_id)]
    for response in (made, listed):
        assert str(w.tutor.user_id) not in response.text


def test_o13_b2_refuses_what_the_caller_may_not_block_with_one_404(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    draft_unknown = add_tutor(sm, state="draft")
    paused_unknown = add_tutor(sm, paused=True)
    listed_unknown = add_tutor(sm, first_name="Omar")
    act_as(client, w.student, Role.student)
    refusals = [
        client.post(B, json={"tutorId": str(target)})
        for target in (uuid.uuid4(), draft_unknown.profile_id, paused_unknown.profile_id)
    ]
    assert [r.status_code for r in refusals] == [404, 404, 404]
    assert {r.text for r in refusals} == {refusals[0].text}
    assert refusals[0].json() == TUTOR_NOT_FOUND
    assert client.post(B, json={"tutorId": str(listed_unknown.profile_id)}).status_code == 201

    stranger = add_student(sm)
    granted = add_student(sm)
    add_grant(sm, granted, w.tutor)
    teacher = add_user(sm, Role.teacher)
    act_as(client, w.tutor.user_id, Role.teacher)
    tutor_refusals = [
        client.post(B, json={"studentId": str(target)})
        for target in (stranger, teacher, uuid.uuid4())
    ]
    assert [r.status_code for r in tutor_refusals] == [404, 404, 404]
    assert {r.text for r in tutor_refusals} == {tutor_refusals[0].text}
    assert tutor_refusals[0].json()["detail"]["code"] == "not_found"
    assert client.post(B, json={"studentId": str(granted)}).status_code == 201
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
    assert client.post(B, json={"studentId": str(w.student)}).status_code == 201
    assert block_count(sm) == 3


def test_o28_b3_resolves_the_counterpart_by_role_within_own_rows(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = related_world(sm)
    other = add_tutor(sm, first_name="Lina")
    add_grant(sm, w.student, other)
    block(sm, w.tutor, w.student, by="student")
    block(sm, w.tutor, w.student, by="tutor")
    block(sm, other, w.student, by="tutor")

    act_as(client, w.student, Role.student)
    assert client.delete(f"{B}/{w.tutor.user_id}").status_code == 404  # a users.id
    assert client.delete(f"{B}/{other.profile_id}").status_code == 404  # the other tutor's row
    assert client.delete(f"{B}/{w.tutor.profile_id}").status_code == 204
    act_as(client, w.tutor.user_id, Role.teacher)
    assert client.delete(f"{B}/{w.tutor.profile_id}").status_code == 404  # not a student id
    assert client.delete(f"{B}/{uuid.uuid4()}").status_code == 404
    assert client.delete(f"{B}/{w.student}").status_code == 204

    def active(blocker: uuid.UUID, blocked: uuid.UUID) -> bool:
        row = block_row(sm, blocker, blocked)
        return row is not None and row[2] is None

    assert not active(w.student, w.tutor.user_id)
    assert not active(w.tutor.user_id, w.student)
    assert active(other.user_id, w.student)


@pytest.mark.parametrize(
    ("role", "body"),
    [
        ("student", {"studentId": "STUDENT"}),
        ("student", {}),
        ("student", {"tutorId": "TUTOR", "studentId": "STUDENT"}),
        ("student", {"tutorId": "not-a-uuid"}),
        ("student", {"tutorId": None}),
        ("teacher", {"tutorId": "TUTOR"}),
        ("teacher", {}),
        ("teacher", {"tutorId": "TUTOR", "studentId": "STUDENT"}),
        ("teacher", {"studentId": "12345"}),
    ],
)
def test_b2_wrong_field_for_the_callers_role_is_422(
    sm: sessionmaker[Session], client: TestClient, role: str, body: dict[str, str | None]
) -> None:
    w = related_world(sm)
    names = {"STUDENT": str(w.student), "TUTOR": str(w.tutor.profile_id)}
    sent = {key: names.get(value, value) if value else value for key, value in body.items()}
    act_as(client, w.student if role == "student" else w.tutor.user_id, Role(role))

    response = client.post(B, json=sent)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_counterpart"
    assert response.headers["Cache-Control"] == NO_STORE
    assert block_count(sm) == 0


def test_b2_unknown_body_field_is_422(sm: sessionmaker[Session], client: TestClient) -> None:
    w = make_world(sm)
    act_as(client, w.student, Role.student)
    response = client.post(B, json={"tutorId": str(w.tutor.profile_id), "blockerId": "x"})
    assert response.status_code == 422
    assert block_count(sm) == 0


# ---------------------------------------------------------------------------
# B1, B2, B3 behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("by", SIDES)
def test_b2_creates_then_answers_200_untouched_and_b1_lists_it(
    sm: sessionmaker[Session], client: TestClient, by: Side
) -> None:
    w = related_world(sm)
    body = as_side(client, w, by)

    first = client.post(B, json=body)
    row = block_row(sm, *pair(w.tutor, w.student, by=by))
    second = client.post(B, json=body)
    listed = client.get(B)

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert block_row(sm, *pair(w.tutor, w.student, by=by)) == row
    expected_name = "Sara M." if by == "student" else student_label(None, w.student)
    assert first.json()["displayName"] == expected_name
    assert first.json()["counterpartId"] == str(counterpart_of(w, by))
    assert listed.status_code == 200
    assert listed.json() == {"items": [first.json()]}
    assert row is not None
    assert first.json()["createdAt"] == iso_instant(row[1])  # the instant it became active


@pytest.mark.parametrize("by", SIDES)
def test_b3_lifts_restores_nothing_and_repeats_as_204(
    sm: sessionmaker[Session], client: TestClient, by: Side
) -> None:
    w = related_world(sm)
    grant = add_grant(sm, w.student, w.tutor)
    body = as_side(client, w, by)
    assert client.post(B, json=body).status_code == 201

    first = client.delete(f"{B}/{counterpart_of(w, by)}")
    lifted = block_row(sm, *pair(w.tutor, w.student, by=by))
    again = client.delete(f"{B}/{counterpart_of(w, by)}")

    assert (first.status_code, again.status_code) == (204, 204)
    assert first.content == b""
    assert block_row(sm, *pair(w.tutor, w.student, by=by)) == lifted  # the repeat wrote nothing
    assert client.get(B).json() == {"items": []}
    assert grant_state(sm, grant)[1] == "block"  # restores nothing (SPEC §b.2 B3)


@pytest.mark.parametrize("by", SIDES)
def test_b2_answers_the_same_whether_or_not_the_other_side_blocked_first(
    sm: sessionmaker[Session], client: TestClient, by: Side
) -> None:
    """SC-11, SPEC §i.8: nothing in B2, B1 or B3 tells the caller that they were blocked."""
    other: Side = "tutor" if by == "student" else "student"
    seen: dict[str, tuple[object, ...]] = {}
    for world in ("alone", "after_other"):
        w = related_world(sm)
        if world == "after_other":
            block(sm, w.tutor, w.student, by=other)
        body = as_side(client, w, by)
        first = client.post(B, json=body)
        second = client.post(B, json=body)
        listed = client.get(B).json()["items"]
        lifted = client.delete(f"{B}/{counterpart_of(w, by)}")
        expected_name = "Sara M." if by == "student" else student_label(None, w.student)
        made = first.json()
        seen[world] = (
            first.status_code,
            sorted(made),
            made.get("displayName") == expected_name,
            made.get("counterpartId") == str(counterpart_of(w, by)),
            second.status_code,
            second.json() == made,
            [item["counterpartId"] == str(counterpart_of(w, by)) for item in listed],
            lifted.status_code,
        )
    assert seen["alone"][0] == 201  # non-vacuity: a real block in both worlds
    assert seen["after_other"] == seen["alone"]


@pytest.mark.parametrize("by", SIDES)
def test_b2_twice_before_and_after_the_note_window_keeps_notes_frozen(
    sm: sessionmaker[Session], client: TestClient, by: Side
) -> None:
    """SPEC §i.8 pin: the second B2, after the note window has closed, writes nothing, so the
    block still began while the notes were open and the tutor still reads ``notesFrozen``."""
    w = make_world(sm)
    recent = add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
    tutor_view = f"/api/tutor/bookings/{recent}"
    act_as(client, w.tutor.user_id, Role.teacher)
    before = client.get(tutor_view).json()
    assert before["notesFrozen"] is False
    assert "post_note" in before["allowedActions"]  # the notes are open before the block

    body = as_side(client, w, by)
    assert client.post(B, json=body).status_code == 201
    act_as(client, w.tutor.user_id, Role.teacher)
    assert client.get(tutor_view).json()["notesFrozen"] is True

    # Nine days pass: the session and the block move back together, so the block began while
    # the notes were open and the notes window has now closed.
    shift = {"s": timedelta(days=9).total_seconds(), "b": recent}
    blocker, blocked = pair(w.tutor, w.student, by=by)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE tutor_bookings SET starts_at = starts_at - make_interval(secs => :s), "
                "ends_at = ends_at - make_interval(secs => :s), "
                "accepted_at = accepted_at - make_interval(secs => :s), "
                "completed_at = completed_at - make_interval(secs => :s) WHERE id = :b"
            ),
            shift,
        )
        session.execute(
            sa.text(
                "UPDATE tutoring_blocks SET created_at = created_at - make_interval(secs => :s), "
                "updated_at = updated_at - make_interval(secs => :s) "
                "WHERE blocker_user_id = :x AND blocked_user_id = :y"
            ),
            {**shift, "x": blocker, "y": blocked},
        )
    act_as(client, w.tutor.user_id, Role.teacher)
    assert client.get(tutor_view).json()["notesFrozen"] is True
    row = block_row(sm, blocker, blocked)

    as_side(client, w, by)
    second = client.post(B, json=body)
    act_as(client, w.tutor.user_id, Role.teacher)
    after = client.get(tutor_view).json()

    assert after["notesFrozen"] is True
    assert "post_note" not in after["allowedActions"]
    assert second.status_code == 200, second.text
    assert block_row(sm, blocker, blocked) == row


# ---------------------------------------------------------------------------
# Notices after commit (SPEC §b.4, §i.8 (c)), D5.9 §1
# ---------------------------------------------------------------------------


def test_tutor_block_tells_the_student_exactly_what_a_suspension_does(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """§i.8 (c): the student reads "can no longer see your progress" after a tutor's block,
    the same notice (type, title, body, payload shape) a suspension sends; the tutor, who
    acted, is told nothing."""
    blocked_world = related_world(sm)
    blocked_grant = add_grant(sm, blocked_world.student, blocked_world.tutor)
    suspended_world = related_world(sm)
    suspended_grant = add_grant(sm, suspended_world.student, suspended_world.tutor)

    act_as(client, blocked_world.tutor.user_id, Role.teacher)
    assert client.post(B, json={"studentId": str(blocked_world.student)}).status_code == 201
    admin = add_user(sm, Role.platform_admin)
    act_as(client, admin, Role.platform_admin)
    suspended = client.post(
        f"/api/admin/tutors/{suspended_world.tutor.profile_id}/suspend", json={"note": None}
    )
    assert suspended.status_code == 200, suspended.text

    after_block = inbox(sm, blocked_world.student)
    after_suspension = inbox(sm, suspended_world.student)
    assert after_block == [
        (
            "tutor_access",
            "Progress sharing ended",
            "Sara M. can no longer see your progress.",
            f"grant:{blocked_grant}:ended",
        )
    ]
    assert [row[:3] for row in after_suspension] == [row[:3] for row in after_block]
    assert after_suspension[0][3] == f"grant:{suspended_grant}:ended"
    assert inbox(sm, blocked_world.tutor.user_id) == []
    with sm() as session:
        payloads = [
            sorted(p)
            for (p,) in session.execute(
                sa.text(
                    "SELECT payload FROM notifications WHERE user_id IN (:a, :b) "
                    "AND type = 'tutor_access'"
                ),
                {"a": blocked_world.student, "b": suspended_world.student},
            ).all()
        ]
    assert payloads == [["grantId"], ["grantId"]]


def test_student_block_tells_the_tutor_only_that_access_ended(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    act_as(client, w.student, Role.student)

    assert client.post(B, json={"tutorId": str(w.tutor.profile_id)}).status_code == 201

    label = student_label(None, w.student)
    assert sorted(inbox(sm, w.tutor.user_id)) == sorted(
        [
            (
                "tutor_access",
                "Progress sharing ended",
                "Access to progress you could see has ended.",
                f"grant:{grant}:ended",
            ),
            (
                "booking_update",
                "Session cancelled",
                f"A session with {label} was cancelled.",
                f"booking:{upcoming}:cancelled",
            ),
        ]
    )
    assert inbox(sm, w.student) == []  # the student acted
    assert inbox(sm, parent) == [
        (
            "booking_update",
            "Session cancelled",
            "Your session with Sara M. was cancelled.",
            f"booking:{upcoming}:cancelled",
        )
    ]


class _RaisingInbox:
    """A ``NotificationService`` whose inbox write always fails."""

    def create(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("inbox is down")


def test_b2_commits_when_the_inbox_write_raises(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    add_parent(sm, w.student)
    grant = add_grant(sm, w.student, w.tutor)
    add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    client = safety_client(sm, notifications=_RaisingInbox())
    act_as(client, w.student, Role.student)

    with structlog.testing.capture_logs() as logs:
        response = client.post(B, json={"tutorId": str(w.tutor.profile_id)})

    assert response.status_code == 201, response.text
    assert block_row(sm, w.student, w.tutor.user_id) is not None
    assert grant_state(sm, grant)[1] == "block"
    failures = [entry for entry in logs if entry["event"] == "notification_create_failed"]
    assert len(failures) == 3  # tutor: grant + booking; parent: booking


# ---------------------------------------------------------------------------
# Cross-cutting: no-store (a), no_tutor_profile (f)
# ---------------------------------------------------------------------------


def test_block_routes_send_no_store_on_success(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    act_as(client, w.student, Role.student)
    body = {"tutorId": str(w.tutor.profile_id)}
    responses = [
        client.post(B, json=body),
        client.post(B, json=body),
        client.get(B),
        client.delete(f"{B}/{w.tutor.profile_id}"),
    ]
    assert [r.status_code for r in responses] == [201, 200, 200, 204]
    assert {r.headers["Cache-Control"] for r in responses} == {NO_STORE}


def test_b1_b2_b3_404_no_tutor_profile(sm: sessionmaker[Session], client: TestClient) -> None:
    """ADR-T01 action 3, PLAN constraint (f): a teacher without a tutor profile holds no blocks."""
    teacher = add_user(sm, Role.teacher)
    student = add_student(sm)
    act_as(client, teacher, Role.teacher)
    responses = [
        client.get(B),
        client.post(B, json={"studentId": str(student)}),
        client.delete(f"{B}/{student}"),
    ]
    assert [r.status_code for r in responses] == [404, 404, 404]
    assert {r.json()["detail"]["code"] for r in responses} == {"no_tutor_profile"}
    assert {r.headers["Cache-Control"] for r in responses} == {NO_STORE}


def test_a_suspended_tutors_profile_still_lists_and_lifts(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """Only B2 is a tutor write route (SPEC §a.4b); B1 and B3 stay open to a suspended tutor."""
    w = related_world(sm)
    block(sm, w.tutor, w.student, by="tutor")
    set_listing(sm, w.tutor, "suspended")
    act_as(client, w.tutor.user_id, Role.teacher)
    assert len(client.get(B).json()["items"]) == 1
    assert client.delete(f"{B}/{w.student}").status_code == 204
