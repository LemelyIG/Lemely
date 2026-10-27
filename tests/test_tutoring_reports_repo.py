"""Tutoring reports in the repository (PLAN T25; SPEC §a.2 ``tutoring_reports``, §a.4b, §i.4).

SPEC ``docs/tutoring/SPEC.md`` §a.2 (one open report per reporter and target, the quota index,
``target_snapshot``), §a.3 ("Resolution clears ``tutor_bookings.notes_frozen_at``"), §a.4b (the
locks), §b.4 (the quota and the admin notice), §i.4 (the per-``targetType`` snapshot key
allowlist), §i.6 (the tutor row ``FOR UPDATE`` before the review helpers) and THREAT-MODEL SC-10
(the safety freeze). Route behaviour is in ``tests/test_web_tutoring_reports.py`` and
``tests/test_web_admin_tutoring_reports.py``; object-level visibility (O12, O19) in
``tests/test_web_tutoring_authz_reports.py``.

The helpers at the top (seeding, ``reports_client``) are imported by the other T25 test files.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.core.keyset import CursorError
from lemely.db.booking_repo import BookingService
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import (
    BookingParty,
    ReportReason,
    ReportResolution,
    ReportState,
    ReportTargetType,
    Role,
)
from lemely.db.models.tutoring import TutoringReport
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_approval_repo import TutorApprovalRepository
from lemely.db.tutor_evidence_repo import TutorEvidenceRepository
from lemely.db.tutor_grant_repo import TutorGrantRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.db.tutoring_reports_repo import (
    REPORT_QUOTA,
    SNAPSHOT_KEYS,
    STUDENT_AUTHOR_LABEL,
    Reporter,
    ReportRefused,
    ReportsKey,
    TutoringReportsRepository,
    allowed_snapshot,
    parse_reports_cursor,
    reports_cursor,
)
from lemely.db.tutoring_sweeps import TutoringSweeps
from lemely.web import schemas_tutoring_admin
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
    admin_tutoring_reports,
    parent_bookings,
    student_bookings,
    tutor_bookings,
    tutoring_booking,
    tutoring_reports,
)
from lemely.web.routers.admin_tutors import get_tutor_approval_repo
from lemely.web.routers.student_tutor_access import get_tutor_grant_repo
from lemely.web.routers.tutor_evidence import get_tutor_evidence_repo
from lemely.web.schemas_tutoring import TutorCardDTO
from tests.test_booking_repo import World, add_booking, add_parent, make_world
from tests.test_tutor_review_repo import add_reply_row, add_review_row
from tests.test_tutoring_sweeps import add_note
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import (
    DbMirror,
    add_user,
    count_statements,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

SPEC = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"
STUDENT_NAME = "Mariam Hassan"
MEETING_LINK = "https://meet.google.com/abc-defg-hij"


# ---------------------------------------------------------------------------
# Shared helpers (imported by the other T25 test files)
# ---------------------------------------------------------------------------


def reports_client(
    sm: sessionmaker[Session],
    *,
    notifications: object | None = None,
    transport: RecordingPushTransport | None = None,
) -> TestClient:
    """R1, A9-A11 and the booking routes a freeze changes, wired to the test database.

    ``notifications`` replaces the inbox service (the D5.9 proofs pass one that raises).
    """
    app = app_with_routers(
        tutoring_reports.router,
        admin_tutoring_reports.router,
        student_bookings.router,
        parent_bookings.router,
        tutor_bookings.router,
    )
    inbox = (
        notifications
        if notifications is not None
        else NotificationService(sm, NotificationPreferencesService(sm))
    )
    push = transport if transport is not None else RecordingPushTransport()
    sweeps = TutoringSweeps(sm)
    app.dependency_overrides.update(
        {
            tutoring_reports.get_tutoring_reports_repo: lambda: TutoringReportsRepository(
                sm, sweeps=sweeps
            ),
            tutoring_booking.get_booking_service: lambda: BookingService(sm),
            tutor_bookings.get_booking_service: lambda: BookingService(sm),
            get_tutor_profile_repo: lambda: TutorProfileRepository(sm),
            get_tutor_grant_repo: lambda: TutorGrantRepository(sm),
            get_tutor_approval_repo: lambda: TutorApprovalRepository(sm),
            get_tutor_evidence_repo: lambda: TutorEvidenceRepository(sm),
            get_parent_link_service: lambda: ParentLinkService(sm),
            get_class_service: lambda: ClassService(sm),
            get_user_mirror: lambda: DbMirror(sm),
            get_notification_service: lambda: inbox,
            get_push_transport: lambda: push,
        }
    )
    return TestClient(app)


def repo_for(sm: sessionmaker[Session]) -> TutoringReportsRepository:
    return TutoringReportsRepository(sm, sweeps=TutoringSweeps(sm))


def student_reporter(user_id: uuid.UUID) -> Reporter:
    return Reporter(user_id=user_id, party="student")


def file_report(
    sm: sessionmaker[Session],
    reporter: Reporter,
    target_type: str,
    target_id: uuid.UUID,
    *,
    reason: str = "harassment",
    details: str | None = None,
) -> uuid.UUID:
    """R1 as the repository runs it; returns the new report's id."""
    filed = repo_for(sm).file(
        reporter,
        target_type=ReportTargetType(target_type),
        target_id=target_id,
        reason=ReportReason(reason),
        details=details,
    )
    return filed.report_id


def add_report_row(
    sm: sessionmaker[Session],
    *,
    reporter: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    party: str = "student",
    reason: str = "harassment",
    created_at: datetime | None = None,
    resolution: str | None = None,
) -> uuid.UUID:
    """A report row written directly (queue and quota tests); resolved if ``resolution`` is set."""
    column = {
        "tutor_profile": "tutor_profile_id",
        "review": "review_id",
        "review_reply": "reply_id",
        "booking": "booking_id",
        "booking_note": "note_id",
    }[target_type]
    report_id = uuid.uuid4()
    state = (
        ReportState.open
        if resolution is None
        else (ReportState.dismissed if resolution == "dismissed" else ReportState.actioned)
    )
    with sm.begin() as session:
        row = TutoringReport(
            id=report_id,
            reporter_user_id=reporter,
            reporter_party=BookingParty(party),
            target_type=ReportTargetType(target_type),
            target_snapshot={},
            reason=ReportReason(reason),
            state=state,
            resolution=ReportResolution(resolution) if resolution is not None else None,
            resolved_at=datetime.now(UTC) if resolution is not None else None,
            **{column: target_id},
        )
        if created_at is not None:
            row.created_at = created_at
            row.updated_at = created_at
        session.add(row)
    return report_id


def report_state(sm: sessionmaker[Session], report_id: uuid.UUID) -> tuple[str, str | None]:
    with sm() as session:
        row = session.execute(
            sa.text("SELECT state::text, resolution::text FROM tutoring_reports WHERE id = :r"),
            {"r": report_id},
        ).one()
    return str(row[0]), row[1]


def stored_snapshot(sm: sessionmaker[Session], report_id: uuid.UUID) -> dict[str, object]:
    with sm() as session:
        value = session.execute(
            sa.text("SELECT target_snapshot FROM tutoring_reports WHERE id = :r"), {"r": report_id}
        ).scalar_one()
    assert isinstance(value, dict)
    return value


def frozen(sm: sessionmaker[Session], booking_id: uuid.UUID) -> bool:
    with sm() as session:
        value = session.execute(
            sa.text("SELECT notes_frozen_at FROM tutor_bookings WHERE id = :b"), {"b": booking_id}
        ).scalar_one()
    return value is not None


def report_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.execute(sa.text("SELECT count(*) FROM tutoring_reports")).scalar_one())


def refused(excinfo: pytest.ExceptionInfo[ReportRefused]) -> tuple[str, int]:
    return excinfo.value.code, excinfo.value.status


def seeded_targets(sm: sessionmaker[Session], w: World) -> dict[str, uuid.UUID]:
    """One target of each type the world's student may report (a completed, reviewed session)."""
    booking = add_booking(sm, w, state="completed", starts_in=-timedelta(days=9))
    note = add_note(sm, booking, w.student, "student", "See you on Thursday")
    review = add_review_row(
        sm, booking=booking, tutor_id=w.tutor.profile_id, student=w.student, stars=2, text="Late"
    )
    reply = add_reply_row(sm, review=review, tutor_id=w.tutor.profile_id, state="approved")
    return {
        "tutor_profile": w.tutor.profile_id,
        "review": review,
        "review_reply": reply,
        "booking": booking,
        "booking_note": note,
    }


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def repo(sm: sessionmaker[Session]) -> TutoringReportsRepository:
    return repo_for(sm)


# ---------------------------------------------------------------------------
# Snapshot allowlist (SPEC §i.4)
# ---------------------------------------------------------------------------


def _spec_snapshot_keys() -> dict[str, set[str]]:
    """The allowlist read from SPEC §i.4's sentence, each phrase turned into DTO keys.

    "card fields" is ``TutorCardDTO``'s fields; "the ``X`` fields" is that admin DTO's fields;
    any other phrase is camelCased ("author party" -> ``authorParty``).
    """
    text = SPEC.read_text(encoding="utf-8")
    found = re.search(r"per-`targetType` key allowlist \(([^)]*)\)", text)
    assert found is not None, "SPEC §i.4 no longer states the snapshot allowlist"
    allowlist: dict[str, set[str]] = {}
    for part in found.group(1).split(";"):
        name, described = (piece.strip() for piece in part.split(":", 1))
        keys: set[str] = set()
        for phrase in (piece.strip() for piece in described.split(" and ")):
            dto = re.fullmatch(r"the `(\w+)` fields", phrase)
            if phrase == "card fields":
                keys |= set(TutorCardDTO.model_fields)
            elif dto is not None:
                keys |= set(getattr(schemas_tutoring_admin, dto.group(1)).model_fields)
            else:
                first, *rest = phrase.split()
                keys.add(first + "".join(word.capitalize() for word in rest))
        allowlist[name] = keys
    return allowlist


def test_snapshot_allowlist_equals_spec_i4() -> None:
    spec = _spec_snapshot_keys()
    assert set(spec) == {target.value for target in ReportTargetType}  # all five, non-vacuous
    assert {target.value: set(keys) for target, keys in SNAPSHOT_KEYS.items()} == spec


def test_allowed_snapshot_drops_every_key_outside_the_allowlist() -> None:
    raw = {
        "stars": 2,
        "text": "Late",
        "studentId": "x",
        "bookingId": "y",
        "meetingLink": MEETING_LINK,
        "studentName": STUDENT_NAME,
    }
    assert allowed_snapshot(ReportTargetType.review, raw) == {"stars": 2, "text": "Late"}
    assert allowed_snapshot(ReportTargetType.review_reply, raw) == {}
    assert allowed_snapshot(ReportTargetType.booking_note, "not a mapping") == {}


@pytest.mark.parametrize("target_type", [target.value for target in ReportTargetType])
def test_file_stores_only_allowlisted_snapshot_keys(
    sm: sessionmaker[Session], target_type: str
) -> None:
    """Each stored snapshot has exactly its allowlisted keys, and never a student's name, id or
    email, a meeting link, or the reviewer's booking (§a.5, §i.4)."""
    w = make_world(sm, display_name=STUDENT_NAME)
    targets = seeded_targets(sm, w)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE tutor_profiles SET bio = 'Ten years teaching IGCSE.' WHERE id = :t"),
            {"t": w.tutor.profile_id},
        )

    report_id = file_report(sm, student_reporter(w.student), target_type, targets[target_type])

    snapshot = stored_snapshot(sm, report_id)
    assert set(snapshot) == set(SNAPSHOT_KEYS[ReportTargetType(target_type)])
    dumped = json.dumps(snapshot)
    for secret in (STUDENT_NAME, str(w.student), f"{w.student}@example.com", MEETING_LINK):
        assert secret not in dumped
    if target_type in {"review", "review_reply", "tutor_profile"}:
        assert str(targets["booking"]) not in dumped


def test_snapshot_copies_the_content_as_reported(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    targets = seeded_targets(sm, w)
    reporter = student_reporter(w.student)

    note_report = file_report(sm, reporter, "booking_note", targets["booking_note"])
    review_report = file_report(sm, reporter, "review", targets["review"])
    booking_report = file_report(sm, reporter, "booking", targets["booking"])
    profile_report = file_report(sm, reporter, "tutor_profile", targets["tutor_profile"])

    assert stored_snapshot(sm, note_report) == {
        "authorParty": "student",
        "body": "See you on Thursday",
    }
    assert stored_snapshot(sm, review_report) == {"stars": 2, "text": "Late"}
    booking = stored_snapshot(sm, booking_report)
    assert booking["bookingId"] == str(targets["booking"])
    assert booking["effectiveState"] == "completed"
    assert booking["completedBy"] == "tutor"
    assert booking["notesFrozen"] is False
    profile = stored_snapshot(sm, profile_report)
    assert profile["tutorId"] == str(w.tutor.profile_id)
    assert profile["publicName"] == "Sara M."
    assert profile["rating"] == {"state": "new", "average": None, "count": 0}


# ---------------------------------------------------------------------------
# One open report per reporter and target; the quota (SPEC §a.2, §b.4)
# ---------------------------------------------------------------------------


def test_one_open_report_per_reporter_and_target(
    sm: sessionmaker[Session], repo: TutoringReportsRepository
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    parent = add_parent(sm, w.student)
    first = file_report(sm, student_reporter(w.student), "booking", booking)

    with pytest.raises(ReportRefused) as excinfo:
        file_report(sm, student_reporter(w.student), "booking", booking, reason="spam")
    assert refused(excinfo) == ("report_exists", 409)

    # Another reporter, or another target, is a new report.
    file_report(sm, Reporter(user_id=parent, party="parent"), "booking", booking)
    file_report(sm, student_reporter(w.student), "tutor_profile", w.tutor.profile_id)

    # Once resolved, the same reporter may report the same target again.
    admin = add_user(sm, Role.platform_admin)
    repo.resolve(first, admin_user_id=admin, resolution=ReportResolution.dismissed, note=None)
    file_report(sm, student_reporter(w.student), "booking", booking)
    assert report_count(sm) == 4


def test_quota_counts_the_last_24_hours_only(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    reporter = student_reporter(w.student)
    old = datetime.now(UTC) - timedelta(hours=25)
    for _ in range(REPORT_QUOTA):
        booking = add_booking(sm, w, state="cancelled", starts_in=-timedelta(days=3))
        add_report_row(
            sm, reporter=w.student, target_type="booking", target_id=booking, created_at=old
        )
    for _ in range(REPORT_QUOTA - 1):
        file_report(sm, reporter, "booking", add_booking(sm, w, state="cancelled"))
    file_report(sm, reporter, "booking", add_booking(sm, w, state="cancelled"))

    with pytest.raises(ReportRefused) as excinfo:
        file_report(sm, reporter, "booking", add_booking(sm, w, state="cancelled"))
    assert refused(excinfo) == ("too_many_requests", 429)
    assert REPORT_QUOTA == 20  # SPEC §b.4: reports <= 20 per reporter per 24 h


def test_details_are_trimmed_and_bounded(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    reporter = student_reporter(w.student)
    blank = file_report(
        sm, reporter, "booking", add_booking(sm, w, state="declined"), details="   "
    )
    kept = file_report(
        sm, reporter, "booking", add_booking(sm, w, state="declined"), details="  Rude.  "
    )
    with sm() as session:
        stored = dict(
            session.execute(
                sa.text("SELECT id, details FROM tutoring_reports WHERE id IN (:a, :b)"),
                {"a": blank, "b": kept},
            ).all()
        )
    assert stored == {blank: None, kept: "Rude."}

    with pytest.raises(ReportRefused) as excinfo:
        file_report(
            sm, reporter, "booking", add_booking(sm, w, state="declined"), details="x" * 1001
        )
    assert refused(excinfo) == ("text_too_long", 422)
    # A safety report keeps contact details: an admin may need them (SC-7 lists no report field).
    file_report(
        sm,
        reporter,
        "booking",
        add_booking(sm, w, state="declined"),
        details="He asked me to call 01012345678",
    )


# ---------------------------------------------------------------------------
# The safety freeze (SC-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target_type", ["booking", "booking_note"])
def test_safety_report_on_booking_or_note_freezes_the_thread(
    sm: sessionmaker[Session], target_type: str
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = add_note(sm, booking, w.tutor.user_id, "tutor", "Bring the past paper")
    target = booking if target_type == "booking" else note

    filed = repo_for(sm).file(
        Reporter(user_id=w.tutor.user_id, party="tutor"),
        target_type=ReportTargetType(target_type),
        target_id=target,
        reason=ReportReason.safety_concern,
        details=None,
    )

    assert filed.froze_notes is True
    assert frozen(sm, booking)


def test_other_reasons_and_targets_freeze_nothing(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    reporter = student_reporter(w.student)
    admin = add_user(sm, Role.platform_admin)
    other_reasons = [reason for reason in ReportReason if reason is not ReportReason.safety_concern]
    assert len(other_reasons) == 6
    for reason in other_reasons:
        report_id = file_report(sm, reporter, "booking", booking, reason=reason.value)
        assert not frozen(sm, booking), reason
        repo_for(sm).resolve(
            report_id, admin_user_id=admin, resolution=ReportResolution.dismissed, note=None
        )
    file_report(sm, reporter, "tutor_profile", w.tutor.profile_id, reason="safety_concern")
    assert not frozen(sm, booking)


def test_resolution_keeps_the_freeze_while_another_open_safety_report_remains(
    sm: sessionmaker[Session], repo: TutoringReportsRepository
) -> None:
    """Two parties report one booking for safety: resolving the first leaves the second's
    freeze in place (SC-10: "until resolution" of each report); the second's resolution
    clears it."""
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = add_note(sm, booking, w.tutor.user_id, "tutor", "Call me")
    admin = add_user(sm, Role.platform_admin)
    first = file_report(
        sm, student_reporter(w.student), "booking", booking, reason="safety_concern"
    )
    second = file_report(
        sm, Reporter(user_id=parent, party="parent"), "booking_note", note, reason="safety_concern"
    )
    # An open report for another reason does not hold the freeze.
    file_report(sm, Reporter(user_id=parent, party="parent"), "booking", booking, reason="spam")

    repo.resolve(first, admin_user_id=admin, resolution=ReportResolution.dismissed, note=None)
    assert frozen(sm, booking)

    repo.resolve(second, admin_user_id=admin, resolution=ReportResolution.dismissed, note=None)
    assert not frozen(sm, booking)


def test_filed_safety_report_names_every_platform_admin(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    admins = {add_user(sm, Role.platform_admin) for _ in range(2)}
    add_user(sm, Role.school_admin)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))

    filed = repo_for(sm).file(
        student_reporter(w.student),
        target_type=ReportTargetType.booking,
        target_id=booking,
        reason=ReportReason.safety_concern,
        details=None,
    )
    other = repo_for(sm).file(
        student_reporter(w.student),
        target_type=ReportTargetType.tutor_profile,
        target_id=w.tutor.profile_id,
        reason=ReportReason.spam,
        details=None,
    )

    assert set(filed.admin_user_ids) == admins
    assert other.admin_user_ids == ()  # only a safety concern notifies admins (SPEC §b.4)


# ---------------------------------------------------------------------------
# A9 queue (safety first, keyset)
# ---------------------------------------------------------------------------


def test_queue_orders_safety_first_then_oldest_and_pages(
    sm: sessionmaker[Session], repo: TutoringReportsRepository
) -> None:
    w = make_world(sm)
    now = datetime.now(UTC)
    rows = []
    for hours, reason in ((5, "spam"), (4, "safety_concern"), (3, "other"), (2, "safety_concern")):
        booking = add_booking(sm, w, state="cancelled")
        rows.append(
            add_report_row(
                sm,
                reporter=w.student,
                target_type="booking",
                target_id=booking,
                reason=reason,
                created_at=now - timedelta(hours=hours),
            )
        )
    add_report_row(
        sm,
        reporter=w.student,
        target_type="tutor_profile",
        target_id=w.tutor.profile_id,
        resolution="dismissed",
    )
    expected = [rows[1], rows[3], rows[0], rows[2]]

    first = repo.queue(ReportState.open, after=None, limit=3)
    assert first.next_key is not None
    after = parse_reports_cursor(reports_cursor(ReportState.open, first.next_key), ReportState.open)
    second = repo.queue(ReportState.open, after=after, limit=3)
    assert second.next_key is None
    assert [item.report_id for item in (*first.items, *second.items)] == expected
    assert len(repo.queue(ReportState.dismissed, after=None, limit=10).items) == 1


def test_queue_cursor_is_bound_to_its_state() -> None:
    key = ReportsKey(safety=True, created_at=datetime.now(UTC), report_id=uuid.uuid4())
    token = reports_cursor(ReportState.open, key)
    assert parse_reports_cursor(token, ReportState.open) == key
    with pytest.raises(CursorError):
        parse_reports_cursor(token, ReportState.dismissed)


# ---------------------------------------------------------------------------
# A10 and A11 in the repository
# ---------------------------------------------------------------------------


def test_admin_notes_carry_the_party_label_never_the_student_name(
    sm: sessionmaker[Session], repo: TutoringReportsRepository
) -> None:
    w = make_world(sm, display_name=STUDENT_NAME)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = add_note(sm, booking, w.student, "student", "Can we move it?")
    add_note(sm, booking, w.tutor.user_id, "tutor", "Yes")
    report_id = file_report(sm, student_reporter(w.student), "booking_note", note)

    detail = repo.detail_for_admin(report_id, admin_user_id=add_user(sm, Role.platform_admin))

    assert detail is not None
    assert [(n.author_party, n.author_name) for n in detail.notes] == [
        ("student", STUDENT_AUTHOR_LABEL),
        ("tutor", "Sara M."),
    ]
    assert STUDENT_AUTHOR_LABEL == "Student"


def test_resolve_locks_the_tutor_row_for_update_before_the_report_and_the_booking(
    sm: sessionmaker[Session], repo: TutoringReportsRepository
) -> None:
    """SPEC §a.4b and §i.6/§i.7: the tutor row ``FOR UPDATE`` comes first (a share lock
    upgraded later deadlocks), then the report row, then the booking and note rows."""
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = add_note(sm, booking, w.tutor.user_id, "tutor", "Off-platform please")
    report_id = file_report(
        sm, student_reporter(w.student), "booking_note", note, reason="safety_concern"
    )
    admin = add_user(sm, Role.platform_admin)

    with count_statements(sm) as seen:
        repo.resolve(
            report_id, admin_user_id=admin, resolution=ReportResolution.content_hidden, note=None
        )

    def first(pattern: str) -> int:
        regex = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        found = [i for i, statement in enumerate(seen) if regex.search(statement)]
        assert found, f"no statement matches {pattern!r}"
        return found[0]

    tutor_lock = first(r"FROM tutor_profiles.*FOR UPDATE")
    report_lock = first(r"FROM tutoring_reports.*FOR UPDATE")
    note_write = first(r"UPDATE tutor_booking_notes")
    booking_write = first(r"UPDATE tutor_bookings")
    assert tutor_lock < report_lock < note_write < booking_write
    assert not any(
        re.search(r"FROM tutor_profiles.*FOR SHARE", statement, re.DOTALL)
        for statement in seen[:tutor_lock]
    )
