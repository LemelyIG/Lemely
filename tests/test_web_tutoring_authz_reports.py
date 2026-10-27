"""Object-level rules on R1 (PLAN T25; SPEC §c.3 O12, O19; THREAT-MODEL SC-10, SC-11, SC-15).

O12: the reporter must see the target. Booking and note: a party (the student, the tutor, a
linked parent of the student). Tutor profile: any party to any booking with that tutor in any
listing state, or any student or parent while it is listed. Review and reply: any student or
parent while the tutor is listed; the tutor for reviews of themself. O19: visibility is
resolved on the server from the target's own parent rows (note -> booking -> participants,
reply -> review -> tutor, review -> booking); nothing the client sends but the target id is
trusted. Every refusal is the same 404 (no existence oracle).

SC-10: a ``safety_concern`` on a booking or a note freezes posting until the report is
resolved. SC-15: R1 is a safety path, so it is open to unverified accounts. SC-11: a block
keeps the thread reportable by both sides and linked parents, and R1's answer never says
anything about a block.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models import ParentChildLink
from lemely.db.models.enums import Role
from tests.test_booking_repo import add_booking, add_parent, add_student, make_world, set_listing
from tests.test_tutor_review_repo import add_reply_row, add_review_row
from tests.test_tutoring_reports_repo import report_count, reports_client
from tests.test_tutoring_sweeps import add_note, block
from tests.tutoring_db import act_as, add_tutor, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

R1 = "/api/tutoring/reports"


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = reports_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def report(
    client: TestClient,
    user: uuid.UUID,
    role: Role,
    target_type: str,
    target_id: uuid.UUID,
    reason: str = "harassment",
) -> int:
    act_as(client, user, role)
    response = client.post(
        R1, json={"targetType": target_type, "targetId": str(target_id), "reason": reason}
    )
    if response.status_code == 404:
        assert response.json() == NOT_FOUND, response.text
    return response.status_code


NOT_FOUND = {"detail": {"code": "not_found", "message": "We could not find that."}}


# ---------------------------------------------------------------------------
# Booking and note targets
# ---------------------------------------------------------------------------


def test_idor_report_note_visibility_resolved_from_note_booking(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """O19: a note is visible through its own booking's participants, whoever asks.

    The red case: a student, a tutor and a parent who hold a booking of their own with the same
    tutor or student, and a note id from someone else's booking, are all refused.
    """
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = add_note(sm, booking, w.tutor.user_id, "tutor", "Meet me after class")

    # Strangers who each have a booking of their own: with the same tutor, with the same student.
    other_student = add_student(sm)
    add_booking(sm, w, student=other_student, state="accepted", starts_in=timedelta(days=4))
    other_parent = add_parent(sm, other_student)
    other_tutor = add_tutor(sm, subjects=(w.subject,))
    add_booking(sm, w, tutor=other_tutor, state="completed", starts_in=-timedelta(days=3))

    refused = {
        "other student": (other_student, Role.student),
        "other student's parent": (other_parent, Role.parent),
        "other tutor of the same student": (other_tutor.user_id, Role.teacher),
    }
    for name, (user, role) in refused.items():
        assert report(client, user, role, "booking_note", note) == 404, name
    assert report_count(sm) == 0

    allowed = {
        "the booking's student": (w.student, Role.student),
        "the booking's tutor": (w.tutor.user_id, Role.teacher),
        "the student's linked parent": (parent, Role.parent),
    }
    for name, (user, role) in allowed.items():
        assert report(client, user, role, "booking_note", note) == 201, name
    with sm() as session:
        stored = session.execute(
            sa.text("SELECT DISTINCT note_id, booking_id FROM tutoring_reports")
        ).all()
    assert stored == [(note, None)]  # the note itself is the target, never a client booking id


@pytest.mark.parametrize(
    ("who", "status"),
    [
        ("student", 201),
        ("tutor", 201),
        ("parent", 201),
        ("other_student", 404),
        ("other_tutor", 404),
        ("unlinked_parent", 404),
    ],
)
def test_idor_report_booking_needs_a_party(
    sm: sessionmaker[Session], client: TestClient, who: str, status: int
) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="declined")
    callers = {
        "student": (w.student, Role.student),
        "tutor": (w.tutor.user_id, Role.teacher),
        "parent": (parent, Role.parent),
        "other_student": (add_student(sm), Role.student),
        "other_tutor": (add_tutor(sm).user_id, Role.teacher),
        "unlinked_parent": (add_user(sm, Role.parent), Role.parent),
    }
    user, role = callers[who]
    assert report(client, user, role, "booking", booking) == status


def test_authz_report_on_a_blocked_pair_stays_open_and_says_nothing(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """SC-11: after a block, either way, both sides and the parent can still report the session
    and its notes, and the receipt is the same as without a block."""
    for by in ("student", "tutor"):
        w = make_world(sm)
        parent = add_parent(sm, w.student)
        booking = add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
        note = add_note(sm, booking, w.student, "student", "Thanks")
        block(sm, w.tutor, w.student, by=by)

        for user, role in (
            (w.student, Role.student),
            (w.tutor.user_id, Role.teacher),
            (parent, Role.parent),
        ):
            act_as(client, user, role)
            for target_type, target in (("booking", booking), ("booking_note", note)):
                response = client.post(
                    R1,
                    json={"targetType": target_type, "targetId": str(target), "reason": "other"},
                )
                assert response.status_code == 201, (by, role, target_type, response.text)
                assert set(response.json()) == {"reportId", "createdAt"}


# ---------------------------------------------------------------------------
# Tutor profile targets
# ---------------------------------------------------------------------------


def test_authz_report_tutor_profile_allowed_for_participant_when_paused(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """SC-10: pausing does not dodge a report. A party to any booking with the tutor reports the
    profile in any listing state; anyone else only while it is listed and not paused."""
    w = make_world(sm, paused=True)
    parent = add_parent(sm, w.student)
    add_booking(sm, w, state="cancelled")
    stranger = add_student(sm)
    stranger_parent = add_parent(sm, stranger)

    assert report(client, stranger, Role.student, "tutor_profile", w.tutor.profile_id) == 404
    assert report(client, stranger_parent, Role.parent, "tutor_profile", w.tutor.profile_id) == 404
    assert report(client, w.student, Role.student, "tutor_profile", w.tutor.profile_id) == 201
    assert report(client, parent, Role.parent, "tutor_profile", w.tutor.profile_id) == 201

    for state in ("pending_review", "rejected", "suspended", "closed"):
        set_listing(sm, w.tutor, state)
        with sm.begin() as session:
            session.execute(sa.text("DELETE FROM tutoring_reports"))
        assert report(client, w.student, Role.student, "tutor_profile", w.tutor.profile_id) == 201
        assert report(client, stranger, Role.student, "tutor_profile", w.tutor.profile_id) == 404, (
            state
        )


def test_authz_report_tutor_profile_listed_open_to_students_and_parents_only(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    stranger = add_student(sm)
    assert report(client, stranger, Role.student, "tutor_profile", w.tutor.profile_id) == 201
    assert (
        report(client, add_user(sm, Role.parent), Role.parent, "tutor_profile", w.tutor.profile_id)
        == 201
    )
    # A teacher, the tutor included, never reports a tutor profile (not a student or parent,
    # and a tutor cannot report themself).
    assert report(client, w.tutor.user_id, Role.teacher, "tutor_profile", w.tutor.profile_id) == 404
    other = add_tutor(sm)
    assert report(client, other.user_id, Role.teacher, "tutor_profile", w.tutor.profile_id) == 404
    assert report(client, stranger, Role.student, "tutor_profile", uuid.uuid4()) == 404


# ---------------------------------------------------------------------------
# Review and reply targets
# ---------------------------------------------------------------------------


def test_idor_report_reply_requires_visible_review(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """O19: a reply is visible only through its own review: an approved reply on a live review of
    a listed, unpaused tutor. Knowing the reply's id is not enough."""
    w = make_world(sm)
    reader = add_student(sm)
    booking = add_booking(sm, w, state="completed", starts_in=-timedelta(days=9))
    review = add_review_row(sm, booking=booking, tutor_id=w.tutor.profile_id, student=w.student)
    reply = add_reply_row(sm, review=review, tutor_id=w.tutor.profile_id, state="approved")
    assert report(client, reader, Role.student, "review_reply", reply) == 201

    # The same approved reply under a review an admin removed: refused.
    second = add_booking(sm, w, state="completed", starts_in=-timedelta(days=12))
    removed = add_review_row(
        sm, booking=second, tutor_id=w.tutor.profile_id, student=w.student, removed=True
    )
    hidden_reply = add_reply_row(sm, review=removed, tutor_id=w.tutor.profile_id, state="approved")
    assert report(client, reader, Role.student, "review_reply", hidden_reply) == 404

    # A reply not yet published, or rejected: refused (SP3 never shows it).
    third = add_booking(sm, w, state="completed", starts_in=-timedelta(days=15))
    live = add_review_row(sm, booking=third, tutor_id=w.tutor.profile_id, student=w.student)
    pending = add_reply_row(sm, review=live, tutor_id=w.tutor.profile_id, state="pending")
    assert report(client, reader, Role.student, "review_reply", pending) == 404

    # The tutor of the review is not paused or unlisted yet; once paused, the reply is hidden.
    other_reader = add_parent(sm)
    assert report(client, other_reader, Role.parent, "review_reply", reply) == 201
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE tutor_profiles SET paused_at = now() WHERE id = :t"),
            {"t": w.tutor.profile_id},
        )
    assert report(client, add_student(sm), Role.student, "review_reply", reply) == 404
    # A tutor never reports a reply (their own words).
    assert report(client, w.tutor.user_id, Role.teacher, "review_reply", reply) == 404


def test_idor_report_review_visibility(sm: sessionmaker[Session], client: TestClient) -> None:
    """Review: students and parents while the tutor is listed (as SP3 shows it: a student in an
    active block with the tutor does not see it); the tutor for reviews of themself, in any
    listing state; never a removed review."""
    w = make_world(sm)
    booking = add_booking(sm, w, state="completed", starts_in=-timedelta(days=9))
    review = add_review_row(sm, booking=booking, tutor_id=w.tutor.profile_id, student=w.student)
    other_tutor = add_tutor(sm)
    blocked_student = add_student(sm)
    add_booking(sm, w, student=blocked_student, state="completed", starts_in=-timedelta(days=4))
    block(sm, w.tutor, blocked_student, by="tutor")

    assert report(client, add_student(sm), Role.student, "review", review) == 201
    assert report(client, add_user(sm, Role.parent), Role.parent, "review", review) == 201
    assert report(client, blocked_student, Role.student, "review", review) == 404
    assert report(client, other_tutor.user_id, Role.teacher, "review", review) == 404
    set_listing(sm, w.tutor, "suspended")
    assert report(client, add_student(sm), Role.student, "review", review) == 404
    assert report(client, w.tutor.user_id, Role.teacher, "review", review) == 201

    second = add_booking(sm, w, state="completed", starts_in=-timedelta(days=12))
    removed = add_review_row(
        sm, booking=second, tutor_id=w.tutor.profile_id, student=w.student, removed=True
    )
    assert report(client, w.tutor.user_id, Role.teacher, "review", removed) == 404


# ---------------------------------------------------------------------------
# SC-10 freeze, SC-15 no verified-email gate
# ---------------------------------------------------------------------------


def test_authz_safety_report_freezes_thread_until_resolved(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    admin = add_user(sm, Role.platform_admin)
    student_notes = f"/api/student/bookings/{booking}/notes"
    tutor_notes = f"/api/tutor/bookings/{booking}/notes"

    act_as(client, w.student, Role.student)
    filed = client.post(
        R1, json={"targetType": "booking", "targetId": str(booking), "reason": "safety_concern"}
    )
    assert filed.status_code == 201, filed.text

    act_as(client, w.student, Role.student)
    assert client.get(student_notes).json()["canPost"] is False
    assert client.get(f"/api/student/bookings/{booking}").json()["notesFrozen"] is True
    posted = client.post(student_notes, json={"body": "Are you there?"})
    assert posted.status_code == 409
    assert posted.json()["detail"]["code"] == "notes_closed"
    act_as(client, w.tutor.user_id, Role.teacher)
    assert client.get(tutor_notes).json()["canPost"] is False
    assert client.post(tutor_notes, json={"body": "Hello?"}).status_code == 409

    act_as(client, admin, Role.platform_admin)
    resolved = client.post(
        f"/api/admin/tutoring/reports/{filed.json()['reportId']}/resolve",
        json={"resolution": "dismissed"},
    )
    assert resolved.status_code == 200, resolved.text

    act_as(client, w.student, Role.student)
    assert client.get(student_notes).json()["canPost"] is True
    assert client.post(student_notes, json={"body": "See you then"}).status_code == 201
    act_as(client, w.tutor.user_id, Role.teacher)
    assert client.get(f"/api/tutor/bookings/{booking}").json()["notesFrozen"] is False
    assert client.post(tutor_notes, json={"body": "Yes"}).status_code == 201


def test_authz_report_allowed_without_verified_email(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """SC-15 exception: a report is a safety path. Every party may file one unverified."""
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE users SET email_verified_at = NULL WHERE id = ANY(CAST(:u AS uuid[]))"),
            {"u": [w.student, w.tutor.user_id]},
        )
    parent = add_user(sm, Role.parent, verified=False)
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=w.student))

    assert report(client, w.student, Role.student, "booking", booking, "safety_concern") == 201
    assert report(client, w.tutor.user_id, Role.teacher, "booking", booking) == 201
    assert report(client, parent, Role.parent, "booking", booking) == 201
    assert report_count(sm) == 3
