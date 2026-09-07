"""The notification jobs a sweeper runs, and the fan-out they share with the composer.

Push-delivery spec §1, §2 and §4. Three jobs live here:

* :func:`publish_due_announcements` — claim announcements whose ``publish_at``
  has passed and notify their audience (§1).
* :func:`warn_streaks` — ``streak_warning`` at 19:00 in each student's own
  zone (§2). Added by a later task.
* :func:`remind_study_plans` — ``study_plan_reminder`` at 08:00 in each
  student's own zone (§2). Added by a later task.

**Idempotency is migration 0018's unique index, not anything in this file.**
Every job passes a ``dedupe_key`` that names the thing being announced (the
announcement id, the student's civil date, the session id), so a re-run —
after a crash, on a second replica, on the next minute's pass — comes back
``outcome=duplicate, push_allowed=False`` from
:meth:`~lemely.db.notification_repo.NotificationService.create` and neither a
duplicate inbox row nor a duplicate push can occur.

:func:`notify_announcement_audience` used to be ``_notify_audience`` in
:mod:`lemely.web.routers.announcements`. It moved here so the composer and
the sweeper share one implementation of "tell the audience"; the router still
calls it for a post that is due the moment it is written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from lemely.db.announcement_repo import DEFAULT_CLAIM_LIMIT
from lemely.db.models.enums import NotificationType
from lemely.web.notify import notify_safely

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from lemely.db.announcement_repo import AnnouncementRow, AnnouncementService
    from lemely.db.notification_repo import NotificationService
    from lemely.web.push import NotificationTransport

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Announcements (§1).
# ---------------------------------------------------------------------------


def notify_announcement_audience(
    service: AnnouncementService,
    notifications: NotificationService,
    transport: NotificationTransport,
    rows: Sequence[AnnouncementRow],
) -> bool:
    """Tell each row's audience. Returns ``True`` when the loop ran to the end.

    Runs after the rows are already written, exactly like ``award_xp_safely``
    and the ``grade_ready`` seam: the announcement exists and stays existing
    whatever happens here (D5.9 §1). ``notify_safely`` already swallows
    per-recipient failures, but the **audience lookup** is a query of our own
    and sits outside it, so the whole loop is wrapped — a teacher must never
    see a 500 for a post that went out fine, and a sweeper pass must never die
    on one row. ``False`` tells the caller not to stamp ``notified_at``: the
    audience was not fully told, and leaving the row unstamped is what lets
    the next pass try again.

    D5.9 §6 fixes this seam's idempotency on the pair
    ``(announcement_id, user_id)``, and the **column value is the announcement
    id alone** because migration 0018's unique index is already
    ``(user_id, type, dedupe_key)`` — the recipient half of the pair comes
    from the index, not from the string. Concatenating the user id in as well
    was the first cut here and it is *not* wrong, merely redundant; it was
    removed because the comment justifying it ("otherwise the first student
    notified suppresses everyone else") is false, and an inversion proved it
    false: with the suffix dropped, every enrolled student is still notified.
    A comment the code disproves is worse than no comment.

    Fan-out is sequential and unbatched. A class is tens of students and a
    school is hundreds, not millions; a queue is the right answer at a scale
    this build does not have, and inventing one now would add an unproven
    moving part to a path whose failure is already harmless.
    """
    try:
        for row in rows:
            for recipient in service.student_recipients(row):
                notify_safely(
                    notifications,
                    transport,
                    user_id=recipient,
                    type=NotificationType.announcement,
                    title="New announcement",
                    # The title the teacher wrote is the pointer. The body is
                    # deliberately not forwarded: it can be long, and the
                    # notification's job is to send the student to the post,
                    # not to be the post (D5.9 §2).
                    body=row.title,
                    payload={"announcementId": str(row.announcement_id)},
                    dedupe_key=str(row.announcement_id),
                    seam="announcement",
                )
    except Exception:
        log.exception("announcement_fanout_failed", announcement_count=len(rows))
        return False
    return True


def deliver_announcements_now(
    service: AnnouncementService,
    notifications: NotificationService,
    transport: NotificationTransport,
    rows: Sequence[AnnouncementRow],
) -> None:
    """The composer's path: fan out the rows that are due now, then stamp them.

    A future-dated row is skipped and left unstamped for
    :func:`publish_due_announcements`; a ``NULL`` or past ``publish_at`` is
    notified immediately, as before. The stamp is wrapped for the same reason
    the fan-out is — nothing here may fail a post that was already written —
    and is skipped when the fan-out did not complete, so the row reads
    honestly as "not yet told" rather than as done.
    """
    due = [row for row in rows if service.is_due(row)]
    if not due:
        return
    if not notify_announcement_audience(service, notifications, transport, due):
        return
    try:
        service.mark_notified([row.announcement_id for row in due])
    except Exception:
        log.exception("announcement_stamp_failed", announcement_count=len(due))


def publish_due_announcements(
    service: AnnouncementService,
    notifications: NotificationService,
    transport: NotificationTransport,
    *,
    now: datetime,
    limit: int = DEFAULT_CLAIM_LIMIT,
) -> int:
    """Claim due rows, fan out, stamp **after** the send. Returns rows stamped.

    Stamping after the send is the deliberate choice (spec §1). A crash between
    the send and the stamp re-runs the row on the next pass, and that re-run
    is harmless: migration 0018's unique index rejects the second insert and
    no second push can occur. Stamping before the send would instead silently
    lose the whole audience's notification on the same crash.
    """
    with service.claim_due(now=now, limit=limit) as claim:
        if not claim.rows:
            return 0
        if not notify_announcement_audience(service, notifications, transport, claim.rows):
            # Leave every claimed row unstamped; the next pass retries them.
            return 0
        claim.stamp(now)
        log.info("announcements_published", count=len(claim.rows))
        return len(claim.rows)


__all__ = [
    "deliver_announcements_now",
    "notify_announcement_audience",
    "publish_due_announcements",
]
