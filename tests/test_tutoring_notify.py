"""After-commit inbox fan-out for the tutoring events (SPEC §b.4, SC-5, SC-9, SC-11, SC-12).

The builders are pure: ids and public names in, ``InboxNotice`` out. Nothing here can carry note
text, a reason, a link or a place, because no builder accepts one (checked from the signatures).
"""

from __future__ import annotations

import inspect
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
import structlog.testing

from lemely.db.email_outbox_repo import enqueue_in_session
from lemely.db.models.enums import (
    GrantRevokeReason,
    NotificationType,
    ReportReason,
    Role,
    TutorApprovalDecision,
)
from lemely.db.models.ops import Notification
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.users import User
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.io.notify_email import EMAIL_TEMPLATES
from lemely.web.push import RecordingPushTransport
from lemely.web.tutoring_notify import (
    InboxNotice,
    booking_notices,
    class_join_notices,
    grant_notices,
    listing_notices,
    note_notices,
    parent_link_notices,
    report_notices,
    review_notices,
    send_after_commit,
)
from tests import test_email_outbox_repo as _outbox
from tests.test_email_outbox_repo import NOW, _user
from tests.test_notify_email import VALID, spec_b4_rows, spec_listing_copy

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

pg_sessionmaker = _outbox.pg_sessionmaker

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

TUTOR = uuid.UUID("a0000000-0000-4000-8000-000000000001")
STUDENT = uuid.UUID("a0000000-0000-4000-8000-000000000002")
PARENT_1 = uuid.UUID("a0000000-0000-4000-8000-000000000003")
PARENT_2 = uuid.UUID("a0000000-0000-4000-8000-000000000004")
ADMIN = uuid.UUID("a0000000-0000-4000-8000-000000000005")
BOOKING = uuid.UUID("b0000000-0000-4000-8000-000000000001")
NOTE_1 = uuid.UUID("b0000000-0000-4000-8000-000000000002")
NOTE_2 = uuid.UUID("b0000000-0000-4000-8000-000000000003")
GRANT = uuid.UUID("b0000000-0000-4000-8000-000000000004")
EVENT = uuid.UUID("b0000000-0000-4000-8000-000000000005")
REVIEW = uuid.UUID("b0000000-0000-4000-8000-000000000006")
ENROLMENT = uuid.UUID("b0000000-0000-4000-8000-000000000007")
REPORT = uuid.UUID("b0000000-0000-4000-8000-000000000008")

PARENTS = [PARENT_1, PARENT_2]

#: Where each decision may leave a profile (SPEC §a.3; only a reinstatement can end either way).
LISTED_AFTER: dict[TutorApprovalDecision, tuple[bool, ...]] = {
    TutorApprovalDecision.approved: (True,),
    TutorApprovalDecision.rejected: (False,),
    TutorApprovalDecision.suspended: (False,),
    TutorApprovalDecision.reinstated: (True, False),
    TutorApprovalDecision.closed: (False,),
}
LISTING_CASES = [
    (decision, listed) for decision, values in LISTED_AFTER.items() for listed in values
]


def _booking(event: str, *, actor: uuid.UUID | None, late: bool = False) -> list[InboxNotice]:
    return booking_notices(
        event=event,  # type: ignore[arg-type]
        booking_id=BOOKING,
        tutor_user_id=TUTOR,
        tutor_name="Sara M.",
        student_user_id=STUDENT,
        student_label="Student 3F2A",
        linked_parent_ids=PARENTS,
        actor_user_id=actor,
        late_tutor_cancel=late,
    )


def _by_user(notices: list[InboxNotice]) -> dict[uuid.UUID, InboxNotice]:
    mapping = {n.user_id: n for n in notices}
    assert len(mapping) == len(notices), "one notice per recipient"
    return mapping


def _note(
    note_id: uuid.UUID,
    author: str,
    *,
    posted_at: datetime,
    parents: list[uuid.UUID] | None = None,
) -> list[InboxNotice]:
    return note_notices(
        note_id=note_id,
        booking_id=BOOKING,
        author=author,  # type: ignore[arg-type]
        tutor_user_id=TUTOR,
        tutor_name="Sara M.",
        student_user_id=STUDENT,
        student_label="Student 3F2A",
        linked_parent_ids=PARENTS if parents is None else parents,
        posted_at=posted_at,
    )


def _every_builder_output() -> list[InboxNotice]:
    """A broad sample: every builder, every event, so the scans below cover the whole table."""
    out: list[InboxNotice] = []
    for event in ("requested", "accepted", "declined", "cancelled", "completed", "no_show"):
        out += _booking(event, actor=None)
    out += _booking("cancelled", actor=TUTOR, late=True)
    out += _note(NOTE_1, "tutor", posted_at=NOW)
    out += _note(NOTE_2, "student", posted_at=NOW)
    for gevent, reason in (
        ("created", None),
        ("ended", GrantRevokeReason.student),
        ("ended", GrantRevokeReason.block),
        ("ended", GrantRevokeReason.tutor_suspended),
        ("ended", GrantRevokeReason.tutor_closed),
    ):
        out += grant_notices(
            event=gevent,  # type: ignore[arg-type]
            grant_id=GRANT,
            tutor_user_id=TUTOR,
            tutor_name="Sara M.",
            student_user_id=STUDENT,
            student_label="Student 3F2A",
            linked_parent_ids=PARENTS,
            ended_reason=reason,
        )
    for decision, listed in LISTING_CASES:
        out += listing_notices(
            approval_event_id=EVENT, tutor_user_id=TUTOR, decision=decision, listed=listed
        )
    for kind in ("review", "reply"):
        for outcome in ("approved", "rejected"):
            out += review_notices(
                kind=kind,  # type: ignore[arg-type]
                target_id=REVIEW,
                recipient_user_id=STUDENT,
                outcome=outcome,  # type: ignore[arg-type]
                revision=1,
            )
    for link_event in ("linked", "unlinked"):
        out += parent_link_notices(
            event=link_event,  # type: ignore[arg-type]
            event_id=EVENT,
            recipient_parent_ids=PARENTS,
        )
    out += class_join_notices(
        enrollment_id=ENROLMENT,
        student_user_id=STUDENT,
        tutor_name="Sara M.",
        linked_parent_ids=PARENTS,
    )
    out += report_notices(
        report_id=REPORT, reason=ReportReason.safety_concern, admin_user_ids=[ADMIN]
    )
    return out


# -- booking ------------------------------------------------------------------


def test_booking_requested_by_a_student_tells_the_tutor_and_every_parent() -> None:
    notices = _by_user(_booking("requested", actor=STUDENT))

    assert set(notices) == {TUTOR, *PARENTS}  # the requester is never told about their own act
    assert notices[TUTOR].type is NotificationType.booking_request
    assert notices[PARENT_1].type is NotificationType.booking_update
    assert {n.dedupe_key for n in notices.values()} == {f"booking:{BOOKING}:requested"}


def test_booking_requested_by_a_parent_also_tells_the_student() -> None:
    notices = _by_user(_booking("requested", actor=PARENT_1))

    assert set(notices) == {TUTOR, STUDENT, PARENT_2}
    assert notices[STUDENT].type is NotificationType.booking_update
    assert notices[TUTOR].type is NotificationType.booking_request


@pytest.mark.parametrize("event", ["accepted", "declined"])
def test_accepted_and_declined_tell_the_student_and_parents_but_not_the_tutor(event: str) -> None:
    notices = _by_user(_booking(event, actor=TUTOR))

    assert set(notices) == {STUDENT, *PARENTS}
    assert {n.type for n in notices.values()} == {NotificationType.booking_update}
    assert {n.dedupe_key for n in notices.values()} == {f"booking:{BOOKING}:{event}"}


def test_cancelled_by_the_student_tells_the_tutor_and_parents() -> None:
    notices = _by_user(_booking("cancelled", actor=STUDENT))
    assert set(notices) == {TUTOR, *PARENTS}
    assert notices[TUTOR].body == "A session with Student 3F2A was cancelled."
    assert notices[PARENT_1].body == "Your session with Sara M. was cancelled."


def test_late_cancel_notice_and_email_carry_no_reason_text() -> None:
    notices = _by_user(_booking("cancelled", actor=TUTOR, late=True))

    assert set(notices) == {STUDENT, *PARENTS}
    assert {n.body for n in notices.values()} == {
        "Sara M. cancelled your session. Open it to see why."
    }
    # No builder accepts a reason, and the cancellation email schema has no field to carry one.
    for builder in (booking_notices, note_notices, grant_notices, listing_notices):
        names = set(inspect.signature(builder).parameters)
        banned = r"(^|_)(reason|text|message|link|place|body|content)($|_)"
        assert {n for n in names if re.search(banned, n)} <= {"ended_reason"}, names
    assert not any(
        "reason" in field
        for field in EMAIL_TEMPLATES["booking_cancelled"].context_fields  # type: ignore[attr-defined]
    )
    assert not any("reason" in str(value).lower() for value in VALID["booking_cancelled"].values())


@pytest.mark.parametrize(
    ("event", "actor", "expected"),
    [
        ("completed", TUTOR, {STUDENT, *PARENTS}),
        ("completed", STUDENT, {TUTOR, *PARENTS}),
        ("completed", PARENT_1, {TUTOR, STUDENT, PARENT_2}),
        ("no_show", TUTOR, {STUDENT, *PARENTS}),
    ],
)
def test_completed_and_no_show_recipients(
    event: str, actor: uuid.UUID, expected: set[uuid.UUID]
) -> None:
    assert set(_by_user(_booking(event, actor=actor))) == expected


def test_a_system_or_admin_action_tells_every_party() -> None:
    assert set(_by_user(_booking("cancelled", actor=None))) == {TUTOR, STUDENT, *PARENTS}


def test_tutor_facing_notices_never_hint_that_a_parent_exists() -> None:
    """SC-9: a tutor never learns whether a student has linked parents."""
    for event in ("requested", "cancelled", "completed"):
        actor = PARENT_1 if event == "requested" else None
        notice = _by_user(_booking(event, actor=actor))[TUTOR]
        text = f"{notice.title} {notice.body}".lower()
        assert "parent" not in text
        assert set(notice.payload) == {"bookingId"}


def test_parent_notices_carry_the_child_id_so_the_screen_can_link() -> None:
    notices = _by_user(_booking("accepted", actor=TUTOR))
    assert notices[PARENT_1].payload == {"bookingId": str(BOOKING), "studentId": str(STUDENT)}
    assert notices[STUDENT].payload == {"bookingId": str(BOOKING)}


# -- notes --------------------------------------------------------------------


def test_notify_note_notification_has_no_body_text() -> None:
    names = set(inspect.signature(note_notices).parameters)
    assert not {n for n in names if re.search(r"text|content|message|comment", n)}
    notices = _by_user(_note(NOTE_1, "student", posted_at=NOW))
    assert set(notices) == {TUTOR}
    assert notices[TUTOR].type is NotificationType.booking_note
    assert notices[TUTOR].body == "New note on your session with Student 3F2A."
    assert notices[TUTOR].dedupe_key == f"note:{NOTE_1}"


def test_notify_parent_notified_of_tutor_note_without_text() -> None:
    notices = _by_user(_note(NOTE_1, "tutor", posted_at=NOW))

    assert set(notices) == {STUDENT, *PARENTS}
    assert notices[STUDENT].body == "New note on your session with Sara M."
    for parent in PARENTS:
        assert notices[parent].type is NotificationType.booking_note
        assert notices[parent].body == "New note on your child's session with Sara M."
        assert notices[parent].payload == {"bookingId": str(BOOKING), "studentId": str(STUDENT)}


def test_parent_note_notice_once_per_day_tutor_notes_only(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = _user(pg_sessionmaker, role=Role.parent)
    student = _user(pg_sessionmaker, role=Role.student)
    tutor = _user(pg_sessionmaker, role=Role.teacher)
    service = NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))
    transport = RecordingPushTransport()

    def notices(note_id: uuid.UUID, author: str, posted_at: datetime) -> list[InboxNotice]:
        return note_notices(
            note_id=note_id,
            booking_id=BOOKING,
            author=author,  # type: ignore[arg-type]
            tutor_user_id=tutor,
            tutor_name="Sara M.",
            student_user_id=student,
            student_label="Student 3F2A",
            linked_parent_ids=[parent],
            posted_at=posted_at,
        )

    # 18:00 and 20:00 UTC on 5 Oct are the same Cairo day; 22:30 UTC is 01:30 on the 6th in Cairo.
    first = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)
    for note_id, author, at in (
        (uuid.uuid4(), "tutor", first),
        (uuid.uuid4(), "tutor", first + timedelta(hours=2)),
        (uuid.uuid4(), "student", first + timedelta(hours=3)),
    ):
        send_after_commit(notices(note_id, author, at), service=service, transport=transport)

    def parent_rows() -> int:
        with pg_sessionmaker() as session:
            return int(
                session.scalar(
                    sa.select(sa.func.count())
                    .select_from(Notification)
                    .where(Notification.user_id == parent)
                )
                or 0
            )

    assert (
        parent_rows() == 1
    )  # two tutor notes the same Cairo day, one notice; the student note adds none

    send_after_commit(
        notices(uuid.uuid4(), "tutor", first + timedelta(hours=4, minutes=30)),
        service=service,
        transport=transport,
    )
    assert parent_rows() == 2  # the next tutor-zone day starts a new notice


def test_the_day_key_is_the_tutor_zone_date_not_the_utc_date() -> None:
    late_utc = datetime(2026, 10, 5, 22, 30, tzinfo=UTC)  # 01:30 on 6 Oct in Cairo
    keys = {
        n.dedupe_key for n in _note(NOTE_1, "tutor", posted_at=late_utc) if n.user_id == PARENT_1
    }
    assert keys == {f"note-day:{BOOKING}:2026-10-06"}


def test_two_notes_one_booking_two_notices(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _user(pg_sessionmaker, role=Role.student)
    tutor = _user(pg_sessionmaker, role=Role.teacher)
    service = NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))

    for note_id in (uuid.uuid4(), uuid.uuid4()):
        send_after_commit(
            note_notices(
                note_id=note_id,
                booking_id=BOOKING,
                author="student",
                tutor_user_id=tutor,
                tutor_name="Sara M.",
                student_user_id=student,
                student_label="Student 3F2A",
                linked_parent_ids=[],
                posted_at=NOW,
            ),
            service=service,
            transport=RecordingPushTransport(),
        )
    with pg_sessionmaker() as session:
        count = session.scalar(
            sa.select(sa.func.count())
            .select_from(Notification)
            .where(Notification.user_id == tutor)
        )
    assert count == 2


# -- grants, listing, reviews, links, reports ----------------------------------


def _grant(event: str, reason: GrantRevokeReason | None = None) -> dict[uuid.UUID, InboxNotice]:
    return _by_user(
        grant_notices(
            event=event,  # type: ignore[arg-type]
            grant_id=GRANT,
            tutor_user_id=TUTOR,
            tutor_name="Sara M.",
            student_user_id=STUDENT,
            student_label="Student 3F2A",
            linked_parent_ids=PARENTS,
            ended_reason=reason,
        )
    )


def test_grant_created_tells_the_tutor_and_parents() -> None:
    notices = _grant("created")
    assert set(notices) == {TUTOR, *PARENTS}
    assert {n.type for n in notices.values()} == {NotificationType.tutor_access}
    assert {n.dedupe_key for n in notices.values()} == {f"grant:{GRANT}:created"}


@pytest.mark.parametrize("reason", [GrantRevokeReason.student, GrantRevokeReason.block])
def test_grant_ended_by_the_student_or_a_block_tells_only_the_tutor_in_generic_words(
    reason: GrantRevokeReason,
) -> None:
    """SC-11: the tutor is told access ended, never why (a block must not announce itself)."""
    notices = _grant("ended", reason)
    assert set(notices) == {TUTOR}
    text = f"{notices[TUTOR].title} {notices[TUTOR].body}".lower()
    for word in ("block", "revok", "student", "suspend", "report", "parent"):
        assert word not in text
    assert notices[TUTOR].dedupe_key == f"grant:{GRANT}:ended"


@pytest.mark.parametrize(
    "reason", [GrantRevokeReason.tutor_suspended, GrantRevokeReason.tutor_closed]
)
def test_grant_ended_by_suspension_or_close_also_tells_the_student(
    reason: GrantRevokeReason,
) -> None:
    notices = _grant("ended", reason)
    assert set(notices) == {TUTOR, STUDENT}
    assert notices[STUDENT].body == "Sara M. can no longer see your progress."


def test_an_ended_grant_without_a_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="reason"):
        _grant("ended", None)


@pytest.mark.parametrize(("decision", "listed"), LISTING_CASES)
def test_listing_notice_names_the_decision_and_never_the_admin_note(
    decision: TutorApprovalDecision, listed: bool
) -> None:
    (notice,) = listing_notices(
        approval_event_id=EVENT, tutor_user_id=TUTOR, decision=decision, listed=listed
    )
    assert notice.user_id == TUTOR
    assert notice.type is NotificationType.tutor_listing
    assert notice.dedupe_key == f"listing:{EVENT}"
    assert notice.payload == {"approvalEventId": str(EVENT)}
    assert not {n for n in inspect.signature(listing_notices).parameters if "note" in n}


def test_every_decision_is_covered_by_the_listing_cases() -> None:
    assert set(LISTED_AFTER) == set(TutorApprovalDecision)
    assert len(LISTING_CASES) == 6  # non-vacuity: five decisions, reinstatement both ways


@pytest.mark.parametrize(("listed", "outcome"), [(True, "listed"), (False, "pending_review")])
def test_reinstatement_notice_says_where_the_profile_went(listed: bool, outcome: str) -> None:
    """T10 EXTRA: back to review is "back in review", never "listed again" (SPEC §b.4)."""
    (notice,) = listing_notices(
        approval_event_id=EVENT,
        tutor_user_id=TUTOR,
        decision=TutorApprovalDecision.reinstated,
        listed=listed,
    )
    assert notice.title == spec_listing_copy()[outcome]


@pytest.mark.parametrize(
    ("decision", "listed"),
    [
        (decision, listed)
        for decision in TutorApprovalDecision
        for listed in (True, False)
        if listed not in LISTED_AFTER[decision]
    ],
)
def test_a_listing_notice_that_would_be_false_is_refused(
    decision: TutorApprovalDecision, listed: bool
) -> None:
    with pytest.raises(ValueError, match="listed"):
        listing_notices(
            approval_event_id=EVENT, tutor_user_id=TUTOR, decision=decision, listed=listed
        )


def test_idor_tutor_review_notification_has_no_booking_or_student_ref() -> None:
    """SC-12: a reply-moderation notice to the tutor holds nothing that identifies the reviewer."""
    (notice,) = review_notices(
        kind="reply", target_id=REVIEW, recipient_user_id=TUTOR, outcome="approved", revision=0
    )
    assert notice.type is NotificationType.tutor_review
    assert notice.user_id == TUTOR
    blob = json.dumps([notice.title, notice.body, notice.payload, notice.dedupe_key]).lower()
    for forbidden in (str(BOOKING), str(STUDENT), "booking", "student", "reviewer"):
        assert forbidden not in blob
    assert set(notice.payload) == {"replyId"}
    assert not {
        name
        for name in inspect.signature(review_notices).parameters
        if re.search(r"booking|student", name)
    }


def test_review_text_moderation_notice_goes_to_the_author_with_the_review_id() -> None:
    (notice,) = review_notices(
        kind="review", target_id=REVIEW, recipient_user_id=STUDENT, outcome="rejected", revision=2
    )
    assert notice.user_id == STUDENT
    assert notice.payload == {"reviewId": str(REVIEW)}
    assert notice.dedupe_key == f"review:{REVIEW}:rejected:2"


def test_re_moderating_an_edited_review_to_the_same_outcome_sends_a_second_notice(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """R5: an edit returns the text to pending (SPEC §a.3); approving it again is a new event."""
    author = _user(pg_sessionmaker, role=Role.student)
    service = NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))

    def moderate(revision: int) -> None:
        send_after_commit(
            review_notices(
                kind="review",
                target_id=REVIEW,
                recipient_user_id=author,
                outcome="approved",
                revision=revision,
            ),
            service=service,
            transport=RecordingPushTransport(),
        )

    def rows() -> int:
        with pg_sessionmaker() as session:
            return int(session.scalar(sa.select(sa.func.count()).select_from(Notification)) or 0)

    moderate(0)
    moderate(0)  # the same moderation delivered twice is still one notice
    assert rows() == 1
    moderate(1)  # the edited text, approved again
    assert rows() == 2


def test_a_negative_revision_is_refused() -> None:
    with pytest.raises(ValueError, match="revision"):
        review_notices(
            kind="review",
            target_id=REVIEW,
            recipient_user_id=STUDENT,
            outcome="approved",
            revision=-1,
        )


@pytest.mark.parametrize("event", ["linked", "unlinked"])
def test_parent_link_notices_go_to_the_given_parents_only(event: str) -> None:
    notices = parent_link_notices(
        event=event,  # type: ignore[arg-type]
        event_id=EVENT,
        recipient_parent_ids=[PARENT_1],
    )
    assert [n.user_id for n in notices] == [PARENT_1]
    assert notices[0].type is NotificationType.parent_link
    assert notices[0].dedupe_key == f"parent-link:{EVENT}"
    assert notices[0].payload == {"eventId": str(EVENT)}


def test_class_join_notices_go_to_every_linked_parent() -> None:
    notices = class_join_notices(
        enrollment_id=ENROLMENT,
        student_user_id=STUDENT,
        tutor_name="Sara M.",
        linked_parent_ids=PARENTS,
    )
    assert {n.user_id for n in notices} == set(PARENTS)
    assert {n.type for n in notices} == {NotificationType.tutor_access}
    assert {n.dedupe_key for n in notices} == {f"class-join:{ENROLMENT}"}
    assert notices[0].payload == {"enrollmentId": str(ENROLMENT), "studentId": str(STUDENT)}


def test_only_a_safety_concern_report_notifies_the_admins() -> None:
    sent = report_notices(
        report_id=REPORT, reason=ReportReason.safety_concern, admin_user_ids=[ADMIN]
    )
    assert [(n.user_id, n.type) for n in sent] == [(ADMIN, NotificationType.tutoring_report)]
    assert sent[0].dedupe_key == f"report:{REPORT}"
    for reason in ReportReason:
        if reason is not ReportReason.safety_concern:
            assert report_notices(report_id=REPORT, reason=reason, admin_user_ids=[ADMIN]) == []


# -- cross-cutting scans over every builder -------------------------------------


def test_every_payload_holds_ids_only_and_copy_is_fixed() -> None:
    notices = _every_builder_output()
    assert len(notices) >= 40  # non-vacuity
    for notice in notices:
        assert notice.payload, notice
        assert all(UUID_RE.match(value) for value in notice.payload.values()), notice
        assert all(re.fullmatch(r"[a-z][A-Za-z]+Id", key) for key in notice.payload), notice
        for text in (notice.title, notice.body or ""):
            assert "!" not in text and "—" not in text and "@" not in text
            assert "http" not in text.lower()
        assert notice.body and len(notice.body) <= 100
        assert notice.seam.startswith("tutoring_")


def test_dedupe_keys_match_spec_table() -> None:
    """Every key the builders emit matches a template in SPEC §b.4's inbox-key column, and each
    template is produced by at least one builder."""
    templates: list[str] = []
    for row in spec_b4_rows():
        templates += re.findall(r"`([^`]+)`", row[2])
    assert len(templates) >= 13  # non-vacuity: thirteen key shapes in the spec table

    def pattern(template: str) -> re.Pattern[str]:
        escaped = re.escape(template)
        escaped = escaped.replace(re.escape("{yyyy-mm-dd}"), r"\d{4}-\d{2}-\d{2}")
        escaped = re.sub(r"\\\{event\\\}", r"[a-z_]+", escaped)
        escaped = re.sub(r"\\\{revision\\\}", r"\\d+", escaped)
        escaped = re.sub(r"\\\{[a-z_]+_id\\\}", r"[0-9a-f-]{36}", escaped)
        return re.compile(f"^{escaped}$")

    patterns = [pattern(t) for t in templates]
    produced = {n.dedupe_key for n in _every_builder_output()}
    for key in produced:
        assert any(p.match(key) for p in patterns), key
    for template, compiled in zip(templates, patterns, strict=True):
        assert any(compiled.match(key) for key in produced), template


# -- send_after_commit -----------------------------------------------------------


def test_transition_commits_when_inbox_write_raises(pg_sessionmaker: sessionmaker[Session]) -> None:
    """D5.9 §1: the state change and its outbox row are committed first; a broken inbox write is
    logged and swallowed, never raised back into the request."""
    recipient = _user(pg_sessionmaker, role=Role.teacher)
    changed = uuid.uuid4()
    with pg_sessionmaker.begin() as session:  # the "transition": a change plus its outbox row
        session.add(User(id=changed, email=f"{changed}@example.org", role=Role.student))
        enqueue_in_session(
            session,
            recipient_user_id=recipient,
            template="booking_requested",
            context=VALID["booking_requested"],
            dedupe_key="transition",
        )

    class _BrokenService:
        def create(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("inbox is down")

    notices = _booking("requested", actor=STUDENT)
    with structlog.testing.capture_logs() as logs:
        send_after_commit(
            notices,
            service=_BrokenService(),  # type: ignore[arg-type]
            transport=RecordingPushTransport(),
        )

    with pg_sessionmaker() as session:
        assert session.get(User, changed) is not None
        assert session.scalar(sa.select(sa.func.count()).select_from(EmailOutbox)) == 1
    failures = [log for log in logs if log["event"] == "notification_create_failed"]
    assert len(failures) == len(notices)
    assert all(
        log["log_level"] == "error" and log["seam"].startswith("tutoring_") for log in failures
    )


def test_send_after_commit_writes_each_inbox_row_and_pushes(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    tutor = _user(pg_sessionmaker, role=Role.teacher)
    student = _user(pg_sessionmaker, role=Role.student)
    service = NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))
    notices = booking_notices(
        event="accepted",
        booking_id=BOOKING,
        tutor_user_id=tutor,
        tutor_name="Sara M.",
        student_user_id=student,
        student_label="Student 3F2A",
        linked_parent_ids=[],
        actor_user_id=tutor,
    )

    send_after_commit(notices, service=service, transport=RecordingPushTransport())
    send_after_commit(notices, service=service, transport=RecordingPushTransport())  # a re-run

    with pg_sessionmaker() as session:
        rows = list(session.scalars(sa.select(Notification)))
    assert [(r.user_id, r.type, r.dedupe_key) for r in rows] == [
        (student, NotificationType.booking_update, f"booking:{BOOKING}:accepted")
    ]
    assert rows[0].body == "Sara M. accepted the session request."
    assert rows[0].payload == {"bookingId": str(BOOKING)}


def test_one_failing_recipient_does_not_stop_the_rest(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    good = _user(pg_sessionmaker, role=Role.student)
    real = NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))
    calls: list[uuid.UUID] = []

    class _FlakyService:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def create(self, user_id: uuid.UUID, *args: object, **kwargs: object) -> object:
            calls.append(user_id)
            if user_id == PARENT_1:
                raise RuntimeError("one recipient is broken")
            return real.create(user_id, *args, **kwargs)  # type: ignore[arg-type]

    notices = [
        InboxNotice(
            PARENT_1,
            NotificationType.booking_update,
            "t",
            "b",
            {"bookingId": str(BOOKING)},
            "k1",
            "tutoring_test",
        ),
        InboxNotice(
            good,
            NotificationType.booking_update,
            "t",
            "b",
            {"bookingId": str(BOOKING)},
            "k2",
            "tutoring_test",
        ),
    ]
    send_after_commit(notices, service=_FlakyService(), transport=RecordingPushTransport())  # type: ignore[arg-type]

    assert calls == [PARENT_1, good]
    with pg_sessionmaker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Notification)) == 1
