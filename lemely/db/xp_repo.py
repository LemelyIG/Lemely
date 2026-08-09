"""XP awards and streak resolution (P5.2 chunk A, D5.1).

Engine only — this module writes and reads ``xp_events``/``streaks`` rows;
no route or call site in the rest of ``lemely`` calls it yet (that is P5.2
chunk B). Shape mirrors :mod:`lemely.db.flashcard_repo`: a plain
``sessionmaker`` constructor argument and an injectable clock (``now``,
defaulting to aware UTC now).

**Non-negotiable rules, each pinned by a test (D5.1):**

1. **:meth:`XpService.award` takes no mark, score, grade, percentage or
   accuracy argument — the parameter does not exist on the signature at
   all** (D5.1 §0). XP answers "did you do the work", never "were you good
   at it"; a leaderboard built from this table must never be a grade ranking
   in a costume.
2. **A streak-day is a civil date in ``Africa/Cairo``, never UTC** (D5.1 §4).
   Every conversion from an aware ``datetime`` to a streak-day goes through
   :func:`civil_date_in_zone`, the one helper in this module that touches a
   ``ZoneInfo`` — nothing else computes a streak date inline, and nothing
   ever hardcodes a ``+02:00`` offset (Egypt's DST history is not constant).
   The zone is a constructor parameter (:data:`DEFAULT_ZONE` is the launch
   default), not baked into the helper, so per-user timezones are a later
   wiring change rather than a rewrite.
3. **A capped award still succeeds and writes no row** (D5.1 §3). Hitting a
   per-source or the global daily cap returns
   ``XpAwardResult(awarded=False, amount=0, ...)`` — never an exception, and
   never a persisted ``amount=0`` row (that would corrupt the "XP this week
   by source" breakdown with entries that contributed nothing). The caller's
   underlying action (the review, the correction, the completion) is never
   gated on this.
4. **Idempotency is a database constraint, not caller discipline** (D5.1
   §8). Every award requires a non-empty ``dedupe_key``; a violation of
   ``uq_xp_events_user_source_dedupe`` (migration ``0013``) is treated as a
   no-op success (``reason=XpCapReason.duplicate``), never re-raised. Only
   *that* specific constraint is swallowed — :func:`_is_dedupe_violation`
   inspects the driver's ``constraint_name`` so a genuine foreign-key
   violation (e.g. an unknown ``subject_code``) still raises.
5. **Streaks resolve lazily, on both read and award** (D5.1 §5). There is no
   scheduler in this build; :meth:`XpService.streak` and the streak
   resolution inside :meth:`XpService.award` both run the same
   ``_resolve_gap`` catch-up logic from whatever ``last_active_on`` was
   persisted last, however long ago that was, and persist the result so a
   later call never re-consumes the same freeze twice.
6. **XP goes to students only** (D5.1 §10). :meth:`XpService.award` raises
   :class:`XpIneligibleUserError` for any other role — engagement mechanics
   are a student surface, and this is enforced structurally rather than
   trusted to every future call site.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from lemely.db.models.engagement import Streak, XpEvent
from lemely.db.models.enums import Role, XpSource
from lemely.db.models.users import User

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

#: Launch-market default (MISSION §1 scopes v1 to Egypt). Not a per-user
#: setting — see the module docstring and D5.1 §4.
DEFAULT_ZONE = ZoneInfo("Africa/Cairo")

#: XP awarded per unit of work (D5.1 §2). The ratios, not the absolute
#: numbers, are what matters: correcting a past paper is the product's core
#: loop and dominates; a flashcard review is one keypress and is worth one
#: point.
XP_AMOUNTS: dict[XpSource, int] = {
    XpSource.paper_corrected: 50,
    XpSource.quiz_completed: 30,
    XpSource.study_session_completed: 20,
    XpSource.flashcard_reviewed: 1,
}

#: Per-user, per-streak-day event-count caps (D5.1 §3). Counting *events*
#: rather than raw XP is deliberate — every source in :data:`XP_AMOUNTS`
#: awards a fixed amount per event, so an event-count cap and an
#: XP-ceiling cap are the same rule; the table below is the one D5.1 states
#: caps against.
DAILY_SOURCE_CAPS: dict[XpSource, int] = {
    XpSource.flashcard_reviewed: 60,
    XpSource.quiz_completed: 3,
    XpSource.paper_corrected: 5,
    XpSource.study_session_completed: 4,
}

#: Global per-user, per-streak-day XP ceiling across all sources (D5.1 §3).
GLOBAL_DAILY_CAP = 250

#: The Postgres constraint name migration ``0013`` creates. Only an
#: ``IntegrityError`` naming exactly this constraint is treated as the
#: idempotent no-op D5.1 §8 describes.
_DEDUPE_CONSTRAINT_NAME = "uq_xp_events_user_source_dedupe"

#: Freezes: one granted per 7 consecutive active days, never more than this
#: many held at once (D5.1 §5).
_MAX_FREEZES = 2
_FREEZE_GRANT_EVERY_DAYS = 7


def civil_date_in_zone(moment: datetime, *, zone: ZoneInfo) -> date:
    """Convert an aware ``datetime`` to its civil (calendar) date in ``zone``.

    The single conversion point D5.1 §4 requires: every place in this module
    that needs "which streak-day is this" goes through this function, never
    ``datetime.now(UTC).date()`` and never a hardcoded offset. ``zone`` is a
    required keyword, not a default baked into the function, so callers are
    forced to be explicit about which zone they mean.

    Raises:
        ValueError: ``moment`` is naive (no ``tzinfo``) — a naive datetime
            has no defined civil date in any zone.
    """
    if moment.tzinfo is None:
        raise ValueError("civil_date_in_zone requires an aware datetime")
    return moment.astimezone(zone).date()


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


class XpError(Exception):
    """Base class for XP/streak service failures."""


class XpUserNotFoundError(XpError):
    """No user exists for the supplied id (→ 404)."""


class XpIneligibleUserError(XpError):
    """The user exists but is not a student (→ 403-shaped; D5.1 §10)."""


class XpCapReason(StrEnum):
    """Why :meth:`XpService.award` wrote no row."""

    source_cap = "source_cap"
    global_cap = "global_cap"
    duplicate = "duplicate"


@dataclass(frozen=True, slots=True)
class XpAwardResult:
    """Outcome of :meth:`XpService.award`.

    ``awarded=False`` is a **success**, not an error — see rule 3 in the
    module docstring. ``amount`` is 0 whenever ``awarded`` is ``False``;
    ``event_id`` is ``None`` in the same case.
    """

    awarded: bool
    amount: int
    awarded_on: date
    reason: XpCapReason | None
    event_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class StreakState:
    """A user's streak as resolved as of a given moment."""

    current_length: int
    longest_length: int
    last_active_on: date | None
    freezes_available: int


@dataclass(frozen=True, slots=True)
class XpBreakdown:
    """A user's XP over an arbitrary date window (S-31), split by source.

    ``by_source`` always has all four :class:`~lemely.db.models.enums
    .XpSource` members as keys, 0 for any source with no XP in the window —
    a caller building a bar chart never has to special-case a missing key.
    """

    total: int
    by_source: dict[XpSource, int]


class XpService:
    """Award XP and resolve streaks against ``xp_events``/``streaks``.

    Constructed with a ``sessionmaker``, an injectable clock (mirroring
    :class:`~lemely.db.flashcard_repo.FlashcardService`), and the civil-date
    zone every streak-day calculation uses (:data:`DEFAULT_ZONE` unless a
    test overrides it).
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        now: Callable[[], datetime] = _utcnow,
        zone: ZoneInfo = DEFAULT_ZONE,
    ) -> None:
        """Wire the service to a session factory, a clock, and a streak-day zone."""
        self._sessionmaker = sessionmaker
        self._now = now
        self._zone = zone

    # -- Awarding -----------------------------------------------------------

    def award(
        self,
        user_id: uuid.UUID | str,
        source: XpSource,
        dedupe_key: str,
        *,
        subject_code: str | None = None,
        now: datetime | None = None,
    ) -> XpAwardResult:
        """Award XP for one occurrence of ``source``, idempotently and cap-aware.

        There is deliberately no mark/score/grade/percentage/accuracy
        parameter anywhere on this signature (D5.1 §0, rule 1 above).

        Args:
            user_id: The student earning XP. Must resolve to a ``users`` row
                with ``role=Role.student`` (D5.1 §10).
            source: Which of the four :class:`XpSource` acts this is.
            dedupe_key: Identity of the thing that caused this award (a
                paper id, assignment id, plan-session id, flashcard-review
                id) — must be non-empty. Combined with ``user_id``/``source``
                this is what migration ``0013``'s partial unique index
                enforces; re-awarding for the same identity is a no-op
                success (``reason=XpCapReason.duplicate``), not an error.
            subject_code: Optional subject attribution (D5.1 §7 as corrected
                by D5.2 — the syllabus code every award seam already carries,
                not a UUID). ``None`` for awards with no subject.
            now: Injected clock override for tests; defaults to this
                service's constructor-supplied clock.

        Raises:
            ValueError: ``dedupe_key`` is empty.
            XpUserNotFoundError: no user exists for ``user_id``.
            XpIneligibleUserError: the user exists but is not a student.
        """
        if not dedupe_key:
            raise ValueError("dedupe_key must be non-empty")
        student_uuid = _as_uuid(user_id)
        moment = now if now is not None else self._now()
        awarded_on = civil_date_in_zone(moment, zone=self._zone)
        amount = XP_AMOUNTS[source]

        with self._sessionmaker() as session, session.begin():
            user = session.get(User, student_uuid)
            if user is None:
                raise XpUserNotFoundError(f"Unknown user: {student_uuid}")
            if user.role != Role.student:
                raise XpIneligibleUserError(
                    f"User {student_uuid} has role={user.role!r}; XP is student-only (D5.1 §10)"
                )

            source_count = (
                session.scalar(
                    select(func.count())
                    .select_from(XpEvent)
                    .where(
                        XpEvent.user_id == student_uuid,
                        XpEvent.source == source,
                        XpEvent.awarded_on == awarded_on,
                    )
                )
                or 0
            )
            if source_count >= DAILY_SOURCE_CAPS[source]:
                return XpAwardResult(
                    awarded=False,
                    amount=0,
                    awarded_on=awarded_on,
                    reason=XpCapReason.source_cap,
                    event_id=None,
                )

            day_total = (
                session.scalar(
                    select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
                        XpEvent.user_id == student_uuid,
                        XpEvent.awarded_on == awarded_on,
                    )
                )
                or 0
            )
            if day_total + amount > GLOBAL_DAILY_CAP:
                return XpAwardResult(
                    awarded=False,
                    amount=0,
                    awarded_on=awarded_on,
                    reason=XpCapReason.global_cap,
                    event_id=None,
                )

            event = XpEvent(
                user_id=student_uuid,
                source=source,
                amount=amount,
                awarded_on=awarded_on,
                subject_code=subject_code,
                dedupe_key=dedupe_key,
            )
            try:
                with session.begin_nested():
                    session.add(event)
                    session.flush()
            except IntegrityError as exc:
                if not _is_dedupe_violation(exc):
                    raise
                return XpAwardResult(
                    awarded=False,
                    amount=0,
                    awarded_on=awarded_on,
                    reason=XpCapReason.duplicate,
                    event_id=None,
                )

            self._touch_streak(session, student_uuid, awarded_on)

            return XpAwardResult(
                awarded=True,
                amount=amount,
                awarded_on=awarded_on,
                reason=None,
                event_id=event.id,
            )

    # -- Reading --------------------------------------------------------------

    def total_xp(self, user_id: uuid.UUID | str) -> int:
        """The user's all-time XP total."""
        student_uuid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
                    XpEvent.user_id == student_uuid
                )
            )
            return int(total or 0)

    def xp_breakdown(self, user_id: uuid.UUID | str, *, start: date, end: date) -> XpBreakdown:
        """The user's XP in ``[start, end]`` (inclusive), split by source.

        Args:
            user_id: The student whose XP is summed.
            start: First ``awarded_on`` civil date included.
            end: Last ``awarded_on`` civil date included.
        """
        student_uuid = _as_uuid(user_id)
        by_source: dict[XpSource, int] = dict.fromkeys(XP_AMOUNTS, 0)
        with self._sessionmaker() as session:
            rows = session.execute(
                select(XpEvent.source, func.sum(XpEvent.amount))
                .where(
                    XpEvent.user_id == student_uuid,
                    XpEvent.awarded_on >= start,
                    XpEvent.awarded_on <= end,
                )
                .group_by(XpEvent.source)
            ).all()
        for source, amount in rows:
            by_source[source] = int(amount or 0)
        return XpBreakdown(total=sum(by_source.values()), by_source=by_source)

    def streak(self, user_id: uuid.UUID | str, *, now: datetime | None = None) -> StreakState:
        """Resolve and return the user's streak as of ``now``.

        Pure catch-up: this never marks the caller active "today" (only
        :meth:`award` does that) — it only resolves and persists whatever
        freeze consumption or reset is due for full missed days strictly
        before today, so a returning user's stale streak never appears
        healthier than it is just because nobody has read it in weeks (D5.1
        §5).
        """
        student_uuid = _as_uuid(user_id)
        moment = now if now is not None else self._now()
        today = civil_date_in_zone(moment, zone=self._zone)
        with self._sessionmaker() as session, session.begin():
            row = session.scalar(select(Streak).where(Streak.user_id == student_uuid))
            if row is None:
                return StreakState(
                    current_length=0, longest_length=0, last_active_on=None, freezes_available=0
                )
            self._resolve_gap(row, today)
            session.flush()
            return StreakState(
                current_length=row.current_length,
                longest_length=row.longest_length,
                last_active_on=row.last_active_on,
                freezes_available=row.freezes_available,
            )

    # -- Streak internals -----------------------------------------------------

    def _touch_streak(self, session: Session, student_uuid: uuid.UUID, today: date) -> StreakState:
        """Resolve any gap, then mark ``today`` active. Called only from :meth:`award`."""
        row = session.scalar(select(Streak).where(Streak.user_id == student_uuid))
        if row is None:
            row = Streak(
                user_id=student_uuid,
                current_length=0,
                longest_length=0,
                last_active_on=None,
                freezes_available=0,
            )
            session.add(row)
            session.flush()

        self._resolve_gap(row, today)

        if row.last_active_on != today:
            row.current_length += 1
            row.longest_length = max(row.longest_length, row.current_length)
            if row.current_length % _FREEZE_GRANT_EVERY_DAYS == 0:
                row.freezes_available = min(_MAX_FREEZES, row.freezes_available + 1)
            row.last_active_on = today

        session.flush()
        return StreakState(
            current_length=row.current_length,
            longest_length=row.longest_length,
            last_active_on=row.last_active_on,
            freezes_available=row.freezes_available,
        )

    def _resolve_gap(self, row: Streak, today: date) -> None:
        """Catch up ``row`` for every full missed day strictly before ``today``.

        Idempotent and safe to call no matter how long ago ``last_active_on``
        was (D5.1 §5's 40-day-absence case) — it always resolves in one step
        rather than iterating day by day:

        * No ``last_active_on`` yet, or it is yesterday or later: nothing to
          resolve (today is still open; a genuinely missed day cannot be
          judged until it is over).
        * Otherwise there are ``missed`` full missed days between
          ``last_active_on`` and yesterday inclusive. If enough freezes are
          held to cover all of them, they are spent and ``current_length``
          is preserved unchanged (D5.1 §5: a freeze preserves but never
          increments). Otherwise every held freeze is spent trying and the
          streak resets to 0 — ``longest_length`` is never touched here
          because it never decreases.

        **``last_active_on`` advances to yesterday only on the freeze branch,
        and deliberately not on the reset branch.** On the freeze branch it
        must advance, or a second call for the same ``today`` (a read
        immediately followed by an award) would recompute the same gap and
        double-spend the freeze. On the reset branch advancing it would be a
        lie: it would report the user as active yesterday when the whole
        reason this branch ran is that they were not. That value is surfaced
        through :class:`StreakState` to S-31, where "last active" is shown to
        the student, and UI spec §1.4 forbids inventing precision. Leaving it
        at the true last-active day costs nothing, because the reset branch is
        already idempotent on its own terms — re-running it recomputes a
        larger ``missed`` against ``current_length=0`` and
        ``freezes_available=0`` and changes neither.
        """
        if row.last_active_on is None:
            return
        yesterday = today - timedelta(days=1)
        if row.last_active_on >= yesterday:
            return
        missed = (yesterday - row.last_active_on).days
        if missed <= row.freezes_available:
            row.freezes_available -= missed
            row.last_active_on = yesterday
        else:
            row.current_length = 0
            row.freezes_available = 0


def _is_dedupe_violation(exc: IntegrityError) -> bool:
    """``True`` only for a violation of ``uq_xp_events_user_source_dedupe``.

    Any other integrity error (a foreign-key violation from an unknown
    ``subject_code``, for instance) must keep propagating — swallowing every
    ``IntegrityError`` indiscriminately would silently turn a real bug into
    a fake "already awarded" no-op.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    return constraint_name == _DEDUPE_CONSTRAINT_NAME


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "DAILY_SOURCE_CAPS",
    "DEFAULT_ZONE",
    "GLOBAL_DAILY_CAP",
    "XP_AMOUNTS",
    "StreakState",
    "XpAwardResult",
    "XpBreakdown",
    "XpCapReason",
    "XpError",
    "XpIneligibleUserError",
    "XpService",
    "XpUserNotFoundError",
    "civil_date_in_zone",
]
