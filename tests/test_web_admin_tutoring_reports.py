"""A9-A11: the platform admin's report queue, detail and resolution (PLAN T25; SPEC §b.2, X-07).

SPEC ``docs/tutoring/SPEC.md`` §b.2 A9 (safety concerns first, ``state`` filter, keyset), A10
(snapshot; for booking and note targets the booking summary and the notes thread, the only
admin path to notes, each view logged as ``report_thread_view``; fail closed, §a.2
``tutoring_admin_access``, SC-23), A11 (every resolution; 409 ``already_resolved`` /
``resolution_not_applicable``), §a.3 (a resolution clears the freeze; ``booking_completed``
only on a ``disputed_outcome`` report targeting the booking), §a.4b (a ``tutor_suspended``
resolution is the A5 sweep, in the resolution's own transaction, under the tutor row
``FOR UPDATE``), §i.4 (snapshot allowlist, party labels), O15 (notes only through A10).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.booking_repo import ADMIN_CANCEL_REASON
from lemely.db.models.enums import BookingParty, BookingState, ReportTargetType, Role
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.db.tutor_review_repo import TutorReviewRepository
from lemely.db.tutoring_reports_repo import REPORT_SUSPENSION_NOTE, SNAPSHOT_KEYS
from lemely.web.schemas_tutoring_admin import (
    AdminBookingSummaryDTO,
    ReportDetailDTO,
    ReportItemDTO,
)
from tests.test_booking_repo import (
    LINK,
    add_booking,
    add_parent,
    add_student,
    make_world,
    stored,
)
from tests.test_tutor_grant_repo import add_grant
from tests.test_tutor_review_repo import add_reply_row, add_review_row, stored_ratings
from tests.test_tutoring_reports_repo import (
    add_report_row,
    file_report,
    frozen,
    report_state,
    reports_client,
    student_reporter,
)
from tests.test_tutoring_sweeps import add_class, add_note, classes_of, enrol, grant_state
from tests.test_web_tutoring_blocks import inbox
from tests.tutoring_db import act_as, add_tutor, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from tests.test_booking_repo import World

A9 = "/api/admin/tutoring/reports"
NO_STORE = "private, no-store"
STUDENT_NAME = "Mariam Hassan"


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


@pytest.fixture
def admin(sm: sessionmaker[Session], client: TestClient) -> uuid.UUID:
    admin_id = add_user(sm, Role.platform_admin)
    act_as(client, admin_id, Role.platform_admin)
    return admin_id


def resolve(
    client: TestClient, report_id: uuid.UUID, resolution: str, note: str | None = None
) -> dict[str, Any]:
    response = client.post(
        f"{A9}/{report_id}/resolve", json={"resolution": resolution, "note": note}
    )
    assert response.headers["Cache-Control"] == NO_STORE
    return {"status": response.status_code, "body": response.json()}


def access_rows(sm: sessionmaker[Session]) -> list[tuple[object, ...]]:
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT admin_user_id, action::text, tutor_profile_id, report_id, booking_id, "
                "evidence_id FROM tutoring_admin_access ORDER BY created_at, id"
            )
        ).all()
    return [tuple(row) for row in rows]


def refuse_writes(sm: sessionmaker[Session], table: str, event: str) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "CREATE FUNCTION t25_refuse() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'unavailable'; END $$"
            )
        )
        session.execute(
            sa.text(
                f"CREATE TRIGGER t25_refuse BEFORE {event} ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION t25_refuse()"
            )
        )


def allow_writes(sm: sessionmaker[Session], table: str) -> None:
    with sm.begin() as session:
        session.execute(sa.text(f"DROP TRIGGER t25_refuse ON {table}"))
        session.execute(sa.text("DROP FUNCTION t25_refuse()"))


# ---------------------------------------------------------------------------
# A9
# ---------------------------------------------------------------------------


def test_a9_lists_safety_first_by_state_with_a_bound_cursor(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    w = make_world(sm)
    now = datetime.now(UTC)
    ids = []
    for hours, reason in ((6, "spam"), (5, "safety_concern"), (4, "other")):
        booking = add_booking(sm, w, state="cancelled")
        ids.append(
            add_report_row(
                sm,
                reporter=w.student,
                target_type="booking",
                target_id=booking,
                reason=reason,
                created_at=now - timedelta(hours=hours),
            )
        )
    dismissed = add_report_row(
        sm,
        reporter=w.student,
        target_type="tutor_profile",
        target_id=w.tutor.profile_id,
        resolution="dismissed",
    )

    first = client.get(A9, params={"limit": 2})
    assert first.status_code == 200, first.text
    assert first.headers["Cache-Control"] == NO_STORE
    page = first.json()
    assert [item["reportId"] for item in page["items"]] == [str(ids[1]), str(ids[0])]
    assert all(set(item) == set(ReportItemDTO.model_fields) for item in page["items"])
    assert page["items"][0]["reason"] == "safety_concern"
    rest = client.get(A9, params={"limit": 2, "cursor": page["nextCursor"]}).json()
    assert [item["reportId"] for item in rest["items"]] == [str(ids[2])]
    assert rest["nextCursor"] is None

    resolved = client.get(A9, params={"state": "dismissed"}).json()
    assert [item["reportId"] for item in resolved["items"]] == [str(dismissed)]
    assert resolved["items"][0]["state"] == "dismissed"

    # O21: a cursor minted for one state is refused for another, and garbage is refused.
    for params in (
        {"state": "dismissed", "cursor": page["nextCursor"]},
        {"cursor": "not-a-cursor"},
    ):
        bad = client.get(A9, params=params)
        assert bad.status_code == 422, params
        assert bad.json()["detail"]["code"] == "invalid_cursor"
        assert bad.headers["Cache-Control"] == NO_STORE


# ---------------------------------------------------------------------------
# A10
# ---------------------------------------------------------------------------


def test_a10_shows_snapshot_summary_and_thread_with_party_labels(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    w = make_world(sm, display_name=STUDENT_NAME)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = add_note(sm, booking, w.student, "student", "Is the address right?")
    add_note(sm, booking, w.tutor.user_id, "tutor", "Message me on WhatsApp")
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE tutor_booking_notes SET hidden_at = now() WHERE booking_id = :b "
                "AND author_party = 'tutor'"
            ),
            {"b": booking},
        )
    report_id = file_report(
        sm,
        student_reporter(w.student),
        "booking_note",
        note,
        reason="safety_concern",
        details="He keeps asking",
    )

    response = client.get(f"{A9}/{report_id}")

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == NO_STORE
    body = response.json()
    assert set(body) == set(ReportDetailDTO.model_fields)
    assert body["targetType"] == "booking_note"
    assert body["reporterParty"] == "student"
    assert body["details"] == "He keeps asking"
    assert body["tutorId"] == str(w.tutor.profile_id)
    assert body["tutorName"] == "Sara M."
    assert body["snapshot"] == {"authorParty": "student", "body": "Is the address right?"}
    assert set(body["snapshot"]) <= SNAPSHOT_KEYS[ReportTargetType.booking_note]
    summary = body["bookingSummary"]
    assert set(summary) == set(AdminBookingSummaryDTO.model_fields)
    assert summary["bookingId"] == str(booking)
    assert summary["effectiveState"] == "accepted"
    assert summary["notesFrozen"] is True
    assert [(n["authorParty"], n["authorName"], n["body"], n["hidden"]) for n in body["notes"]] == [
        ("student", "Student", "Is the address right?", False),
        ("tutor", "Sara M.", "Message me on WhatsApp", True),  # hidden bodies visible to admin
    ]
    assert body["resolution"] is None and body["resolvedAt"] is None
    # Never a student's name, id or email, and never a meeting link (§a.5, O16).
    text = json.dumps(body)
    for secret in (STUDENT_NAME, str(w.student), "@example.com", LINK):
        assert secret not in text


def test_a10_writes_report_thread_view_and_fails_closed(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = add_note(sm, booking, w.tutor.user_id, "tutor", "Secret plan")
    booking_report = file_report(sm, student_reporter(w.student), "booking", booking)
    note_report = file_report(sm, student_reporter(w.student), "booking_note", note)
    profile_report = file_report(
        sm, student_reporter(w.student), "tutor_profile", w.tutor.profile_id
    )

    assert client.get(f"{A9}/{booking_report}").status_code == 200
    assert client.get(f"{A9}/{note_report}").status_code == 200
    assert client.get(f"{A9}/{profile_report}").status_code == 200  # no thread, no row

    assert access_rows(sm) == [
        (admin, "report_thread_view", w.tutor.profile_id, booking_report, booking, None),
        (admin, "report_thread_view", w.tutor.profile_id, note_report, booking, None),
    ]
    # Every view is logged again.
    client.get(f"{A9}/{booking_report}")
    assert len(access_rows(sm)) == 3

    # Fail closed (SC-23): when the log write fails, the request fails and no note leaves.
    refuse_writes(sm, "tutoring_admin_access", "INSERT")
    try:
        quiet = TestClient(client.app, raise_server_exceptions=False)
        failed = quiet.get(f"{A9}/{booking_report}")
    finally:
        allow_writes(sm, "tutoring_admin_access")
    assert failed.status_code == 500
    assert "Secret plan" not in failed.text
    assert "notes" not in failed.text
    assert len(access_rows(sm)) == 3


def test_a10_unknown_report_is_404(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    response = client.get(f"{A9}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
    assert response.headers["Cache-Control"] == NO_STORE
    assert access_rows(sm) == []


@pytest.mark.parametrize("role", [Role.student, Role.parent, Role.teacher, Role.school_admin])
def test_admin_report_routes_refuse_every_other_role(
    sm: sessionmaker[Session], client: TestClient, role: Role
) -> None:
    """Only a platform admin reads a snapshot or a thread (§a.5, O15): nobody else, not even the
    reporter or the reported tutor."""
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    report_id = file_report(sm, student_reporter(w.student), "booking", booking)
    users = {
        Role.student: w.student,
        Role.parent: add_parent(sm, w.student),
        Role.teacher: w.tutor.user_id,
        Role.school_admin: add_user(sm, Role.school_admin),
    }
    act_as(client, users[role], role)
    for method, path in (
        ("GET", A9),
        ("GET", f"{A9}/{report_id}"),
        ("POST", f"{A9}/{report_id}/resolve"),
    ):
        response = client.request(method, path, json={"resolution": "dismissed"})
        assert response.status_code == 403, (role, path)
        assert "snapshot" not in response.text
        assert response.headers["Cache-Control"] == NO_STORE
    assert report_state(sm, report_id) == ("open", None)
    assert access_rows(sm) == []


# ---------------------------------------------------------------------------
# A11: every resolution
# ---------------------------------------------------------------------------


def test_a11_dismiss_closes_the_report_and_lifts_the_freeze(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    report_id = file_report(
        sm, student_reporter(w.student), "booking", booking, reason="safety_concern"
    )
    assert frozen(sm, booking)

    result = resolve(client, report_id, "dismissed", "  Talked to both families.  ")

    assert result["status"] == 200, result
    body = result["body"]
    assert body["state"] == "dismissed"
    assert body["resolution"] == "dismissed"
    assert body["resolutionNote"] == "Talked to both families."
    assert body["resolvedAt"] is not None
    assert body["notes"] == []  # O15: the thread only through A10
    assert body["bookingSummary"]["notesFrozen"] is False
    assert not frozen(sm, booking)
    assert access_rows(sm) == []  # A11 shows no thread, so it logs no view
    assert stored(sm, booking).state is BookingState.accepted


def test_a11_content_hidden_hides_the_note_review_or_reply(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="completed", starts_in=-timedelta(days=9))
    note = add_note(sm, booking, w.tutor.user_id, "tutor", "Add me on Instagram")
    other_student = add_student(sm)
    other_booking = add_booking(
        sm, w, student=other_student, state="completed", starts_in=-timedelta(days=12)
    )
    kept = add_review_row(
        sm, booking=other_booking, tutor_id=w.tutor.profile_id, student=other_student, stars=5
    )
    review = add_review_row(
        sm, booking=booking, tutor_id=w.tutor.profile_id, student=w.student, stars=1, text="Bad"
    )
    reply = add_reply_row(sm, review=kept, tutor_id=w.tutor.profile_id, state="approved")
    TutorReviewRepository(sm).recompute_ratings(w.tutor.profile_id)
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (6, 2)
    reporter = student_reporter(w.student)
    reports = {
        "booking_note": file_report(sm, reporter, "booking_note", note),
        "review": file_report(sm, student_reporter(add_student(sm)), "review", review),
        "review_reply": file_report(sm, reporter, "review_reply", reply),
    }

    for target_type, report_id in reports.items():
        result = resolve(client, report_id, "content_hidden")
        assert result["status"] == 200, (target_type, result)
        assert result["body"]["state"] == "actioned"
        assert result["body"]["resolution"] == "content_hidden"

    with sm() as session:
        assert session.execute(
            sa.text(
                "SELECT hidden_at IS NOT NULL, hidden_by_user_id FROM tutor_booking_notes "
                "WHERE id = :n"
            ),
            {"n": note},
        ).one() == (True, admin)
        assert session.execute(
            sa.text("SELECT removed_at IS NOT NULL FROM tutor_reviews WHERE id = :r"),
            {"r": review},
        ).scalar_one()
        assert (
            session.execute(
                sa.text("SELECT text_state::text FROM tutor_review_replies WHERE id = :r"),
                {"r": reply},
            ).scalar_one()
            == "rejected"
        )
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (5, 1)  # recomputed in the resolution


def _not_applicable_case(sm: sessionmaker[Session], w: World, case: str) -> tuple[uuid.UUID, str]:
    """``(report_id, resolution)`` for one case A11 must refuse, seeded directly."""
    student = w.student

    def row(target_type: str, target_id: uuid.UUID, reason: str = "harassment") -> uuid.UUID:
        return add_report_row(
            sm, reporter=student, target_type=target_type, target_id=target_id, reason=reason
        )

    def booking(state: str, starts_in: timedelta) -> uuid.UUID:
        return add_booking(sm, w, state=state, starts_in=starts_in)

    def reviewed() -> uuid.UUID:
        done = booking("completed", -timedelta(days=9))
        return add_review_row(sm, booking=done, tutor_id=w.tutor.profile_id, student=student)

    awaiting = -timedelta(hours=60)  # accepted, ended 59 hours ago: awaiting_outcome
    builders: dict[str, tuple[Callable[[], uuid.UUID], str]] = {
        "hide_profile": (lambda: row("tutor_profile", w.tutor.profile_id), "content_hidden"),
        "hide_booking": (
            lambda: row("booking", booking("accepted", timedelta(days=2))),
            "content_hidden",
        ),
        "cancel_profile": (lambda: row("tutor_profile", w.tutor.profile_id), "booking_cancelled"),
        "cancel_review": (lambda: row("review", reviewed()), "booking_cancelled"),
        "cancel_reply": (
            lambda: row(
                "review_reply",
                add_reply_row(sm, review=reviewed(), tutor_id=w.tutor.profile_id, state="approved"),
            ),
            "booking_cancelled",
        ),
        "cancel_after_start": (
            lambda: row("booking", booking("accepted", -timedelta(minutes=30))),
            "booking_cancelled",
        ),
        "cancel_already_cancelled": (
            lambda: row("booking", booking("cancelled", timedelta(days=2))),
            "booking_cancelled",
        ),
        "complete_not_ended": (
            lambda: row("booking", booking("accepted", timedelta(days=2)), "disputed_outcome"),
            "booking_completed",
        ),
        "complete_already_completed": (
            lambda: row("booking", booking("completed", -timedelta(days=3)), "disputed_outcome"),
            "booking_completed",
        ),
        "complete_not_a_dispute": (
            lambda: row("booking", booking("accepted", awaiting), "harassment"),
            "booking_completed",
        ),
        "complete_note_target": (
            lambda: row(
                "booking_note",
                add_note(sm, booking("accepted", awaiting), student, "student", "It happened"),
                "disputed_outcome",
            ),
            "booking_completed",
        ),
    }
    build, resolution = builders[case]
    return build(), resolution


NOT_APPLICABLE = [
    "hide_profile",
    "hide_booking",
    "cancel_profile",
    "cancel_review",
    "cancel_reply",
    "cancel_after_start",
    "cancel_already_cancelled",
    "complete_not_ended",
    "complete_already_completed",
    "complete_not_a_dispute",
    "complete_note_target",
]


@pytest.mark.parametrize("case", NOT_APPLICABLE)
def test_a11_resolution_not_applicable_cases(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID, case: str
) -> None:
    w = make_world(sm)
    report_id, resolution = _not_applicable_case(sm, w, case)
    with sm() as session:
        before = session.execute(
            sa.text("SELECT id, state::text, updated_at FROM tutor_bookings ORDER BY id")
        ).all()

    result = resolve(client, report_id, resolution)

    assert result["status"] == 409, (case, result)
    assert result["body"]["detail"]["code"] == "resolution_not_applicable"
    assert report_state(sm, report_id) == ("open", None)
    with sm() as session:
        after = session.execute(
            sa.text("SELECT id, state::text, updated_at FROM tutor_bookings ORDER BY id")
        ).all()
    assert after == before  # a refusal writes nothing


@pytest.mark.parametrize("state", ["draft", "suspended", "closed"])
def test_a11_suspend_not_applicable_unless_the_tutor_can_be_suspended(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID, state: str
) -> None:
    tutor = add_tutor(sm, state=state)
    reporter = add_student(sm)
    report_id = add_report_row(
        sm, reporter=reporter, target_type="tutor_profile", target_id=tutor.profile_id
    )

    result = resolve(client, report_id, "tutor_suspended")

    assert result["status"] == 409, result
    assert result["body"]["detail"]["code"] == "resolution_not_applicable"
    assert report_state(sm, report_id) == ("open", None)
    assert inbox(sm, tutor.user_id) == []


def test_a11_already_resolved_unknown_and_note_too_long(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    w = make_world(sm)
    report_id = add_report_row(
        sm, reporter=w.student, target_type="tutor_profile", target_id=w.tutor.profile_id
    )
    too_long = resolve(client, report_id, "dismissed", "x" * 1001)
    assert too_long["status"] == 422
    assert too_long["body"]["detail"]["code"] == "note_too_long"
    assert resolve(client, report_id, "dismissed")["status"] == 200

    again = resolve(client, report_id, "tutor_suspended")
    assert again["status"] == 409
    assert again["body"]["detail"]["code"] == "already_resolved"
    assert report_state(sm, report_id) == ("dismissed", "dismissed")
    assert TutorProfileRepository(sm).for_user(w.tutor.user_id).listing_state.value == "listed"

    unknown = resolve(client, uuid.uuid4(), "dismissed")
    assert unknown["status"] == 404
    assert unknown["body"]["detail"]["code"] == "not_found"


@pytest.mark.parametrize("target_type", ["booking", "booking_note"])
def test_a11_booking_cancelled_before_the_start(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID, target_type: str
) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=3))
    note = add_note(sm, booking, w.tutor.user_id, "tutor", "Come alone")
    target = booking if target_type == "booking" else note
    report_id = file_report(
        sm, student_reporter(w.student), target_type, target, reason="safety_concern"
    )

    result = resolve(client, report_id, "booking_cancelled", "Unsafe meeting place.")

    assert result["status"] == 200, result
    assert result["body"]["resolution"] == "booking_cancelled"
    assert result["body"]["bookingSummary"]["effectiveState"] == "cancelled"
    row = stored(sm, booking)
    assert row.state is BookingState.cancelled
    assert row.cancelled_by_party is BookingParty.platform_admin
    assert row.cancelled_by_user_id == admin
    assert row.cancel_reason == ADMIN_CANCEL_REASON
    assert row.notes_frozen_at is None
    for user in (w.student, parent, w.tutor.user_id):
        rows = inbox(sm, user)
        assert [entry[0] for entry in rows] == ["booking_update"], user
        assert all("Unsafe" not in (entry[2] or "") for entry in rows)


@pytest.mark.parametrize("state", ["accepted", "no_show"])
def test_a11_booking_completed_on_a_disputed_outcome(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID, state: str
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state=state, starts_in=-timedelta(hours=60))
    report_id = file_report(
        sm, student_reporter(w.student), "booking", booking, reason="disputed_outcome"
    )

    result = resolve(client, report_id, "booking_completed")

    assert result["status"] == 200, result
    assert result["body"]["bookingSummary"]["effectiveState"] == "completed"
    assert result["body"]["bookingSummary"]["completedBy"] == "platform_admin"
    row = stored(sm, booking)
    assert row.state is BookingState.completed
    assert row.completed_by_party is BookingParty.platform_admin


def test_a11_suspend_resolution_runs_sanction_sweep(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    """A11 ``tutor_suspended`` is A5's sweep in the resolution's transaction: future sessions
    cancelled by the platform, every live grant revoked ``tutor_suspended``, school-less
    enrolments removed, the listing suspended with its approval event; the freeze is lifted
    and the report actioned. The tutor reads a fixed note, never the admin's resolution note."""
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    own_class = add_class(sm, w.tutor.user_id)
    enrol(sm, own_class, w.student)
    report_id = file_report(
        sm, student_reporter(w.student), "booking", upcoming, reason="safety_concern"
    )
    internal = "Internal: the student described grooming."

    result = resolve(client, report_id, "tutor_suspended", internal)

    assert result["status"] == 200, result
    assert result["body"]["state"] == "actioned"
    assert result["body"]["resolution"] == "tutor_suspended"
    assert result["body"]["resolutionNote"] == internal
    profile = TutorProfileRepository(sm).own_profile(w.tutor.profile_id)
    assert profile is not None
    assert profile.listing_state.value == "suspended"
    assert profile.review_note == REPORT_SUSPENSION_NOTE
    row = stored(sm, upcoming)
    assert row.state is BookingState.cancelled
    assert row.cancelled_by_party is BookingParty.platform_admin
    assert row.notes_frozen_at is None
    assert grant_state(sm, grant)[1] == "tutor_suspended"
    assert classes_of(sm, w.student) == set()
    with sm() as session:
        events = session.execute(
            sa.text(
                "SELECT decision::text, note, admin_user_id FROM tutor_approval_events "
                "WHERE tutor_profile_id = :t"
            ),
            {"t": w.tutor.profile_id},
        ).all()
    assert events == [("suspended", REPORT_SUSPENSION_NOTE, admin)]

    assert sorted(entry[:2] for entry in inbox(sm, w.tutor.user_id)) == [
        ("tutor_access", "Progress sharing ended"),
        ("tutor_listing", "Your tutor profile is suspended"),
    ]
    assert sorted(entry[:2] for entry in inbox(sm, w.student)) == [
        ("booking_update", "Session cancelled"),
        ("tutor_access", "Progress sharing ended"),
    ]
    assert [entry[:2] for entry in inbox(sm, parent)] == [("booking_update", "Session cancelled")]
    for user in (w.tutor.user_id, w.student, parent):
        assert all("grooming" not in (entry[2] or "") for entry in inbox(sm, user))


def test_a11_suspend_rolls_back_with_its_report(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    """One transaction: when the report row cannot be written, the sweep is undone too."""
    w = make_world(sm)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    report_id = file_report(
        sm, student_reporter(w.student), "booking", upcoming, reason="safety_concern"
    )

    refuse_writes(sm, "tutoring_reports", "UPDATE")
    try:
        quiet = TestClient(client.app, raise_server_exceptions=False)
        failed = quiet.post(f"{A9}/{report_id}/resolve", json={"resolution": "tutor_suspended"})
    finally:
        allow_writes(sm, "tutoring_reports")

    assert failed.status_code == 500
    assert TutorProfileRepository(sm).for_user(w.tutor.user_id).listing_state.value == "listed"
    assert stored(sm, upcoming).state is BookingState.accepted
    assert grant_state(sm, grant) == (None, None)
    assert frozen(sm, upcoming)
    assert report_state(sm, report_id) == ("open", None)
    assert inbox(sm, w.tutor.user_id) == []
