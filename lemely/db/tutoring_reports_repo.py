"""Tutoring reports: R1 filing, the A9 queue, the A10 detail and A11 resolution (SPEC §b.2).

The single writer of ``tutoring_reports`` and of the ``report_thread_view`` rows of
``tutoring_admin_access`` (PLAN §1.4 #2). SPEC ``docs/tutoring/SPEC.md`` §a.2, §a.3 ("Report"),
§a.4b, §b.2 R1 and A9-A11, §b.4, §c.3 O12/O15/O19, §i.4; THREAT-MODEL SC-10, SC-11, SC-15, SC-23.

**Who may report what (O12, O19).** Visibility is resolved here, from the target's own parent
rows, never from anything the client sends but the target's id: a note through its booking, a
reply through its review and that review's booking, a review through its booking. A booking or
a note is visible to its parties: the student, the tutor (``tutor_profiles.user_id``) and a
linked parent of the student (``ParentLinkService``, the single link query, F32). A tutor
profile is visible to a party to any booking with that tutor, in any listing state (SC-10:
pausing must not dodge a report), and to any student or parent while it is listed and not
paused; a teacher never reports a profile (a tutor cannot report themself). A review is visible
to a student or parent as SP3 shows it (listed, not paused, not removed; a student in an active
block with the tutor sees nothing) and to the tutor it is about, in any listing state; a reply
only to a student or parent, only when approved and under such a review. Anything else is
:data:`NOT_FOUND`, one body for every reason (no existence oracle). A block never hides a
booking or a note from its parties (SC-11), and nothing a reporter receives says whether one
exists: R1 answers with a receipt.

**What is stored (§a.2, §i.4).** ``target_snapshot`` is built here, inside the filing
transaction, through :func:`allowed_snapshot` and its per-``targetType`` key allowlist
(:data:`SNAPSHOT_KEYS`): a tutor profile's card fields and bio; a review's stars and text; a
reply's body; a booking's admin summary (no student, no meeting link, no place); a note's
author party and body. The same function filters the snapshot again when A10 reads it.
``details`` is trimmed and at most 1000 characters; it is not run through
``core.contact_patterns``: SC-7 lists no report field, and a safety report may need to quote
the contact details a tutor sent.

**Limits (§a.2, §b.4, SC-15).** One open report per reporter and target
(``uq_tutoring_reports_open_per_reporter`` -> 409 ``report_exists``), at most
:data:`REPORT_QUOTA` per reporter in 24 elapsed hours (429 ``too_many_requests``; a COUNT over
``ix_tutoring_reports_reporter_day``, the same window as the booking quotas). No verified email
is needed: a report is a safety path.

**The safety freeze (SC-10).** A ``safety_concern`` on a booking or a note (whose reporter is a
party by the rule above) sets ``tutor_bookings.notes_frozen_at`` in the filing transaction,
under the §a.4b locks a note post takes (the tutor row ``FOR SHARE``, the reporter's ``users``
row ``FOR KEY SHARE`` before the pair lock, §i.7, then the pair lock), so no note is posted after
the report commits. Resolving a report clears the freeze unless another open ``safety_concern``
on the same booking or one of its notes still holds it: each report freezes "until resolution".

**A10 (SC-23, O15).** For a booking or note target, one ``report_thread_view`` row is written
before the thread is read, in the same transaction; if it cannot be written the read fails and
nothing leaves. The thread is the only admin path to notes: every note, hidden ones with their
body, a student author named by party (:data:`STUDENT_AUTHOR_LABEL`), never by name (§a.5).

**A11 and its locks (§a.4b, §i.6, §i.7, W6 hand-off).** Every resolution takes the tutor row
``FOR UPDATE`` first (:func:`~lemely.db.tutoring_sweeps.lock_tutor_for_sweep`; a share lock
upgraded later can deadlock), then the report row ``FOR UPDATE`` (refusing a report resolved
meanwhile), then runs its action, each of which takes its own later locks: ``dismissed`` does
nothing more; ``content_hidden`` hides a note (``BookingService.hide_note_in_session``),
removes a review and recomputes the rating (``TutorReviewRepository.remove_review_in_session``)
or takes a reply down (``hide_reply_in_session``), and does not apply to a profile or a
booking; ``tutor_suspended`` is A5's sweep (``TutoringSweeps.sweep_sanction_in_session``) with
the fixed :data:`REPORT_SUSPENSION_NOTE`, because the tutor reads a suspension note and the
admin's resolution note may describe the reporter; ``booking_cancelled`` applies to a booking
or a note's booking that is active and not started (``BookingService.admin_cancel_in_session``);
``booking_completed`` only to a ``disputed_outcome`` report on the booking itself, ended and
awaiting an outcome or marked ``no_show`` (``admin_complete_in_session``). Those helpers run
before the freeze is lifted and before the report row is written, all in one transaction, so a
refusal (409 ``resolution_not_applicable``) or a failure writes nothing.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from lemely.core.booking import effective_state
from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.core.tutor_directory import public_name
from lemely.core.tutor_ratings import rating_display
from lemely.db.booking_repo import (
    QUOTA_BINDS,
    QUOTA_SINCE_SQL,
    BookingRefused,
    BookingRow,
    BookingService,
    lock_pair_in_session,
)
from lemely.db.models.enums import (
    ReportReason,
    ReportResolution,
    ReportState,
    ReportTargetType,
    TutoringAdminAction,
)
from lemely.db.models.tutoring import TutoringAdminAccess
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_approval_repo import IllegalApprovalTransitionError
from lemely.db.tutor_directory_repo import MODES, subjects_by_tutor
from lemely.db.tutor_review_repo import TutorReviewRepository
from lemely.db.tutoring_predicates import active_block_between_sql, listed_and_not_paused_sql
from lemely.db.tutoring_sweeps import (
    SweepResult,
    TutoringSweeps,
    lock_tutor_for_sweep,
    lock_users_for_insert,
)
from lemely.io.tutoring_areas import AreaCatalogue, load_tutoring_areas

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import RowMapping
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.booking import BookingStateLit, EffectiveState

ReporterParty = Literal["student", "parent", "tutor"]
NoteParty = Literal["student", "tutor"]

#: SC-15, SPEC §b.4: at most this many reports per reporter per 24 elapsed hours.
REPORT_QUOTA: Final = 20
#: ``ck_tutoring_reports_details_len``.
MAX_DETAILS_LENGTH: Final = 1000
#: ``ck_tutoring_reports_resolution_note_len``.
MAX_RESOLUTION_NOTE_LENGTH: Final = 1000
#: SPEC §0 "Paging": ``limit`` 1..50.
MAX_PAGE_SIZE: Final = 50
#: How a student author is named in an admin response (§a.5, §i.4): by party, never by name.
STUDENT_AUTHOR_LABEL: Final = "Student"
#: The suspension note an A11 ``tutor_suspended`` records, which the tutor reads (SPEC §a.2).
#: Fixed copy: the admin's resolution note stays on the report, since it may name the reporter.
REPORT_SUSPENSION_NOTE: Final = "Lemely suspended your tutor profile."

#: SPEC §i.4: the keys ``target_snapshot`` may hold, per target type. Pinned to the SPEC
#: sentence by ``tests/test_tutoring_reports_repo.py``.
SNAPSHOT_KEYS: Final[Mapping[ReportTargetType, frozenset[str]]] = MappingProxyType(
    {
        ReportTargetType.tutor_profile: frozenset(
            {"tutorId", "publicName", "headline", "subjects", "modes", "area", "rating", "bio"}
        ),
        ReportTargetType.review: frozenset({"stars", "text"}),
        ReportTargetType.review_reply: frozenset({"body"}),
        ReportTargetType.booking: frozenset(
            {
                "bookingId",
                "subject",
                "mode",
                "startsAt",
                "endsAt",
                "effectiveState",
                "completedBy",
                "notesFrozen",
            }
        ),
        ReportTargetType.booking_note: frozenset({"authorParty", "body"}),
    }
)

#: The column of ``tutoring_reports`` that holds each target type's id.
_TARGET_COLUMN: Final[Mapping[ReportTargetType, str]] = MappingProxyType(
    {
        ReportTargetType.tutor_profile: "tutor_profile_id",
        ReportTargetType.review: "review_id",
        ReportTargetType.review_reply: "reply_id",
        ReportTargetType.booking: "booking_id",
        ReportTargetType.booking_note: "note_id",
    }
)

_OPEN_PER_REPORTER: Final = "uq_tutoring_reports_open_per_reporter"

_STATUS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "not_found": 404,
        "text_too_long": 422,
        "note_too_long": 422,
        "too_many_requests": 429,
    }
)

_MESSAGES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "not_found": "We could not find that.",
        "report_not_found": "Report not found.",
        "text_too_long": f"Keep the details to {MAX_DETAILS_LENGTH} characters.",
        "note_too_long": f"Keep the note to {MAX_RESOLUTION_NOTE_LENGTH} characters.",
        "too_many_requests": "That is happening too often. Try again in a little while.",
        "report_exists": "You have already reported this. We are looking at it.",
        "already_resolved": "This report has already been resolved.",
        "resolution_not_applicable": "That resolution does not apply to this report.",
    }
)


class ReportRefused(Exception):
    """A refusal the route sends as ``tutoring_error(status, code, message)``."""

    def __init__(self, code: str, status: int, message: str) -> None:
        """Record the stable API code, its HTTP status and one plain English sentence."""
        self.code = code
        self.status = status
        self.message = message
        super().__init__(message)


def _refuse(code: str, *, message_key: str | None = None) -> ReportRefused:
    return ReportRefused(code, _STATUS.get(code, 409), _MESSAGES[message_key or code])


# ---------------------------------------------------------------------------
# Inputs and read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reporter:
    """Who files a report: the caller's ``users.id`` and party (R1's role, a teacher as tutor)."""

    user_id: uuid.UUID
    party: ReporterParty


@dataclass(frozen=True, slots=True)
class FiledReport:
    """R1's result.

    ``admin_user_ids`` are the platform admins to tell after the commit (SC-10): every one for
    a ``safety_concern``, none otherwise.
    """

    report_id: uuid.UUID
    created_at: datetime
    reason: ReportReason
    froze_notes: bool
    admin_user_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class ReportsKey:
    """Keyset position in the A9 queue: safety concerns first, then oldest first."""

    safety: bool
    created_at: datetime
    report_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ReportItem:
    """One row of the A9 queue."""

    report_id: uuid.UUID
    target_type: ReportTargetType
    reason: ReportReason
    state: ReportState
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReportsPage:
    """One page of A9."""

    items: tuple[ReportItem, ...]
    next_key: ReportsKey | None


@dataclass(frozen=True, slots=True)
class BookingSummary:
    """The booking a booking or note report concerns, as an admin sees it.

    No student, no meeting link and no place (§a.5); ``effective_state`` is read at the
    database clock.
    """

    booking_id: uuid.UUID
    subject_code: str
    subject_name: str
    mode: str
    starts_at: datetime
    ends_at: datetime
    effective_state: EffectiveState
    completed_by: str | None
    notes_frozen: bool


@dataclass(frozen=True, slots=True)
class AdminNote:
    """One note of the thread A10 shows: hidden or not, with its body; a student by party."""

    note_id: uuid.UUID
    author_party: NoteParty
    author_name: str
    body: str
    hidden: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReportDetail:
    """A10 and A11: the report, the tutor its target belongs to, and what the target was."""

    item: ReportItem
    reporter_party: ReporterParty
    details: str | None
    tutor_profile_id: uuid.UUID
    tutor_name: str
    snapshot: Mapping[str, object]
    booking: BookingSummary | None
    notes: tuple[AdminNote, ...]
    resolution: ReportResolution | None
    resolution_note: str | None
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class ResolveOutcome:
    """A11's result: the resolved report (no thread, O15) and what to announce after commit."""

    detail: ReportDetail
    booking_change: BookingRow | None
    sweep: SweepResult | None


@dataclass(frozen=True, slots=True)
class _Located:
    """A target resolved from its own rows (O19): the tutor it belongs to and its booking."""

    target_type: ReportTargetType
    target_id: uuid.UUID
    tutor_profile_id: uuid.UUID
    tutor_user_id: uuid.UUID
    booking_id: uuid.UUID | None
    student_id: uuid.UUID | None
    live: bool
    listed: bool


@dataclass(frozen=True, slots=True)
class _Head:
    """A report row's own columns."""

    report_id: uuid.UUID
    reporter_party: ReporterParty
    target_type: ReportTargetType
    target_id: uuid.UUID
    snapshot: object
    reason: ReportReason
    details: str | None
    state: ReportState
    resolution: ReportResolution | None
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime

    @property
    def item(self) -> ReportItem:
        return ReportItem(
            report_id=self.report_id,
            target_type=self.target_type,
            reason=self.reason,
            state=self.state,
            created_at=self.created_at,
        )


# ---------------------------------------------------------------------------
# Snapshots and cursors
# ---------------------------------------------------------------------------


def allowed_snapshot(target_type: ReportTargetType, raw: object) -> dict[str, object]:
    """The keys of ``raw`` that SPEC §i.4 allows for ``target_type``; nothing else, ever.

    Used when a snapshot is written (R1) and again when it is read (A10, A11), so a key that
    reached the column some other way is still never served.
    """
    if not isinstance(raw, Mapping):
        return {}
    keys = SNAPSHOT_KEYS[target_type]
    return {str(key): value for key, value in raw.items() if key in keys}


def _endpoint(state: ReportState) -> str:
    return f"admin_reports:{state.value}"


def reports_cursor(state: ReportState, key: ReportsKey) -> str:
    """Encode ``key`` for the A9 queue filtered to ``state`` (O21: bound to that state)."""
    return encode_cursor(_endpoint(state), [key.safety, key.created_at, key.report_id])


def parse_reports_cursor(token: str, state: ReportState) -> ReportsKey:
    """Decode a cursor minted by :func:`reports_cursor` for the same ``state``.

    Raises :class:`~lemely.core.keyset.CursorError` for anything else.
    """
    safety, created_at, report_id = decode_cursor(
        token, endpoint=_endpoint(state), types=(bool, datetime, uuid.UUID)
    )
    if not (
        isinstance(safety, bool)
        and isinstance(created_at, datetime)
        and isinstance(report_id, uuid.UUID)
    ):  # pragma: no cover - decode_cursor already returns these types
        raise CursorError("cursor has the wrong shape")
    return ReportsKey(safety=safety, created_at=created_at, report_id=report_id)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _opt_uuid(value: object) -> uuid.UUID | None:
    return None if value is None else _uuid(value)


def _instant(value: object) -> datetime:
    if not isinstance(value, datetime):  # pragma: no cover - timestamptz is a datetime
        raise TypeError(f"expected a datetime, got {value!r}")
    return value


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _clean_text(value: str | None, *, limit: int, code: str) -> str | None:
    """Trimmed; blank is ``None``; longer than ``limit`` is refused with ``code``."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    if len(text) > limit:
        raise _refuse(code)
    return text


def _constraint(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return name if isinstance(name, str) else None


def _reporter_party(value: object) -> ReporterParty:
    text = str(value)
    if text not in {"student", "parent", "tutor"}:  # pragma: no cover - the CHECK forbids it
        raise ValueError(f"unexpected reporter party {text!r}")
    return cast("ReporterParty", text)


def _note_party(value: object) -> NoteParty:
    return "tutor" if str(value) == "tutor" else "student"


_LISTED: Final = listed_and_not_paused_sql("tp")

#: Each target resolved through its own parent rows (O19): note -> booking, reply -> review ->
#: booking, review -> booking. ``live`` is "a reader of SP3 would see it" for a review or reply.
_LOCATE_SQL: Final[Mapping[ReportTargetType, str]] = MappingProxyType(
    {
        ReportTargetType.tutor_profile: (
            "SELECT tp.id AS tutor_profile_id, tp.user_id AS tutor_user_id, "  # noqa: S608 - constants
            "NULL::uuid AS booking_id, NULL::uuid AS student_id, TRUE AS live, "
            f"{_LISTED} AS listed FROM tutor_profiles tp WHERE tp.id = :t"
        ),
        ReportTargetType.review: (
            "SELECT b.tutor_profile_id, tp.user_id AS tutor_user_id, "  # noqa: S608 - constants
            "NULL::uuid AS booking_id, NULL::uuid AS student_id, "
            f"(r.removed_at IS NULL) AS live, {_LISTED} AS listed "
            "FROM tutor_reviews r JOIN tutor_bookings b ON b.id = r.booking_id "
            "JOIN tutor_profiles tp ON tp.id = b.tutor_profile_id WHERE r.id = :t"
        ),
        ReportTargetType.review_reply: (
            "SELECT b.tutor_profile_id, tp.user_id AS tutor_user_id, "  # noqa: S608 - constants
            "NULL::uuid AS booking_id, NULL::uuid AS student_id, "
            "(r.removed_at IS NULL AND rp.text_state = 'approved') AS live, "
            f"{_LISTED} AS listed FROM tutor_review_replies rp "
            "JOIN tutor_reviews r ON r.id = rp.review_id "
            "JOIN tutor_bookings b ON b.id = r.booking_id "
            "JOIN tutor_profiles tp ON tp.id = b.tutor_profile_id WHERE rp.id = :t"
        ),
        ReportTargetType.booking: (
            "SELECT b.tutor_profile_id, tp.user_id AS tutor_user_id, b.id AS booking_id, "  # noqa: S608 - constants
            f"b.student_id, TRUE AS live, {_LISTED} AS listed FROM tutor_bookings b "
            "JOIN tutor_profiles tp ON tp.id = b.tutor_profile_id WHERE b.id = :t"
        ),
        ReportTargetType.booking_note: (
            "SELECT b.tutor_profile_id, tp.user_id AS tutor_user_id, b.id AS booking_id, "  # noqa: S608 - constants
            f"b.student_id, TRUE AS live, {_LISTED} AS listed FROM tutor_booking_notes n "
            "JOIN tutor_bookings b ON b.id = n.booking_id "
            "JOIN tutor_profiles tp ON tp.id = b.tutor_profile_id WHERE n.id = :t"
        ),
    }
)

_HEAD_SQL: Final = (
    "SELECT r.id, r.reporter_party::text AS reporter_party, r.target_type::text AS target_type, "
    "COALESCE(r.tutor_profile_id, r.review_id, r.reply_id, r.booking_id, r.note_id) AS target_id, "
    "r.target_snapshot, r.reason::text AS reason, r.details, r.state::text AS state, "
    "r.resolution::text AS resolution, r.resolution_note, r.resolved_at, r.created_at "
    "FROM tutoring_reports r WHERE r.id = :r"
)

_SAFETY: Final = "(r.reason = 'safety_concern')"


def _head(session: Session, report_id: uuid.UUID, *, lock: bool = False) -> _Head | None:
    m = (
        session.execute(sa.text(_HEAD_SQL + (" FOR UPDATE" if lock else "")), {"r": report_id})
        .mappings()
        .first()
    )
    if m is None:
        return None
    return _Head(
        report_id=_uuid(m["id"]),
        reporter_party=_reporter_party(m["reporter_party"]),
        target_type=ReportTargetType(str(m["target_type"])),
        target_id=_uuid(m["target_id"]),
        snapshot=m["target_snapshot"],
        reason=ReportReason(str(m["reason"])),
        details=_opt_str(m["details"]),
        state=ReportState(str(m["state"])),
        resolution=None if m["resolution"] is None else ReportResolution(str(m["resolution"])),
        resolution_note=_opt_str(m["resolution_note"]),
        resolved_at=None if m["resolved_at"] is None else _instant(m["resolved_at"]),
        created_at=_instant(m["created_at"]),
    )


def _locate(
    session: Session, target_type: ReportTargetType, target_id: uuid.UUID
) -> _Located | None:
    m = session.execute(sa.text(_LOCATE_SQL[target_type]), {"t": target_id}).mappings().first()
    if m is None:
        return None
    return _Located(
        target_type=target_type,
        target_id=target_id,
        tutor_profile_id=_uuid(m["tutor_profile_id"]),
        tutor_user_id=_uuid(m["tutor_user_id"]),
        booking_id=_opt_uuid(m["booking_id"]),
        student_id=_opt_uuid(m["student_id"]),
        live=bool(m["live"]),
        listed=bool(m["listed"]),
    )


def _blocked(session: Session, student_id: uuid.UUID, tutor_user_id: uuid.UUID) -> bool:
    """An active block between the pair, either way (as SP3 hides a tutor's reviews, O11)."""
    sql = f"SELECT {active_block_between_sql(':student_id', ':tutor_user_id')}"
    return bool(
        session.execute(
            sa.text(sql), {"student_id": student_id, "tutor_user_id": tutor_user_id}
        ).scalar_one()
    )


def _booked_with(
    session: Session, tutor_profile_id: uuid.UUID, students: Sequence[uuid.UUID]
) -> bool:
    """Any booking, in any state, between the tutor and one of ``students``."""
    if not students:
        return False
    return bool(
        session.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM tutor_bookings b WHERE b.tutor_profile_id = :t "
                "AND b.student_id = ANY(CAST(:students AS uuid[])))"
            ),
            {"t": tutor_profile_id, "students": list(students)},
        ).scalar_one()
    )


def _lock_tutor_share(session: Session, tutor_profile_id: uuid.UUID) -> None:
    """§a.4b step 1 for a write on one booking: the tutor row ``FOR SHARE``."""
    session.execute(
        sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR SHARE"), {"t": tutor_profile_id}
    )


def _booking_summary(session: Session, booking_id: uuid.UUID) -> BookingSummary:
    m = (
        session.execute(
            sa.text(
                "SELECT b.id, b.subject_code, s.name AS subject_name, b.mode::text AS mode, "
                "b.starts_at, b.ends_at, b.state::text AS state, "
                "b.completed_by_party::text AS completed_by, "
                "(b.notes_frozen_at IS NOT NULL) AS frozen, now() AS db_now "
                "FROM tutor_bookings b JOIN subjects s ON s.code = b.subject_code "
                "WHERE b.id = :b"
            ),
            {"b": booking_id},
        )
        .mappings()
        .one()
    )
    starts_at, ends_at = _instant(m["starts_at"]), _instant(m["ends_at"])
    return BookingSummary(
        booking_id=_uuid(m["id"]),
        subject_code=str(m["subject_code"]),
        subject_name=str(m["subject_name"]),
        mode=str(m["mode"]),
        starts_at=starts_at,
        ends_at=ends_at,
        effective_state=effective_state(
            cast("BookingStateLit", str(m["state"])),
            starts_at=starts_at,
            ends_at=ends_at,
            now=_instant(m["db_now"]),
        ),
        completed_by=_opt_str(m["completed_by"]),
        notes_frozen=bool(m["frozen"]),
    )


def _summary_fields(summary: BookingSummary) -> dict[str, object]:
    """The ``AdminBookingSummaryDTO`` fields of ``summary`` as JSON values (§i.4 booking keys)."""
    return {
        "bookingId": str(summary.booking_id),
        "subject": {"code": summary.subject_code, "name": summary.subject_name},
        "mode": summary.mode,
        "startsAt": _iso(summary.starts_at),
        "endsAt": _iso(summary.ends_at),
        "effectiveState": summary.effective_state,
        "completedBy": summary.completed_by,
        "notesFrozen": summary.notes_frozen,
    }


def _modes(m: RowMapping) -> list[str]:
    offered = {
        "virtual": m["offers_virtual"],
        "in_person": m["offers_in_person"],
        "other": m["offers_other"],
    }
    return [mode for mode in MODES if offered[mode]]


# ---------------------------------------------------------------------------
# The repository
# ---------------------------------------------------------------------------


class TutoringReportsRepository:
    """R1 and A9-A11 over a ``sessionmaker``; each public method is one transaction."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        parents: ParentLinkService | None = None,
        bookings: BookingService | None = None,
        sweeps: TutoringSweeps | None = None,
        areas: AreaCatalogue | None = None,
    ) -> None:
        """Wire the repository to a session factory and the services a resolution composes."""
        self._sessionmaker = sessionmaker
        self._parents = parents if parents is not None else ParentLinkService(sessionmaker)
        self._bookings = (
            bookings
            if bookings is not None
            else BookingService(sessionmaker, parents=self._parents)
        )
        self._sweeps = (
            sweeps
            if sweeps is not None
            else TutoringSweeps(sessionmaker, bookings=self._bookings, parents=self._parents)
        )
        self._areas = areas if areas is not None else load_tutoring_areas()

    # -- R1 ---------------------------------------------------------------------

    def file(
        self,
        reporter: Reporter,
        *,
        target_type: ReportTargetType,
        target_id: uuid.UUID,
        reason: ReportReason,
        details: str | None,
    ) -> FiledReport:
        """R1: file a report on a target the reporter can see (O12, O19).

        Raises :class:`ReportRefused`: 422 ``text_too_long``, 429 ``too_many_requests``,
        404 ``not_found`` (one body whatever the reason), 409 ``report_exists``.
        """
        cleaned = _clean_text(details, limit=MAX_DETAILS_LENGTH, code="text_too_long")
        children: tuple[uuid.UUID, ...] = ()
        if reporter.party == "parent" and target_type is ReportTargetType.tutor_profile:
            children = tuple(
                child.child_id for child in self._parents.linked_children(reporter.user_id)
            )
        try:
            with self._sessionmaker.begin() as session:
                self._check_quota(session, reporter.user_id)
                located = _locate(session, target_type, target_id)
                if located is None or not self._visible(session, reporter, located, children):
                    raise _refuse("not_found")
                freeze = reason is ReportReason.safety_concern and located.booking_id is not None
                if freeze and located.student_id is not None:
                    _lock_tutor_share(session, located.tutor_profile_id)
                    lock_users_for_insert(session, [reporter.user_id])
                    lock_pair_in_session(
                        session,
                        student_id=located.student_id,
                        tutor_profile_id=located.tutor_profile_id,
                    )
                snapshot = self._snapshot(session, located)
                froze = (
                    BookingService.freeze_notes_in_session(session, located.booking_id)
                    if freeze and located.booking_id is not None
                    else False
                )
                inserted = session.execute(
                    sa.text(
                        "INSERT INTO tutoring_reports (reporter_user_id, reporter_party, "  # noqa: S608 - column from a constant map
                        f"target_type, {_TARGET_COLUMN[target_type]}, target_snapshot, reason, "
                        "details) VALUES (:reporter, CAST(:party AS bookingparty), "
                        "CAST(:target_type AS reporttargettype), :target, "
                        "CAST(:snapshot AS jsonb), CAST(:reason AS reportreason), :details) "
                        "RETURNING id, created_at"
                    ),
                    {
                        "reporter": reporter.user_id,
                        "party": reporter.party,
                        "target_type": target_type.value,
                        "target": target_id,
                        "snapshot": json.dumps(snapshot),
                        "reason": reason.value,
                        "details": cleaned,
                    },
                ).one()
                admins: tuple[uuid.UUID, ...] = ()
                if reason is ReportReason.safety_concern:
                    admins = tuple(
                        _uuid(value)
                        for value in session.scalars(
                            sa.text(
                                "SELECT id FROM users WHERE role = 'platform_admin' ORDER BY id"
                            )
                        )
                    )
        except IntegrityError as exc:
            if _constraint(exc) == _OPEN_PER_REPORTER:
                raise _refuse("report_exists") from exc
            raise
        return FiledReport(
            report_id=_uuid(inserted[0]),
            created_at=_instant(inserted[1]),
            reason=reason,
            froze_notes=froze,
            admin_user_ids=admins,
        )

    @staticmethod
    def _check_quota(session: Session, reporter_id: uuid.UUID) -> None:
        count = session.execute(
            sa.text(
                "SELECT count(*) FROM tutoring_reports WHERE reporter_user_id = :u "  # noqa: S608 - constant
                f"AND created_at > {QUOTA_SINCE_SQL}"
            ),
            {**QUOTA_BINDS, "u": reporter_id},
        ).scalar_one()
        if int(count) >= REPORT_QUOTA:
            raise _refuse("too_many_requests")

    def _visible(
        self,
        session: Session,
        reporter: Reporter,
        located: _Located,
        children: Sequence[uuid.UUID],
    ) -> bool:
        """O12 for one located target (see the module docstring)."""
        target_type = located.target_type
        if target_type in {ReportTargetType.booking, ReportTargetType.booking_note}:
            return self._is_party(session, reporter, located)
        if target_type is ReportTargetType.tutor_profile:
            if reporter.party == "tutor":
                return False
            students = (reporter.user_id,) if reporter.party == "student" else tuple(children)
            return located.listed or _booked_with(session, located.tutor_profile_id, students)
        if not located.live:
            return False
        if reporter.party == "tutor":
            return (
                target_type is ReportTargetType.review and located.tutor_user_id == reporter.user_id
            )
        if not located.listed:
            return False
        return reporter.party == "parent" or not _blocked(
            session, reporter.user_id, located.tutor_user_id
        )

    def _is_party(self, session: Session, reporter: Reporter, located: _Located) -> bool:
        """The booking's student, its tutor or a linked parent of its student."""
        if located.student_id is None:  # pragma: no cover - booking targets always carry it
            return False
        if reporter.party == "student":
            return located.student_id == reporter.user_id
        if reporter.party == "tutor":
            return located.tutor_user_id == reporter.user_id
        return reporter.user_id in self._parents.linked_parent_ids_in_session(
            session, located.student_id
        )

    def _snapshot(self, session: Session, located: _Located) -> dict[str, object]:
        """The target's content as reported, through the §i.4 allowlist."""
        target_type, target_id = located.target_type, located.target_id
        raw: dict[str, object]
        if target_type is ReportTargetType.tutor_profile:
            raw = self._profile_snapshot(session, target_id)
        elif target_type is ReportTargetType.review:
            m = session.execute(
                sa.text("SELECT stars, body FROM tutor_reviews WHERE id = :t"), {"t": target_id}
            ).one()
            raw = {"stars": int(m.stars), "text": _opt_str(m.body)}
        elif target_type is ReportTargetType.review_reply:
            body = session.execute(
                sa.text("SELECT body FROM tutor_review_replies WHERE id = :t"), {"t": target_id}
            ).scalar_one()
            raw = {"body": str(body)}
        elif target_type is ReportTargetType.booking_note:
            m = session.execute(
                sa.text(
                    "SELECT author_party::text AS author_party, body FROM tutor_booking_notes "
                    "WHERE id = :t"
                ),
                {"t": target_id},
            ).one()
            raw = {"authorParty": _note_party(m.author_party), "body": str(m.body)}
        else:
            if located.booking_id is None:  # pragma: no cover - booking targets always carry it
                raise ValueError("a booking target has no booking id")
            raw = _summary_fields(_booking_summary(session, located.booking_id))
        return allowed_snapshot(target_type, raw)

    def _profile_snapshot(self, session: Session, tutor_profile_id: uuid.UUID) -> dict[str, object]:
        m = (
            session.execute(
                sa.text(
                    "SELECT public_first_name, public_last_initial, headline, bio, "
                    "offers_virtual, offers_in_person, offers_other, area_code, rating_sum, "
                    "rating_count FROM tutor_profiles WHERE id = :t"
                ),
                {"t": tutor_profile_id},
            )
            .mappings()
            .one()
        )
        subjects = subjects_by_tutor(session, [tutor_profile_id]).get(tutor_profile_id, ())
        rating = rating_display(int(m["rating_sum"]), int(m["rating_count"]))
        area = str(m["area_code"])
        return {
            "tutorId": str(tutor_profile_id),
            "publicName": public_name(
                str(m["public_first_name"]), _opt_str(m["public_last_initial"])
            ),
            "headline": str(m["headline"]),
            "subjects": [{"code": subject.code, "name": subject.name} for subject in subjects],
            "modes": _modes(m),
            "area": {"code": area, "name": self._areas.name_for(area)},
            "rating": {"state": rating.state, "average": rating.average, "count": rating.count},
            "bio": str(m["bio"]),
        }

    # -- A9 ---------------------------------------------------------------------

    def queue(self, state: ReportState, *, after: ReportsKey | None, limit: int) -> ReportsPage:
        """A9: the reports in ``state``, safety concerns first, then oldest first (SC-10)."""
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be 1..{MAX_PAGE_SIZE}")
        where = "r.state = CAST(:state AS reportstate)"
        params: dict[str, object] = {"state": state.value, "row_limit": limit + 1}
        if after is not None:
            where += (
                f" AND ({_SAFETY} < :k_safety OR ({_SAFETY} = :k_safety "
                "AND (r.created_at, r.id) > (:k_created, :k_id)))"
            )
            params.update(k_safety=after.safety, k_created=after.created_at, k_id=after.report_id)
        with self._sessionmaker() as session:
            rows = session.execute(
                sa.text(
                    "SELECT r.id, r.target_type::text AS target_type, r.reason::text AS reason, "  # noqa: S608 - constants
                    f"r.state::text AS state, r.created_at, {_SAFETY} AS safety "
                    f"FROM tutoring_reports r WHERE {where} "
                    f"ORDER BY {_SAFETY} DESC, r.created_at, r.id LIMIT :row_limit"
                ),
                params,
            ).all()
        items = tuple(
            ReportItem(
                report_id=_uuid(row.id),
                target_type=ReportTargetType(str(row.target_type)),
                reason=ReportReason(str(row.reason)),
                state=ReportState(str(row.state)),
                created_at=_instant(row.created_at),
            )
            for row in rows[:limit]
        )
        next_key = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_key = ReportsKey(
                safety=bool(last.safety),
                created_at=_instant(last.created_at),
                report_id=_uuid(last.id),
            )
        return ReportsPage(items=items, next_key=next_key)

    # -- A10 --------------------------------------------------------------------

    def detail_for_admin(
        self, report_id: uuid.UUID, *, admin_user_id: uuid.UUID
    ) -> ReportDetail | None:
        """A10: the report, its snapshot and, for a booking or note target, the thread.

        The ``report_thread_view`` row is written before the thread is read, in the same
        transaction; a failed write propagates and nothing is returned (SC-23: fail closed).
        ``None`` for an unknown report.
        """
        with self._sessionmaker.begin() as session:
            head = _head(session, report_id)
            if head is None:
                return None
            located = self._located(session, head)
            if located.booking_id is not None:
                session.add(
                    TutoringAdminAccess(
                        admin_user_id=admin_user_id,
                        action=TutoringAdminAction.report_thread_view,
                        tutor_profile_id=located.tutor_profile_id,
                        report_id=report_id,
                        booking_id=located.booking_id,
                    )
                )
                session.flush()
            return self._detail(session, head, located, with_notes=True)

    @staticmethod
    def _located(session: Session, head: _Head) -> _Located:
        located = _locate(session, head.target_type, head.target_id)
        if located is None:  # pragma: no cover - every target FK is RESTRICT
            raise LookupError(f"report {head.report_id} lost its target")
        return located

    def _detail(
        self, session: Session, head: _Head, located: _Located, *, with_notes: bool
    ) -> ReportDetail:
        names = session.execute(
            sa.text(
                "SELECT public_first_name, public_last_initial FROM tutor_profiles WHERE id = :t"
            ),
            {"t": located.tutor_profile_id},
        ).one()
        tutor_name = public_name(str(names[0]), _opt_str(names[1]))
        summary = None
        notes: tuple[AdminNote, ...] = ()
        if located.booking_id is not None:
            summary = _booking_summary(session, located.booking_id)
            if with_notes:
                notes = self._thread(session, located.booking_id, tutor_name)
        return ReportDetail(
            item=head.item,
            reporter_party=head.reporter_party,
            details=head.details,
            tutor_profile_id=located.tutor_profile_id,
            tutor_name=tutor_name,
            snapshot=allowed_snapshot(head.target_type, head.snapshot),
            booking=summary,
            notes=notes,
            resolution=head.resolution,
            resolution_note=head.resolution_note,
            resolved_at=head.resolved_at,
        )

    @staticmethod
    def _thread(session: Session, booking_id: uuid.UUID, tutor_name: str) -> tuple[AdminNote, ...]:
        rows = session.execute(
            sa.text(
                "SELECT n.id, n.author_party::text AS author_party, n.body, n.hidden_at, "
                "n.created_at FROM tutor_booking_notes n WHERE n.booking_id = :b "
                "ORDER BY n.created_at, n.id"
            ),
            {"b": booking_id},
        ).all()
        notes: list[AdminNote] = []
        for row in rows:
            party = _note_party(row.author_party)
            notes.append(
                AdminNote(
                    note_id=_uuid(row.id),
                    author_party=party,
                    author_name=tutor_name if party == "tutor" else STUDENT_AUTHOR_LABEL,
                    body=str(row.body),
                    hidden=row.hidden_at is not None,
                    created_at=_instant(row.created_at),
                )
            )
        return tuple(notes)

    # -- A11 --------------------------------------------------------------------

    def resolve(
        self,
        report_id: uuid.UUID,
        *,
        admin_user_id: uuid.UUID,
        resolution: ReportResolution,
        note: str | None,
    ) -> ResolveOutcome:
        """A11: resolve an open report with ``resolution`` in one transaction (see the module).

        Raises :class:`ReportRefused`: 422 ``note_too_long``, 404 ``not_found``, 409
        ``already_resolved`` or ``resolution_not_applicable``. A refusal writes nothing.
        """
        cleaned = _clean_text(note, limit=MAX_RESOLUTION_NOTE_LENGTH, code="note_too_long")
        with self._sessionmaker.begin() as session:
            head = _head(session, report_id)
            if head is None:
                raise _refuse("not_found", message_key="report_not_found")
            if head.state is not ReportState.open:
                raise _refuse("already_resolved")
            located = self._located(session, head)
            lock_tutor_for_sweep(session, located.tutor_profile_id)
            head = _head(session, report_id, lock=True)
            if head is None or head.state is not ReportState.open:
                raise _refuse("already_resolved")
            booking_change, sweep = self._act(session, head, located, resolution, admin_user_id)
            if located.booking_id is not None:
                self._release_freeze(session, located.booking_id, report_id)
            session.execute(
                sa.text(
                    "UPDATE tutoring_reports SET state = CAST(:state AS reportstate), "
                    "resolution = CAST(:resolution AS reportresolution), "
                    "resolution_note = :note, resolved_by = :admin, resolved_at = now(), "
                    "updated_at = now() WHERE id = :r AND state = 'open'"
                ),
                {
                    "state": (
                        ReportState.dismissed
                        if resolution is ReportResolution.dismissed
                        else ReportState.actioned
                    ).value,
                    "resolution": resolution.value,
                    "note": cleaned,
                    "admin": admin_user_id,
                    "r": report_id,
                },
            )
            resolved = _head(session, report_id)
            if resolved is None:  # pragma: no cover - the row is locked by this transaction
                raise LookupError(f"report {report_id} vanished inside its own transaction")
            detail = self._detail(session, resolved, located, with_notes=False)
        return ResolveOutcome(detail=detail, booking_change=booking_change, sweep=sweep)

    def _act(
        self,
        session: Session,
        head: _Head,
        located: _Located,
        resolution: ReportResolution,
        admin_user_id: uuid.UUID,
    ) -> tuple[BookingRow | None, SweepResult | None]:
        """Run ``resolution``'s action; ``resolution_not_applicable`` where it has none."""
        if resolution is ReportResolution.dismissed:
            return None, None
        if resolution is ReportResolution.content_hidden:
            self._hide(session, located, admin_user_id)
            return None, None
        if resolution is ReportResolution.tutor_suspended:
            try:
                sweep = self._sweeps.sweep_sanction_in_session(
                    session,
                    tutor_profile_id=located.tutor_profile_id,
                    reason="tutor_suspended",
                    admin_user_id=admin_user_id,
                    note=REPORT_SUSPENSION_NOTE,
                )
            except IllegalApprovalTransitionError as exc:
                raise _refuse("resolution_not_applicable") from exc
            return None, sweep
        if located.booking_id is None:
            raise _refuse("resolution_not_applicable")
        summary = _booking_summary(session, located.booking_id)
        try:
            if resolution is ReportResolution.booking_cancelled:
                if summary.effective_state not in {"requested", "accepted"} or not (
                    _db_now(session) < summary.starts_at
                ):
                    raise _refuse("resolution_not_applicable")
                row = self._bookings.admin_cancel_in_session(
                    session, booking_id=located.booking_id, admin_user_id=admin_user_id
                )
            else:
                if (
                    head.target_type is not ReportTargetType.booking
                    or head.reason is not ReportReason.disputed_outcome
                    or summary.effective_state not in {"awaiting_outcome", "no_show"}
                ):
                    raise _refuse("resolution_not_applicable")
                row = self._bookings.admin_complete_in_session(
                    session, booking_id=located.booking_id, admin_user_id=admin_user_id
                )
        except BookingRefused as exc:
            raise _refuse("resolution_not_applicable") from exc
        return row, None

    @staticmethod
    def _hide(session: Session, located: _Located, admin_user_id: uuid.UUID) -> None:
        """``content_hidden``: a note hidden, a review removed (rating recomputed), a reply down.

        The caller holds the tutor row ``FOR UPDATE``, which the review helper takes again
        (SPEC §i.6: never after a share lock).
        """
        if located.target_type is ReportTargetType.booking_note:
            BookingService.hide_note_in_session(session, located.target_id, admin_user_id)
        elif located.target_type is ReportTargetType.review:
            TutorReviewRepository.remove_review_in_session(
                session, located.target_id, admin_user_id
            )
        elif located.target_type is ReportTargetType.review_reply:
            TutorReviewRepository.hide_reply_in_session(session, located.target_id, admin_user_id)
        else:
            raise _refuse("resolution_not_applicable")

    @staticmethod
    def _release_freeze(session: Session, booking_id: uuid.UUID, report_id: uuid.UUID) -> None:
        """Lift the freeze unless another open safety report on the booking or a note holds it."""
        held = session.execute(
            sa.text(
                f"SELECT EXISTS (SELECT 1 FROM tutoring_reports r WHERE r.state = 'open' "  # noqa: S608 - constant
                f"AND {_SAFETY} AND r.id <> :r AND (r.booking_id = :b OR r.note_id IN "
                "(SELECT n.id FROM tutor_booking_notes n WHERE n.booking_id = :b)))"
            ),
            {"r": report_id, "b": booking_id},
        ).scalar_one()
        if not held:
            BookingService.unfreeze_notes_in_session(session, booking_id)


def _db_now(session: Session) -> datetime:
    return _instant(session.execute(sa.text("SELECT now()")).scalar_one())


__all__ = [
    "MAX_DETAILS_LENGTH",
    "MAX_PAGE_SIZE",
    "MAX_RESOLUTION_NOTE_LENGTH",
    "REPORT_QUOTA",
    "REPORT_SUSPENSION_NOTE",
    "SNAPSHOT_KEYS",
    "STUDENT_AUTHOR_LABEL",
    "AdminNote",
    "BookingSummary",
    "FiledReport",
    "ReportDetail",
    "ReportItem",
    "ReportRefused",
    "Reporter",
    "ReporterParty",
    "ReportsKey",
    "ReportsPage",
    "ResolveOutcome",
    "TutoringReportsRepository",
    "allowed_snapshot",
    "parse_reports_cursor",
    "reports_cursor",
]
