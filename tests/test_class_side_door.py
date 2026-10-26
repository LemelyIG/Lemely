"""The roster side door (SPEC §c.4, decision row 14 = SC-2; XT-1, XT-2, CB-8, CB-10).

What each test pins:

* Joining a **school-less** class whose teacher holds a tutor profile, through either join
  route (``POST /api/student/classes/join`` and the class branch of
  ``POST /api/invites/{code}/redeem``, bare join code or minted class invite), writes a
  ``class_joined_tutor`` outbox row for each linked parent in the enrolment's transaction and
  sends each a ``tutor_access`` inbox notice after commit. A school class, a teacher without
  a tutor profile, and a re-join that enrols nobody new tell nobody.
* ``DELETE /api/student/classes/{class_id}`` (S17) removes only the caller's own enrolment,
  only in a school-less class; everything else is 404.
* ``ClassService.remove_school_less_enrolments_in_session`` (named students; an empty list
  removes nothing) and ``remove_all_school_less_enrolments_in_session`` (every student), used
  by the block, suspension and close sweeps, touch only that teacher's school-less classes.
* ``ClassService.join_by_code`` writes the same class-join outbox rows as the join routes,
  and the notice goes out whatever state the teacher's tutor profile is in.
* ``GET /api/student/tutor-access/classes`` (S16) lists exactly the caller's classes, with
  ``leavable`` and ``teacherIsYourTutor`` (a booking or a grant with the class teacher's
  tutor profile), and never an email address.
* S16 and S17 send ``Cache-Control: private, no-store``.

Symbols this task adds are imported inside the tests that need them, so the file collects,
and its behaviour tests fail on assertions, against the code before the change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteService
from lemely.db.models import (
    ClassEnrollment,
    Notification,
    ParentChildLink,
    School,
    SchoolMembership,
    User,
)
from lemely.db.models.enums import (
    BookingParty,
    MembershipRole,
    NotificationType,
    Role,
    TutoringMode,
)
from lemely.db.models.tutoring import EmailOutbox, TutorBooking, TutorDataGrant
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.web.app import create_app
from lemely.web.deps import (
    get_class_service,
    get_invite_service,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
)
from lemely.web.push import RecordingPushTransport
from tests.tutoring_db import (
    act_as,
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

S16 = "/api/student/tutor-access/classes"
NO_STORE = "private, no-store"


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(sm: sessionmaker[Session]) -> TestClient:
    links = ParentLinkService(sm)
    classes = ClassService(sm)
    invites = InviteService(sm, classes, links)
    notifications = NotificationService(sm, NotificationPreferencesService(sm))
    transport = RecordingPushTransport()
    app = create_app()
    app.dependency_overrides[get_parent_link_service] = lambda: links
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_invite_service] = lambda: invites
    app.dependency_overrides[get_notification_service] = lambda: notifications
    app.dependency_overrides[get_push_transport] = lambda: transport
    return TestClient(app)


def _tutor_teacher(
    sm: sessionmaker[Session],
    display_name: str | None = "Ms Sara",
    *,
    state: str = "listed",
    paused: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A teacher who holds a tutor profile: ``(user_id, profile_id)``."""
    tutor = add_tutor(sm, first_name="Sara", initial="M", state=state, paused=paused)
    with sm.begin() as session:
        user = session.get(User, tutor.user_id)
        assert user is not None
        user.display_name = display_name
    return tutor.user_id, tutor.profile_id


def _school_for(
    sm: sessionmaker[Session], teacher: uuid.UUID, name: str = "Nile School"
) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name=name, seat_quota=10))
        session.flush()
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=teacher, membership_role=MembershipRole.teacher
            )
        )
    return school_id


def _class(
    sm: sessionmaker[Session],
    teacher: uuid.UUID,
    *,
    school_id: uuid.UUID | None = None,
    name: str = "Maths 10",
) -> tuple[uuid.UUID, str]:
    row = ClassService(sm).create_class(teacher, name, school_id=school_id)
    assert row.join_code is not None
    return row.class_id, row.join_code


def _enrol(sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student))


def _student_with_parents(
    sm: sessionmaker[Session], count: int
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    student = add_user(sm, Role.student, display_name="Maya")
    parents = [add_user(sm, Role.parent) for _ in range(count)]
    with sm.begin() as session:
        for parent in parents:
            session.add(ParentChildLink(parent_id=parent, child_id=student))
    return student, parents


def _enrollment_id(
    sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID
) -> uuid.UUID | None:
    with sm() as session:
        return session.scalar(
            sa.select(ClassEnrollment.id).where(
                ClassEnrollment.class_id == class_id, ClassEnrollment.student_id == student
            )
        )


def _enrolled_classes(sm: sessionmaker[Session], student: uuid.UUID) -> set[uuid.UUID]:
    with sm() as session:
        return set(
            session.scalars(
                sa.select(ClassEnrollment.class_id).where(ClassEnrollment.student_id == student)
            )
        )


def _outbox(sm: sessionmaker[Session]) -> list[tuple[uuid.UUID, str, dict[str, object], str]]:
    with sm() as session:
        rows = session.execute(
            sa.select(
                EmailOutbox.recipient_user_id,
                EmailOutbox.template,
                EmailOutbox.context,
                EmailOutbox.dedupe_key,
            )
        ).all()
    return [(row[0], row[1], dict(row[2]), row[3]) for row in rows]


def _inbox(
    sm: sessionmaker[Session],
) -> list[tuple[uuid.UUID, NotificationType, str | None, dict[str, object]]]:
    with sm() as session:
        rows = session.execute(
            sa.select(
                Notification.user_id,
                Notification.type,
                Notification.dedupe_key,
                Notification.payload,
            )
        ).all()
    return [(row[0], row[1], row[2], dict(row[3])) for row in rows]


def _join(
    client: TestClient,
    sm: sessionmaker[Session],
    route: str,
    code: str,
    class_id: uuid.UUID,
    teacher: uuid.UUID,
) -> int:
    """Join through one of the three entry points; returns the status code."""
    if route == "student_join":
        return client.post("/api/student/classes/join", json={"joinCode": code}).status_code
    if route == "redeem_join_code":
        return client.post(f"/api/invites/{code}/redeem").status_code
    invite = InviteService(sm, ClassService(sm), ParentLinkService(sm)).mint_class_invite(
        teacher, Role.teacher, class_id
    )
    return client.post(f"/api/invites/{invite.code}/redeem").status_code


_JOIN_ROUTES = ("student_join", "redeem_join_code", "redeem_class_invite")


# ---------------------------------------------------------------------------
# Class-join notices (SC-2d)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", _JOIN_ROUTES)
def test_join_school_less_class_of_tutor_notifies_parents(
    sm: sessionmaker[Session], route: str
) -> None:
    teacher, _ = _tutor_teacher(sm)
    class_id, code = _class(sm, teacher)
    student, parents = _student_with_parents(sm, 2)
    client = _client(sm)
    act_as(client, student, Role.student)

    assert _join(client, sm, route, code, class_id, teacher) == 200

    enrollment = _enrollment_id(sm, class_id, student)
    assert enrollment is not None
    expected_context = {
        "tutor_first_name": "Sara",
        "tutor_last_initial": "M",
        "enrollment_id": str(enrollment),
        "child_id": str(student),
    }
    assert sorted(_outbox(sm), key=lambda row: str(row[0])) == sorted(
        (
            (parent, "class_joined_tutor", expected_context, f"class-join:{enrollment}:{parent}")
            for parent in parents
        ),
        key=lambda row: str(row[0]),
    )
    inbox = _inbox(sm)
    assert {row[0] for row in inbox} == set(parents)  # never the student or the tutor
    assert all(
        row[1:]
        == (
            NotificationType.tutor_access,
            f"class-join:{enrollment}",
            {"enrollmentId": str(enrollment), "studentId": str(student)},
        )
        for row in inbox
    )


@pytest.mark.parametrize("case", ["school_class_of_tutor", "school_less_class_of_non_tutor"])
@pytest.mark.parametrize("route", _JOIN_ROUTES)
def test_join_school_class_or_non_tutor_teacher_no_notice(
    sm: sessionmaker[Session], case: str, route: str
) -> None:
    if case == "school_class_of_tutor":
        teacher, _ = _tutor_teacher(sm)
        class_id, code = _class(sm, teacher, school_id=_school_for(sm, teacher))
    else:
        teacher = add_user(sm, Role.teacher, display_name="Mr Plain")
        class_id, code = _class(sm, teacher)
    student, _parents = _student_with_parents(sm, 2)
    client = _client(sm)
    act_as(client, student, Role.student)

    assert _join(client, sm, route, code, class_id, teacher) == 200

    assert _enrollment_id(sm, class_id, student) is not None
    assert _outbox(sm) == []
    assert _inbox(sm) == []


@pytest.mark.parametrize("route", _JOIN_ROUTES)
def test_rejoin_is_idempotent_no_second_notice(sm: sessionmaker[Session], route: str) -> None:
    teacher, _ = _tutor_teacher(sm)
    class_id, code = _class(sm, teacher)
    student, parents = _student_with_parents(sm, 2)
    client = _client(sm)
    act_as(client, student, Role.student)

    assert _join(client, sm, "student_join", code, class_id, teacher) == 200
    first_outbox, first_inbox = _outbox(sm), _inbox(sm)
    assert _join(client, sm, route, code, class_id, teacher) == 200

    assert len(first_outbox) == len(parents)
    assert len(first_inbox) == len(parents)
    assert _outbox(sm) == first_outbox
    assert _inbox(sm) == first_inbox
    assert _enrolled_classes(sm, student) == {class_id}


#: ``(listing state, paused)`` per profile state, or ``None`` for a teacher with no profile.
_PROFILE_STATES: dict[str, tuple[str, bool] | None] = {
    "draft": ("draft", False),
    "pending_review": ("pending_review", False),
    "listed": ("listed", False),
    "paused": ("listed", True),
    "rejected": ("rejected", False),
    "suspended": ("suspended", False),
    "closed": ("closed", False),
    "no_profile": None,
}


@pytest.mark.parametrize("profile", list(_PROFILE_STATES))
def test_class_join_notice_in_every_tutor_profile_state(
    sm: sessionmaker[Session], profile: str
) -> None:
    """Owning a tutor profile, in any state, makes a school-less class a side door (SC-2d)."""
    state = _PROFILE_STATES[profile]
    if state is None:
        teacher = add_user(sm, Role.teacher, display_name="Mr Plain")
    else:
        teacher, _ = _tutor_teacher(sm, state=state[0], paused=state[1])
    class_id, code = _class(sm, teacher)
    student, parents = _student_with_parents(sm, 2)
    client = _client(sm)
    act_as(client, student, Role.student)

    assert _join(client, sm, "student_join", code, class_id, teacher) == 200

    enrollment = _enrollment_id(sm, class_id, student)
    assert enrollment is not None
    expected = set() if state is None else set(parents)
    assert {row[0] for row in _outbox(sm)} == expected
    assert {row[1] for row in _outbox(sm)} <= {"class_joined_tutor"}
    assert {row[0] for row in _inbox(sm)} == expected
    assert {row[1] for row in _inbox(sm)} <= {NotificationType.tutor_access}


def test_join_by_code_queues_the_class_join_notice(sm: sessionmaker[Session]) -> None:
    """The older ``join_by_code`` entry point writes the same outbox rows: no side door."""
    teacher, _ = _tutor_teacher(sm)
    class_id, code = _class(sm, teacher)
    student, parents = _student_with_parents(sm, 2)

    row = ClassService(sm).join_by_code(student, code)
    again = ClassService(sm).join_by_code(student, code)

    assert row.class_id == class_id
    assert row.student_count == 1
    assert again == row
    enrollment = _enrollment_id(sm, class_id, student)
    assert enrollment is not None
    assert sorted(_outbox(sm), key=lambda item: str(item[0])) == sorted(
        (
            (
                parent,
                "class_joined_tutor",
                {
                    "tutor_first_name": "Sara",
                    "tutor_last_initial": "M",
                    "enrollment_id": str(enrollment),
                    "child_id": str(student),
                },
                f"class-join:{enrollment}:{parent}",
            )
            for parent in parents
        ),
        key=lambda item: str(item[0]),
    )


# ---------------------------------------------------------------------------
# Leaving a school-less class (S17, SC-2c, O24)
# ---------------------------------------------------------------------------


def test_leave_school_less_class_204_then_404(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    class_id, _ = _class(sm, teacher)
    student = add_user(sm, Role.student)
    _enrol(sm, class_id, student)
    client = _client(sm)
    act_as(client, student, Role.student)

    first = client.delete(f"/api/student/classes/{class_id}")
    second = client.delete(f"/api/student/classes/{class_id}")

    assert first.status_code == 204
    assert first.content == b""
    assert second.status_code == 404
    assert _enrolled_classes(sm, student) == set()


def test_leave_school_class_404(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    class_id, _ = _class(sm, teacher, school_id=_school_for(sm, teacher))
    student = add_user(sm, Role.student)
    _enrol(sm, class_id, student)
    client = _client(sm)
    act_as(client, student, Role.student)

    resp = client.delete(f"/api/student/classes/{class_id}")

    assert resp.status_code == 404
    assert _enrolled_classes(sm, student) == {class_id}


def test_leave_class_not_enrolled_404(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    class_id, _ = _class(sm, teacher)
    student = add_user(sm, Role.student)
    client = _client(sm)
    act_as(client, student, Role.student)

    assert client.delete(f"/api/student/classes/{class_id}").status_code == 404
    assert client.delete(f"/api/student/classes/{uuid.uuid4()}").status_code == 404
    assert client.delete("/api/student/classes/not-a-uuid").status_code == 422


def test_authz_student_can_leave_school_less_class_only(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    school_less, _ = _class(sm, teacher, name="Evening group")
    school_class, _ = _class(sm, teacher, school_id=_school_for(sm, teacher), name="Year 10")
    leaver = add_user(sm, Role.student)
    classmate = add_user(sm, Role.student)
    for class_id in (school_less, school_class):
        _enrol(sm, class_id, leaver)
        _enrol(sm, class_id, classmate)
    client = _client(sm)

    act_as(client, leaver, Role.student)
    assert client.delete(f"/api/student/classes/{school_class}").status_code == 404
    assert client.delete(f"/api/student/classes/{school_less}").status_code == 204

    assert _enrolled_classes(sm, leaver) == {school_class}
    assert _enrolled_classes(sm, classmate) == {school_less, school_class}
    for role in (Role.teacher, Role.parent, Role.school_admin, Role.platform_admin):
        act_as(client, teacher, role)
        assert client.delete(f"/api/student/classes/{school_less}").status_code == 403
    assert _enrolled_classes(sm, classmate) == {school_less, school_class}


def test_remove_school_less_enrolments_only_school_less(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    other_teacher = add_user(sm, Role.teacher)
    group_a, _ = _class(sm, teacher, name="A")
    group_b, _ = _class(sm, teacher, name="B")
    school_class, _ = _class(sm, teacher, school_id=_school_for(sm, teacher), name="C")
    elsewhere, _ = _class(sm, other_teacher, name="D")
    first, second = add_user(sm, Role.student), add_user(sm, Role.student)
    for class_id in (group_a, group_b, school_class, elsewhere):
        _enrol(sm, class_id, first)
    _enrol(sm, group_a, second)
    service = ClassService(sm)

    # An empty list removes nothing: it never widens to "every student".
    with sm.begin() as session:
        none_removed = service.remove_school_less_enrolments_in_session(
            session, teacher_user_id=teacher, student_ids=[]
        )
    assert none_removed == 0
    assert _enrolled_classes(sm, first) == {group_a, group_b, school_class, elsewhere}
    assert _enrolled_classes(sm, second) == {group_a}

    with sm.begin() as session:
        removed = service.remove_school_less_enrolments_in_session(
            session, teacher_user_id=teacher, student_ids=[first]
        )
    assert removed == 2
    assert _enrolled_classes(sm, first) == {school_class, elsewhere}
    assert _enrolled_classes(sm, second) == {group_a}

    # It writes in the caller's transaction: a rollback keeps the enrolment.
    with sm() as session:
        assert (
            service.remove_school_less_enrolments_in_session(
                session, teacher_user_id=teacher, student_ids=[second]
            )
            == 1
        )
        session.rollback()
    assert _enrolled_classes(sm, second) == {group_a}


def test_remove_all_school_less_enrolments_only_that_teachers_school_less(
    sm: sessionmaker[Session],
) -> None:
    """The close/suspend sweep: every student of the teacher's school-less classes, nothing else."""
    teacher = add_user(sm, Role.teacher)
    other_teacher = add_user(sm, Role.teacher)
    group_a, _ = _class(sm, teacher, name="A")
    group_b, _ = _class(sm, teacher, name="B")
    school_class, _ = _class(sm, teacher, school_id=_school_for(sm, teacher), name="C")
    elsewhere, _ = _class(sm, other_teacher, name="D")
    first, second = add_user(sm, Role.student), add_user(sm, Role.student)
    for class_id in (group_a, group_b, school_class, elsewhere):
        _enrol(sm, class_id, first)
    _enrol(sm, group_b, second)
    _enrol(sm, elsewhere, second)
    service = ClassService(sm)

    # In the caller's transaction: a rollback keeps every enrolment.
    with sm() as session:
        assert (
            service.remove_all_school_less_enrolments_in_session(session, teacher_user_id=teacher)
            == 3
        )
        session.rollback()
    assert _enrolled_classes(sm, first) == {group_a, group_b, school_class, elsewhere}

    with sm.begin() as session:
        removed = service.remove_all_school_less_enrolments_in_session(
            session, teacher_user_id=teacher
        )
    assert removed == 3
    assert _enrolled_classes(sm, first) == {school_class, elsewhere}
    assert _enrolled_classes(sm, second) == {elsewhere}

    with sm.begin() as session:
        assert (
            service.remove_all_school_less_enrolments_in_session(session, teacher_user_id=teacher)
            == 0
        )


# ---------------------------------------------------------------------------
# The class-access list (S16, SC-2e, XT-2, O25)
# ---------------------------------------------------------------------------


def _booking(sm: sessionmaker[Session], profile_id: uuid.UUID, student: uuid.UUID) -> None:
    starts = datetime.now(UTC) + timedelta(days=3)
    with sm.begin() as session:
        session.add(
            TutorBooking(
                tutor_profile_id=profile_id,
                student_id=student,
                requested_by_user_id=student,
                requested_by_party=BookingParty.student,
                subject_code=add_subject(sm),
                mode=TutoringMode.virtual,
                starts_at=starts,
                ends_at=starts + timedelta(hours=1),
            )
        )


def _grant(sm: sessionmaker[Session], profile_id: uuid.UUID, student: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(TutorDataGrant(student_id=student, tutor_profile_id=profile_id))


def test_s16_lists_only_callers_classes_with_teacher_is_your_tutor(
    sm: sessionmaker[Session],
) -> None:
    student = add_user(sm, Role.student)
    stranger = add_user(sm, Role.student)
    granted_teacher, granted_profile = _tutor_teacher(sm, display_name="Ms Grant")
    booked_teacher, booked_profile = _tutor_teacher(sm, display_name="Mr Booked")
    school_tutor, _ = _tutor_teacher(sm, display_name="Dr School")
    plain_teacher = add_user(sm, Role.teacher, display_name="Mr Plain")
    email_named = add_user(sm, Role.teacher)
    with sm.begin() as session:
        named = session.get(User, email_named)
        assert named is not None
        named.display_name = named.email  # a display name that is an address must not leak

    granted_class, _ = _class(sm, granted_teacher, name="A granted")
    booked_class, _ = _class(sm, booked_teacher, name="B booked")
    school_class, _ = _class(
        sm, school_tutor, school_id=_school_for(sm, school_tutor), name="C school"
    )
    plain_class, _ = _class(sm, plain_teacher, name="D plain")
    email_class, _ = _class(sm, email_named, name="E email")
    not_mine, _ = _class(sm, plain_teacher, name="F not mine")
    for class_id in (granted_class, booked_class, school_class, plain_class, email_class):
        _enrol(sm, class_id, student)
    _enrol(sm, not_mine, stranger)
    _grant(sm, granted_profile, student)
    _booking(sm, booked_profile, student)
    _grant(sm, granted_profile, stranger)
    client = _client(sm)
    act_as(client, student, Role.student)

    resp = client.get(S16)

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [item["classId"] for item in items] == [
        str(c) for c in (granted_class, booked_class, school_class, plain_class, email_class)
    ]
    by_class = {item["classId"]: item for item in items}
    assert by_class[str(granted_class)] == {
        "classId": str(granted_class),
        "className": "A granted",
        "teacherName": "Ms Grant",
        "schoolName": None,
        "leavable": True,
        "teacherIsYourTutor": True,
    }
    assert by_class[str(booked_class)]["teacherIsYourTutor"] is True
    assert by_class[str(school_class)]["schoolName"] == "Nile School"
    assert by_class[str(school_class)]["leavable"] is False
    assert by_class[str(school_class)]["teacherIsYourTutor"] is False
    assert by_class[str(plain_class)]["teacherIsYourTutor"] is False
    assert by_class[str(plain_class)]["teacherName"] == "Mr Plain"
    assert "@" not in by_class[str(email_class)]["teacherName"]
    assert "@" not in resp.text

    act_as(client, stranger, Role.student)
    stranger_items = client.get(S16).json()["items"]
    assert [item["classId"] for item in stranger_items] == [str(not_mine)]
    assert stranger_items[0]["teacherIsYourTutor"] is False

    act_as(client, add_user(sm, Role.student), Role.student)
    assert client.get(S16).json() == {"items": []}


def test_s16_s17_send_no_store(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    class_id, _ = _class(sm, teacher)
    student = add_user(sm, Role.student)
    _enrol(sm, class_id, student)
    client = _client(sm)
    act_as(client, student, Role.student)

    listed = client.get(S16)
    left = client.delete(f"/api/student/classes/{class_id}")
    missing = client.delete(f"/api/student/classes/{class_id}")

    assert listed.status_code == 200
    assert listed.headers.get("cache-control") == NO_STORE
    assert left.status_code == 204
    assert left.headers.get("cache-control") == NO_STORE
    assert missing.status_code == 404
    assert missing.headers.get("cache-control") == NO_STORE
