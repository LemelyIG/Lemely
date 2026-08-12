"""The notification inbox and push-subscription storage (P5.6 chunk A, D5.9).

This module owns every ``notifications`` and ``push_subscriptions`` query in
the codebase; no route touches either table directly. It is the *consumer*
``lemely.db.notification_prefs_repo`` was written without — that module's
docstring says explicitly that deciding whether a notification would be
delivered "belongs to P5, which owns notification delivery end to end". This
is that decision, and it is made here rather than there so preferences stay a
storage concern.

**What this module deliberately does not do: send anything.** It writes the
inbox row and reports whether a push *may* be attempted; the transport that
actually pushes is P5.6 chunk B, injected at the router layer. Keeping the
send out of here is what makes D5.9 §1 enforceable — a push failure cannot
roll back an inbox write it has no access to.

The two preference mechanisms are not interchangeable and this module is where
that distinction lives (D5.9 §2):

* **A type toggle off suppresses the row itself.** It is a content preference
  — "do not notify me about this" — and an inbox that accumulates items the
  user explicitly refused is not a feature. This is safe only because a
  notification is always a pointer and never the data: the ready grade is
  still on the results screen, the announcement is still in P5.5's list with
  its own read receipts, the streak is still on the dashboard. If a future
  notification type is ever the *sole* record of something, this rule must be
  revisited rather than extended to it.
* **Quiet hours suppress only the push.** They are a timing preference — "do
  not buzz my phone at 2am" — so the row is always written and the user reads
  it when they next open the app. Dropping the row here would lose a
  notification for the sole reason that it arrived while its recipient was
  asleep, which is the opposite of what the setting asks for.

A user with **no** preferences row wants everything:
:meth:`~lemely.db.notification_prefs_repo.NotificationPreferencesService.get`
returns an all-defaults row for them, and every default is ``True``. Reading
a missing row as opt-out would silence exactly the users who never opened
settings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from enum import Enum
from typing import TYPE_CHECKING, Final, Protocol, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from lemely.db.models import Notification, NotificationType, PushSubscription
from lemely.db.xp_repo import DEFAULT_ZONE

if TYPE_CHECKING:
    from collections.abc import Callable
    from zoneinfo import ZoneInfo

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.notification_prefs_repo import (
        NotificationPreferencesRow,
        NotificationPreferencesService,
    )

#: Default page size for the inbox. Mirrors P5.5's ``DEFAULT_STUDENT_LIMIT``.
DEFAULT_INBOX_LIMIT: Final = 50

#: Hard ceiling on an inbox page, whatever a caller asks for.
MAX_INBOX_LIMIT: Final = 200

#: Name of the partial unique index migration 0018 creates.
_DEDUPE_CONSTRAINT_NAME: Final = "uq_notifications_user_type_dedupe"

#: Name of the endpoint unique constraint migration 0018 creates.
_ENDPOINT_CONSTRAINT_NAME: Final = "uq_push_subscriptions_endpoint"

#: Maps each notification type to the preference column that gates it.
#:
#: The two vocabularies are identical by construction — every
#: :class:`~lemely.db.models.enums.NotificationType` member has a
#: same-named boolean on ``notification_preferences`` — but "identical by
#: construction" is exactly the kind of claim that rots silently when someone
#: adds a sixth type. ``tests/test_notification_repo.py`` pins this mapping
#: against both vocabularies, following the three-way vocabulary pin
#: ``tests/test_db_schema.py`` already applies to the enum and the columns.
PREFERENCE_FIELD_FOR_TYPE: Final[dict[NotificationType, str]] = {
    NotificationType.grade_ready: "grade_ready",
    NotificationType.announcement: "announcement",
    NotificationType.streak_warning: "streak_warning",
    NotificationType.study_plan_reminder: "study_plan_reminder",
    NotificationType.at_risk_alert: "at_risk_alert",
}


class NotificationOutcome(Enum):
    """Why :meth:`NotificationService.create` did what it did."""

    #: The row was written.
    created = "created"
    #: An identical ``(user, type, dedupe_key)`` row already existed.
    duplicate = "duplicate"
    #: The user turned this notification type off, so no row was written.
    opted_out = "opted_out"


@dataclass(frozen=True, slots=True)
class NotificationRow:
    """One inbox row, detached from its session."""

    id: uuid.UUID
    user_id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None
    payload: dict[str, object]
    created_at: datetime
    read_at: datetime | None

    @property
    def is_read(self) -> bool:
        """``True`` when this notification has been marked read."""
        return self.read_at is not None


@dataclass(frozen=True, slots=True)
class CreateResult:
    """What happened to one :meth:`NotificationService.create` call.

    ``push_allowed`` is a *separate* answer from ``outcome`` and never
    derivable from it, which is the whole point of returning both: a row can
    be created and still not be pushable (quiet hours, D5.9 §2), and a caller
    that inferred "created ⇒ push" would buzz a sleeping student's phone.
    """

    outcome: NotificationOutcome
    row: NotificationRow | None
    push_allowed: bool
    #: Set when ``push_allowed`` is ``False`` despite a row existing.
    push_suppressed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PushSubscriptionRow:
    """One stored push endpoint, detached from its session.

    ``p256dh``/``auth`` are included because the transport needs them to
    encrypt a payload. They are the browser's *public* material and useless
    without its private key, but no wire DTO exposes this dataclass — the
    client already has its own subscription and has no use for anyone else's.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    endpoint: str
    p256dh: str
    auth: str
    user_agent: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NotificationCounts:
    """Inbox totals for a badge."""

    unread: int
    total: int
    by_type: dict[NotificationType, int] = field(default_factory=dict)


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


class _HasRowcount(Protocol):
    """The one attribute :func:`_rowcount` needs off a DML result."""

    @property
    def rowcount(self) -> int:
        """Number of rows the statement affected."""


def _rowcount(result: object) -> int:
    """Rows affected by an UPDATE or DELETE.

    ``Session.execute`` is typed as returning ``Result``, which has no
    ``rowcount``; what a DML statement actually returns at runtime is a
    ``CursorResult``, which does. Narrowing through a one-attribute
    ``Protocol`` rather than ``cast("CursorResult[Any]", ...)`` keeps this
    inside mypy's no-explicit-``Any`` rule, and states precisely which part of
    the runtime object is being relied on.
    """
    return int(cast("_HasRowcount", result).rowcount or 0)


def civil_time_in_zone(moment: datetime, *, zone: ZoneInfo) -> time:
    """Convert an aware ``datetime`` to its wall-clock time in ``zone``.

    The quiet-hours analogue of
    :func:`lemely.db.xp_repo.civil_date_in_zone`, and it exists for the same
    reason: a quiet-hours window is written by a human in their own local
    time, so comparing it against a UTC timestamp is wrong by two hours in
    Cairo and by more elsewhere. ``zone`` is a required keyword so no caller
    can silently mean "the server's zone".

    Raises:
        ValueError: ``moment`` is naive — a naive datetime has no defined
            wall-clock time in any zone.
    """
    if moment.tzinfo is None:
        raise ValueError("civil_time_in_zone requires an aware datetime")
    return moment.astimezone(zone).timetz().replace(tzinfo=None)


def is_within_quiet_hours(
    moment_local: time,
    start: time | None,
    end: time | None,
) -> bool:
    """``True`` when ``moment_local`` falls inside the ``[start, end)`` window.

    **A half-configured window is not a window.** If either bound is ``None``
    the answer is ``False``, because the alternative — treating a set start
    with no end as "quiet from 22:00 until further notice" — silently
    disables push forever.

    This is defence in depth rather than a case the product can currently
    produce: ``NotificationPreferencesService.set`` already raises
    ``ValueError`` when the merged result would leave exactly one bound set.
    But the two columns are independently nullable in the DB, so a row
    written by a migration, a fixture or a future second writer can still
    hold that state, and the send path is the wrong place to raise.

    **The window wraps midnight when ``start > end``**, which is the normal
    case: quiet hours are 22:00→07:00 far more often than 09:00→17:00. A
    naive ``start <= t < end`` comparison would make the common configuration
    match nothing at all.

    ``start == end`` is a zero-length window, not a 24-hour one: it reads as
    "no quiet hours", which is the safer of the two readings — the failure
    mode of the other is a user who never receives a push again and cannot
    tell why.
    """
    if start is None or end is None:
        return False
    if start == end:
        return False
    if start < end:
        return start <= moment_local < end
    return moment_local >= start or moment_local < end


class NotificationService:
    """Write and read the notification inbox, and store push subscriptions.

    Constructed with a ``sessionmaker``, the preferences service that gates
    delivery, an injectable clock, and the zone quiet hours are evaluated in
    — the same four-part shape as
    :class:`~lemely.db.xp_repo.XpService`.

    The preferences service is *injected* rather than constructed here so the
    two share one session factory and so a test can drive the gate directly.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        preferences: NotificationPreferencesService,
        *,
        now: Callable[[], datetime] = _utcnow,
        zone: ZoneInfo = DEFAULT_ZONE,
    ) -> None:
        """Wire the service to a session factory, the preference gate, a clock, and a zone."""
        self._sessionmaker = sessionmaker
        self._preferences = preferences
        self._now = now
        self._zone = zone

    # -- Writing ------------------------------------------------------------

    def create(
        self,
        user_id: uuid.UUID | str,
        type: NotificationType,
        title: str,
        *,
        body: str | None = None,
        payload: dict[str, object] | None = None,
        dedupe_key: str | None = None,
        now: datetime | None = None,
    ) -> CreateResult:
        """Create one inbox row, gated by preferences and idempotent on ``dedupe_key``.

        ``dedupe_key`` is optional and its absence is meaningful, not lazy:
        some notification types have no natural idempotency key at all (two
        ``study_plan_reminder`` rows a week apart are two real reminders), and
        those rows carry ``NULL`` and are exempt from the partial unique index
        migration 0018 creates. This mirrors D5.3's split for XP, where the
        paper seam dedupes and the flashcard seam deliberately does not.

        Returns:
            A :class:`CreateResult` whose ``push_allowed`` is a separate
            answer from its ``outcome`` — see that class.
        """
        recipient = _as_uuid(user_id)
        moment = now if now is not None else self._now()
        prefs = self._preferences.get(recipient)

        if not _type_is_enabled(prefs, type):
            return CreateResult(
                outcome=NotificationOutcome.opted_out,
                row=None,
                push_allowed=False,
                push_suppressed_reason="opted_out",
            )

        notification = Notification(
            user_id=recipient,
            type=type,
            title=title,
            body=body,
            payload=dict(payload or {}),
            dedupe_key=dedupe_key,
        )

        with self._sessionmaker() as session, session.begin():
            try:
                # A savepoint, not a bare flush: once a failing INSERT poisons
                # the enclosing transaction there is nothing left to recover
                # with, which is the correction D5.7 had to make in
                # FriendService.request after asserting otherwise.
                with session.begin_nested():
                    session.add(notification)
                    session.flush()
            except IntegrityError as exc:
                if not _is_dedupe_violation(exc):
                    raise
                return CreateResult(
                    outcome=NotificationOutcome.duplicate,
                    row=None,
                    push_allowed=False,
                    push_suppressed_reason="duplicate",
                )
            row = _row_from_model(notification)

        quiet = is_within_quiet_hours(
            civil_time_in_zone(moment, zone=self._zone),
            prefs.quiet_hours_start,
            prefs.quiet_hours_end,
        )
        return CreateResult(
            outcome=NotificationOutcome.created,
            row=row,
            push_allowed=not quiet,
            push_suppressed_reason="quiet_hours" if quiet else None,
        )

    def mark_read(
        self,
        user_id: uuid.UUID | str,
        notification_id: uuid.UUID | str,
        *,
        now: datetime | None = None,
    ) -> NotificationRow | None:
        """Mark one notification read, idempotently. ``None`` if it is not the user's.

        Re-marking an already-read notification **does not move
        ``read_at``**: first-read time is the useful number and "last opened"
        is a different feature nobody asked for. Same call P5.5 made for
        announcement read receipts.

        The ``user_id`` predicate is in the UPDATE's WHERE clause rather than
        checked after a fetch, so another user's notification id is
        indistinguishable from a nonexistent one — no existence oracle, the
        rule P5.3's leaderboard 403 already follows.
        """
        recipient = _as_uuid(user_id)
        target = _as_uuid(notification_id)
        moment = now if now is not None else self._now()

        with self._sessionmaker() as session, session.begin():
            model = session.execute(
                sa.select(Notification).where(
                    Notification.id == target,
                    Notification.user_id == recipient,
                )
            ).scalar_one_or_none()
            if model is None:
                return None
            if model.read_at is None:
                model.read_at = moment
                session.flush()
            return _row_from_model(model)

    def mark_all_read(
        self,
        user_id: uuid.UUID | str,
        *,
        now: datetime | None = None,
    ) -> int:
        """Mark every unread notification of this user read. Returns how many changed.

        The ``read_at IS NULL`` predicate is what keeps this idempotent and
        keeps it from rewriting the first-read time of everything already
        read — a second call returns 0 rather than re-stamping the inbox.
        """
        recipient = _as_uuid(user_id)
        moment = now if now is not None else self._now()

        with self._sessionmaker() as session, session.begin():
            result = session.execute(
                sa.update(Notification)
                .where(
                    Notification.user_id == recipient,
                    Notification.read_at.is_(None),
                )
                .values(read_at=moment)
            )
            return _rowcount(result)

    # -- Reading ------------------------------------------------------------

    def list_for_user(
        self,
        user_id: uuid.UUID | str,
        *,
        unread_only: bool = False,
        limit: int = DEFAULT_INBOX_LIMIT,
    ) -> list[NotificationRow]:
        """Return this user's notifications, newest first.

        Ordering breaks ties on ``id`` as well as ``created_at``. Two
        notifications written by one action land in the same transaction and
        can share a timestamp to the microsecond; without the tiebreak their
        relative order is whatever Postgres feels like that day, and a client
        paging through would see rows shuffle between requests.
        """
        recipient = _as_uuid(user_id)
        capped = max(1, min(limit, MAX_INBOX_LIMIT))

        stmt = sa.select(Notification).where(Notification.user_id == recipient)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(capped)

        with self._sessionmaker() as session:
            models = session.execute(stmt).scalars().all()
            return [_row_from_model(model) for model in models]

    def counts(self, user_id: uuid.UUID | str) -> NotificationCounts:
        """Return unread/total counts plus an unread breakdown by type."""
        recipient = _as_uuid(user_id)
        unread_case = sa.case((Notification.read_at.is_(None), 1), else_=0)

        with self._sessionmaker() as session:
            totals = session.execute(
                sa.select(
                    sa.func.count(Notification.id),
                    sa.func.coalesce(sa.func.sum(unread_case), 0),
                ).where(Notification.user_id == recipient)
            ).one()
            per_type = session.execute(
                sa.select(Notification.type, sa.func.count(Notification.id))
                .where(
                    Notification.user_id == recipient,
                    Notification.read_at.is_(None),
                )
                .group_by(Notification.type)
            ).all()

        return NotificationCounts(
            unread=int(totals[1]),
            total=int(totals[0]),
            by_type={row[0]: int(row[1]) for row in per_type},
        )

    # -- Push subscriptions -------------------------------------------------

    def subscribe(
        self,
        user_id: uuid.UUID | str,
        endpoint: str,
        p256dh: str,
        auth: str,
        *,
        user_agent: str | None = None,
    ) -> PushSubscriptionRow:
        """Store (or move) a browser's push subscription. Idempotent per endpoint.

        **Re-subscribing an endpoint that belongs to another user moves the
        row rather than adding one.** The endpoint identifies a browser
        install, not a person, so two users on one browser produce the same
        endpoint; leaving the first row in place would keep pushing the first
        user's notifications to a browser the second is now using. That is a
        privacy defect, not a duplicate-row nuisance, which is why migration
        0018 makes ``endpoint`` unique across the whole table and this method
        updates on conflict.

        The keys are refreshed on every call because a browser may rotate
        them while keeping the endpoint.
        """
        owner = _as_uuid(user_id)
        if not endpoint:
            raise ValueError("endpoint must not be empty")

        with self._sessionmaker() as session, session.begin():
            existing = session.execute(
                sa.select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            ).scalar_one_or_none()
            if existing is not None:
                existing.user_id = owner
                existing.p256dh = p256dh
                existing.auth = auth
                existing.user_agent = user_agent
                session.flush()
                return _subscription_from_model(existing)

            model = PushSubscription(
                user_id=owner,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
            )
            try:
                with session.begin_nested():
                    session.add(model)
                    session.flush()
            except IntegrityError as exc:
                if not _is_endpoint_violation(exc):
                    raise
                # Lost the race to another request subscribing the same
                # endpoint. Resolve through the same UPDATE path the
                # sequential case takes, so the two cannot drift (D5.7).
                winner = session.execute(
                    sa.select(PushSubscription).where(PushSubscription.endpoint == endpoint)
                ).scalar_one()
                winner.user_id = owner
                winner.p256dh = p256dh
                winner.auth = auth
                winner.user_agent = user_agent
                session.flush()
                return _subscription_from_model(winner)
            return _subscription_from_model(model)

    def unsubscribe(self, user_id: uuid.UUID | str, endpoint: str) -> bool:
        """Remove one of this user's push subscriptions. ``True`` if a row went.

        Scoped to the caller so one user cannot unsubscribe another's browser
        by guessing an endpoint.
        """
        owner = _as_uuid(user_id)
        with self._sessionmaker() as session, session.begin():
            result = session.execute(
                sa.delete(PushSubscription).where(
                    PushSubscription.endpoint == endpoint,
                    PushSubscription.user_id == owner,
                )
            )
            return _rowcount(result) > 0

    def forget_endpoint(self, endpoint: str) -> bool:
        """Delete a subscription the push service reported as gone (404/410).

        Deliberately **not** scoped to a user: the caller is the send path
        reacting to the push service, not a request acting on someone's
        behalf, and by then the endpoint is known-dead for whoever owns it
        (D5.9 §4). Retrying a 410 endpoint forever grows a table of rows that
        can never succeed.
        """
        with self._sessionmaker() as session, session.begin():
            result = session.execute(
                sa.delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
            return _rowcount(result) > 0

    def subscriptions_for(self, user_id: uuid.UUID | str) -> list[PushSubscriptionRow]:
        """Every stored push endpoint for one user, oldest first."""
        owner = _as_uuid(user_id)
        with self._sessionmaker() as session:
            models = (
                session.execute(
                    sa.select(PushSubscription)
                    .where(PushSubscription.user_id == owner)
                    .order_by(PushSubscription.created_at.asc(), PushSubscription.id.asc())
                )
                .scalars()
                .all()
            )
            return [_subscription_from_model(model) for model in models]


def _type_is_enabled(prefs: NotificationPreferencesRow, type: NotificationType) -> bool:
    """Read the preference boolean gating ``type``.

    ``PREFERENCE_FIELD_FOR_TYPE`` is exhaustive over the enum and pinned by a
    test, so a missing entry is a bug rather than a silent default. It is read
    with a lookup that raises rather than ``.get(..., True)``: defaulting an
    unmapped type to "enabled" would deliver a notification the user was never
    offered a way to refuse.
    """
    return bool(getattr(prefs, PREFERENCE_FIELD_FOR_TYPE[type]))


def _row_from_model(model: Notification) -> NotificationRow:
    """Detach a :class:`Notification` into a frozen row."""
    return NotificationRow(
        id=model.id,
        user_id=model.user_id,
        type=model.type,
        title=model.title,
        body=model.body,
        payload=dict(model.payload or {}),
        created_at=model.created_at,
        read_at=model.read_at,
    )


def _subscription_from_model(model: PushSubscription) -> PushSubscriptionRow:
    """Detach a :class:`PushSubscription` into a frozen row."""
    return PushSubscriptionRow(
        id=model.id,
        user_id=model.user_id,
        endpoint=model.endpoint,
        p256dh=model.p256dh,
        auth=model.auth,
        user_agent=model.user_agent,
        created_at=model.created_at,
    )


def _is_dedupe_violation(exc: IntegrityError) -> bool:
    """``True`` only for a violation of ``uq_notifications_user_type_dedupe``.

    Any other integrity error — a foreign-key violation from a user id that
    does not exist, say — must keep propagating. Swallowing every
    ``IntegrityError`` indiscriminately would report a real bug as a
    reassuring "already notified" no-op (D5.3's shape, and ``xp_repo`` makes
    the same call for the same reason).
    """
    return _constraint_name(exc) == _DEDUPE_CONSTRAINT_NAME


def _is_endpoint_violation(exc: IntegrityError) -> bool:
    """``True`` only for a violation of ``uq_push_subscriptions_endpoint``."""
    return _constraint_name(exc) == _ENDPOINT_CONSTRAINT_NAME


def _constraint_name(exc: IntegrityError) -> str | None:
    """Best-effort constraint name off a psycopg ``IntegrityError``."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name is not None else None


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc
