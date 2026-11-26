"""The notification jobs a sweeper runs, and the fan-out they share with the composer.

Push-delivery spec §1, §2 and §4. Three notification jobs live here, and the
sweeper runs a fourth that is not a notification:

* :func:`publish_due_announcements` — claim announcements whose ``publish_at``
  has passed and notify their audience (§1).
* :func:`warn_streaks` — ``streak_warning`` at 19:00 in each student's own
  zone (§2). Added by a later task.
* :func:`remind_study_plans` — ``study_plan_reminder`` at 08:00 in each
  student's own zone (§2). Added by a later task.
* :func:`lemely.web.purge.purge_expired_papers` — the fourth job, not a
  notification: permanently removes papers deleted longer ago than the
  retention window (paper-deletion design §7). It lives in
  :mod:`lemely.web.purge` and runs only on a sweeper built with storage and a
  bucket. :func:`lemely.web.purge.purge_expired_teacher_papers` runs beside it,
  under the same condition, for a teacher's deleted console papers (R2).

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

import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from sqlalchemy import select

from lemely.db.admin_customer_repo import expire_manual_subscriptions
from lemely.db.announcement_repo import DEFAULT_CLAIM_LIMIT
from lemely.db.billing_observability_repo import prune_webhook_failures
from lemely.db.merchant_charge_repo import BatchStops
from lemely.db.models.engagement import Streak
from lemely.db.models.enums import NotificationType
from lemely.db.models.study_plan import StudyPlan as DbStudyPlan
from lemely.db.models.study_plan import StudyPlanSession
from lemely.db.models.users import User
from lemely.db.xp_repo import DEFAULT_ZONE, resolve_zone
from lemely.runtime.config import (
    CHARGE_REQUESTS,
    SWEEP_HARD_LIMIT_MARGIN_SECONDS,
    SWEEP_LOCK_IDLE_TIMEOUT_SECONDS,
    PaymobSettings,
    sweep_unit_hard_seconds,
    sweep_unit_typical_seconds,
)
from lemely.web.llm_price_refresh import refresh_prices
from lemely.web.notify import notify_safely
from lemely.web.purge import purge_expired_papers, purge_expired_teacher_papers
from lemely.web.subscription_jobs import (
    drift_check_job,
    expire_overdue_job,
    monthly_seat_allowance_job,
    period_end_job,
    release_due_seats_job,
    terms_change_notices_job,
    terms_move_fixed_path_job,
)
from lemely.web.tutoring_email import deliver_tutoring_email
from lemely.web.usage_sweeps import ReconcileMemo, RepairCursor, usage_jobs

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql import ColumnElement

    from lemely.db.announcement_repo import AnnouncementRow, AnnouncementService
    from lemely.db.billing_observability_repo import JobRunRecorder
    from lemely.db.notification_repo import NotificationService
    from lemely.io.notify_email import TransactionalEmailProvider
    from lemely.io.storage import StorageBackend
    from lemely.runtime.config import NotificationsSettings
    from lemely.web.push import NotificationTransport
    from lemely.web.subscription_deps import SubscriptionDeps

log = structlog.get_logger(__name__)

#: Bounds the idle time of the sweep's lock transaction, and of nothing else (``SET LOCAL``).
_LOCK_IDLE_TIMEOUT_SQL = (
    f"SET LOCAL idle_in_transaction_session_timeout = '{SWEEP_LOCK_IDLE_TIMEOUT_SECONDS}s'"
)

#: Text key (hashed by ``hashtextextended``, as ``subscription_repo`` keys its locks) of the
#: advisory lock :meth:`Sweeper.sweep_exclusive` holds for the length of one pass.
SWEEP_LOCK_KEY = "lemely.sweeper.pass"

#: Each payment batch's slice of a pass's budget, a fairness cap measured from the job's start.
#: Once a batch has used its slice it starts no further unit, so a long backlog in one batch
#: cannot take the time of the batches behind it; the units it leaves stay due and are the first
#: it takes on the next pass. The first unit of each kind is exempt, so every batch does some
#: work on a pass that has room for it. The job order is neither changed nor rotated: it is
#: load-bearing (an expired plan's seats are handled before the next month's grant, DV-32).
#:
#: The two saved-card batches (extra-seat renewal, then auto top-up) do not both fit a full pass
#: when every backlog is full, so they alternate priority (:data:`PAYMENT_TURN_MINUTES`): the
#: batches before the one with priority keep a planning reserve free for it, the expected time
#: (:class:`UnitCost`) of one database row (for the top-up, one refusal row) and one charge, and
#: the subscription batches give up their later units to that reserve first. Priority is not a
#: minimum charge per pass: a refusal step with more than one row, or a later job that does not
#: check the budget, can use up the reserve. Under the modelled timings on the default 60 s
#: budget, the batch with priority starts a charge while the jobs before the reconcile batch take
#: no more than about 44 s. The windows assume the shipped once-a-minute trigger; a trigger
#: aligned to every 10 minutes would always land in the same window and starve one batch. When
#: the Paymob calls are faster than expected, each slice fits several units.
RECONCILE_SHARE = 0.13
EXPIRE_OVERDUE_SHARE = 0.1
PERIOD_END_SHARE = 0.1
DRIFT_CHECK_SHARE = 0.15
EXTRA_SEAT_RENEWAL_SHARE = 0.1

#: Length of one payment turn. The turn comes from the pass's own clock, in alternating windows
#: counted from the Unix epoch (the extra-seat renewal has the even ones), so it needs no stored
#: state and every replica agrees on it. Five minutes holds at least two passes on the
#: once-a-minute schedule even when Cloud Scheduler skips a minute behind a slow pass.
PAYMENT_TURN_MINUTES = 5


def seat_charges_have_the_turn(moment: datetime) -> bool:
    """Whether the extra-seat renewal, not the auto top-up, has the payment turn at ``moment``."""
    window = int(moment.timestamp() // 60) // PAYMENT_TURN_MINUTES
    return window % 2 == 0


@dataclass(frozen=True, slots=True)
class UnitRequests:
    """The outbound Paymob requests of one unit of a batch: usually, and at most."""

    typical: int
    most: int


#: One inquiry. Paymob rejecting the auth token costs a mint and a repeat.
RECONCILE_ROW = UnitRequests(1, 3)
#: One cancel, with the same allowance for a rejected token.
EXPIRE_ROW = UnitRequests(1, 3)
#: An amount push or a cancel. Cancelling a plan that has ended reads it twice first.
PERIOD_END_ROW = UnitRequests(1, 5)
#: Two reads, then a repair that may write the plan and its amount.
DRIFT_ROW = UnitRequests(2, 5)
#: A row that touches only the database.
DATABASE_ROW = UnitRequests(0, 0)
#: A saved-card charge: the intention, then the payment. Both use the secret key, not the auth
#: token, and neither is ever repeated, so the count is fixed once the charge is claimed.
CHARGE = UnitRequests(CHARGE_REQUESTS, CHARGE_REQUESTS)


@dataclass(frozen=True, slots=True)
class UnitCost:
    """What one unit of a batch is expected to take, and the longest it can take, in seconds."""

    typical: float
    hard: float


@dataclass(slots=True)
class PassBudget:
    """The wall-clock allowance of one sweep pass, on a monotonic clock.

    ``seconds`` is what a pass is planned to take: a unit of work starts only if its expected
    time still fits. ``hard_seconds`` is a planning ceiling (the sweep lock's idle timeout less a
    margin): a unit starts only if its worst case, the sum of its client timeouts, ends under it
    as well. That arithmetic assumes the process keeps running; it is not a wall-clock guarantee
    (a stalled or CPU-throttled process, or a server that trickles bytes, can take longer). A unit
    once started always finishes, so a pass can run past ``seconds``. ``started`` defaults to the
    moment the budget is made.
    """

    seconds: float
    clock: Callable[[], float] = time.monotonic
    hard_seconds: float = math.inf
    started: float = math.nan

    def __post_init__(self) -> None:
        """Start the clock, unless the caller read it already."""
        if math.isnan(self.started):
            self.started = self.clock()

    def elapsed(self) -> float:
        return self.clock() - self.started

    def spent(self) -> bool:
        return self.elapsed() >= self.seconds

    def admits(self, unit: UnitCost, *, reserve: float = 0.0) -> bool:
        """Whether ``unit`` may start now, keeping ``reserve`` seconds for the jobs after it."""
        elapsed = self.elapsed()
        return (
            elapsed + unit.typical + reserve <= self.seconds
            and elapsed + unit.hard <= self.hard_seconds
        )

    def job(self, fraction: float | None = None) -> JobAllowance:
        """The allowance of a job starting now: ``fraction`` of the budget, or no cap."""
        cap = math.inf if fraction is None else self.seconds * fraction
        return JobAllowance(self, cap, began=self.clock())


@dataclass(slots=True)
class JobAllowance:
    """One job's slice of a pass, a cap on top of the pass budget."""

    budget: PassBudget
    seconds: float
    began: float

    def stop_before(self, unit: UnitCost, *, reserve: float = 0.0) -> Callable[[], bool]:
        """The stop check a batch asks before each unit of one kind; ``True`` means stop.

        A unit starts only if the pass budget admits it with ``reserve`` seconds left for the
        jobs after this one (:meth:`PassBudget.admits`), and, after the first unit of its kind,
        only while the job has used less than its slice. Each ``False`` answer is a unit started.
        """
        started = False

        def stop() -> bool:
            nonlocal started
            if not self.budget.admits(unit, reserve=reserve):
                return True
            if started and self.budget.clock() - self.began >= self.seconds:
                return True
            started = True
            return False

        return stop


@dataclass(frozen=True, slots=True)
class SweepPass:
    """What one bounded pass did: counts per job that ran, and the jobs it ran out of time for."""

    results: dict[str, int | None]
    skipped: list[str]


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


# ---------------------------------------------------------------------------
# The runner (§4).
# ---------------------------------------------------------------------------


def _never() -> bool:
    """The stop check of an unbounded pass: never."""
    return False


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


def _record_safely(step: Callable[[], None], *, job: str, phase: str) -> None:
    """Run one recorder write; a failure is logged (type only) and never reaches the job.

    Losing one health row must not stop a billing job or change its result. The exception
    message is not logged: a driver error can echo SQL parameters.
    """
    try:
        step()
    except Exception as exc:
        log.warning("job_run_record_failed", job=job, phase=phase, error_type=type(exc).__name__)


def _run_one(
    name: str,
    job: Callable[[], int],
    recorder: JobRunRecorder | None,
    now: Callable[[], datetime],
) -> int | None:
    """One job's count, or ``None`` when it threw; reported to ``recorder`` either way."""
    if recorder is not None:
        started = now()
        _record_safely(partial(recorder.start, name, started), job=name, phase="start")
    error: Exception | None = None
    count: int | None = None
    try:
        count = job()
    except Exception as exc:
        log.warning("sweep_job_failed", job=name, exc_info=True)
        error = exc
    if recorder is not None:
        _record_safely(
            partial(recorder.record_finish, name, now=now(), count=count, error=error),
            job=name,
            phase="finish",
        )
    return count


def run_jobs(
    jobs: Sequence[tuple[str, Callable[[], int]]],
    *,
    recorder: JobRunRecorder | None = None,
    now: Callable[[], datetime] = _utcnow,
    spent: Callable[[], bool] | None = None,
) -> dict[str, int | None]:
    """Run each job in turn, each wrapped individually.

    A job that throws is a logged warning and the others still run (§4). The
    returned map carries each job's count, or ``None`` for one that threw, so
    a caller (and a test) can see exactly which did what.

    ``spent`` is asked before each job starts; once it says so, every job not yet started is
    left out of the map (neither run nor failed: the caller reports them as skipped).

    ``recorder`` (the admin health view's ``job_runs`` writer) hears about the start and
    the end of every job, success or failure. It never changes a result: a recorder that
    raises is logged as ``job_run_record_failed`` and ignored.
    """
    results: dict[str, int | None] = {}
    for name, job in jobs:
        if spent is not None and spent():
            break
        results[name] = _run_one(name, job, recorder, now)
    return results


@dataclass(slots=True)
class Sweeper:
    """One tick's worth of the jobs, with the state that persists between ticks.

    The two memos are the per-zone optimisation §4 describes and are the only
    state a sweeper carries; everything else is a collaborator the app already
    has. ``deps.get_sweeper`` builds one per process.

    ``storage`` and ``bucket`` are for the purge job alone and default to
    ``None``, which leaves purge out of the pass: a sweeper built only for
    notifications (as most tests build one) never touches object storage.
    """

    sessionmaker: sessionmaker[Session]
    announcements: AnnouncementService
    notifications: NotificationService
    transport: NotificationTransport
    settings: NotificationsSettings
    now: Callable[[], datetime] = _utcnow
    streak_memo: ZoneDateMemo = field(default_factory=ZoneDateMemo)
    plan_memo: ZoneDateMemo = field(default_factory=ZoneDateMemo)
    storage: StorageBackend | None = None
    bucket: str | None = None
    #: The tutoring email job (SPEC §b.4) runs only when a provider is given, the same
    #: optional-collaborator pattern as ``storage``/``bucket`` above, so a sweeper built
    #: without one keeps exactly the pre-tutoring job set.
    email_provider: TransactionalEmailProvider | None = None
    email_daily_cap: int = 60
    #: ``billing.reconcile_pending`` (billing spec §5.10), given only when Paymob is
    #: configured, the same optional-collaborator pattern as ``email_provider``.
    #: Called with the pass moment and a stop check it asks before each row, so a long batch
    #: ends at its slice of the pass budget (:data:`RECONCILE_SHARE`).
    billing_reconcile: Callable[[datetime, Callable[[], bool]], int] | None = None
    #: Billing spec §5.7: the usage ledger's sweeps run only where metering is enforced
    #: (``deps.get_sweeper``); a sweeper built for notifications alone, as most tests
    #: build one, keeps exactly the jobs it had.
    usage_metering: bool = False
    usage_reconcile: ReconcileMemo = field(default_factory=ReconcileMemo)
    usage_repair: RepairCursor = field(default_factory=RepairCursor)
    #: Writes ``job_runs`` for the admin health view (Phase 07). ``deps.get_sweeper`` sets it;
    #: ``None`` for a sweeper built without a database, as most tests build one.
    job_recorder: JobRunRecorder | None = None
    #: Paymob billing Phase 05: the subscription jobs run only when given (Paymob configured),
    #: the same optional-collaborator pattern as ``billing_reconcile``.
    subscriptions: SubscriptionDeps | None = None
    #: The two seat jobs run whatever the Paymob configuration: manual teacher plans grant
    #: seats too (DV-22). ``deps.get_sweeper`` sets it; tests that build a sweeper for
    #: notifications alone keep the jobs they had.
    seat_allowances: bool = False
    #: Collaborators for the local part of ``subscriptions.expire_overdue`` when Paymob is not
    #: configured: the row still expires and stops granting seat allowance, and the Paymob cancel
    #: is left to the failed-cancel retry once Paymob is configured (DV-32).
    expiry: SubscriptionDeps | None = None
    #: Paymob billing Phase 06, given only where saved-card charges are configured: the fallback
    #: renewal seat charge, then the auto top-up. Both run after every Phase 05 job, so an
    #: expired plan's seats are handled first. Each is called with the pass moment and the stop
    #: checks it asks before each database row and each charge claim (:class:`BatchStops`).
    billing_extra_seat_renewal: Callable[[datetime, BatchStops], int] | None = None
    billing_auto_topup: Callable[[datetime, BatchStops], int] | None = None
    #: The clock the pass budget runs on; tests inject their own.
    monotonic: Callable[[], float] = time.monotonic
    #: The Paymob timeouts, which bound the longest a unit calling Paymob can take.
    paymob: PaymobSettings = field(default_factory=PaymobSettings)

    def sweep_unbounded_for_tests(self) -> dict[str, int | None]:
        """Run every job given once, with no lock and no pass budget. For tests only.

        Production passes go through :meth:`sweep_exclusive`, which takes the advisory lock and
        bounds the pass. This entry point does neither, so a test can run the full job set and
        read each job's count without a time limit cutting the pass short.
        """
        return self._sweep(None).results

    def _cost(self, requests: UnitRequests) -> UnitCost:
        return UnitCost(
            typical=sweep_unit_typical_seconds(self.settings, requests=requests.typical),
            hard=sweep_unit_hard_seconds(self.settings, self.paymob, requests=requests.most),
        )

    def _sweep(self, budget: PassBudget | None) -> SweepPass:
        moment = self.now()
        # The saved-card batch whose turn it is (see PAYMENT_TURN_MINUTES) gets room for one
        # database row and one charge: every batch before it keeps that much of the budget free.
        # The other batch still runs in its place in the order and uses whatever is left.
        row_time, charge_time = self._cost(DATABASE_ROW).typical, self._cost(CHARGE).typical
        seats_turn = self.billing_extra_seat_renewal is not None and (
            self.billing_auto_topup is None or seat_charges_have_the_turn(moment)
        )
        paying = self.billing_extra_seat_renewal is not None or self.billing_auto_topup is not None
        reserve = row_time + charge_time if paying else 0.0
        # On its turn the seat batch keeps its charge's time free while it works through rows and
        # then charges up to its slice; off its turn it keeps the top-up's reserve throughout.
        seat_row_keep, seat_charge_keep = (charge_time, 0.0) if seats_turn else (reserve, reserve)

        def gate(fraction: float, requests: UnitRequests) -> Callable[[], bool] | None:
            if budget is None:
                return None
            return budget.job(fraction).stop_before(self._cost(requests), reserve=reserve)

        def charge_stops(
            fraction: float | None, *, row_keep: float, charge_keep: float
        ) -> BatchStops:
            if budget is None:
                return BatchStops(row=_never, charge=_never)
            allowance = budget.job(fraction)
            return BatchStops(
                row=allowance.stop_before(self._cost(DATABASE_ROW), reserve=row_keep),
                charge=allowance.stop_before(self._cost(CHARGE), reserve=charge_keep),
            )

        jobs: list[tuple[str, Callable[[], int]]] = [
            (
                "publish_due_announcements",
                lambda: publish_due_announcements(
                    self.announcements, self.notifications, self.transport, now=moment
                ),
            ),
            (
                "warn_streaks",
                lambda: warn_streaks(
                    self.sessionmaker,
                    self.notifications,
                    self.transport,
                    now=moment,
                    hour=self.settings.streak_warning_hour,
                    memo=self.streak_memo,
                ),
            ),
            (
                "remind_study_plans",
                lambda: remind_study_plans(
                    self.sessionmaker,
                    self.notifications,
                    self.transport,
                    now=moment,
                    hour=self.settings.study_plan_reminder_hour,
                    memo=self.plan_memo,
                ),
            ),
            (
                "admin.expire_manual_subscriptions",
                lambda: expire_manual_subscriptions(self.sessionmaker, now=moment),
            ),
        ]
        storage, bucket = self.storage, self.bucket
        if storage is not None and bucket is not None:
            jobs.append(
                (
                    "purge_expired_papers",
                    lambda: purge_expired_papers(self.sessionmaker, storage, bucket, now=moment),
                )
            )
            jobs.append(
                (
                    "purge_expired_teacher_papers",
                    lambda: purge_expired_teacher_papers(
                        self.sessionmaker, storage, bucket, now=moment
                    ),
                )
            )
        provider = self.email_provider
        if provider is not None:
            jobs.append(
                (
                    "deliver_tutoring_email",
                    lambda: deliver_tutoring_email(
                        sessionmaker=self.sessionmaker,
                        provider=provider,
                        daily_cap=self.email_daily_cap,
                        now=self.now,
                    ),
                )
            )
        billing_reconcile = self.billing_reconcile
        if billing_reconcile is not None:
            jobs.append(
                (
                    "billing.reconcile_pending",
                    lambda: billing_reconcile(
                        moment, gate(RECONCILE_SHARE, RECONCILE_ROW) or _never
                    ),
                )
            )
        if self.job_recorder is not None:
            # The admin health surface: ``job_runs`` is written for every job, and the
            # refused-callback table it reads beside it is bounded (UD-6, 90 days). Wired
            # together by ``deps.get_sweeper``, like the other optional collaborators, so a
            # sweeper built without a recorder keeps exactly the jobs it had.
            jobs.append(
                (
                    "billing.prune_webhook_failures",
                    lambda: prune_webhook_failures(self.sessionmaker, now=moment),
                )
            )
            # UD13-D, DV-6: refreshes the instance serving this pass; the others refresh on a stale
            # price read (lemely.web.llm_price_refresh.install_stale_refresh).
            jobs.append(("billing.llm_price_refresh", lambda: refresh_prices(self.sessionmaker)))
        if self.usage_metering:
            jobs.extend(
                usage_jobs(
                    self.sessionmaker,
                    now=moment,
                    memo=self.usage_reconcile,
                    repair=self.usage_repair,
                )
            )
        # DV-32: an expired teacher plan grants no new month, and a seat leaving at month end
        # is released before the new month's grant, so the order below is load-bearing.
        subscriptions = self.subscriptions
        expiry = subscriptions or self.expiry
        if subscriptions is not None:
            # Plan terms moves (UD13-A): announce them, then cancel the plans a move would reprice
            # where Paymob cannot change the amount, before the sweep that pushes cancels.
            jobs.extend(
                [
                    (
                        "billing.terms_change_notices",
                        lambda: terms_change_notices_job(subscriptions, now=moment),
                    ),
                    (
                        "billing.terms_move_fixed_path",
                        lambda: terms_move_fixed_path_job(subscriptions, now=moment),
                    ),
                ]
            )
        if expiry is not None:
            jobs.append(
                (
                    "subscriptions.expire_overdue",
                    lambda: expire_overdue_job(
                        expiry, now=moment, should_stop=gate(EXPIRE_OVERDUE_SHARE, EXPIRE_ROW)
                    ),
                )
            )
        if subscriptions is not None:
            jobs.extend(
                [
                    (
                        "subscriptions.period_end",
                        lambda: period_end_job(
                            subscriptions,
                            now=moment,
                            should_stop=gate(PERIOD_END_SHARE, PERIOD_END_ROW),
                        ),
                    ),
                    (
                        "subscriptions.drift_check",
                        lambda: drift_check_job(
                            subscriptions,
                            now=moment,
                            should_stop=gate(DRIFT_CHECK_SHARE, DRIFT_ROW),
                        ),
                    ),
                ]
            )
        if self.seat_allowances:
            jobs.extend(
                [
                    (
                        "seats.release_due",
                        lambda: release_due_seats_job(self.sessionmaker, now=moment),
                    ),
                    (
                        "seats.monthly_allowance",
                        lambda: monthly_seat_allowance_job(self.sessionmaker, now=moment),
                    ),
                ]
            )
        extra_seat_renewal = self.billing_extra_seat_renewal
        if extra_seat_renewal is not None:
            jobs.append(
                (
                    "billing.extra_seat_renewal_charge",
                    lambda: extra_seat_renewal(
                        moment,
                        charge_stops(
                            EXTRA_SEAT_RENEWAL_SHARE,
                            row_keep=seat_row_keep,
                            charge_keep=seat_charge_keep,
                        ),
                    ),
                )
            )
        auto_topup = self.billing_auto_topup
        if auto_topup is not None:
            # Last in the pass, so it may use whatever the budget has left: on its turn the batches
            # before it kept room for one row and one charge, otherwise that is what remains.
            jobs.append(
                (
                    "billing.auto_topup",
                    lambda: auto_topup(moment, charge_stops(None, row_keep=0.0, charge_keep=0.0)),
                )
            )
        results = run_jobs(
            jobs,
            recorder=self.job_recorder,
            now=self.now,
            spent=budget.spent if budget else None,
        )
        skipped = [name for name, _job in jobs if name not in results]
        if skipped:
            log.warning("sweep_pass_budget_spent", skipped=skipped, ran=len(results))
        return SweepPass(results=results, skipped=skipped)

    def sweep_exclusive(self) -> SweepPass | None:
        """One bounded pass, unless another exclusive pass is already running; ``None`` then.

        The one entry point of both the in-process loop and the Cloud Scheduler trigger
        (``POST /api/internal/jobs/sweep``), so a loop pass and a trigger, on this replica or
        another, never run side by side: the second returns at once. A transaction-scoped
        advisory lock on :data:`SWEEP_LOCK_KEY` is held for the whole pass. It lives on one
        connection that sits idle in its transaction meanwhile (the jobs use their own
        sessions, so the pool needs two connections: ``DatabaseSettings`` enforces it), which
        also works behind a transaction-mode pooler. It is released when the pass ends, however
        it ends, or the connection dies.

        That transaction sets ``idle_in_transaction_session_timeout`` for itself alone (``SET
        LOCAL``) to :data:`~lemely.runtime.config.SWEEP_LOCK_IDLE_TIMEOUT_SECONDS`. If the process
        stalls mid-pass (CPU throttled outside a request, a hung worker thread), Postgres ends the
        transaction and frees the lock, so a stalled pass cannot hold off every later trigger. The
        stalled pass then fails when it tries to commit, which is reported as a failed pass; the
        jobs it already ran stay done.

        The pass is planned to ``settings.sweep_pass_budget_seconds`` of wall clock, counted from
        the moment this method is entered, so waiting for a pooled connection or the lock counts
        too. A unit of work (a row, a charge) starts only if its expected time fits in what is
        left and its worst case, from the Paymob timeouts, would end under the lock's idle timeout
        less :data:`~lemely.runtime.config.SWEEP_HARD_LIMIT_MARGIN_SECONDS`. That is a planning
        bound for a process that keeps its CPU, not a wall-clock guarantee: the only limit actually
        enforced is Postgres ending the idle lock transaction. A unit once started is never
        interrupted, so a pass can overrun its budget; that is logged as
        ``sweep_pass_overran``, apart from job failures. Jobs not started because the budget was
        spent are returned as ``skipped`` and run on the next tick.

        It is an overlap guard, not a correctness one. A pass whose connection dropped loses
        the lock, and every job stays safe then: each is idempotent by row state (see
        ``billing_jobs`` and ``usage_sweeps``), exactly as with two replicas' loops.
        """
        budget = PassBudget(
            self.settings.sweep_pass_budget_seconds,
            clock=self.monotonic,
            hard_seconds=SWEEP_LOCK_IDLE_TIMEOUT_SECONDS - SWEEP_HARD_LIMIT_MARGIN_SECONDS,
        )
        ran = False
        try:
            with self.sessionmaker() as session, session.begin():
                # Well above a healthy pass, and under Cloud Run's 300 s request timeout, so a
                # stalled pass frees the lock before the platform would end the request.
                session.execute(sa.text(_LOCK_IDLE_TIMEOUT_SQL))
                locked = session.scalar(
                    sa.text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": SWEEP_LOCK_KEY},
                )
                if not locked:
                    return None
                ran = True
                return self._sweep(budget)
        finally:
            elapsed = budget.elapsed()
            if ran and elapsed > budget.seconds:
                log.warning(
                    "sweep_pass_overran",
                    elapsed_seconds=round(elapsed, 1),
                    budget_seconds=budget.seconds,
                )


async def run_sweeper(sweeper: Sweeper, *, poll_seconds: float, stop: asyncio.Event) -> None:
    """Sweep now, then every ``poll_seconds``, until ``stop`` is set.

    The first pass is immediate rather than after one interval: on Cloud Run
    a freshly scaled-up instance is the only chance a missed pass gets, and
    making it wait a minute first would lose the 19:00 warning for anyone
    whose zone crossed the trigger while nothing was running (§4's caveat).

    Each pass runs in a worker thread (``asyncio.to_thread``): every job is
    synchronous SQLAlchemy, and running it on the event loop would stall every
    request for the duration of a fan-out. It goes through
    :meth:`Sweeper.sweep_exclusive`, the entry point of the Cloud Scheduler trigger too,
    so the loop and a trigger never run a pass side by side; a pass skipped because
    another holds the lock is not an error.
    """
    while not stop.is_set():
        try:
            await asyncio.to_thread(sweeper.sweep_exclusive)
        except Exception:
            # ``run_jobs`` already wraps each job; this catches the pass
            # itself dying (the clock, a thread failure) so the loop lives.
            log.warning("sweep_pass_failed", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue


__all__ = [
    "CHARGE",
    "DATABASE_ROW",
    "DRIFT_CHECK_SHARE",
    "DRIFT_ROW",
    "EXPIRE_OVERDUE_SHARE",
    "EXPIRE_ROW",
    "EXTRA_SEAT_RENEWAL_SHARE",
    "PAYMENT_TURN_MINUTES",
    "PERIOD_END_ROW",
    "PERIOD_END_SHARE",
    "RECONCILE_ROW",
    "RECONCILE_SHARE",
    "STREAK_WARNING_TITLE",
    "STUDY_PLAN_REMINDER_TITLE",
    "SWEEP_LOCK_KEY",
    "JobAllowance",
    "PassBudget",
    "SweepPass",
    "Sweeper",
    "UnitCost",
    "UnitRequests",
    "ZoneDateMemo",
    "deliver_announcements_now",
    "due_zones",
    "notify_announcement_audience",
    "publish_due_announcements",
    "remind_study_plans",
    "run_jobs",
    "run_sweeper",
    "seat_charges_have_the_turn",
    "streak_tonight",
    "streak_warning_body",
    "study_plan_reminder_body",
    "warn_streaks",
    "zone_bucket",
    "zones_in_use",
]
