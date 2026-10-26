"""After-commit inbox fan-out for the tutoring events (SPEC §b.4, D5.9 §1).

The shape every tutoring change follows:

1. inside the change's transaction, write the state and (for the events that have one) the email
   outbox row with :func:`lemely.db.email_outbox_repo.enqueue_in_session`; commit;
2. after the commit, build the notices with one of the builders here and hand them to
   :func:`send_after_commit`, which writes each inbox row and pushes through
   :func:`lemely.web.notify.notify_safely`. A failure is logged at exception level with the
   seam and the recipient id and never reaches the caller: the action has already succeeded.

**Every title and body is fixed copy built from names and nothing else** (SC-9, CS-9). The
builders take ids, a tutor's public name (``core.tutor_directory.public_name``) and a student's
``student_label`` only: no builder has a parameter for note text, a cancellation reason, a link,
a place or an admin note, so none of them can leak into the inbox, a push, or the persisted
react-query cache. Payloads hold ids only.

Three disclosure rules are encoded in the copy rather than left to the caller:

* a notice to a **tutor** never mentions a parent and never carries the student's id (SC-9: a
  tutor must not learn whether a student has linked parents);
* the notice that a grant ended says only that access ended, never why (SC-11: a block must not
  announce itself);
* a notice to a **tutor** about a review reply carries no booking and no student reference
  (SC-12: timing must not identify the reviewer).

The acting user is never told about their own action: ``actor_user_id`` is dropped from the
recipients.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal
from zoneinfo import ZoneInfo

import structlog

from lemely.db.models.enums import (
    GrantRevokeReason,
    NotificationType,
    ReportReason,
    TutorApprovalDecision,
)
from lemely.web.notify import notify_safely

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    from lemely.db.notification_repo import NotificationService
    from lemely.web.push import NotificationTransport

log = structlog.get_logger(__name__)

BookingEvent = Literal["requested", "accepted", "declined", "cancelled", "completed", "no_show"]
Party = Literal["tutor", "student", "parent"]

DEFAULT_TUTOR_ZONE: Final = "Africa/Cairo"


@dataclass(frozen=True, slots=True)
class InboxNotice:
    """One inbox row to write after commit. ``payload`` holds ids only."""

    user_id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None
    payload: dict[str, str]
    dedupe_key: str
    seam: str


def _parties(
    *,
    tutor_user_id: uuid.UUID,
    student_user_id: uuid.UUID,
    linked_parent_ids: Sequence[uuid.UUID],
    actor_user_id: uuid.UUID | None,
) -> list[tuple[uuid.UUID, Party]]:
    """Every party to a booking except the one who acted, tutor first."""
    everyone: list[tuple[uuid.UUID, Party]] = [
        (tutor_user_id, "tutor"),
        (student_user_id, "student"),
        *((parent, "parent") for parent in linked_parent_ids),
    ]
    return [(user, party) for user, party in everyone if user != actor_user_id]


def _stop(sentence: str) -> str:
    """End ``sentence`` with one full stop (a public name such as "Sara M." already has one)."""
    return sentence if sentence.endswith(".") else f"{sentence}."


def _payload(booking_id: uuid.UUID, party: Party, student_user_id: uuid.UUID) -> dict[str, str]:
    """A parent's link needs the child; a tutor's must not carry the student (SC-9)."""
    payload = {"bookingId": str(booking_id)}
    if party == "parent":
        payload["studentId"] = str(student_user_id)
    return payload


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------


def _booking_copy(
    event: BookingEvent,
    party: Party,
    *,
    tutor_name: str,
    student_label: str,
    late_tutor_cancel: bool,
) -> tuple[str, str]:
    """``(title, body)`` for one recipient. Fixed copy; no reason, link or place."""
    if event == "requested":
        if party == "tutor":
            return "New session request", f"{student_label} asked to book a session."
        return "Session requested", f"A session with {tutor_name} was requested."
    if event == "accepted":
        return "Session accepted", f"{tutor_name} accepted the session request."
    if event == "declined":
        return "Session declined", f"{tutor_name} declined the session request."
    if event == "cancelled":
        if party == "tutor":
            return "Session cancelled", f"A session with {student_label} was cancelled."
        if late_tutor_cancel:
            return "Session cancelled", f"{tutor_name} cancelled your session. Open it to see why."
        return "Session cancelled", f"Your session with {tutor_name} was cancelled."
    other = student_label if party == "tutor" else tutor_name
    if event == "completed":
        return "Session completed", f"Your session with {other} was marked as completed."
    return "No-show recorded", f"Your session with {other} was marked as a no-show."


def booking_notices(
    *,
    event: BookingEvent,
    booking_id: uuid.UUID,
    tutor_user_id: uuid.UUID,
    tutor_name: str,
    student_user_id: uuid.UUID,
    student_label: str,
    linked_parent_ids: Sequence[uuid.UUID],
    actor_user_id: uuid.UUID | None = None,
    late_tutor_cancel: bool = False,
) -> list[InboxNotice]:
    """Notices for a booking transition, to every party except ``actor_user_id``.

    A request goes to the tutor as ``booking_request`` and to the others as ``booking_update``;
    every other event is ``booking_update``. ``late_tutor_cancel`` selects the fixed line for a
    tutor's late cancellation (row 18); the reason itself is read only in the booking.
    """
    notices: list[InboxNotice] = []
    for user_id, party in _parties(
        tutor_user_id=tutor_user_id,
        student_user_id=student_user_id,
        linked_parent_ids=linked_parent_ids,
        actor_user_id=actor_user_id,
    ):
        title, body = _booking_copy(
            event,
            party,
            tutor_name=tutor_name,
            student_label=student_label,
            late_tutor_cancel=late_tutor_cancel,
        )
        is_tutor_request = event == "requested" and party == "tutor"
        notices.append(
            InboxNotice(
                user_id=user_id,
                type=(
                    NotificationType.booking_request
                    if is_tutor_request
                    else NotificationType.booking_update
                ),
                title=title,
                body=body,
                payload=_payload(booking_id, party, student_user_id),
                dedupe_key=f"booking:{booking_id}:{event}",
                seam="tutoring_booking",
            )
        )
    return notices


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def note_notices(
    *,
    note_id: uuid.UUID,
    booking_id: uuid.UUID,
    author: Literal["student", "tutor"],
    tutor_user_id: uuid.UUID,
    tutor_name: str,
    student_user_id: uuid.UUID,
    student_label: str,
    linked_parent_ids: Sequence[uuid.UUID],
    posted_at: datetime,
    tutor_zone: str = DEFAULT_TUTOR_ZONE,
) -> list[InboxNotice]:
    """Notices for a new booking note. The note text is not a parameter and never travels.

    The other participant gets one notice per note. A **tutor-authored** note also notifies each
    linked parent, at most one per booking per tutor-zone day (SC-9): the parent's dedupe key is
    the tutor-zone date, so a second note the same day collides with the first.
    """
    if posted_at.tzinfo is None:
        raise ValueError("posted_at must be timezone-aware")
    notices: list[InboxNotice] = []
    if author == "tutor":
        notices.append(
            InboxNotice(
                user_id=student_user_id,
                type=NotificationType.booking_note,
                title="New note",
                body=_stop(f"New note on your session with {tutor_name}"),
                payload={"bookingId": str(booking_id)},
                dedupe_key=f"note:{note_id}",
                seam="tutoring_note",
            )
        )
        day = posted_at.astimezone(ZoneInfo(tutor_zone)).date().isoformat()
        notices.extend(
            InboxNotice(
                user_id=parent,
                type=NotificationType.booking_note,
                title="New note",
                body=_stop(f"New note on your child's session with {tutor_name}"),
                payload=_payload(booking_id, "parent", student_user_id),
                dedupe_key=f"note-day:{booking_id}:{day}",
                seam="tutoring_note",
            )
            for parent in linked_parent_ids
        )
    else:
        notices.append(
            InboxNotice(
                user_id=tutor_user_id,
                type=NotificationType.booking_note,
                title="New note",
                body=_stop(f"New note on your session with {student_label}"),
                payload={"bookingId": str(booking_id)},
                dedupe_key=f"note:{note_id}",
                seam="tutoring_note",
            )
        )
    return notices


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------


def grant_notices(
    *,
    event: Literal["created", "ended"],
    grant_id: uuid.UUID,
    tutor_user_id: uuid.UUID,
    tutor_name: str,
    student_user_id: uuid.UUID,
    student_label: str,
    linked_parent_ids: Sequence[uuid.UUID],
    ended_reason: GrantRevokeReason | None = None,
) -> list[InboxNotice]:
    """Notices for a data grant being created or ending.

    Created: the tutor and every linked parent. Ended: the tutor, in generic words whatever the
    reason (SC-11), plus the student when the end came from the tutor's suspension or closing.

    Raises:
        ValueError: ``event`` is ``"ended"`` and ``ended_reason`` is missing.
    """
    key = f"grant:{grant_id}:{event}"

    def notice(user_id: uuid.UUID, title: str, body: str, *, parent: bool = False) -> InboxNotice:
        payload = {"grantId": str(grant_id)}
        if parent:
            payload["studentId"] = str(student_user_id)
        return InboxNotice(
            user_id=user_id,
            type=NotificationType.tutor_access,
            title=title,
            body=body,
            payload=payload,
            dedupe_key=key,
            seam="tutoring_grant",
        )

    if event == "created":
        title = "Progress sharing started"
        return [
            notice(tutor_user_id, title, f"{student_label} shared their progress with you."),
            *(
                notice(
                    parent,
                    title,
                    _stop(f"Your child shared their progress with {tutor_name}"),
                    parent=True,
                )
                for parent in linked_parent_ids
            ),
        ]
    if ended_reason is None:
        raise ValueError("an ended grant needs its reason to decide who is told")
    title = "Progress sharing ended"
    notices = [notice(tutor_user_id, title, "Access to progress you could see has ended.")]
    if ended_reason in (GrantRevokeReason.tutor_suspended, GrantRevokeReason.tutor_closed):
        notices.append(
            notice(student_user_id, title, f"{tutor_name} can no longer see your progress.")
        )
    return notices


# ---------------------------------------------------------------------------
# Listing, reviews, parent links, class joins, reports
# ---------------------------------------------------------------------------

_LISTING_COPY: Final[dict[TutorApprovalDecision, tuple[str, str]]] = {
    TutorApprovalDecision.approved: (
        "Your tutor profile is listed",
        "Your profile was approved and is now visible to students.",
    ),
    TutorApprovalDecision.rejected: (
        "Your tutor profile was not approved",
        "Open your profile to see the note from Lemely.",
    ),
    TutorApprovalDecision.suspended: (
        "Your tutor profile is suspended",
        "Open your profile to see the note from Lemely.",
    ),
    TutorApprovalDecision.reinstated: (
        "Your tutor profile is listed again",
        "Your profile is visible to students again.",
    ),
    TutorApprovalDecision.closed: (
        "Your tutor profile is closed",
        "Your profile is no longer visible to students.",
    ),
}


def listing_notices(
    *,
    approval_event_id: uuid.UUID,
    tutor_user_id: uuid.UUID,
    decision: TutorApprovalDecision,
) -> list[InboxNotice]:
    """The tutor's notice for an approval decision. The admin's note is never copied in."""
    title, body = _LISTING_COPY[decision]
    return [
        InboxNotice(
            user_id=tutor_user_id,
            type=NotificationType.tutor_listing,
            title=title,
            body=body,
            payload={"approvalEventId": str(approval_event_id)},
            dedupe_key=f"listing:{approval_event_id}",
            seam="tutoring_listing",
        )
    ]


def review_notices(
    *,
    kind: Literal["review", "reply"],
    target_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    outcome: Literal["approved", "rejected"],
    revision: int,
) -> list[InboxNotice]:
    """The author's notice that a review's text, or a tutor's reply, was moderated.

    ``revision`` counts the text's versions (0 for the first). An edit returns the text to
    pending (SPEC §a.3), so moderating the edited text to the same outcome is a new event and
    must not collide with the first notice's dedupe key.

    The payload is the review or reply id alone: no booking and no student reference, so a
    notice to a tutor cannot identify who wrote the review (SC-12). There is no "new review"
    notice to tutors at all.
    """
    if revision < 0:
        raise ValueError("revision must be zero or more")
    noun = kind
    published = outcome == "approved"
    return [
        InboxNotice(
            user_id=recipient_user_id,
            type=NotificationType.tutor_review,
            title=f"Your {noun} is published" if published else f"Your {noun} was not published",
            body=(
                f"Lemely checked your {noun} and it is now public."
                if published
                else f"Lemely checked your {noun} and did not publish the text."
            ),
            payload={f"{kind}Id": str(target_id)},
            dedupe_key=f"{kind}:{target_id}:{outcome}:{revision}",
            seam="tutoring_review",
        )
    ]


def parent_link_notices(
    *,
    event: Literal["linked", "unlinked"],
    event_id: uuid.UUID,
    recipient_parent_ids: Sequence[uuid.UUID],
) -> list[InboxNotice]:
    """Notices for a parent link change: the unlinked parent, or every parent already linked."""
    if event == "linked":
        title, body = "A parent was added", "Another parent was linked to a child on your account."
    else:
        title, body = "You were unlinked", "Your account was unlinked from a child's account."
    return [
        InboxNotice(
            user_id=parent,
            type=NotificationType.parent_link,
            title=title,
            body=body,
            payload={"eventId": str(event_id)},
            dedupe_key=f"parent-link:{event_id}",
            seam="tutoring_parent_link",
        )
        for parent in recipient_parent_ids
    ]


def class_join_notices(
    *,
    enrollment_id: uuid.UUID,
    student_user_id: uuid.UUID,
    tutor_name: str,
    linked_parent_ids: Sequence[uuid.UUID],
) -> list[InboxNotice]:
    """Notices to a student's linked parents that the child joined a tutor's school-less class."""
    return [
        InboxNotice(
            user_id=parent,
            type=NotificationType.tutor_access,
            title="Child joined a tutor's class",
            body=f"Your child joined a class taught by {tutor_name}, a tutor on Lemely.",
            payload={"enrollmentId": str(enrollment_id), "studentId": str(student_user_id)},
            dedupe_key=f"class-join:{enrollment_id}",
            seam="tutoring_class_join",
        )
        for parent in linked_parent_ids
    ]


def report_notices(
    *,
    report_id: uuid.UUID,
    reason: ReportReason,
    admin_user_ids: Sequence[uuid.UUID],
) -> list[InboxNotice]:
    """Notices to every platform admin for a ``safety_concern`` report; none for other reasons."""
    if reason is not ReportReason.safety_concern:
        return []
    return [
        InboxNotice(
            user_id=admin,
            type=NotificationType.tutoring_report,
            title="New safety report",
            body="A safety concern was reported. Open the reports queue.",
            payload={"reportId": str(report_id)},
            dedupe_key=f"report:{report_id}",
            seam="tutoring_report",
        )
        for admin in admin_user_ids
    ]


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def send_after_commit(
    notices: Sequence[InboxNotice],
    *,
    service: NotificationService,
    transport: NotificationTransport,
) -> None:
    """Write each inbox row and push it. Call only after the change has committed.

    Never raises: :func:`~lemely.web.notify.notify_safely` logs a failed write with the seam and
    recipient id, and a notice that fails does not stop the ones after it. ``transport`` is
    required because ``notify_safely`` pushes through it (payload-less, D5.10).
    """
    for notice in notices:
        try:
            notify_safely(
                service,
                transport,
                user_id=notice.user_id,
                type=notice.type,
                title=notice.title,
                body=notice.body,
                payload=dict(notice.payload),
                dedupe_key=notice.dedupe_key,
                seam=notice.seam,
            )
        except Exception:
            log.exception("tutoring_notice_failed", seam=notice.seam, user_id=str(notice.user_id))


__all__ = [
    "BookingEvent",
    "InboxNotice",
    "booking_notices",
    "class_join_notices",
    "grant_notices",
    "listing_notices",
    "note_notices",
    "parent_link_notices",
    "report_notices",
    "review_notices",
    "send_after_commit",
]
