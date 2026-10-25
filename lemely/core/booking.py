"""Tutoring booking rules: the state machine and bookable slots (SPEC §a.3, §e.1).

Pure by construction: no ``lemely.db``, ``web``, ``io`` or ``app`` import, no
SQLAlchemy, no FastAPI and no clock of its own (import-linter ``forbidden``
contract, SPEC §e.1). Every rule that depends on time takes ``now``; inside a
write transaction the caller passes the database ``now()`` (SPEC §0 "Clock",
BK-7), and the compare-and-set ``WHERE`` repeats the same guard.

**Literals are written out here on purpose.** ``BookingStateLit`` and ``Party``
mirror the Postgres enums ``bookingstate`` and ``bookingparty``. ``core`` may
not import ``lemely.db``, so the pin against the Python enums lives in
``tests/test_tutoring_cross_pins.py`` (PLAN §1.4 #11), the same split as
``PaperOrigin`` and ``AttemptOrigin`` in :mod:`lemely.core.history`.

**State machine** (:func:`check_transition`, SPEC §a.3). Each refusal carries
the code its route returns:

- ``accept``/``decline``: the tutor, on ``requested``, while ``now < starts_at``
  (later: ``already_started``).
- ``cancel``: the student, or the parent who requested it (``not_requester``
  otherwise, O8). A ``requested`` booking until its start (afterwards it is
  expired: ``illegal_transition``); an ``accepted`` one while
  ``now <= starts_at - CANCEL_CUTOFF`` (later: ``cancel_window_closed``, row 18).
  The tutor cancels an ``accepted`` booking until the start
  (``already_started``), and inside the 24 hours only with a reason
  (``reason_required``, row 18); a tutor declines a request rather than cancel
  it. ``platform_admin`` (A11, suspension, close) and ``system`` (block)
  cancel any active booking before its start: the booking table lists them for
  ``accepted`` only, but §a.2 (blocks) and the §a.3 listing table cancel
  "future active bookings", which includes ``requested``.
- ``complete``/``no_show``: the tutor, on ``accepted``, once ``now >= ends_at``
  (``not_ended``, SC-17). ``platform_admin`` completes an ended ``accepted``
  booking or a ``no_show`` (A11 on a ``disputed_outcome`` report).
- ``claim_complete``: the student or the requesting parent, on ``accepted``,
  from ``ends_at + OUTCOME_CLAIM_AFTER`` while no tutor outcome is recorded;
  every other case is ``outcome_claim_not_open`` (O23).
- ``expire``: ``system``, lazily, on ``requested`` once ``now >= starts_at``.

Anything else is ``illegal_transition``.

**Slots and daylight saving** (F27). Weekly rules are wall clock in the tutor's
zone. :func:`occurrences` turns each rule into UTC bounds with every endpoint
round-trip checked, because ``zoneinfo`` does not raise for a wall time that
does not exist: it silently shifts it by the size of the gap. A missing time is
clipped to the first valid instant after it (the moment the clocks jump); a
repeated one resolves with ``fold=0``. :func:`bookable_slots` steps in absolute
time inside each occurrence and never offers a slot whose local start or end is
ambiguous, so the clock-change hour is never bookable and no two offered slots
share a label. :func:`bookable` is defined as membership in
:func:`bookable_slots`, so the server accepts only instants it could have
offered (BK-7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Final, Literal
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

BookingStateLit = Literal[
    "requested", "accepted", "declined", "cancelled", "completed", "no_show", "expired"
]
EffectiveState = Literal[
    "requested",
    "accepted",
    "declined",
    "cancelled",
    "completed",
    "no_show",
    "expired",
    "awaiting_outcome",
]
Party = Literal["student", "parent", "tutor", "platform_admin", "system"]
Action = Literal["accept", "decline", "cancel", "complete", "no_show", "expire", "claim_complete"]

# Pinned to both exclusion constraints' ``where`` text and the ORM (T05).
ACTIVE_STATES: Final[frozenset[str]] = frozenset({"requested", "accepted"})
CANCEL_CUTOFF: Final = timedelta(hours=24)  # row 9; pinned to ck_tutor_bookings_late_cancel_reason
MIN_NOTICE: Final = timedelta(hours=2)  # O-10
MAX_BOOKING_HORIZON: Final = timedelta(days=28)  # SC-8
ALLOWED_DURATIONS: Final = (45, 60, 90, 120)
MAX_PENDING_PER_STUDENT: Final = 5
NOTE_POST_GRACE: Final = timedelta(days=7)
OUTCOME_CLAIM_AFTER: Final = timedelta(hours=48)  # SC-17
SLOT_STEP: Final = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class AvailabilityRule:
    """One weekly window in the tutor's zone; ISO weekday (Monday = 1), minutes of day."""

    iso_weekday: int
    start_minute: int
    end_minute: int


@dataclass(frozen=True, slots=True)
class BookingFacts:
    """What a transition or the viewer's action list depends on, besides ``now``.

    ``viewer_is_requester`` matters for a parent only (O8): the student is the
    booking's subject and may act whoever requested it.
    """

    state: BookingStateLit
    starts_at: datetime
    ends_at: datetime
    viewer: Party
    viewer_is_requester: bool
    tutor_outcome_recorded: bool


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why a transition or a booking request is refused; ``code`` is the API error code."""

    code: str


class OverlappingRules(ValueError):
    """Two availability rules share time on the same weekday (422 ``overlapping_rules``)."""

    def __init__(self, first: AvailabilityRule, second: AvailabilityRule) -> None:
        super().__init__(
            f"availability rules overlap on ISO weekday {first.iso_weekday}: "
            f"{first.start_minute}-{first.end_minute} and "
            f"{second.start_minute}-{second.end_minute}"
        )
        self.first = first
        self.second = second


_ILLEGAL: Final = Refusal("illegal_transition")
_ALREADY_STARTED: Final = Refusal("already_started")
_CANCEL_WINDOW_CLOSED: Final = Refusal("cancel_window_closed")
_REASON_REQUIRED: Final = Refusal("reason_required")
_NOT_ENDED: Final = Refusal("not_ended")
_NOT_REQUESTER: Final = Refusal("not_requester")
_OUTCOME_CLAIM_NOT_OPEN: Final = Refusal("outcome_claim_not_open")
_BEYOND_HORIZON: Final = Refusal("beyond_horizon")
_NOT_BOOKABLE: Final = Refusal("not_bookable")

_TARGET_STATE: Final[Mapping[Action, BookingStateLit]] = {
    "accept": "accepted",
    "decline": "declined",
    "cancel": "cancelled",
    "complete": "completed",
    "no_show": "no_show",
    "expire": "expired",
    "claim_complete": "completed",
}
_TUTOR_ACTIONS: Final[tuple[Action, ...]] = ("accept", "decline", "complete", "no_show")
_DURATIONS: Final = frozenset(timedelta(minutes=minutes) for minutes in ALLOWED_DURATIONS)
_ONE_SECOND: Final = timedelta(seconds=1)
_MINUTES_PER_DAY: Final = 24 * 60
_RULE_GRANULARITY: Final = 15


# --- availability rules and slots ---------------------------------------------------------


def _check_rule(rule: AvailabilityRule) -> None:
    """Refuse a rule the ``tutor_availability_rules`` CHECKs would refuse (SPEC §a.2)."""
    start, end = rule.start_minute, rule.end_minute
    if not (
        1 <= rule.iso_weekday <= 7
        and 0 <= start < end <= _MINUTES_PER_DAY
        and start % _RULE_GRANULARITY == 0
        and end % _RULE_GRANULARITY == 0
    ):
        raise ValueError(f"invalid availability rule {rule!r}")


def normalize_rules(rules: Iterable[AvailabilityRule]) -> tuple[AvailabilityRule, ...]:
    """Validate rules and return them sorted by weekday and start.

    Windows are half-open ``[start, end)`` like the exclusion constraint
    ``excl_tutor_availability_rules_no_overlap``, so adjacent rules are allowed
    and are not merged. Raises :class:`OverlappingRules` for an overlap and
    :class:`ValueError` for a rule outside the table's CHECKs.
    """
    ordered = sorted(rules, key=lambda rule: (rule.iso_weekday, rule.start_minute))
    for rule in ordered:
        _check_rule(rule)
    for previous, current in pairwise(ordered):
        if previous.iso_weekday == current.iso_weekday and current.start_minute < (
            previous.end_minute
        ):
            raise OverlappingRules(previous, current)
    return tuple(ordered)


def _wall_of(instant: datetime, tz: ZoneInfo) -> datetime:
    return instant.astimezone(tz).replace(tzinfo=None)


def _first_instant_after_gap(wall: datetime, tz: ZoneInfo) -> datetime:
    """The first instant whose wall time is at or after a nonexistent ``wall``.

    Read with the offset after the jump (``fold=1``) the wall time lands before
    the gap; read with the offset before it (``fold=0``) it lands after. The
    jump lies between the two; a binary search over whole seconds finds it
    (tz transitions fall on whole seconds).
    """
    before = wall.replace(tzinfo=tz, fold=1).astimezone(UTC)
    after = wall.replace(tzinfo=tz, fold=0).astimezone(UTC)
    while after - before > _ONE_SECOND:
        middle = before + timedelta(seconds=int((after - before).total_seconds()) // 2)
        if _wall_of(middle, tz) >= wall:
            after = middle
        else:
            before = middle
    return after


def _resolve_wall(wall: datetime, tz: ZoneInfo) -> datetime:
    """UTC instant of a tutor-zone wall time, round-trip checked (F27)."""
    instant = wall.replace(tzinfo=tz, fold=0).astimezone(UTC)
    if _wall_of(instant, tz) == wall:
        return instant  # exists; a repeated wall time resolves with fold=0
    return _first_instant_after_gap(wall, tz)


def _wall_is_unique(instant: datetime, tz: ZoneInfo) -> bool:
    """True when the instant's wall time occurs exactly once (exists, not repeated)."""
    wall = _wall_of(instant, tz)
    return all(wall.replace(tzinfo=tz, fold=fold).astimezone(UTC) == instant for fold in (0, 1))


def occurrences(
    rules: Iterable[AvailabilityRule], *, zone: str, start: date, days: int
) -> list[tuple[datetime, datetime]]:
    """UTC bounds of every rule occurrence on ``days`` tutor-zone dates from ``start``.

    A rule whose window falls wholly inside a missing hour yields nothing. The
    result is sorted and non-overlapping (rules are normalised first).
    """
    tz = ZoneInfo(zone)
    ordered = normalize_rules(rules)
    bounds: list[tuple[datetime, datetime]] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        midnight = datetime.combine(day, time())
        for rule in ordered:
            if rule.iso_weekday != day.isoweekday():
                continue
            lower = _resolve_wall(midnight + timedelta(minutes=rule.start_minute), tz)
            upper = _resolve_wall(midnight + timedelta(minutes=rule.end_minute), tz)
            if lower < upper:
                bounds.append((lower, upper))
    return bounds


def _overlaps_any(
    lower: datetime, upper: datetime, busy: Sequence[tuple[datetime, datetime]]
) -> bool:
    return any(lower < busy_end and busy_start < upper for busy_start, busy_end in busy)


def bookable_slots(
    rules: Iterable[AvailabilityRule],
    *,
    zone: str,
    start: date,
    days: int,
    duration: timedelta,
    busy: Sequence[tuple[datetime, datetime]],
    now: datetime,
) -> list[tuple[datetime, datetime]]:
    """Every offerable ``[starts_at, ends_at)`` in the window, in UTC and in order.

    Slots start at each occurrence's start plus whole ``SLOT_STEP`` steps of
    absolute time, end inside the occurrence, start in
    ``[now + MIN_NOTICE, now + MAX_BOOKING_HORIZON]``, overlap no ``busy``
    interval (adjacent is fine) and have an unambiguous local start and end.
    Raises :class:`ValueError` for a duration outside ``ALLOWED_DURATIONS``.
    """
    if duration not in _DURATIONS:
        raise ValueError(f"duration {duration} is not one of {ALLOWED_DURATIONS} minutes")
    tz = ZoneInfo(zone)
    earliest = now + MIN_NOTICE
    latest = now + MAX_BOOKING_HORIZON
    slots: list[tuple[datetime, datetime]] = []
    for lower, upper in occurrences(rules, zone=zone, start=start, days=days):
        slot_start = lower
        while slot_start + duration <= upper:
            slot_end = slot_start + duration
            if (
                earliest <= slot_start <= latest
                and _wall_is_unique(slot_start, tz)
                and _wall_is_unique(slot_end, tz)
                and not _overlaps_any(slot_start, slot_end, busy)
            ):
                slots.append((slot_start, slot_end))
            slot_start += SLOT_STEP
    return slots


def bookable(
    rules: Iterable[AvailabilityRule],
    *,
    zone: str,
    starts_at: datetime,
    ends_at: datetime,
    busy: Sequence[tuple[datetime, datetime]],
    now: datetime,
) -> Refusal | None:
    """``None`` exactly when ``(starts_at, ends_at)`` is in :func:`bookable_slots`.

    ``beyond_horizon`` when ``starts_at`` is later than ``now +
    MAX_BOOKING_HORIZON`` (SC-8); ``not_bookable`` for every other non-member,
    including a duration outside ``ALLOWED_DURATIONS``.
    """
    if starts_at > now + MAX_BOOKING_HORIZON:
        return _BEYOND_HORIZON
    duration = ends_at - starts_at
    if duration not in _DURATIONS:
        return _NOT_BOOKABLE
    # An occurrence never extends past the next local midnight, plus a clipped gap;
    # the slot's own local date and its neighbours cover every occurrence it can be in.
    local_day = starts_at.astimezone(ZoneInfo(zone)).date()
    slots = bookable_slots(
        rules,
        zone=zone,
        start=local_day - timedelta(days=1),
        days=3,
        duration=duration,
        busy=busy,
        now=now,
    )
    return None if (starts_at, ends_at) in slots else _NOT_BOOKABLE


# --- state machine ------------------------------------------------------------------------


def effective_state(
    state: BookingStateLit, *, starts_at: datetime, ends_at: datetime, now: datetime
) -> EffectiveState:
    """Read-time state; mirrors the SQL predicates of the SPEC §a.3 table."""
    if state == "requested":
        return "requested" if starts_at > now else "expired"
    if state == "accepted":
        return "accepted" if ends_at > now else "awaiting_outcome"
    return state


def _answer_request(facts: BookingFacts, *, now: datetime) -> Refusal | None:
    if facts.viewer != "tutor" or facts.state != "requested":
        return _ILLEGAL
    return None if now < facts.starts_at else _ALREADY_STARTED


def _cancel(facts: BookingFacts, *, now: datetime, has_reason: bool) -> Refusal | None:
    if facts.viewer == "parent" and not facts.viewer_is_requester:
        return _NOT_REQUESTER
    if facts.state not in ACTIVE_STATES:
        return _ILLEGAL
    if facts.viewer in ("student", "parent"):
        if facts.state == "requested":
            return None if now < facts.starts_at else _ILLEGAL
        return None if now <= facts.starts_at - CANCEL_CUTOFF else _CANCEL_WINDOW_CLOSED
    if facts.viewer == "tutor":
        if facts.state == "requested":
            return _ILLEGAL
        if now >= facts.starts_at:
            return _ALREADY_STARTED
        if now > facts.starts_at - CANCEL_CUTOFF and not has_reason:
            return _REASON_REQUIRED
        return None
    return None if now < facts.starts_at else _ALREADY_STARTED


def _record_outcome(action: Action, facts: BookingFacts, *, now: datetime) -> Refusal | None:
    if facts.viewer == "tutor" and facts.state == "accepted":
        return None if now >= facts.ends_at else _NOT_ENDED
    if action == "complete" and facts.viewer == "platform_admin":
        if facts.state == "no_show":
            return None
        if facts.state == "accepted":
            return None if now >= facts.ends_at else _NOT_ENDED
    return _ILLEGAL


def _claim_complete(facts: BookingFacts, *, now: datetime) -> Refusal | None:
    if facts.viewer not in ("student", "parent"):
        return _ILLEGAL
    if facts.viewer == "parent" and not facts.viewer_is_requester:
        return _NOT_REQUESTER
    if (
        facts.state == "accepted"
        and not facts.tutor_outcome_recorded
        and now >= facts.ends_at + OUTCOME_CLAIM_AFTER
    ):
        return None
    return _OUTCOME_CLAIM_NOT_OPEN


def check_transition(
    action: Action, facts: BookingFacts, *, now: datetime, has_reason: bool = False
) -> Refusal | None:
    """``None`` when ``facts.viewer`` may apply ``action`` now; otherwise the refusal.

    ``has_reason``: the request carries a non-blank reason (the caller strips
    it). It only matters for a tutor cancelling inside ``CANCEL_CUTOFF``.
    """
    if action in ("accept", "decline"):
        return _answer_request(facts, now=now)
    if action == "cancel":
        return _cancel(facts, now=now, has_reason=has_reason)
    if action in ("complete", "no_show"):
        return _record_outcome(action, facts, now=now)
    if action == "claim_complete":
        return _claim_complete(facts, now=now)
    if facts.viewer == "system" and facts.state == "requested" and now >= facts.starts_at:
        return None  # expire
    return _ILLEGAL


def is_late_cancel(*, cancelled_by: Party, cancelled_at: datetime, starts_at: datetime) -> bool:
    """A tutor cancelled inside ``CANCEL_CUTOFF`` of the start (``BookingDTO.cancelledLate``)."""
    return cancelled_by == "tutor" and cancelled_at > starts_at - CANCEL_CUTOFF


def target_state(action: Action) -> BookingStateLit:
    return _TARGET_STATE[action]


def allowed_actions(
    facts: BookingFacts,
    *,
    now: datetime,
    has_review: bool,
    blocked: bool,
    review_account_ok: bool,
) -> frozenset[str]:
    """The ``BookingDTO.allowedActions`` a student, parent or tutor viewer gets now.

    Derived from :func:`check_transition`, so it never offers a refused action.
    ``complete`` is the tutor's outcome for a tutor and the 48-hour claim for a
    student or requesting parent. A tutor inside ``CANCEL_CUTOFF`` gets
    ``cancel_with_reason`` instead of ``cancel`` (row 18); ``blocked`` withholds
    ``accept`` (T11). ``review`` goes to the student of a ``completed`` booking
    from :func:`review_open_at` when no review exists and the account is old
    enough (O10). Never ``post_note``: that needs :func:`can_post_note`'s
    ``tutor_inactive`` and ``frozen``, so the DTO builder adds it. Other viewers
    get nothing.
    """
    if facts.viewer not in ("student", "parent", "tutor"):
        return frozenset()
    actions: set[str] = set()
    if facts.viewer == "tutor":
        actions.update(
            action for action in _TUTOR_ACTIONS if check_transition(action, facts, now=now) is None
        )
        if blocked:
            actions.discard("accept")
    elif check_transition("claim_complete", facts, now=now) is None:
        actions.add("complete")
    refusal = check_transition("cancel", facts, now=now)
    if refusal is None:
        actions.add("cancel")
    elif (
        refusal == _REASON_REQUIRED
        and check_transition("cancel", facts, now=now, has_reason=True) is None
    ):
        actions.add("cancel_with_reason")
    if (
        facts.viewer == "student"
        and facts.state == "completed"
        and not has_review
        and review_account_ok
        and now >= review_open_at(facts.ends_at)
    ):
        actions.add("review")
    return frozenset(actions)


def can_post_note(
    state: EffectiveState,
    *,
    ends_at: datetime,
    now: datetime,
    blocked: bool,
    tutor_inactive: bool,
    frozen: bool,
) -> bool:
    """Whether the booking's student or tutor may post a note (SPEC §a.3 notes table, SC-8).

    ``state`` is the effective state. Notes close at ``ends_at`` for a live
    request or an upcoming session, and at ``ends_at + NOTE_POST_GRACE`` after
    the session, the instant reviews open.
    """
    if blocked or tutor_inactive or frozen:
        return False
    if state in ("requested", "accepted"):
        return now < ends_at
    if state in ("awaiting_outcome", "completed"):
        return now < ends_at + NOTE_POST_GRACE
    return False


def review_open_at(ends_at: datetime) -> datetime:
    """When the student may review: notes close and reviews open together (O10)."""
    return ends_at + NOTE_POST_GRACE
