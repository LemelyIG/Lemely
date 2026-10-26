"""Tutoring bookings and their notes: the booking service (SPEC §a.3, §a.4, §a.4b, §b.2, §b.4).

This module is the single writer of ``tutor_bookings`` and ``tutor_booking_notes``. It serves the
family routes (SP5, SP6, S1-S5, S14, PA1-PA5), the tutor routes (T9-T17) and, through the
``*_in_session`` helpers, the block, suspension and report paths that run inside another
module's transaction (T21, T25).

**Rules come from the core, SQL from the shared predicates.** Every decision a transition makes
is ``core.booking.check_transition`` evaluated against the row read *inside* the write
transaction, with the database ``now()`` (SPEC §0 "Clock", BK-7). The same rule is then repeated
in the compare-and-set ``WHERE`` (:func:`transition_guard_sql`, parity-tested against the core
over generated rows), so a write that slipped past the core still matches no row. Effective
states, live pending requests, listing visibility and blocks are the fragments of
:mod:`lemely.db.tutoring_predicates`, never restated here.

**Lock order (SPEC §a.4b, §i.6).** Every write takes, in this order and only these:

1. the ``tutor_profiles`` row ``FOR SHARE`` (a block, suspension or close holds it
   ``FOR UPDATE``, so none of them can interleave with a booking write);
2. the subject student's ``users`` row: ``FOR UPDATE`` for a booking create, which serialises the
   live pending count (BK-2, SC-24); ``FOR KEY SHARE`` for every other write. The weaker lock is
   still taken *before* step 3 on purpose: the writes after it insert rows that reference the
   student (an outbox row, a note, ``cancelled_by_user_id``), and those foreign-key checks take
   ``KEY SHARE`` on the student row. Taken late, that check would wait on a create holding the
   row ``FOR UPDATE`` while the create waits on this write's pair lock: a deadlock. ``KEY SHARE``
   does not conflict with the child row's ``FOR NO KEY UPDATE`` that an unlink takes (T09). The
   sweeps (block, suspension, close) follow the same rule for every student they cancel for:
   they take those rows ``FOR KEY SHARE``, in id order, before their ``UPDATE`` (see
   ``BookingService._cancel_future``);
3. the pair lock, ``pg_advisory_xact_lock(hashtextextended(student_id || ':' || tutor_profile_id,
   0))`` (:func:`lock_pair_in_session`, shared with the grant and block paths);
4. a parent actor's link, ``ParentLinkService.lock_link_in_session`` (``FOR SHARE``), always
   after the child row (SPEC §i.6). The link is never read with SQL here: ``parent_repo`` stays
   the single ``parent_child_links`` query;
5. the booking rows, through the compare-and-set ``UPDATE`` (a note post takes its booking row
   ``FOR SHARE`` instead, so a safety freeze cannot interleave with it).

Every guard is read *after* the locks, in a later statement than the one that waited for them,
so a block or a suspension committed while this transaction queued is seen.

**Compare-and-set (SPEC §a.3).** ``UPDATE ... WHERE id AND <state, time and party guard> AND
<owner> AND <tutor active> RETURNING id``. Zero rows: the row is read again; if the target state
already holds the call is an idempotent repeat (200, no notice, no email); otherwise the refusal
is the core's code, or ``illegal_transition``. The row-18 CHECK
``ck_tutor_bookings_late_cancel_reason`` is the last of three layers and is deliberately *not*
mapped: reaching it means the first two failed, and it raises.

**Errors.** :class:`BookingRefused` carries the API code and status the route sends. Constraint
violations are mapped by ``constraint_name`` (SPEC §a.4): ``excl_tutor_bookings_tutor_slot`` ->
409 ``slot_taken``, ``excl_tutor_bookings_student_slot`` -> 409 ``student_busy``,
``uq_tutor_bookings_one_pending`` -> 409 ``already_pending``; anything else propagates.

**Side effects (SPEC §b.4, D5.9 §1).** Email outbox rows are written here, in the change's own
transaction, so they commit or roll back with it. Inbox notices are the caller's, after commit:
each write returns a :class:`BookingRow` (or :class:`NoteRow`) whose ``notice`` names the event,
the actor and the linked parents read inside the transaction, and
``lemely.web.booking_view.booking_notices_for`` turns that into the notices. Nobody is told about
their own action. A requesting parent gets no ``booking_requested_family`` email for the request
they made themselves (the same rule as the inbox, SPEC §i.5).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, cast
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from lemely.core.booking import (
    ALLOWED_DURATIONS,
    CANCEL_CUTOFF,
    MAX_BOOKING_HORIZON,
    MAX_PENDING_PER_STUDENT,
    OUTCOME_CLAIM_AFTER,
    AvailabilityRule,
    BookingFacts,
    bookable,
    bookable_slots,
    can_post_note,
    check_transition,
    effective_state,
    is_late_cancel,
    target_state,
)
from lemely.core.contact_patterns import find_contact_details, meeting_link_allowed
from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.core.tutor_directory import public_name, student_label
from lemely.db.email_outbox_repo import enqueue_in_session
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_directory_repo import MODES, TutorCard, subjects_by_tutor
from lemely.db.tutoring_predicates import (
    ACTIVE_STATES_SQL,
    EFFECTIVE_STATE_SQL,
    LIVE_PENDING_SQL,
    active_block_between_sql,
    listed_and_not_paused_sql,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from sqlalchemy.engine import RowMapping
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.booking import Action, BookingStateLit, EffectiveState, Party
    from lemely.db.tutor_directory_repo import Mode

ActorParty = Literal["student", "parent", "tutor"]
When = Literal["upcoming", "past"]
BookingEvent = Literal["requested", "accepted", "declined", "cancelled", "completed", "no_show"]
Audience = Literal["tutor", "student", "parent"]

#: SPEC §0 "Paging": ``limit`` 1..50.
MAX_PAGE_SIZE: Final = 50
#: ``ck_tutor_booking_notes_body_len``: 1..2000 characters after trimming.
MAX_NOTE_LENGTH: Final = 2000
#: ``decline_reason``/``cancel_reason`` are varchar(300).
MAX_REASON_LENGTH: Final = 300
#: ``location_detail`` is varchar(300).
MAX_LOCATION_LENGTH: Final = 300
#: ``other_mode_note`` is varchar(300).
MAX_OTHER_MODE_NOTE_LENGTH: Final = 300
#: SC-15: at most this many booking requests per requester per :data:`QUOTA_WINDOW`.
BOOKING_CREATE_QUOTA: Final = 10
#: SC-15: at most this many cancellations per canceller per :data:`QUOTA_WINDOW`.
CANCEL_QUOTA: Final = 10
QUOTA_WINDOW: Final = timedelta(hours=24)
#: The fixed reason a block's cancellations carry (party ``system``). It names nobody, so the
#: student or tutor reading it cannot tell who blocked whom; the tutor reads "Cancelled" (SC-11).
SYSTEM_CANCEL_REASON: Final = "This session was cancelled."
#: The fixed reason of a platform cancellation: a suspension, a close or a report decision.
ADMIN_CANCEL_REASON: Final = "This session was cancelled by Lemely."

#: The binds every :func:`transition_guard_sql` fragment may name besides ``actor_id`` and
#: ``reason``: the row-18 cutoff and the outcome-claim delay from ``core.booking``, as elapsed
#: seconds (SPEC §i.4). Never bind a ``timedelta`` here: psycopg sends ``timedelta(hours=24)`` as
#: ``'1 day'``, a calendar day, and in a session whose time zone keeps daylight saving
#: (``Africa/Cairo``) ``starts_at - interval '1 day'`` is 23 or 25 hours across a clock change,
#: so the guard would disagree with the core and with the CHECK's literal ``'24 hours'``.
GUARD_BINDS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "cancel_cutoff_s": CANCEL_CUTOFF.total_seconds(),
        "claim_after_s": OUTCOME_CLAIM_AFTER.total_seconds(),
    }
)
#: The start of the SC-15 quota window, :data:`QUOTA_WINDOW` of elapsed time before ``now()``.
QUOTA_SINCE_SQL: Final = "now() - make_interval(secs => CAST(:quota_window_s AS double precision))"
#: The bind :data:`QUOTA_SINCE_SQL` names, in seconds for the reason given at :data:`GUARD_BINDS`.
QUOTA_BINDS: Final[Mapping[str, object]] = MappingProxyType(
    {"quota_window_s": QUOTA_WINDOW.total_seconds()}
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

#: Status per refusal code; every code not listed is a 409 (SPEC §0 "Errors", §b.2).
_STATUS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "not_found": 404,
        "not_self": 403,
        "not_linked": 403,
        "not_requester": 403,
        "student_required": 422,
        "note_not_allowed_for_parent": 422,
        "contact_details_not_allowed": 422,
        "text_too_long": 422,
        "note_empty": 422,
        "reason_required": 422,
        "meeting_link_not_allowed": 422,
        "location_required": 422,
        "invalid_starts_at": 422,
        "invalid_window": 422,
        "invalid_duration": 422,
        "too_many_requests": 429,
    }
)

_MESSAGES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "not_found": "Booking not found.",
        "not_self": "You can only book a session for yourself.",
        "not_linked": "This child is not linked to your account.",
        "not_requester": "Only the person who requested this session can do that.",
        "student_required": "Choose which child the session is for.",
        "note_not_allowed_for_parent": "Only the student can add a first note.",
        "contact_details_not_allowed": (
            "Keep phone numbers, emails and links out. Lemely connects students and tutors."
        ),
        "text_too_long": "That text is too long.",
        "note_empty": "Write a note first.",
        "reason_required": "Add a reason. Cancelling this close to the start needs one.",
        "meeting_link_not_allowed": "Use a Google Meet, Zoom, Teams or Whereby link.",
        "location_required": "Add where the session will take place.",
        "invalid_starts_at": "Send the start time with its time zone.",
        "invalid_window": "Choose dates from today up to 28 days ahead.",
        "invalid_duration": "Choose 45, 60, 90 or 120 minutes.",
        "too_many_requests": "That is happening too often. Try again in a little while.",
        "tutor_not_listed": "This tutor is not taking requests right now.",
        "blocked": "You can't book this tutor.",
        "not_bookable": "That time, subject or way of meeting can't be booked with this tutor.",
        "beyond_horizon": "Sessions can only be booked up to 28 days ahead.",
        "slot_taken": "That time was just taken. Choose another.",
        "student_busy": "There is already a session at that time.",
        "already_pending": "There is already a request waiting with this tutor.",
        "pending_limit": "Five requests are already waiting. Wait for an answer first.",
        "safety_notice_required": "Read the safety notice first.",
        "illegal_transition": "This session can't be changed that way now.",
        "cancel_window_closed": "Sessions can't be cancelled in the 24 hours before they start.",
        "already_started": "This session has already started.",
        "not_ended": "This session has not ended yet.",
        "outcome_claim_not_open": (
            "You can mark a session completed 48 hours after it ends if the tutor has not."
        ),
        "notes_closed": "Notes are closed for this session.",
        "tutor_suspended": "Your tutor profile is suspended.",
        "tutor_closed": "Your tutor profile is closed.",
        "access_ended": "You can't accept this request.",
    }
)
#: ``tutor_not_listed`` as the tutor reads it when accepting on a draft or rejected profile: the
#: message above is the family's (SP6) and speaks of "this tutor".
_TUTOR_NOT_LISTED_FOR_TUTOR: Final = (
    "Your tutor profile is not listed right now, so you can't accept requests."
)


class BookingRefused(Exception):
    """A refusal the route sends as ``tutoring_error(status, code, message)``.

    ``code`` is the stable API code (SPEC §b.2), ``status`` its HTTP status and ``message`` one
    plain English sentence.
    """

    def __init__(self, code: str, status: int, message: str | None = None) -> None:
        """Record the code, status and message."""
        self.code = code
        self.status = status
        self.message = message or _MESSAGES.get(code, "This request can't be completed.")
        super().__init__(self.message)


def _refuse(code: str, message: str | None = None) -> BookingRefused:
    return BookingRefused(code, _STATUS.get(code, 409), message)


_CONSTRAINT_REFUSALS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "excl_tutor_bookings_tutor_slot": "slot_taken",
        "excl_tutor_bookings_student_slot": "student_busy",
        "uq_tutor_bookings_one_pending": "already_pending",
    }
)


def _constraint_refusal(exc: IntegrityError) -> BookingRefused | None:
    """The refusal for a known constraint (SPEC §a.4), or ``None`` to let ``exc`` propagate."""
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    code = _CONSTRAINT_REFUSALS.get(name) if isinstance(name, str) else None
    return _refuse(code) if code is not None else None


# ---------------------------------------------------------------------------
# Inputs and read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Actor:
    """Who acts or views: the caller's ``users.id`` and party.

    ``child_id`` is a parent's child from the route path (PA routes) and is required for a
    parent; the route has already checked the link (O7), and writes lock it again (§a.4b step 4).
    """

    user_id: uuid.UUID
    party: ActorParty
    child_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AcceptDetails:
    """T11 body: a meeting link for a virtual session, a place for an in-person one."""

    meeting_link: str | None = None
    location_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewRef:
    """The booking's live (not removed) review, for the student viewer's ``BookingDTO.review``."""

    review_id: uuid.UUID
    stars: int
    text_state: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BookingNotice:
    """What a write announces after commit: the event, who acted and the child's parents."""

    event: BookingEvent
    actor_user_id: uuid.UUID | None
    linked_parent_ids: tuple[uuid.UUID, ...]
    late_tutor_cancel: bool = False


@dataclass(frozen=True, slots=True)
class BookingRow:
    """One booking as its readers see it: the stored facts plus what the DTO builder needs.

    ``tutor`` is the public card (``tutor_id`` is the profile id, never a ``users.id``);
    ``tutor_user_id`` is for notices only and never serialised. ``blocked`` is an active block
    between the pair, read with the row. ``has_review`` counts a removed review too (one review
    per booking, ever); ``review`` is the live one. ``notice`` is set only on the row a write
    returns, when that write changed something.
    """

    id: uuid.UUID
    tutor: TutorCard
    tutor_user_id: uuid.UUID
    tutor_listing_state: str
    tutor_zone: str
    student_id: uuid.UUID
    student_display_name: str | None
    student_created_at: datetime
    requested_by_user_id: uuid.UUID | None
    requested_by_party: Literal["student", "parent"]
    subject_code: str
    subject_name: str
    mode: Mode
    starts_at: datetime
    ends_at: datetime
    state: BookingStateLit
    meeting_link: str | None
    location_detail: str | None
    other_mode_note: str | None
    decline_reason: str | None
    cancel_reason: str | None
    cancelled_by_party: Party | None
    cancelled_at: datetime | None
    completed_by_party: Party | None
    notes_frozen: bool
    accepted_at: datetime | None
    created_at: datetime
    review: ReviewRef | None
    has_review: bool
    blocked: bool
    notice: BookingNotice | None = None


@dataclass(frozen=True, slots=True)
class BookingsKey:
    """Keyset position in a booking list; ``split`` is fixed by the first page (F25)."""

    split: datetime
    starts_at: datetime
    booking_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class BookingsPage:
    """One page of S1, T9 or PA1."""

    items: tuple[BookingRow, ...]
    next_key: BookingsKey | None


@dataclass(frozen=True, slots=True)
class NoteNotice:
    """What a new note announces after commit (``tutoring_notify.note_notices``)."""

    tutor_user_id: uuid.UUID
    tutor_name: str
    student_id: uuid.UUID
    student_label: str
    linked_parent_ids: tuple[uuid.UUID, ...]
    tutor_zone: str


@dataclass(frozen=True, slots=True)
class NoteRow:
    """One note as a participant or linked parent sees it: ``body`` is ``None`` once hidden."""

    id: uuid.UUID
    booking_id: uuid.UUID
    author_party: Literal["student", "tutor"]
    author_name: str
    body: str | None
    hidden: bool
    created_at: datetime
    notice: NoteNotice | None = None


@dataclass(frozen=True, slots=True)
class NotesKey:
    """Keyset position in a notes thread (oldest first)."""

    created_at: datetime
    note_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class NotesPage:
    """One page of S4, T16 or PA3; ``can_post`` is always false for a parent."""

    items: tuple[NoteRow, ...]
    next_key: NotesKey | None
    can_post: bool


@dataclass(frozen=True, slots=True)
class SlotsView:
    """SP5: the bookable slots of a window, as UTC instants, labelled in the tutor's zone."""

    tutor_id: uuid.UUID
    zone: str
    duration_minutes: int
    window_start: datetime
    window_end: datetime
    slots: tuple[tuple[datetime, datetime], ...]


# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------

_ALIAS: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: A parent acts on a booking only if they requested it (O8).
_REQUESTER: Final = (
    "{b}.requested_by_party = 'parent' AND {b}.requested_by_user_id = CAST(:actor_id AS uuid)"
)
#: ``CANCEL_CUTOFF`` and ``OUTCOME_CLAIM_AFTER`` as elapsed-time intervals (:data:`GUARD_BINDS`).
_CUTOFF: Final = "make_interval(secs => CAST(:cancel_cutoff_s AS double precision))"
_CLAIM_AFTER: Final = "make_interval(secs => CAST(:claim_after_s AS double precision))"
_FAMILY_CANCEL: Final = (
    "(({b}.state = 'requested' AND now() < {b}.starts_at) OR "
    f"({{b}}.state = 'accepted' AND now() <= {{b}}.starts_at - {_CUTOFF}))"
)
_CLAIM: Final = f"({{b}}.state = 'accepted' AND now() >= {{b}}.ends_at + {_CLAIM_AFTER})"
_BEFORE_START_ACTIVE: Final = "({b}.state IN ('requested', 'accepted') AND now() < {b}.starts_at)"
_ENDED_ACCEPTED: Final = "({b}.state = 'accepted' AND now() >= {b}.ends_at)"
_ANSWERABLE: Final = "({b}.state = 'requested' AND now() < {b}.starts_at)"

#: The state, time and party rule of each (action, party), as ``core.booking.check_transition``
#: decides it. Parity-tested in ``tests/test_booking_predicates_parity.py``.
_GUARDS: Final[Mapping[tuple[str, str], str]] = MappingProxyType(
    {
        ("accept", "tutor"): _ANSWERABLE,
        ("decline", "tutor"): _ANSWERABLE,
        ("cancel", "student"): _FAMILY_CANCEL,
        ("cancel", "parent"): f"({_FAMILY_CANCEL} AND {_REQUESTER})",
        # Row 18: until the start, and inside CANCEL_CUTOFF only with a non-blank reason.
        ("cancel", "tutor"): (
            "({b}.state = 'accepted' AND now() < {b}.starts_at AND "
            f"(now() <= {{b}}.starts_at - {_CUTOFF} OR "
            "(CAST(:reason AS text) IS NOT NULL "
            "AND char_length(btrim(CAST(:reason AS text))) >= 1)))"
        ),
        ("cancel", "platform_admin"): _BEFORE_START_ACTIVE,
        ("cancel", "system"): _BEFORE_START_ACTIVE,
        ("complete", "tutor"): _ENDED_ACCEPTED,
        ("no_show", "tutor"): _ENDED_ACCEPTED,
        ("complete", "platform_admin"): f"({_ENDED_ACCEPTED} OR {{b}}.state = 'no_show')",
        ("claim_complete", "student"): _CLAIM,
        ("claim_complete", "parent"): f"({_CLAIM} AND {_REQUESTER})",
        ("expire", "system"): "({b}.state = 'requested' AND now() >= {b}.starts_at)",
    }
)


def transition_guard_sql(action: Action, party: Party, alias: str = "b") -> str:
    """The compare-and-set ``WHERE`` fragment for ``party`` applying ``action`` to ``alias``.

    Exactly the state, time and requester rules of ``core.booking.check_transition`` (SPEC §a.3),
    against the database ``now()``. Binds: ``:cancel_cutoff_s`` and ``:claim_after_s``
    (:data:`GUARD_BINDS`, elapsed seconds), ``:actor_id`` (a parent's own id) and ``:reason``
    (the trimmed reason, or NULL). Raises :class:`ValueError` for a pair the core never allows,
    or a bad alias.
    """
    if _ALIAS.fullmatch(alias) is None:
        raise ValueError(f"alias must be a plain SQL alias, got {alias!r}")
    fragment = _GUARDS.get((action, party))
    if fragment is None:
        raise ValueError(f"no compare-and-set guard for {party} {action}")
    return fragment.format(b=alias)


_LIVE_SQL: Final = (
    f"({EFFECTIVE_STATE_SQL['requested']} OR {EFFECTIVE_STATE_SQL['accepted']} OR "
    f"{EFFECTIVE_STATE_SQL['awaiting_outcome']})"
)

#: S1, T9, PA1 ``when`` (SPEC §b.2 S1): upcoming = effective requested, accepted or
#: awaiting_outcome with ``ends_at > :split``; past = the rest. Over ``tutor_bookings b``.
BOOKING_WHEN_SQL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "upcoming": f"({_LIVE_SQL} AND b.ends_at > :split)",
        "past": f"(NOT ({_LIVE_SQL} AND b.ends_at > :split))",
    }
)

_BLOCK_B: Final = active_block_between_sql("b.student_id", "tp.user_id")

_ROW_SQL: Final = (
    "SELECT b.id, b.tutor_profile_id, b.student_id, b.requested_by_user_id, "  # noqa: S608 - constants
    "b.requested_by_party::text AS requested_by_party, b.subject_code, s.name AS subject_name, "
    "b.mode::text AS mode, b.starts_at, b.ends_at, b.state::text AS state, b.meeting_link, "
    "b.location_detail, b.other_mode_note, b.decline_reason, b.cancel_reason, "
    "b.cancelled_by_party::text AS cancelled_by_party, b.cancelled_at, "
    "b.completed_by_party::text AS completed_by_party, b.notes_frozen_at, b.accepted_at, "
    "b.created_at, tp.user_id AS tutor_user_id, tp.listing_state::text AS listing_state, "
    "tp.zone, tp.public_first_name, tp.public_last_initial, tp.headline, tp.offers_virtual, "
    "tp.offers_in_person, tp.offers_other, tp.area_code, tp.rating_sum, tp.rating_count, "
    "u.display_name AS student_display_name, u.created_at AS student_created_at, "
    "r.id AS review_id, r.stars AS review_stars, r.text_state::text AS review_text_state, "
    "r.created_at AS review_created_at, r.removed_at AS review_removed_at, "
    f"{_BLOCK_B} AS blocked "
    "FROM tutor_bookings b "
    "JOIN tutor_profiles tp ON tp.id = b.tutor_profile_id "
    "JOIN users u ON u.id = b.student_id "
    "JOIN subjects s ON s.code = b.subject_code "
    "LEFT JOIN tutor_reviews r ON r.booking_id = b.id "
)

_CHANGE_FACTS_SQL: Final = (
    "SELECT b.state::text AS state, b.starts_at, b.ends_at, b.mode::text AS mode, "  # noqa: S608 - constants
    "b.requested_by_party::text AS requested_by_party, b.requested_by_user_id, "
    "b.completed_by_party::text AS completed_by_party, b.notes_frozen_at, "
    "tp.listing_state::text AS listing_state, now() AS db_now, "
    f"{_BLOCK_B} AS blocked, (u.role = 'student') AS subject_is_student, "
    "EXISTS (SELECT 1 FROM student_tutoring_preferences p WHERE p.user_id = b.student_id "
    "AND p.safety_notice_acknowledged_at IS NOT NULL) AS acknowledged "
    "FROM tutor_bookings b "
    "JOIN tutor_profiles tp ON tp.id = b.tutor_profile_id "
    "JOIN users u ON u.id = b.student_id "
    "WHERE b.id = :booking_id"
)

_CREATE_FACTS_SQL: Final = (
    f"SELECT now() AS db_now, {listed_and_not_paused_sql('tp')} AS listed, "  # noqa: S608 - constants
    f"{active_block_between_sql(':student_id', 'tp.user_id')} AS blocked, tp.zone, "
    "tp.offers_virtual, tp.offers_in_person, tp.offers_other, "
    "EXISTS (SELECT 1 FROM tutor_subjects ts WHERE ts.tutor_profile_id = tp.id "
    "AND ts.subject_code = :subject_code) AS teaches, "
    "EXISTS (SELECT 1 FROM student_tutoring_preferences p WHERE p.user_id = :student_id "
    "AND p.safety_notice_acknowledged_at IS NOT NULL) AS acknowledged, "
    "(SELECT count(*) FROM tutor_bookings q WHERE q.requested_by_user_id = :requester_id "
    f"AND q.created_at > {QUOTA_SINCE_SQL}) AS created_recently, "
    "(SELECT coalesce(json_agg(json_build_array(r.iso_weekday, r.start_minute, r.end_minute)), "
    "'[]'::json) FROM tutor_availability_rules r WHERE r.tutor_profile_id = tp.id) AS rules "
    "FROM tutor_profiles tp WHERE tp.id = :tutor_profile_id"
)

_SET: Final[Mapping[str, str]] = MappingProxyType(
    {
        "accept": (
            "state = 'accepted', accepted_at = now(), meeting_link = :meeting_link, "
            "location_detail = :location_detail"
        ),
        "decline": "state = 'declined', declined_at = now(), decline_reason = :reason",
        "cancel": (
            "state = 'cancelled', cancelled_at = now(), "
            "cancelled_by_party = CAST(:party AS bookingparty), "
            "cancelled_by_user_id = :cancelled_by, cancel_reason = :reason"
        ),
        "complete": (
            "state = 'completed', completed_at = now(), "
            "completed_by_party = CAST(:party AS bookingparty)"
        ),
        "claim_complete": (
            "state = 'completed', completed_at = now(), "
            "completed_by_party = CAST(:party AS bookingparty)"
        ),
        "no_show": "state = 'no_show', no_show_marked_at = now()",
        "expire": "state = 'expired', expired_at = now()",
    }
)

#: A tutor's write needs a profile that is neither suspended nor closed (CB-7).
_TUTOR_ACTIVE: Final = (
    "EXISTS (SELECT 1 FROM tutor_profiles g WHERE g.id = b.tutor_profile_id "
    "AND g.listing_state NOT IN ('suspended', 'closed'))"
)
#: Accept also needs a listing that may take students, no active block and a subject who is
#: still a student (SPEC §a.3, BK-4).
_ACCEPTABLE: Final = (
    "EXISTS (SELECT 1 FROM tutor_profiles g WHERE g.id = b.tutor_profile_id "  # noqa: S608 - constants
    "AND g.listing_state IN ('listed', 'pending_review') "
    f"AND NOT {active_block_between_sql('b.student_id', 'g.user_id')}) "
    "AND EXISTS (SELECT 1 FROM users su WHERE su.id = b.student_id AND su.role = 'student')"
)

_EVENT: Final[Mapping[str, BookingEvent]] = MappingProxyType(
    {
        "accept": "accepted",
        "decline": "declined",
        "cancel": "cancelled",
        "complete": "completed",
        "claim_complete": "completed",
        "no_show": "no_show",
    }
)

#: Which email each audience gets per event (SPEC §b.4); ``None``: no email.
_EMAILS: Final[Mapping[str, tuple[str | None, str | None, str | None]]] = MappingProxyType(
    {
        "requested": ("booking_requested", None, "booking_requested_family"),
        "accepted": (None, "booking_accepted", "booking_accepted"),
        "declined": (None, "booking_declined", "booking_declined"),
        "cancelled": ("booking_cancelled", "booking_cancelled", "booking_cancelled"),
    }
)

_ACTOR_ACTIONS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "tutor": frozenset({"accept", "decline", "cancel", "complete", "no_show"}),
        "student": frozenset({"cancel", "claim_complete"}),
        "parent": frozenset({"cancel", "claim_complete"}),
    }
)

_ACCEPT_LISTINGS: Final = frozenset({"listed", "pending_review"})
_INACTIVE_LISTINGS: Final = frozenset({"suspended", "closed"})
_STATES: Final = frozenset(
    {"requested", "accepted", "declined", "cancelled", "completed", "no_show", "expired"}
)
_PARTIES: Final = frozenset({"student", "parent", "tutor", "platform_admin", "system"})
_MAIL_FORBIDDEN: Final = frozenset("/@:\\<>")
_MAIL_SUBJECT_MAX: Final = 80
_BOOKINGS_CURSOR_TYPES: Final = (datetime, datetime, uuid.UUID)
_NOTES_CURSOR_TYPES: Final = (datetime, uuid.UUID)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _opt_uuid(value: object) -> uuid.UUID | None:
    return None if value is None else _uuid(value)


def _instant(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError(f"expected an aware datetime, got {value!r}")
    return value.astimezone(UTC)


def _opt_instant(value: object) -> datetime | None:
    return None if value is None else _instant(value)


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def _state(value: object) -> BookingStateLit:
    text = str(value)
    if text not in _STATES:
        raise ValueError(f"unknown booking state {text!r}")
    return cast("BookingStateLit", text)


def _party(value: object) -> Party | None:
    if value is None:
        return None
    text = str(value)
    if text not in _PARTIES:
        raise ValueError(f"unknown booking party {text!r}")
    return cast("Party", text)


def _mode(value: object) -> Mode:
    text = str(value)
    for mode in MODES:
        if mode == text:
            return mode
    raise ValueError(f"unknown tutoring mode {text!r}")


def _clean_text(value: str | None, *, limit: int, what: str) -> str | None:
    """Trimmed free text, or ``None`` when absent or blank.

    Refused with 422 when too long (``text_too_long``) or carrying a contact detail (SC-7).
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > limit:
        raise _refuse("text_too_long", f"{what} can be at most {limit} characters.")
    if find_contact_details(text):
        raise _refuse("contact_details_not_allowed")
    return text


def _mail_subject(name: str, code: str) -> str:
    """The subject name as an email context may carry it (no control or URL characters)."""
    cleaned = "".join(
        " " if unicodedata.category(char)[0] == "C" or char in _MAIL_FORBIDDEN else char
        for char in name
    )
    text = " ".join(cleaned.split())[:_MAIL_SUBJECT_MAX].strip()
    return text or code


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be 1 to {MAX_PAGE_SIZE}, got {limit}")


def _local_midnight(day: date, zone: str) -> datetime:
    return datetime.combine(day, time(), tzinfo=ZoneInfo(zone)).astimezone(UTC)


def _rules(raw: object) -> tuple[AvailabilityRule, ...]:
    if not isinstance(raw, list):
        raise TypeError(f"availability aggregate is not a list: {raw!r}")
    rules: list[AvailabilityRule] = []
    for item in raw:
        if not (
            isinstance(item, list) and len(item) == 3 and all(isinstance(v, int) for v in item)
        ):
            raise TypeError(f"availability entry is not three integers: {item!r}")
        rules.append(
            AvailabilityRule(iso_weekday=item[0], start_minute=item[1], end_minute=item[2])
        )
    return tuple(rules)


def _modes_offered(mapping: RowMapping) -> tuple[Mode, ...]:
    flags = {
        "virtual": mapping["offers_virtual"],
        "in_person": mapping["offers_in_person"],
        "other": mapping["offers_other"],
    }
    return tuple(mode for mode in MODES if flags[mode])


# ---------------------------------------------------------------------------
# Cursors (O21)
# ---------------------------------------------------------------------------


def bookings_cursor(endpoint: str, key: BookingsKey) -> str:
    """The opaque cursor of a booking list page, tagged with the route's ``endpoint``."""
    return encode_cursor(endpoint, (key.split, key.starts_at, key.booking_id))


def parse_bookings_cursor(token: str, endpoint: str) -> BookingsKey:
    """Decode a booking list cursor; raises ``CursorError`` (a 422) for anything not minted here."""
    split, starts_at, booking_id = decode_cursor(
        token, endpoint=endpoint, types=_BOOKINGS_CURSOR_TYPES
    )
    if not (
        isinstance(split, datetime)
        and isinstance(starts_at, datetime)
        and isinstance(booking_id, uuid.UUID)
    ):
        raise CursorError("cursor has the wrong shape")
    return BookingsKey(split=split, starts_at=starts_at, booking_id=booking_id)


def notes_cursor(endpoint: str, key: NotesKey) -> str:
    """The opaque cursor of a notes page, tagged with the route's ``endpoint``."""
    return encode_cursor(endpoint, (key.created_at, key.note_id))


def parse_notes_cursor(token: str, endpoint: str) -> NotesKey:
    """Decode a notes cursor; raises ``CursorError`` (a 422) for anything not minted here."""
    created_at, note_id = decode_cursor(token, endpoint=endpoint, types=_NOTES_CURSOR_TYPES)
    if not (isinstance(created_at, datetime) and isinstance(note_id, uuid.UUID)):
        raise CursorError("cursor has the wrong shape")
    return NotesKey(created_at=created_at, note_id=note_id)


# ---------------------------------------------------------------------------
# Session-level steps shared with other modules
# ---------------------------------------------------------------------------


def lock_pair_in_session(
    session: Session, *, student_id: uuid.UUID, tutor_profile_id: uuid.UUID
) -> None:
    """Take the (student, tutor) pair lock of SPEC §a.4b step 3 for the caller's transaction.

    ``pg_advisory_xact_lock(hashtextextended(student_id::text || ':' || tutor_profile_id::text,
    0))``: the same key for every path that writes for this pair (bookings, grants, blocks).
    """
    session.execute(
        sa.text(
            "SELECT pg_advisory_xact_lock(hashtextextended("
            "CAST(CAST(:student_id AS uuid) AS text) || ':' || "
            "CAST(CAST(:tutor_profile_id AS uuid) AS text), 0))"
        ),
        {"student_id": student_id, "tutor_profile_id": tutor_profile_id},
    )


def live_pending_count_in_session(session: Session, student_id: uuid.UUID) -> int:
    """The student's live requests (``LIVE_PENDING_SQL``), as ``MAX_PENDING_PER_STUDENT`` caps them.

    Stale ``requested`` rows are not counted, so ignored requests never lock a student out (BK-2).
    """
    count = session.execute(
        sa.text(
            f"SELECT count(*) FROM tutor_bookings WHERE student_id = :student_id "  # noqa: S608 - constant
            f"AND {LIVE_PENDING_SQL}"
        ),
        {"student_id": student_id},
    ).scalar_one()
    return int(count)


def _lock_tutor(session: Session, tutor_profile_id: uuid.UUID) -> bool:
    """§a.4b step 1: the tutor row ``FOR SHARE``; ``False`` when there is no such profile."""
    found = session.execute(
        sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR SHARE"), {"t": tutor_profile_id}
    ).first()
    return found is not None


def _lock_user(
    session: Session, user_id: uuid.UUID, mode: Literal["UPDATE", "KEY SHARE"]
) -> str | None:
    """§a.4b step 2: the student's ``users`` row; returns its role, or ``None`` if missing."""
    role = session.execute(
        sa.text(f"SELECT role::text FROM users WHERE id = :u FOR {mode}"),  # noqa: S608 - literal mode
        {"u": user_id},
    ).scalar_one_or_none()
    return None if role is None else str(role)


@dataclass(frozen=True, slots=True)
class _ChangeFacts:
    """The booking, read again after the locks, with the database ``now()``."""

    state: BookingStateLit
    starts_at: datetime
    ends_at: datetime
    mode: Mode
    requested_by_party: str
    requested_by_user_id: uuid.UUID | None
    completed_by_party: str | None
    notes_frozen: bool
    listing_state: str
    db_now: datetime
    blocked: bool
    subject_is_student: bool
    acknowledged: bool

    def core(self, viewer: Party, actor_id: uuid.UUID) -> BookingFacts:
        return BookingFacts(
            state=self.state,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            viewer=viewer,
            viewer_is_requester=(
                self.requested_by_party == "parent" and self.requested_by_user_id == actor_id
            ),
            tutor_outcome_recorded=self.state == "no_show" or self.completed_by_party == "tutor",
        )


def _change_facts(session: Session, booking_id: uuid.UUID) -> _ChangeFacts:
    m = session.execute(sa.text(_CHANGE_FACTS_SQL), {"booking_id": booking_id}).mappings().one()
    return _ChangeFacts(
        state=_state(m["state"]),
        starts_at=_instant(m["starts_at"]),
        ends_at=_instant(m["ends_at"]),
        mode=_mode(m["mode"]),
        requested_by_party=str(m["requested_by_party"]),
        requested_by_user_id=_opt_uuid(m["requested_by_user_id"]),
        completed_by_party=_opt_str(m["completed_by_party"]),
        notes_frozen=m["notes_frozen_at"] is not None,
        listing_state=str(m["listing_state"]),
        db_now=_instant(m["db_now"]),
        blocked=bool(m["blocked"]),
        subject_is_student=bool(m["subject_is_student"]),
        acknowledged=bool(m["acknowledged"]),
    )


def _refuse_inactive_tutor(listing_state: str) -> None:
    if listing_state == "suspended":
        raise _refuse("tutor_suspended")
    if listing_state == "closed":
        raise _refuse("tutor_closed")


def _owner_where(viewer: Actor) -> tuple[str, dict[str, object]]:
    """The ``WHERE`` that scopes a booking to the viewer (O4, O5, O7)."""
    if viewer.party == "tutor":
        return "tp.user_id = :viewer_id", {"viewer_id": viewer.user_id}
    if viewer.party == "student":
        return "b.student_id = :viewer_id", {"viewer_id": viewer.user_id}
    if viewer.party == "parent":
        if viewer.child_id is None:
            raise ValueError("a parent viewer needs the child from the route")
        return "b.student_id = :child_id", {"child_id": viewer.child_id}
    raise ValueError(f"no booking scope for party {viewer.party!r}")


def _review_ref(m: RowMapping) -> ReviewRef | None:
    if m["review_id"] is None or m["review_removed_at"] is not None:
        return None
    return ReviewRef(
        review_id=_uuid(m["review_id"]),
        stars=int(m["review_stars"]),
        text_state=str(m["review_text_state"]),
        created_at=_instant(m["review_created_at"]),
    )


def _booking_row(m: RowMapping, card: TutorCard) -> BookingRow:
    requested_by = str(m["requested_by_party"])
    if requested_by not in {"student", "parent"}:
        raise ValueError(f"unexpected requester party {requested_by!r}")
    return BookingRow(
        id=_uuid(m["id"]),
        tutor=card,
        tutor_user_id=_uuid(m["tutor_user_id"]),
        tutor_listing_state=str(m["listing_state"]),
        tutor_zone=str(m["zone"]),
        student_id=_uuid(m["student_id"]),
        student_display_name=_opt_str(m["student_display_name"]),
        student_created_at=_instant(m["student_created_at"]),
        requested_by_user_id=_opt_uuid(m["requested_by_user_id"]),
        requested_by_party=cast("Literal['student', 'parent']", requested_by),
        subject_code=str(m["subject_code"]),
        subject_name=str(m["subject_name"]),
        mode=_mode(m["mode"]),
        starts_at=_instant(m["starts_at"]),
        ends_at=_instant(m["ends_at"]),
        state=_state(m["state"]),
        meeting_link=_opt_str(m["meeting_link"]),
        location_detail=_opt_str(m["location_detail"]),
        other_mode_note=_opt_str(m["other_mode_note"]),
        decline_reason=_opt_str(m["decline_reason"]),
        cancel_reason=_opt_str(m["cancel_reason"]),
        cancelled_by_party=_party(m["cancelled_by_party"]),
        cancelled_at=_opt_instant(m["cancelled_at"]),
        completed_by_party=_party(m["completed_by_party"]),
        notes_frozen=m["notes_frozen_at"] is not None,
        accepted_at=_opt_instant(m["accepted_at"]),
        created_at=_instant(m["created_at"]),
        review=_review_ref(m),
        has_review=m["review_id"] is not None,
        blocked=bool(m["blocked"]),
    )


def _fetch_rows(
    session: Session,
    where: str,
    params: Mapping[str, object],
    *,
    order: str = "b.starts_at ASC, b.id ASC",
    limit: int | None = None,
) -> list[BookingRow]:
    """Booking rows in two statements whatever their number (SPEC §e.3): rows, then subjects.

    ``where`` and ``order`` are fragments written in this module, never caller text.
    """
    tail = f" ORDER BY {order}" + (" LIMIT :row_limit" if limit is not None else "")
    bound = dict(params)
    if limit is not None:
        bound["row_limit"] = limit
    found = session.execute(sa.text(f"{_ROW_SQL}WHERE {where}{tail}"), bound).mappings().all()
    tutor_ids = list(dict.fromkeys(_uuid(m["tutor_profile_id"]) for m in found))
    subjects = subjects_by_tutor(session, tutor_ids)
    rows: list[BookingRow] = []
    for m in found:
        tutor_id = _uuid(m["tutor_profile_id"])
        card = TutorCard(
            tutor_id=tutor_id,
            public_first_name=str(m["public_first_name"]),
            public_last_initial=_opt_str(m["public_last_initial"]),
            headline=str(m["headline"]),
            subjects=subjects.get(tutor_id, ()),
            modes=_modes_offered(m),
            area_code=str(m["area_code"]),
            rating_sum=int(m["rating_sum"]),
            rating_count=int(m["rating_count"]),
        )
        rows.append(_booking_row(m, card))
    return rows


def _load_one(session: Session, booking_id: uuid.UUID) -> BookingRow:
    rows = _fetch_rows(session, "b.id = :booking_id", {"booking_id": booking_id})
    if not rows:
        raise RuntimeError(f"booking {booking_id} vanished inside its own transaction")
    return rows[0]


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class BookingService:
    """Booking and note reads and writes over a ``sessionmaker``.

    Each public method is one transaction. ``clock`` is the app clock, used only for reads
    (the slots offered, the first page's upcoming/past split, a notes page's ``can_post``);
    every write guard uses the database ``now()``.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = _utc_now,
        parents: ParentLinkService | None = None,
    ) -> None:
        """Wire the service to a session factory, a read clock and the parent-link service."""
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._parents = parents if parents is not None else ParentLinkService(sessionmaker)

    # -- SP6 ------------------------------------------------------------------

    def create(
        self,
        *,
        requester: Actor,
        tutor_profile_id: uuid.UUID,
        student_id: uuid.UUID | None,
        subject_code: str,
        mode: Mode,
        starts_at: datetime,
        duration_minutes: int,
        other_mode_note: str | None = None,
        first_note: str | None = None,
    ) -> BookingRow:
        """SP6: a booking request by a student for themselves or by a parent for a linked child.

        Refusals (SPEC §b.2 SP6): 403 ``not_self``/``not_linked``; 404 ``not_found`` (tutor or
        child); 409 ``tutor_not_listed``, ``blocked``, ``safety_notice_required`` (a student
        requester only), ``not_bookable``, ``beyond_horizon``, ``pending_limit``, and from the
        constraints ``slot_taken``, ``student_busy``, ``already_pending``; 422
        ``note_not_allowed_for_parent``, ``student_required``, ``contact_details_not_allowed``,
        ``text_too_long``, ``invalid_starts_at``; 429 ``too_many_requests``. An
        ``other_mode_note`` is kept for mode ``other`` only. Nothing is written on a refusal.
        """
        subject_id = self._subject_of(requester, student_id)
        note: str | None = None
        if first_note is not None:
            if requester.party == "parent":
                raise _refuse("note_not_allowed_for_parent")
            note = _clean_text(first_note, limit=MAX_NOTE_LENGTH, what="A note")
        other_note = (
            _clean_text(other_mode_note, limit=MAX_OTHER_MODE_NOTE_LENGTH, what="The note")
            if mode == "other"
            else None
        )
        if starts_at.tzinfo is None or starts_at.utcoffset() is None:
            raise _refuse("invalid_starts_at")
        if duration_minutes not in ALLOWED_DURATIONS:
            raise _refuse("not_bookable")
        ends_at = starts_at + timedelta(minutes=duration_minutes)
        try:
            with self._sessionmaker.begin() as session:
                booking_id = self._insert_request(
                    session,
                    requester=requester,
                    tutor_profile_id=tutor_profile_id,
                    student_id=subject_id,
                    subject_code=subject_code,
                    mode=mode,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    other_note=other_note,
                )
                if note is not None:
                    self._insert_note(session, booking_id, requester.user_id, "student", note)
                row = _load_one(session, booking_id)
                parents = tuple(self._parents.linked_parent_ids_in_session(session, subject_id))
                self._enqueue_emails(
                    session, row, event="requested", parents=parents, actor=requester.user_id
                )
                return replace(
                    row,
                    notice=BookingNotice(
                        event="requested",
                        actor_user_id=requester.user_id,
                        linked_parent_ids=parents,
                    ),
                )
        except IntegrityError as exc:
            refused = _constraint_refusal(exc)
            if refused is None:
                raise
            raise refused from exc

    @staticmethod
    def _subject_of(requester: Actor, student_id: uuid.UUID | None) -> uuid.UUID:
        """The booking's subject: the student themselves, or a parent's named child (O6)."""
        if requester.party == "student":
            if student_id is not None and student_id != requester.user_id:
                raise _refuse("not_self")
            return requester.user_id
        if requester.party == "parent":
            if student_id is None:
                raise _refuse("student_required")
            return student_id
        raise ValueError("only a student or a parent requests a booking")

    def _insert_request(
        self,
        session: Session,
        *,
        requester: Actor,
        tutor_profile_id: uuid.UUID,
        student_id: uuid.UUID,
        subject_code: str,
        mode: Mode,
        starts_at: datetime,
        ends_at: datetime,
        other_note: str | None,
    ) -> uuid.UUID:
        """Locks 1-4, every SP6 guard on fresh reads, lazy expiry, then the insert (§a.4b)."""
        if not _lock_tutor(session, tutor_profile_id):
            raise _refuse("not_found", "Tutor not found.")
        if _lock_user(session, student_id, "UPDATE") != "student":
            raise _refuse("not_found", "Student not found.")
        lock_pair_in_session(session, student_id=student_id, tutor_profile_id=tutor_profile_id)
        if requester.party == "parent" and not self._parents.lock_link_in_session(
            session, requester.user_id, student_id
        ):
            raise _refuse("not_linked")
        f = (
            session.execute(
                sa.text(_CREATE_FACTS_SQL),
                {
                    **QUOTA_BINDS,
                    "tutor_profile_id": tutor_profile_id,
                    "student_id": student_id,
                    "requester_id": requester.user_id,
                    "subject_code": subject_code,
                },
            )
            .mappings()
            .one()
        )
        if not f["listed"]:
            raise _refuse("tutor_not_listed")
        if f["blocked"]:
            raise _refuse("blocked")
        if requester.party == "student" and not f["acknowledged"]:
            raise _refuse("safety_notice_required")
        if int(f["created_recently"]) >= BOOKING_CREATE_QUOTA:
            raise _refuse("too_many_requests")
        if not f["teaches"] or mode not in _modes_offered(f):
            raise _refuse("not_bookable")
        refusal = bookable(
            _rules(f["rules"]),
            zone=str(f["zone"]),
            starts_at=starts_at,
            ends_at=ends_at,
            busy=(),  # the exclusion constraints answer for taken slots (slot_taken, student_busy)
            now=_instant(f["db_now"]),
        )
        if refusal is not None:
            raise _refuse(refusal.code)
        # Lazy expiry (§a.3): the pair's stale request stops holding the one-pending index.
        session.execute(
            sa.text(
                f"UPDATE tutor_bookings AS b SET {_SET['expire']}, updated_at = now() "  # noqa: S608 - constants
                "WHERE b.student_id = :student_id AND b.tutor_profile_id = :tutor_profile_id "
                f"AND {transition_guard_sql('expire', 'system')}"
            ),
            {"student_id": student_id, "tutor_profile_id": tutor_profile_id},
        )
        if live_pending_count_in_session(session, student_id) >= MAX_PENDING_PER_STUDENT:
            raise _refuse("pending_limit")
        booking_id = session.execute(
            sa.text(
                "INSERT INTO tutor_bookings (tutor_profile_id, student_id, requested_by_user_id, "
                "requested_by_party, subject_code, mode, starts_at, ends_at, other_mode_note) "
                "VALUES (:tutor_profile_id, :student_id, :requester_id, "
                "CAST(:party AS bookingparty), :subject_code, CAST(:mode AS tutoringmode), "
                ":starts_at, :ends_at, :other_note) RETURNING id"
            ),
            {
                "tutor_profile_id": tutor_profile_id,
                "student_id": student_id,
                "requester_id": requester.user_id,
                "party": requester.party,
                "subject_code": subject_code,
                "mode": mode,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "other_note": other_note,
            },
        ).scalar_one()
        return _uuid(booking_id)

    # -- S3, S14, T11-T15, PA4, PA5 --------------------------------------------

    def transition(
        self,
        *,
        booking_id: uuid.UUID,
        actor: Actor,
        action: Action,
        reason: str | None = None,
        accept: AcceptDetails | None = None,
    ) -> BookingRow:
        """Apply ``action`` for ``actor`` by compare-and-set (SPEC §a.3, §a.4b).

        ``complete`` from a student or parent is the 48-hour claim (``claim_complete``).
        ``reason`` is the decline or cancel reason (trimmed; required from a tutor inside 24 h
        of the start, row 18). ``accept`` carries the meeting link (virtual) or place (in
        person); only the one the booking's mode keeps is checked, and the other is dropped
        unread (:meth:`_accept_values`). Raises :class:`BookingRefused`; an idempotent repeat
        returns the row with ``notice=None``.
        """
        resolved = self._resolve_action(actor, action)
        clean_reason = _clean_text(reason, limit=MAX_REASON_LENGTH, what="A reason")
        with self._sessionmaker.begin() as session:
            tutor_profile_id, student_id = self._locate(session, booking_id, actor)
            self._lock_for_change(
                session,
                tutor_profile_id=tutor_profile_id,
                student_id=student_id,
                parent_id=actor.user_id if actor.party == "parent" else None,
            )
            facts = _change_facts(session, booking_id)
            if actor.party == "tutor":
                _refuse_inactive_tutor(facts.listing_state)
            core_facts = facts.core(actor.party, actor.user_id)
            if actor.party == "parent" and not core_facts.viewer_is_requester:
                raise _refuse("not_requester")
            if facts.state == target_state(resolved):
                return _load_one(session, booking_id)  # an idempotent repeat
            refusal = check_transition(
                resolved, core_facts, now=facts.db_now, has_reason=clean_reason is not None
            )
            if refusal is not None:
                raise _refuse(refusal.code)
            link, place = (
                self._accept_values(facts, accept) if resolved == "accept" else (None, None)
            )
            if resolved == "cancel":
                self._check_cancel_quota(session, actor.user_id)
            changed = self._compare_and_set(
                session,
                booking_id=booking_id,
                action=resolved,
                party=actor.party,
                actor_id=actor.user_id,
                cancelled_by=actor.user_id,
                reason=clean_reason,
                tutor_profile_id=tutor_profile_id,
                student_id=student_id,
                link=link,
                place=place,
            )
            if not changed:
                return self._missed(
                    session,
                    booking_id,
                    resolved,
                    actor.party,
                    actor.user_id,
                    has_reason=clean_reason is not None,
                )
            return self._announce(session, booking_id, _EVENT[resolved], actor.user_id)

    @staticmethod
    def _resolve_action(actor: Actor, action: Action) -> Action:
        resolved: Action = (
            "claim_complete"
            if action == "complete" and actor.party in ("student", "parent")
            else action
        )
        if resolved not in _ACTOR_ACTIONS.get(actor.party, frozenset()):
            raise _refuse("illegal_transition")
        return resolved

    @staticmethod
    def _locate(
        session: Session, booking_id: uuid.UUID, actor: Actor
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """The booking's tutor and student if ``actor`` may act on it, else 404 (O4, O5, O7)."""
        where, params = _owner_where(actor)
        found = session.execute(
            sa.text(
                "SELECT b.tutor_profile_id, b.student_id FROM tutor_bookings b "  # noqa: S608 - constants
                "JOIN tutor_profiles tp ON tp.id = b.tutor_profile_id "
                f"WHERE b.id = :booking_id AND {where}"
            ),
            {"booking_id": booking_id, **params},
        ).first()
        if found is None:
            raise _refuse("not_found")
        return _uuid(found[0]), _uuid(found[1])

    def _lock_for_change(
        self,
        session: Session,
        *,
        tutor_profile_id: uuid.UUID,
        student_id: uuid.UUID,
        parent_id: uuid.UUID | None,
    ) -> None:
        """Steps 1-4 of §a.4b for a write on an existing booking (see the module docstring)."""
        _lock_tutor(session, tutor_profile_id)
        _lock_user(session, student_id, "KEY SHARE")
        lock_pair_in_session(session, student_id=student_id, tutor_profile_id=tutor_profile_id)
        if parent_id is not None and not self._parents.lock_link_in_session(
            session, parent_id, student_id
        ):
            raise _refuse("not_linked")

    @staticmethod
    def _accept_values(
        facts: _ChangeFacts, accept: AcceptDetails | None
    ) -> tuple[str | None, str | None]:
        """The accept guards beyond the core's (SPEC §a.3, BK-4), then ``(link, place)`` to store.

        Only the detail the booking's mode keeps is read and checked: a virtual session needs an
        allowlisted meeting link, an in-person one a place free of contact details (SC-7). The
        other detail is dropped unread, so it is never stored (the ``meeting_link_mode`` and
        ``location_detail_mode`` CHECKs) and cannot refuse the accept; mode ``other`` keeps
        neither.
        """
        if facts.blocked:
            raise _refuse("access_ended")
        if facts.listing_state not in _ACCEPT_LISTINGS:
            raise _refuse("tutor_not_listed", _TUTOR_NOT_LISTED_FOR_TUTOR)
        if not facts.subject_is_student:
            raise _refuse("illegal_transition")
        if facts.mode == "virtual":
            link = (accept.meeting_link or "").strip() if accept is not None else ""
            if not link or not meeting_link_allowed(link):
                raise _refuse("meeting_link_not_allowed")
            return link, None
        if facts.mode == "in_person":
            place = _clean_text(
                accept.location_detail if accept is not None else None,
                limit=MAX_LOCATION_LENGTH,
                what="The place",
            )
            if place is None:
                raise _refuse("location_required")
            return None, place
        return None, None

    @staticmethod
    def _check_cancel_quota(session: Session, user_id: uuid.UUID) -> None:
        count = session.execute(
            sa.text(
                "SELECT count(*) FROM tutor_bookings WHERE cancelled_by_user_id = :u "  # noqa: S608 - constant
                f"AND cancelled_at > {QUOTA_SINCE_SQL}"
            ),
            {**QUOTA_BINDS, "u": user_id},
        ).scalar_one()
        if int(count) >= CANCEL_QUOTA:
            raise _refuse("too_many_requests")

    @staticmethod
    def _compare_and_set(
        session: Session,
        *,
        booking_id: uuid.UUID,
        action: Action,
        party: Party,
        actor_id: uuid.UUID | None,
        cancelled_by: uuid.UUID | None,
        reason: str | None,
        tutor_profile_id: uuid.UUID,
        student_id: uuid.UUID,
        link: str | None = None,
        place: str | None = None,
    ) -> bool:
        """One guarded ``UPDATE``; ``True`` when it changed the row."""
        conditions = [
            "b.id = :booking_id",
            "b.tutor_profile_id = :tutor_profile_id",
            "b.student_id = :student_id",
            transition_guard_sql(action, party),
        ]
        if party == "tutor":
            conditions.append(_ACCEPTABLE if action == "accept" else _TUTOR_ACTIVE)
        changed = session.execute(
            sa.text(
                f"UPDATE tutor_bookings AS b SET {_SET[action]}, updated_at = now() "  # noqa: S608 - constants
                f"WHERE {' AND '.join(conditions)} RETURNING b.id"
            ),
            {
                **GUARD_BINDS,
                "booking_id": booking_id,
                "tutor_profile_id": tutor_profile_id,
                "student_id": student_id,
                "actor_id": actor_id,
                "cancelled_by": cancelled_by,
                "party": party,
                "reason": reason,
                "meeting_link": link,
                "location_detail": place,
            },
        ).first()
        return changed is not None

    @staticmethod
    def _missed(
        session: Session,
        booking_id: uuid.UUID,
        action: Action,
        party: Party,
        actor_id: uuid.UUID,
        *,
        has_reason: bool = False,
    ) -> BookingRow:
        """After a compare-and-set that matched no row: an idempotent repeat, or a refusal.

        The refusal is the core's code for the row as it now stands, or ``illegal_transition``
        when the core would allow it: the ``WHERE`` alone refused (defence in depth, P24).
        """
        facts = _change_facts(session, booking_id)
        if facts.state == target_state(action):
            return _load_one(session, booking_id)
        refusal = check_transition(
            action, facts.core(party, actor_id), now=facts.db_now, has_reason=has_reason
        )
        raise _refuse(refusal.code if refusal is not None else "illegal_transition")

    def _announce(
        self,
        session: Session,
        booking_id: uuid.UUID,
        event: BookingEvent,
        actor_id: uuid.UUID | None,
    ) -> BookingRow:
        """Read the changed row, queue its emails and attach the after-commit notice."""
        row = _load_one(session, booking_id)
        parents = tuple(self._parents.linked_parent_ids_in_session(session, row.student_id))
        self._enqueue_emails(session, row, event=event, parents=parents, actor=actor_id)
        late = (
            event == "cancelled"
            and row.cancelled_by_party is not None
            and row.cancelled_at is not None
            and is_late_cancel(
                cancelled_by=row.cancelled_by_party,
                cancelled_at=row.cancelled_at,
                starts_at=row.starts_at,
            )
        )
        return replace(
            row,
            notice=BookingNotice(
                event=event,
                actor_user_id=actor_id,
                linked_parent_ids=parents,
                late_tutor_cancel=late,
            ),
        )

    @staticmethod
    def _enqueue_emails(
        session: Session,
        row: BookingRow,
        *,
        event: BookingEvent,
        parents: Sequence[uuid.UUID],
        actor: uuid.UUID | None,
        tell_tutor: bool = True,
    ) -> None:
        """The SPEC §b.4 email rows for ``event``, in the caller's transaction; never the actor."""
        templates = _EMAILS.get(event)
        if templates is None:
            return
        tutor_template, student_template, parent_template = templates
        recipients: list[tuple[uuid.UUID, str, Audience]] = []
        if tutor_template is not None and tell_tutor:
            recipients.append((row.tutor_user_id, tutor_template, "tutor"))
        if student_template is not None:
            recipients.append((row.student_id, student_template, "student"))
        if parent_template is not None:
            recipients.extend((parent, parent_template, "parent") for parent in parents)
        for user_id, template, audience in recipients:
            if user_id == actor:
                continue
            context: dict[str, object] = {
                "booking_id": row.id,
                "audience": audience,
                "subject_name": _mail_subject(row.subject_name, row.subject_code),
                "starts_at": row.starts_at,
                "tutor_zone": row.tutor_zone,
                "mode": row.mode,
                "tutor_first_name": row.tutor.public_first_name,
                "tutor_last_initial": row.tutor.public_last_initial,
            }
            if audience == "parent":
                context["child_id"] = row.student_id
            enqueue_in_session(
                session,
                recipient_user_id=user_id,
                template=template,
                context=context,
                dedupe_key=f"booking:{row.id}:{event}:{user_id}",
            )

    # -- SP5 ------------------------------------------------------------------

    def slots(
        self,
        tutor_profile_id: uuid.UUID,
        *,
        start: date,
        days: int,
        duration_minutes: int,
        student_id: uuid.UUID | None = None,
    ) -> SlotsView:
        """SP5: the slots ``core.booking.bookable_slots`` offers, minus the tutor's active bookings.

        ``start`` is a tutor-zone date from today; ``start + days`` may not pass today + 28
        days (422 ``invalid_window``); ``duration_minutes`` one of 45/60/90/120 (422
        ``invalid_duration``). A tutor who is not listed, is paused or is in an active block with
        ``student_id`` (the viewing student; ``None`` for a parent) is 404 (O11).
        """
        if duration_minutes not in ALLOWED_DURATIONS:
            raise _refuse("invalid_duration")
        if not 1 <= days <= MAX_BOOKING_HORIZON.days:
            raise _refuse("invalid_window")
        where = f"tp.id = :tutor_profile_id AND {listed_and_not_paused_sql('tp')}"
        params: dict[str, object] = {"tutor_profile_id": tutor_profile_id}
        if student_id is not None:
            where += f" AND NOT {active_block_between_sql(':student_id', 'tp.user_id')}"
            params["student_id"] = student_id
        now = self._clock()
        with self._sessionmaker() as session:
            profile = (
                session.execute(
                    sa.text(
                        "SELECT tp.zone, (SELECT coalesce(json_agg(json_build_array("  # noqa: S608 - constants
                        "r.iso_weekday, r.start_minute, r.end_minute)), '[]'::json) "
                        "FROM tutor_availability_rules r "
                        "WHERE r.tutor_profile_id = tp.id) AS rules "
                        f"FROM tutor_profiles tp WHERE {where}"
                    ),
                    params,
                )
                .mappings()
                .first()
            )
            if profile is None:
                raise _refuse("not_found", "Tutor not found.")
            zone = str(profile["zone"])
            today = now.astimezone(ZoneInfo(zone)).date()
            if start < today or start + timedelta(days=days) > today + MAX_BOOKING_HORIZON:
                raise _refuse("invalid_window")
            window_start = _local_midnight(start, zone)
            window_end = _local_midnight(start + timedelta(days=days), zone)
            busy = session.execute(
                sa.text(
                    "SELECT starts_at, ends_at FROM tutor_bookings "  # noqa: S608 - constant
                    f"WHERE tutor_profile_id = :tutor_profile_id AND {ACTIVE_STATES_SQL} "
                    "AND starts_at < :window_end AND ends_at > :window_start"
                ),
                {
                    "tutor_profile_id": tutor_profile_id,
                    "window_start": window_start,
                    "window_end": window_end,
                },
            ).all()
        offered = bookable_slots(
            _rules(profile["rules"]),
            zone=zone,
            start=start,
            days=days,
            duration=timedelta(minutes=duration_minutes),
            busy=[(_instant(lower), _instant(upper)) for lower, upper in busy],
            now=now,
        )
        return SlotsView(
            tutor_id=tutor_profile_id,
            zone=zone,
            duration_minutes=duration_minutes,
            window_start=window_start,
            window_end=window_end,
            slots=tuple(offered),
        )

    # -- S1, S2, T9, T10, PA1, PA2 ---------------------------------------------

    def get_for_viewer(self, booking_id: uuid.UUID, viewer: Actor) -> BookingRow | None:
        """One booking if ``viewer`` may see it, else ``None`` (two statements)."""
        where, params = _owner_where(viewer)
        with self._sessionmaker() as session:
            rows = _fetch_rows(
                session, f"b.id = :booking_id AND {where}", {"booking_id": booking_id, **params}
            )
        return rows[0] if rows else None

    def list_for_student(
        self, student_id: uuid.UUID, *, when: When, after: BookingsKey | None, limit: int
    ) -> BookingsPage:
        """S1: the student's own bookings."""
        return self._list("b.student_id = :owner", student_id, when, None, after, limit)

    def list_for_tutor(
        self,
        tutor_profile_id: uuid.UUID,
        *,
        when: When,
        state: EffectiveState | None = None,
        after: BookingsKey | None,
        limit: int,
    ) -> BookingsPage:
        """T9: the tutor's bookings, optionally one effective state (its §a.3 predicate)."""
        return self._list(
            "b.tutor_profile_id = :owner", tutor_profile_id, when, state, after, limit
        )

    def list_for_child(
        self, child_id: uuid.UUID, *, when: When, after: BookingsKey | None, limit: int
    ) -> BookingsPage:
        """PA1: a linked child's bookings (the route checked the link, O7)."""
        return self._list("b.student_id = :owner", child_id, when, None, after, limit)

    def _list(
        self,
        owner: str,
        owner_id: uuid.UUID,
        when: When,
        state: EffectiveState | None,
        after: BookingsKey | None,
        limit: int,
    ) -> BookingsPage:
        _check_limit(limit)
        split = after.split if after is not None else self._clock()
        clauses = [owner, BOOKING_WHEN_SQL[when]]
        params: dict[str, object] = {"owner": owner_id, "split": split}
        if state is not None:
            clauses.append(EFFECTIVE_STATE_SQL[state])
        upcoming = when == "upcoming"
        if after is not None:
            clauses.append(
                "(b.starts_at, b.id) > (:after_start, :after_id)"
                if upcoming
                else "(b.starts_at, b.id) < (:after_start, :after_id)"
            )
            params.update(after_start=after.starts_at, after_id=after.booking_id)
        order = "b.starts_at ASC, b.id ASC" if upcoming else "b.starts_at DESC, b.id DESC"
        with self._sessionmaker() as session:
            rows = _fetch_rows(session, " AND ".join(clauses), params, order=order, limit=limit + 1)
        page = rows[:limit]
        next_key = None
        if len(rows) > limit:
            last = page[-1]
            next_key = BookingsKey(split=split, starts_at=last.starts_at, booking_id=last.id)
        return BookingsPage(items=tuple(page), next_key=next_key)

    # -- S4, S5, T16, T17, PA3 --------------------------------------------------

    def post_note(self, *, booking_id: uuid.UUID, actor: Actor, body: str) -> NoteRow:
        """S5, T17: a note by the booking's student or tutor (O9; parents only read).

        Refusals: 404; 409 ``notes_closed`` (``core.booking.can_post_note`` over the effective
        state, a block, an inactive tutor, a safety freeze), ``tutor_suspended``/``tutor_closed``
        (a tutor author), ``safety_notice_required`` (a student author, row 16 ii); 422
        ``note_empty``, ``text_too_long``, ``contact_details_not_allowed``.
        """
        if actor.party not in ("student", "tutor"):
            raise ValueError("only the booking's student or tutor writes notes")
        text = _clean_text(body, limit=MAX_NOTE_LENGTH, what="A note")
        if text is None:
            raise _refuse("note_empty")
        with self._sessionmaker.begin() as session:
            tutor_profile_id, student_id = self._locate(session, booking_id, actor)
            self._lock_for_change(
                session, tutor_profile_id=tutor_profile_id, student_id=student_id, parent_id=None
            )
            session.execute(
                sa.text("SELECT 1 FROM tutor_bookings WHERE id = :b FOR SHARE"), {"b": booking_id}
            )
            facts = _change_facts(session, booking_id)
            if actor.party == "tutor":
                _refuse_inactive_tutor(facts.listing_state)
            allowed = can_post_note(
                effective_state(
                    facts.state, starts_at=facts.starts_at, ends_at=facts.ends_at, now=facts.db_now
                ),
                ends_at=facts.ends_at,
                now=facts.db_now,
                blocked=facts.blocked,
                tutor_inactive=facts.listing_state in _INACTIVE_LISTINGS,
                frozen=facts.notes_frozen,
            )
            if not allowed:
                raise _refuse("notes_closed")
            if actor.party == "student" and not facts.acknowledged:
                raise _refuse("safety_notice_required")
            note_id, created_at = self._insert_note(
                session, booking_id, actor.user_id, actor.party, text
            )
            row = _load_one(session, booking_id)
            parents = tuple(self._parents.linked_parent_ids_in_session(session, student_id))
        tutor_name = public_name(row.tutor.public_first_name, row.tutor.public_last_initial)
        label = student_label(row.student_display_name, row.student_id)
        return NoteRow(
            id=note_id,
            booking_id=booking_id,
            author_party=actor.party,
            author_name=tutor_name if actor.party == "tutor" else label,
            body=text,
            hidden=False,
            created_at=created_at,
            notice=NoteNotice(
                tutor_user_id=row.tutor_user_id,
                tutor_name=tutor_name,
                student_id=row.student_id,
                student_label=label,
                linked_parent_ids=parents,
                tutor_zone=row.tutor_zone,
            ),
        )

    @staticmethod
    def _insert_note(
        session: Session,
        booking_id: uuid.UUID,
        author_id: uuid.UUID,
        party: Literal["student", "tutor"],
        body: str,
    ) -> tuple[uuid.UUID, datetime]:
        inserted = session.execute(
            sa.text(
                "INSERT INTO tutor_booking_notes (booking_id, author_user_id, author_party, body) "
                "VALUES (:booking_id, :author_id, CAST(:party AS bookingparty), :body) "
                "RETURNING id, created_at"
            ),
            {"booking_id": booking_id, "author_id": author_id, "party": party, "body": body},
        ).one()
        return _uuid(inserted[0]), _instant(inserted[1])

    def list_notes(
        self, *, booking_id: uuid.UUID, viewer: Actor, after: NotesKey | None, limit: int
    ) -> NotesPage | None:
        """S4, T16, PA3: the thread, oldest first; ``None`` when the viewer may not see it.

        Reading is always allowed to those who can see the booking (SPEC §a.3); a hidden note
        keeps its place with no body. ``can_post`` is ``can_post_note`` for the booking's
        student or tutor at the app clock, and always false for a parent.
        """
        _check_limit(limit)
        where, params = _owner_where(viewer)
        with self._sessionmaker() as session:
            rows = _fetch_rows(
                session, f"b.id = :booking_id AND {where}", {"booking_id": booking_id, **params}
            )
            if not rows:
                return None
            note_where = "n.booking_id = :booking_id"
            note_params: dict[str, object] = {"booking_id": booking_id, "row_limit": limit + 1}
            if after is not None:
                note_where += " AND (n.created_at, n.id) > (:after_created, :after_id)"
                note_params.update(after_created=after.created_at, after_id=after.note_id)
            found = session.execute(
                sa.text(
                    "SELECT n.id, n.author_party::text AS author_party, n.body, n.hidden_at, "  # noqa: S608 - constants
                    f"n.created_at FROM tutor_booking_notes n WHERE {note_where} "
                    "ORDER BY n.created_at, n.id LIMIT :row_limit"
                ),
                note_params,
            ).all()
        row = rows[0]
        tutor_name = public_name(row.tutor.public_first_name, row.tutor.public_last_initial)
        label = student_label(row.student_display_name, row.student_id)
        items: list[NoteRow] = []
        for note_id, author_party, body, hidden_at, created_at in found[:limit]:
            party: Literal["student", "tutor"] = "tutor" if author_party == "tutor" else "student"
            items.append(
                NoteRow(
                    id=_uuid(note_id),
                    booking_id=booking_id,
                    author_party=party,
                    author_name=tutor_name if party == "tutor" else label,
                    body=None if hidden_at is not None else str(body),
                    hidden=hidden_at is not None,
                    created_at=_instant(created_at),
                )
            )
        next_key = None
        if len(found) > limit:
            next_key = NotesKey(created_at=items[-1].created_at, note_id=items[-1].id)
        now = self._clock()
        can_post = viewer.party in ("student", "tutor") and can_post_note(
            effective_state(row.state, starts_at=row.starts_at, ends_at=row.ends_at, now=now),
            ends_at=row.ends_at,
            now=now,
            blocked=row.blocked,
            tutor_inactive=row.tutor_listing_state in _INACTIVE_LISTINGS,
            frozen=row.notes_frozen,
        )
        return NotesPage(items=tuple(items), next_key=next_key, can_post=can_post)

    # -- In the caller's transaction (T21 sweeps, T25 reports) ----------------

    @staticmethod
    def freeze_notes_in_session(session: Session, booking_id: uuid.UUID) -> bool:
        """Freeze the thread for a ``safety_concern`` report (SC-10); ``True`` if this call did."""
        return (
            session.execute(
                sa.text(
                    "UPDATE tutor_bookings SET notes_frozen_at = now(), updated_at = now() "
                    "WHERE id = :b AND notes_frozen_at IS NULL RETURNING id"
                ),
                {"b": booking_id},
            ).first()
            is not None
        )

    @staticmethod
    def unfreeze_notes_in_session(session: Session, booking_id: uuid.UUID) -> bool:
        """Clear the freeze at report resolution; ``True`` if this call did."""
        return (
            session.execute(
                sa.text(
                    "UPDATE tutor_bookings SET notes_frozen_at = NULL, updated_at = now() "
                    "WHERE id = :b AND notes_frozen_at IS NOT NULL RETURNING id"
                ),
                {"b": booking_id},
            ).first()
            is not None
        )

    @staticmethod
    def hide_note_in_session(
        session: Session, note_id: uuid.UUID, admin_user_id: uuid.UUID
    ) -> bool:
        """Hide a note by report resolution; it keeps its place with no body. ``True`` if new."""
        return (
            session.execute(
                sa.text(
                    "UPDATE tutor_booking_notes SET hidden_at = now(), hidden_by_user_id = :admin, "
                    "updated_at = now() WHERE id = :n AND hidden_at IS NULL RETURNING id"
                ),
                {"n": note_id, "admin": admin_user_id},
            ).first()
            is not None
        )

    def cancel_future_for_pair_in_session(
        self,
        session: Session,
        *,
        tutor_profile_id: uuid.UUID,
        student_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
    ) -> list[uuid.UUID]:
        """A block's cancellations (SPEC §a.2 blocks): the pair's active bookings not yet started.

        Overrides the 24-hour window (row 15a); party ``system``, reason
        :data:`SYSTEM_CANCEL_REASON`, no ``cancelled_by_user_id``. The caller holds the tutor
        row ``FOR UPDATE`` and the pair lock (§a.4b, Block). Emails go to every party and linked
        parent except ``actor_user_id`` (the blocker). Returns the ids, earliest start first.
        """
        return self._cancel_future(
            session,
            where="b.tutor_profile_id = :tutor_profile_id AND b.student_id = :student_id",
            params={"tutor_profile_id": tutor_profile_id, "student_id": student_id},
            party="system",
            reason=SYSTEM_CANCEL_REASON,
            actor_user_id=actor_user_id,
            tell_tutor=True,
        )

    def cancel_future_for_tutor_in_session(
        self, session: Session, *, tutor_profile_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """A suspension's or close's cancellations (SPEC §a.3): every active booking not started.

        Party ``platform_admin``, reason :data:`ADMIN_CANCEL_REASON`. The caller holds the tutor
        row ``FOR UPDATE``. Emails go to each student and their linked parents, not to the
        tutor (who is told about the listing decision instead). Earliest start first.
        """
        return self._cancel_future(
            session,
            where="b.tutor_profile_id = :tutor_profile_id",
            params={"tutor_profile_id": tutor_profile_id},
            party="platform_admin",
            reason=ADMIN_CANCEL_REASON,
            actor_user_id=None,
            tell_tutor=False,
        )

    def _cancel_future(
        self,
        session: Session,
        *,
        where: str,
        params: Mapping[str, object],
        party: Party,
        reason: str,
        actor_user_id: uuid.UUID | None,
        tell_tutor: bool,
    ) -> list[uuid.UUID]:
        """Cancel the active bookings ``where`` selects that have not started, then queue emails.

        **Lock rule (SPEC §a.4b step 2, §i.6).** Before any booking row is touched, the ``users``
        rows of every student this sweep will cancel for are taken ``FOR KEY SHARE``, in id
        order. The emails queued afterwards reference those students, and their foreign-key
        checks take that same lock; taken only then, after the ``UPDATE``, it deadlocks against a
        booking create for one of those students with another tutor. The create holds the
        student row ``FOR UPDATE`` (step 2) and its student-slot exclusion check waits for this
        transaction's half-cancelled row, while this transaction waits for the student row
        (``40P01``). Taken first, the sweep simply queues behind the create, or the create behind
        the sweep. The set of students cannot grow between the lock and the ``UPDATE``: the
        caller holds the tutor row ``FOR UPDATE`` (step 1), so no booking with this tutor can be
        created meanwhile, and ``now()`` is fixed for the transaction.
        """
        bound = {**GUARD_BINDS, **params, "party": party, "cancelled_by": None, "reason": reason}
        guard = transition_guard_sql("cancel", party)
        session.execute(
            sa.text(
                "SELECT 1 FROM users WHERE id IN (SELECT b.student_id FROM tutor_bookings b "  # noqa: S608 - constants
                f"WHERE {where} AND {guard}) ORDER BY id FOR KEY SHARE"
            ),
            bound,
        )
        cancelled = session.execute(
            sa.text(
                f"UPDATE tutor_bookings AS b SET {_SET['cancel']}, updated_at = now() "  # noqa: S608 - constants
                f"WHERE {where} AND {guard} RETURNING b.id"
            ),
            bound,
        ).all()
        ids = [_uuid(found[0]) for found in cancelled]
        if not ids:
            return []
        rows = _fetch_rows(
            session,
            "b.id = ANY(CAST(:ids AS uuid[]))",
            {"ids": ids},
            order="b.starts_at ASC, b.id ASC",
        )
        parents_of: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {}
        for row in rows:
            if row.student_id not in parents_of:
                parents_of[row.student_id] = tuple(
                    self._parents.linked_parent_ids_in_session(session, row.student_id)
                )
            self._enqueue_emails(
                session,
                row,
                event="cancelled",
                parents=parents_of[row.student_id],
                actor=actor_user_id,
                tell_tutor=tell_tutor,
            )
        return [row.id for row in rows]

    def admin_cancel_in_session(
        self, session: Session, *, booking_id: uuid.UUID, admin_user_id: uuid.UUID
    ) -> BookingRow:
        """A11 ``booking_cancelled``: a platform cancellation before the start (§a.3).

        Takes steps 1-3 of §a.4b itself. Raises :class:`BookingRefused` (``not_found``,
        ``already_started``, ``illegal_transition``); an already cancelled booking is returned
        with ``notice=None``. Emails every party and linked parent.
        """
        return self._admin_change(session, booking_id, admin_user_id, "cancel")

    def admin_complete_in_session(
        self, session: Session, *, booking_id: uuid.UUID, admin_user_id: uuid.UUID
    ) -> BookingRow:
        """A11 ``booking_completed``: an ended accepted booking or a no-show becomes completed.

        Raises :class:`BookingRefused` (``not_found``, ``not_ended``, ``illegal_transition``);
        an already completed booking is returned with ``notice=None``.
        """
        return self._admin_change(session, booking_id, admin_user_id, "complete")

    def _admin_change(
        self, session: Session, booking_id: uuid.UUID, admin_user_id: uuid.UUID, action: Action
    ) -> BookingRow:
        found = session.execute(
            sa.text("SELECT tutor_profile_id, student_id FROM tutor_bookings WHERE id = :b"),
            {"b": booking_id},
        ).first()
        if found is None:
            raise _refuse("not_found")
        tutor_profile_id, student_id = _uuid(found[0]), _uuid(found[1])
        self._lock_for_change(
            session, tutor_profile_id=tutor_profile_id, student_id=student_id, parent_id=None
        )
        facts = _change_facts(session, booking_id)
        if facts.state == target_state(action):
            return _load_one(session, booking_id)
        refusal = check_transition(
            action, facts.core("platform_admin", admin_user_id), now=facts.db_now
        )
        if refusal is not None:
            raise _refuse(refusal.code)
        changed = self._compare_and_set(
            session,
            booking_id=booking_id,
            action=action,
            party="platform_admin",
            actor_id=admin_user_id,
            cancelled_by=admin_user_id,
            reason=ADMIN_CANCEL_REASON if action == "cancel" else None,
            tutor_profile_id=tutor_profile_id,
            student_id=student_id,
        )
        if not changed:
            return self._missed(session, booking_id, action, "platform_admin", admin_user_id)
        return self._announce(session, booking_id, _EVENT[action], admin_user_id)


__all__ = [
    "ADMIN_CANCEL_REASON",
    "BOOKING_CREATE_QUOTA",
    "BOOKING_WHEN_SQL",
    "CANCEL_QUOTA",
    "GUARD_BINDS",
    "MAX_NOTE_LENGTH",
    "MAX_PAGE_SIZE",
    "MAX_REASON_LENGTH",
    "QUOTA_BINDS",
    "QUOTA_SINCE_SQL",
    "QUOTA_WINDOW",
    "SYSTEM_CANCEL_REASON",
    "AcceptDetails",
    "Actor",
    "BookingEvent",
    "BookingNotice",
    "BookingRefused",
    "BookingRow",
    "BookingService",
    "BookingsKey",
    "BookingsPage",
    "NoteNotice",
    "NoteRow",
    "NotesKey",
    "NotesPage",
    "ReviewRef",
    "SlotsView",
    "When",
    "bookings_cursor",
    "live_pending_count_in_session",
    "lock_pair_in_session",
    "notes_cursor",
    "parse_bookings_cursor",
    "parse_notes_cursor",
    "transition_guard_sql",
]
