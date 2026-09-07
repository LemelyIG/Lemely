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

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from sqlalchemy import select

from lemely.db.announcement_repo import DEFAULT_CLAIM_LIMIT
from lemely.db.models.engagement import Streak
from lemely.db.models.enums import NotificationType
from lemely.db.models.study_plan import StudyPlan as DbStudyPlan
from lemely.db.models.study_plan import StudyPlanSession
from lemely.db.models.users import User
from lemely.db.xp_repo import DEFAULT_ZONE, resolve_zone
from lemely.web.notify import notify_safely

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql import ColumnElement

    from lemely.db.announcement_repo import AnnouncementRow, AnnouncementService
    from lemely.db.notification_repo import NotificationService
    from lemely.web.push import NotificationTransport

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Firing a per-user hour without scanning every user (§4).
# ---------------------------------------------------------------------------


def zones_in_use(session: Session) -> list[str]:
    """Every distinct ``users.timezone``, plus the default bucket that covers ``NULL``.

    Tiny by construction — distinct zones, not users — so the two daily jobs
    do work proportional to the number of zones in use.
    """
    stored = session.scalars(
        select(User.timezone).where(User.timezone.is_not(None)).distinct()
    ).all()
    return sorted({DEFAULT_ZONE.key, *(name for name in stored if name is not None)})


def due_zones(zone_names: Iterable[str], *, now: datetime, hour: int) -> list[tuple[str, date]]:
    """The zones whose local civil time is at or past ``hour``, with their civil date.

    The date is that zone's own, which is what every notification from these
    jobs is keyed on (spec §2). A name ``resolve_zone`` cannot resolve keeps
    its own bucket name — that is what ``users.timezone`` says for those users
    — but is timed on the launch zone, so they are reached an hour or two off
    rather than never.
    """
    due: list[tuple[str, date]] = []
    for name in zone_names:
        local = now.astimezone(resolve_zone(name))
        if local.hour >= hour:
            due.append((name, local.date()))
    return due


def zone_bucket(zone_name: str) -> ColumnElement[bool]:
    """``COALESCE(users.timezone, '<default>') = :zone`` — the per-zone candidate filter."""
    return sa.func.coalesce(User.timezone, DEFAULT_ZONE.key) == zone_name


@dataclass(slots=True)
class ZoneDateMemo:
    """The last civil date each zone's job completed. An optimisation, not a guard.

    After 19:00 in a zone the candidate query would otherwise repeat every
    minute until midnight, doing real work only for the unique index to
    discard it. Correctness comes from that index (spec §2), which is also
    what keeps two replicas — each with its own memo — from double-sending.
    A job that throws mid-zone never marks it, so the next pass retries.
    """

    _done: dict[str, date] = field(default_factory=dict)

    def is_done(self, zone: str, day: date) -> bool:
        """Whether this zone's job already completed for ``day``."""
        return self._done.get(zone) == day

    def mark_done(self, zone: str, day: date) -> None:
        """Record that this zone's job completed for ``day``."""
        self._done[zone] = day


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


# ---------------------------------------------------------------------------
# streak_warning (§2).
# ---------------------------------------------------------------------------

#: Spec §2's copy. ``Profile.tsx`` states the streak is "offered, never used as
#: leverage — no countdown to losing it, no red, no 'don't break it now!'". A
#: 19:00 warning is the exact shape that sentence refuses, so the constraint
#: moved into the wording: each body states the situation once, no exclamation,
#: no countdown, no second sentence stacking urgency on the first.
STREAK_WARNING_TITLE = "Nothing logged today"


def streak_warning_body(length: int, *, freeze_available: bool) -> str:
    """The one sentence a streak warning carries. See :data:`STREAK_WARNING_TITLE`."""
    if freeze_available:
        return f"A freeze will cover today. Your {length}-day streak stays."
    return f"Your {length}-day streak ends if today stays empty."


def streak_tonight(row: Streak, today: date) -> tuple[int, bool] | None:
    """``(length, freeze_available)`` for a streak still alive tonight, else ``None``.

    Streaks resolve **lazily** (D5.1 §5): a row nobody has read in days still
    carries its old ``current_length``, and
    :meth:`~lemely.db.xp_repo.XpService._resolve_gap` is what would zero it on
    the next read. This applies that method's arithmetic without persisting
    it — the days missed between ``last_active_on`` and yesterday are covered
    by held freezes or they are not. A streak the next read would reset gets
    no warning, because "your 5-day streak ends if today stays empty" would
    name a streak that has already ended. ``freeze_available`` is whether a
    freeze remains *after* covering those days: the one that would cover
    today, which is what the body promises.
    """
    if row.current_length < 1 or row.last_active_on is None:
        return None
    yesterday = today - timedelta(days=1)
    missed = max(0, (yesterday - row.last_active_on).days)
    if missed > row.freezes_available:
        return None
    return row.current_length, row.freezes_available - missed >= 1


def warn_streaks(
    sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: NotificationTransport,
    *,
    now: datetime,
    hour: int,
    memo: ZoneDateMemo,
) -> int:
    """Send ``streak_warning`` to every student whose day is past ``hour`` with nothing logged.

    Per due zone (§4): candidates are ``streaks`` rows in that zone's bucket
    with ``current_length >= 1`` and ``last_active_on < today``, where
    ``today`` is that zone's own civil date. Streaks belong to students by
    construction — XP is only ever awarded to one — so no role filter is
    needed. The key is that date, one per student per their own day; the
    unique index makes every later pass that day a ``duplicate``. Returns how
    many rows were created.

    Fires even when a freeze would cover the day, and says so — the kinder
    message is the one that tells a student a freeze is being spent (§2).
    """
    created = 0
    with sessionmaker() as session:
        for zone_name, today in due_zones(zones_in_use(session), now=now, hour=hour):
            if memo.is_done(zone_name, today):
                continue
            candidates = session.scalars(
                select(Streak)
                .join(User, User.id == Streak.user_id)
                .where(
                    zone_bucket(zone_name),
                    Streak.current_length >= 1,
                    Streak.last_active_on.is_not(None),
                    Streak.last_active_on < today,
                )
            ).all()
            for row in candidates:
                tonight = streak_tonight(row, today)
                if tonight is None:
                    continue
                length, freeze_available = tonight
                result = notify_safely(
                    notifications,
                    transport,
                    user_id=row.user_id,
                    type=NotificationType.streak_warning,
                    title=STREAK_WARNING_TITLE,
                    body=streak_warning_body(length, freeze_available=freeze_available),
                    payload={
                        "streakLength": str(length),
                        "freezeAvailable": "true" if freeze_available else "false",
                    },
                    dedupe_key=today.isoformat(),
                    seam="streak_warning",
                )
                created += 1 if result.created else 0
            memo.mark_done(zone_name, today)
    if created:
        log.info("streak_warnings_sent", count=created)
    return created


# ---------------------------------------------------------------------------
# study_plan_reminder (§2).
# ---------------------------------------------------------------------------

STUDY_PLAN_REMINDER_TITLE = "Today's study session"


def study_plan_reminder_body(topic: str, duration_minutes: int) -> str:
    """A pointer to the session, not a summary of it: ``Algebraic fractions · 40 min``."""
    return f"{topic} · {duration_minutes} min"


def remind_study_plans(
    sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: NotificationTransport,
    *,
    now: datetime,
    hour: int,
    memo: ZoneDateMemo,
) -> int:
    """Send ``study_plan_reminder`` for every incomplete session dated today, once ever.

    Per due zone (§4): ``study_plan_sessions`` joined to their plan where the
    plan is active (``superseded_at IS NULL``), ``session.date`` is that zone's
    civil today, and ``completed_at IS NULL``. The key is the **session id**,
    so each scheduled session prompts exactly once, ever — across a day
    boundary, a restart, or a plan regenerated mid-week. Returns rows created.

    Volume, stated rather than discovered later (§2): a plan is
    single-subject, so a student studying three subjects with a session dated
    today receives three notifications at ``hour``. The collapse to one per
    day is a one-line change of shape and is deliberately not made here.
    """
    created = 0
    with sessionmaker() as session:
        for zone_name, today in due_zones(zones_in_use(session), now=now, hour=hour):
            if memo.is_done(zone_name, today):
                continue
            candidates = session.execute(
                select(StudyPlanSession, DbStudyPlan.user_id, DbStudyPlan.subject_code)
                .join(DbStudyPlan, DbStudyPlan.id == StudyPlanSession.plan_id)
                .join(User, User.id == DbStudyPlan.user_id)
                .where(
                    zone_bucket(zone_name),
                    DbStudyPlan.superseded_at.is_(None),
                    StudyPlanSession.completed_at.is_(None),
                    StudyPlanSession.date == today,
                )
                .order_by(StudyPlanSession.id)
            ).all()
            for row, user_id, subject_code in candidates:
                result = notify_safely(
                    notifications,
                    transport,
                    user_id=user_id,
                    type=NotificationType.study_plan_reminder,
                    title=STUDY_PLAN_REMINDER_TITLE,
                    body=study_plan_reminder_body(row.topic, row.duration_minutes),
                    payload={
                        "sessionId": str(row.id),
                        "subjectCode": subject_code,
                        "topic": row.topic,
                    },
                    dedupe_key=str(row.id),
                    seam="study_plan_reminder",
                )
                created += 1 if result.created else 0
            memo.mark_done(zone_name, today)
    if created:
        log.info("study_plan_reminders_sent", count=created)
    return created


__all__ = [
    "STREAK_WARNING_TITLE",
    "STUDY_PLAN_REMINDER_TITLE",
    "ZoneDateMemo",
    "deliver_announcements_now",
    "due_zones",
    "notify_announcement_audience",
    "publish_due_announcements",
    "remind_study_plans",
    "streak_tonight",
    "streak_warning_body",
    "study_plan_reminder_body",
    "warn_streaks",
    "zone_bucket",
    "zones_in_use",
]
