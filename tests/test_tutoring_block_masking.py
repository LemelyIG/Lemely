"""A block never tells the blocked party who blocked (SPEC §i.7, THREAT-MODEL SC-11).

Route-level, with real blocks: a ``tutoring_blocks`` row and, in the same transaction, the
sweeps T21 runs (the tutor row ``FOR UPDATE``, the pair lock, ``cancel_future_for_pair_in_session``
and ``revoke_live_in_session``), compared with a real suspension, close, safety freeze and admin
cancel. The routers are mounted through ``tests.tutoring_app.app_with_routers`` (a lane never
edits ``lemely/web/app.py``).

* **The family (S1, S2, S4, PA1, PA2).** A block's cancellations carry the party ``system``. The
  student and their parents read them exactly as a platform cancellation, so a tutor's block,
  the student's own block, a suspension and a close read the same.
* **Grant status (S8, S10, PA6).** A grant ended by the tutor's block reads
  ``tutor_unavailable``, the status a grant has when its tutor is not listed; ``blocked`` stays
  only when the student's own block explains it (``core.tutor_grants.grant_status_for_student``,
  checked here on its own as well).
* **The tutor (T9, T10, T16, T17).** After the student's block, notes on a session still inside
  its note window close. The tutor reads that closure exactly as a safety freeze
  (``notesFrozen: true``), and the block's cancellation exactly as an admin cancel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.core import tutor_grants
from lemely.core.tutor_grants import GrantFacts, grant_status
from lemely.db.booking_repo import BookingService, lock_pair_in_session
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import GrantRevokeReason, Role
from lemely.db.models.tutoring import TutoringBlock
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_grant_repo import TutorGrantRepository, revoke_live_in_session
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.web.deps import (
    get_class_service,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
    get_user_mirror,
)
from lemely.web.deps_tutoring import get_tutor_profile_repo
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import (
    parent_bookings,
    parent_tutor_access,
    student_bookings,
    student_tutor_access,
    tutor_bookings,
    tutoring_booking,
)
from lemely.web.routers.student_tutor_access import get_tutor_grant_repo
from tests.test_booking_repo import add_booking, add_parent, make_world, set_listing
from tests.test_tutor_grant_repo import add_grant, add_student
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import (
    DbMirror,
    act_as,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from tests.test_booking_repo import World
    from tests.tutoring_db import SeededTutor

Sweep = Literal["tutor_block", "student_block", "suspension", "close"]
SWEEPS: tuple[Sweep, ...] = ("tutor_block", "student_block", "suspension", "close")

#: Every ``BookingDTO`` field that says what happened to a session, its notes and its actions.
#: The rest (ids, names, the tutor card and the instants, ``reviewOpensAt`` included) differ
#: between worlds by construction; for ``reviewOpensAt`` only whether it is shown is compared.
OUTCOME_FIELDS = (
    "effectiveState",
    "requestedBy",
    "cancelledBy",
    "cancelReason",
    "cancelledLate",
    "completedBy",
    "declineReason",
    "notesFrozen",
    "allowedActions",
    "meetingLink",
    "locationDetail",
    "review",
    "studentShared",
)


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


def masking_client(sm: sessionmaker[Session]) -> TestClient:
    """S1-S4, S8-S10, PA1-PA3, PA6, T9-T17 on a fresh app wired to the test database."""
    app = app_with_routers(
        student_bookings.router,
        parent_bookings.router,
        tutor_bookings.router,
        student_tutor_access.router,
        parent_tutor_access.router,
    )
    inbox = NotificationService(sm, NotificationPreferencesService(sm))
    push = RecordingPushTransport()
    app.dependency_overrides[tutoring_booking.get_booking_service] = lambda: BookingService(sm)
    app.dependency_overrides[tutor_bookings.get_booking_service] = lambda: BookingService(sm)
    app.dependency_overrides[get_tutor_profile_repo] = lambda: TutorProfileRepository(sm)
    app.dependency_overrides[get_tutor_grant_repo] = lambda: TutorGrantRepository(sm)
    app.dependency_overrides[get_parent_link_service] = lambda: ParentLinkService(sm)
    app.dependency_overrides[get_class_service] = lambda: ClassService(sm)
    app.dependency_overrides[get_user_mirror] = lambda: DbMirror(sm)
    app.dependency_overrides[get_notification_service] = lambda: inbox
    app.dependency_overrides[get_push_transport] = lambda: push
    return TestClient(app)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = masking_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Real blocks and sanctions (the T21 order: tutor row, pair lock, sweeps)
# ---------------------------------------------------------------------------


def _lock_tutor(session: Session, tutor: SeededTutor) -> None:
    session.execute(
        sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR UPDATE"), {"t": tutor.profile_id}
    )


def block(
    sm: sessionmaker[Session],
    tutor: SeededTutor,
    student: uuid.UUID,
    *,
    by: Literal["student", "tutor"],
) -> None:
    """A new block and its effects in one transaction (SPEC §a.2 ``tutoring_blocks``, §a.4b)."""
    blocker, blocked = (student, tutor.user_id) if by == "student" else (tutor.user_id, student)
    with sm.begin() as session:
        _lock_tutor(session, tutor)
        lock_pair_in_session(session, student_id=student, tutor_profile_id=tutor.profile_id)
        session.add(TutoringBlock(blocker_user_id=blocker, blocked_user_id=blocked))
        session.flush()
        BookingService(sm).cancel_future_for_pair_in_session(
            session, tutor_profile_id=tutor.profile_id, student_id=student, actor_user_id=blocker
        )
        revoke_live_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            student_id=student,
            reason=GrantRevokeReason.block,
        )


def sanction(
    sm: sessionmaker[Session], tutor: SeededTutor, *, state: Literal["suspended", "closed"]
) -> None:
    """A suspension or close and its sweeps in one transaction (SPEC §a.3)."""
    reason = (
        GrantRevokeReason.tutor_suspended
        if state == "suspended"
        else GrantRevokeReason.tutor_closed
    )
    with sm.begin() as session:
        _lock_tutor(session, tutor)
        session.execute(
            sa.text(
                "UPDATE tutor_profiles SET listing_state = CAST(:s AS tutorlistingstate), "
                "closed_at = CASE WHEN :s = 'closed' THEN now() END WHERE id = :t"
            ),
            {"s": state, "t": tutor.profile_id},
        )
        BookingService(sm).cancel_future_for_tutor_in_session(
            session, tutor_profile_id=tutor.profile_id
        )
        revoke_live_in_session(
            session, tutor_profile_id=tutor.profile_id, student_id=None, reason=reason
        )


def sweep(sm: sessionmaker[Session], w: World, kind: Sweep) -> None:
    if kind == "tutor_block":
        block(sm, w.tutor, w.student, by="tutor")
    elif kind == "student_block":
        block(sm, w.tutor, w.student, by="student")
    else:
        sanction(sm, w.tutor, state="suspended" if kind == "suspension" else "closed")


def get_json(client: TestClient, path: str, **params: str) -> dict[str, object]:
    response = client.get(path, params=params)
    assert response.status_code == 200, (path, response.text)
    body = response.json()
    assert isinstance(body, dict)
    return body


def outcome(body: dict[str, object]) -> dict[str, object]:
    return {
        **{field: body[field] for field in OUTCOME_FIELDS},
        "reviewOpensAt shown": body["reviewOpensAt"] is not None,
    }


def outcomes(page: dict[str, object]) -> list[dict[str, object]]:
    items = page["items"]
    assert isinstance(items, list)
    return [outcome(item) for item in items]


# ---------------------------------------------------------------------------
# The family: S1, S2, S4, PA1, PA2
# ---------------------------------------------------------------------------


def test_family_reads_every_block_and_sanction_cancellation_the_same(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """SC-11: the student and their parents cannot tell who blocked, or a block from a sanction.

    Each world has an accepted session in three days (the sweep cancels it) and a session
    completed two days ago (its notes would still be open). Everything the family reads about
    both must be identical across a tutor's block, the student's own block, a suspension and a
    close.
    """
    seen: dict[Sweep, dict[str, object]] = {}
    for kind in SWEEPS:
        w = make_world(sm)
        parent = add_parent(sm, w.student)
        upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=3))
        recent = add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
        sweep(sm, w, kind)

        act_as(client, w.student, Role.student)
        student = {
            "S2 upcoming": outcome(get_json(client, f"/api/student/bookings/{upcoming}")),
            "S2 recent": outcome(get_json(client, f"/api/student/bookings/{recent}")),
            "S1 past": outcomes(get_json(client, "/api/student/bookings", when="past")),
            "S4 canPost": get_json(client, f"/api/student/bookings/{recent}/notes")["canPost"],
        }
        act_as(client, parent, Role.parent)
        child = f"/api/parent/children/{w.student}/bookings"
        family = {
            "PA2 upcoming": outcome(get_json(client, f"{child}/{upcoming}")),
            "PA2 recent": outcome(get_json(client, f"{child}/{recent}")),
            "PA1 past": outcomes(get_json(client, child, when="past")),
        }
        seen[kind] = {**student, **family}

    reference = seen["suspension"]
    # Non-vacuity: the swept session really was cancelled, and reads as a platform cancellation;
    # both sessions are in the past list.
    assert reference["S2 upcoming"]["effectiveState"] == "cancelled"  # type: ignore[index]
    assert reference["S2 upcoming"]["cancelledBy"] == "platform_admin"  # type: ignore[index]
    assert reference["PA2 upcoming"]["cancelledBy"] == "platform_admin"  # type: ignore[index]
    assert len(reference["S1 past"]) == len(reference["PA1 past"]) == 2  # type: ignore[arg-type]
    assert reference["S4 canPost"] is False
    for kind in ("tutor_block", "student_block", "close"):
        assert seen[kind].keys() == reference.keys(), kind
        for key, expected in reference.items():
            assert seen[kind][key] == expected, (kind, key)


# ---------------------------------------------------------------------------
# Grant status: S8, S10, PA6
# ---------------------------------------------------------------------------


def test_grant_status_never_names_the_tutors_block(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """A tutor's block reads as the tutor being unavailable; the student's own keeps ``blocked``."""
    student = add_student(sm)
    parent = add_parent(sm, student)
    tutors = {
        "tutor_block": add_tutor(sm, first_name="Tamer"),
        "unlisted": add_tutor(sm, first_name="Omar"),
        "student_block": add_tutor(sm, first_name="Lina"),
        "suspended": add_tutor(sm, first_name="Hana"),
    }
    grants = {name: add_grant(sm, student, tutor) for name, tutor in tutors.items()}
    block(sm, tutors["tutor_block"], student, by="tutor")
    set_listing(sm, tutors["unlisted"], "rejected")
    block(sm, tutors["student_block"], student, by="student")
    sanction(sm, tutors["suspended"], state="suspended")

    act_as(client, student, Role.student)
    s8 = get_json(client, "/api/student/tutor-grants")
    revoked = client.post(f"/api/student/tutor-grants/{grants['tutor_block']}/revoke")
    assert revoked.status_code == 200, revoked.text
    act_as(client, parent, Role.parent)
    pa6 = get_json(client, f"/api/parent/children/{student}/tutor-grants")

    for route, page in (("S8", s8), ("PA6", pa6)):
        items = page["items"]
        assert isinstance(items, list)
        by_tutor = {item["tutor"]["tutorId"]: item["status"] for item in items}
        status = {name: by_tutor[str(tutor.profile_id)] for name, tutor in tutors.items()}
        assert len(status) == 4, route  # non-vacuity: every grant listed
        # The same non-revealing status as a tutor who is simply not listed (SPEC §e.1).
        assert status["tutor_block"] == status["unlisted"], route
        assert status == {
            "tutor_block": "tutor_unavailable",
            "unlisted": "tutor_unavailable",
            "student_block": "blocked",
            "suspended": "tutor_suspended",
        }, route
    # S10 answers with the grant as S8 shows it: a repeat revoke cannot uncover the block either.
    assert revoked.json()["status"] == "tutor_unavailable"


# ---------------------------------------------------------------------------
# The tutor: T9, T10, T16, T17
# ---------------------------------------------------------------------------


def test_tutor_reads_the_students_block_as_a_freeze_and_an_admin_cancel(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """The student's block, seen by the tutor, equals a safety freeze plus an admin cancel.

    Notes on a session completed two days ago are still open (7-day window) until the block
    closes them; without masking the tutor would read closed notes with ``notesFrozen: false``
    on a listed profile, which only a block produces.
    """
    worlds = {"block": make_world(sm), "freeze": make_world(sm)}
    made = {
        name: (
            add_booking(sm, w, state="accepted", starts_in=timedelta(days=3)),
            add_booking(sm, w, state="completed", starts_in=-timedelta(days=2)),
        )
        for name, w in worlds.items()
    }
    blocked_world = worlds["block"]
    act_as(client, blocked_world.tutor.user_id, Role.teacher)
    before = get_json(client, f"/api/tutor/bookings/{made['block'][1]}")
    assert "post_note" in before["allowedActions"]  # type: ignore[operator]  # red case: open

    block(sm, blocked_world.tutor, blocked_world.student, by="student")
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        assert BookingService.freeze_notes_in_session(session, made["freeze"][1]) is True
        BookingService(sm).admin_cancel_in_session(
            session, booking_id=made["freeze"][0], admin_user_id=admin
        )

    views: dict[str, dict[str, object]] = {}
    for name, w in worlds.items():
        upcoming, recent = made[name]
        act_as(client, w.tutor.user_id, Role.teacher)
        posted = client.post(f"/api/tutor/bookings/{recent}/notes", json={"body": "See you soon"})
        views[name] = {
            "T10 upcoming": outcome(get_json(client, f"/api/tutor/bookings/{upcoming}")),
            "T10 recent": outcome(get_json(client, f"/api/tutor/bookings/{recent}")),
            "T9 past": outcomes(get_json(client, "/api/tutor/bookings", when="past")),
            "T16 canPost": get_json(client, f"/api/tutor/bookings/{recent}/notes")["canPost"],
            "T17": (posted.status_code, posted.json()),
        }

    frozen = views["freeze"]
    # Non-vacuity: the reference really is a freeze and an admin cancellation.
    assert frozen["T10 recent"]["notesFrozen"] is True  # type: ignore[index]
    assert frozen["T10 upcoming"]["cancelledBy"] == "platform_admin"  # type: ignore[index]
    assert frozen["T16 canPost"] is False
    assert frozen["T17"][0] == 409  # type: ignore[index]
    assert len(frozen["T9 past"]) == 2  # type: ignore[arg-type]
    assert views["block"].keys() == frozen.keys()
    for key, expected in frozen.items():
        assert views["block"][key] == expected, key


# ---------------------------------------------------------------------------
# core.tutor_grants.grant_status_for_student (pure)
# ---------------------------------------------------------------------------

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
GRANTED = T0
ENDED = T0 + timedelta(days=5)
LATER = T0 + timedelta(days=30)


def facts(
    *, revoke_reason: str | None, blocked: bool = False, listing: str = "listed"
) -> GrantFacts:
    return GrantFacts(
        created_at=GRANTED,
        revoked_at=ENDED if revoke_reason is not None else None,
        revoke_reason=revoke_reason,
        expires_at=None,
        tutor_listing_state=listing,
        blocked=blocked,
    )


@pytest.mark.parametrize(
    ("student_blocked_at", "shown"),
    [
        (ENDED, "blocked"),  # the student's own block ended it, in its transaction
        (GRANTED, "blocked"),  # inclusive at the grant's start
        (GRANTED + timedelta(days=2), "blocked"),
        (None, "tutor_unavailable"),  # only the tutor ever blocked
        (GRANTED - timedelta(seconds=1), "tutor_unavailable"),  # an older, lifted block
        (ENDED + timedelta(seconds=1), "tutor_unavailable"),  # the student blocked afterwards
    ],
)
def test_a_block_revoke_reads_blocked_only_for_the_students_own_block(
    student_blocked_at: datetime | None, shown: str
) -> None:
    ended_by_block = facts(revoke_reason="block")
    assert grant_status(ended_by_block, now=LATER) == "blocked"  # what the core status says
    assert (
        tutor_grants.grant_status_for_student(
            ended_by_block, now=LATER, student_blocked_at=student_blocked_at
        )
        == shown
    )


def test_a_live_grant_under_a_block_reads_blocked_only_for_the_students_own_block() -> None:
    live = facts(revoke_reason=None, blocked=True)
    show = tutor_grants.grant_status_for_student
    assert grant_status(live, now=LATER) == "blocked"
    assert show(live, now=LATER, student_blocked_at=LATER) == "blocked"  # inclusive at now
    assert show(live, now=LATER, student_blocked_at=ENDED) == "blocked"
    assert show(live, now=LATER, student_blocked_at=None) == "tutor_unavailable"
    assert show(live, now=LATER, student_blocked_at=GRANTED - timedelta(days=1)) == (
        "tutor_unavailable"
    )


def test_every_other_status_passes_through_unchanged() -> None:
    show = tutor_grants.grant_status_for_student
    cases = [
        facts(revoke_reason=None),
        facts(revoke_reason="student"),
        facts(revoke_reason="tutor_suspended"),
        facts(revoke_reason="tutor_closed"),
        facts(revoke_reason=None, listing="rejected"),
        facts(revoke_reason="student", blocked=True),
    ]
    seen = set()
    for case in cases:
        expected = grant_status(case, now=LATER)
        for blocked_at in (None, ENDED):
            assert show(case, now=LATER, student_blocked_at=blocked_at) == expected
        seen.add(expected)
    # Non-vacuity: five distinct statuses, none of them "blocked".
    assert seen == {"active", "revoked", "tutor_suspended", "tutor_closed", "tutor_unavailable"}


def test_a_naive_block_instant_is_refused() -> None:
    with pytest.raises(ValueError, match="student_blocked_at"):
        tutor_grants.grant_status_for_student(
            facts(revoke_reason="block"), now=LATER, student_blocked_at=datetime(2026, 10, 3, 9)
        )
