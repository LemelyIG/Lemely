"""Viewer-dependent booking and note DTOs, and a booking write's after-commit notices.

SPEC ``docs/tutoring/SPEC.md`` §b.3 "Viewer-dependent serialisation" and §b.4. One builder per
DTO, taking the viewer; every route that returns a ``BookingDTO``, ``NoteDTO``, ``SlotsDTO`` or
their pages builds it here, so the disclosure rules live in one place:

* ``meetingLink`` and ``locationDetail`` once the booking was accepted (stored ``accepted``,
  ``completed`` or ``no_show``) and only to the booking's student, its tutor and a linked parent
  (O16). A parent viewer is a linked parent by construction: every PA route checks the link on
  each call (O7) before it reads the booking;
* ``review`` and ``reviewOpensAt`` to the student only (SC-12); ``studentShared`` to the tutor
  only (the grant predicate, no audit row, F13);
* a cancellation by ``system`` or ``platform_admin`` reads "Cancelled" to the tutor (SC-11): its
  fixed reason never tells a tutor that a block or a sanction was the cause;
* a tutor never sees the party ``parent``: ``requestedBy``, ``cancelledBy`` and ``completedBy``
  read ``student`` instead (SC-9, SPEC §i.4), so no tutor-facing DTO reveals a parent link;
* a tutor never sees the party ``system`` either: only a block's sweep cancels as ``system``, so
  it would tell the tutor that the child blocked them. It reads ``platform_admin``, which with
  the "Cancelled" reason makes a block's cancellation identical to a suspension's (SC-11);
* ``allowedActions`` is ``core.booking.allowed_actions`` plus ``post_note``, which the core never
  returns: the builder adds it for a student or tutor viewer from ``can_post_note`` over the
  effective state at the same ``now`` (SPEC §i.4). A suspended or closed tutor gets no write
  action at all (CB-7), and ``accept`` is withheld unless the listing may take students
  (``listed`` or ``pending_review``, SPEC §a.3);
* a student's name is ``core.tutor_directory.student_label`` for every viewer (F12).

The notices (D5.9 §1) are built from the ``notice`` facts a write returns, after the commit:
``send_after_commit(booking_notices_for(row), service=..., transport=...)``.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from lemely.core.booking import (
    BookingFacts,
    allowed_actions,
    can_post_note,
    effective_state,
    is_late_cancel,
    review_open_at,
)
from lemely.core.tutor_directory import public_name, student_label, zone_label
from lemely.core.tutor_ratings import REVIEW_MIN_ACCOUNT_AGE, review_edit_deadline
from lemely.io.tutoring_areas import load_tutoring_areas
from lemely.web.schemas_tutoring import (
    BookingDTO,
    BookingsPageDTO,
    NoteDTO,
    NotesPageDTO,
    SlotDTO,
    SlotsDTO,
)
from lemely.web.tutoring_http import area_ref_dto, iso_instant, tutor_card_dto
from lemely.web.tutoring_notify import booking_notices, note_notices

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from lemely.core.booking import EffectiveState, Party
    from lemely.db.booking_repo import Actor, BookingRow, NoteRow, NotesPage, SlotsView
    from lemely.io.tutoring_areas import AreaCatalogue
    from lemely.web.tutoring_notify import InboxNotice

#: ``ViewerActionLit`` order (SPEC §b.3), so a list is stable whatever the set's order.
ACTION_ORDER: Final = (
    "accept",
    "decline",
    "cancel",
    "cancel_with_reason",
    "complete",
    "no_show",
    "review",
    "post_note",
)
#: What the tutor viewer reads for a system or platform cancellation reason (SC-11).
TUTOR_SYSTEM_CANCEL_TEXT: Final = "Cancelled"

_TUTOR_WRITE_ACTIONS: Final = frozenset(
    {"accept", "decline", "cancel", "cancel_with_reason", "complete", "no_show", "post_note"}
)
_LINK_STATES: Final = frozenset({"accepted", "completed", "no_show"})
_VIEWERS: Final = frozenset({"student", "tutor", "parent"})
_SYSTEM_PARTIES: Final = frozenset({"system", "platform_admin"})
#: The parties a tutor viewer reads in place of the stored ones (SC-9, SC-11).
_TUTOR_PARTY: Final[Mapping[str, str]] = MappingProxyType(
    {"parent": "student", "system": "platform_admin"}
)
_ACCEPT_LISTINGS: Final = frozenset({"listed", "pending_review"})
_INACTIVE_LISTINGS: Final = frozenset({"suspended", "closed"})


def _party_for(viewer: Actor, party: Party | str | None) -> str | None:
    """A booking party as ``viewer`` may read it.

    A tutor never sees ``parent`` (SC-9) nor ``system`` (SC-11: only a block cancels as
    ``system``); they read ``student`` and ``platform_admin``.
    """
    if viewer.party == "tutor":
        return _TUTOR_PARTY.get(party, party) if party is not None else None
    return party


def _actions(
    view: BookingRow, viewer: Actor, *, now: datetime, effective: EffectiveState
) -> list[str]:
    if viewer.party not in _VIEWERS:
        return []
    facts = BookingFacts(
        state=view.state,
        starts_at=view.starts_at,
        ends_at=view.ends_at,
        viewer=viewer.party,
        viewer_is_requester=(
            viewer.party == "parent"
            and view.requested_by_party == "parent"
            and view.requested_by_user_id == viewer.user_id
        ),
        tutor_outcome_recorded=view.state == "no_show" or view.completed_by_party == "tutor",
    )
    actions = set(
        allowed_actions(
            facts,
            now=now,
            has_review=view.has_review,
            blocked=view.blocked,
            review_account_ok=now - view.student_created_at >= REVIEW_MIN_ACCOUNT_AGE,
        )
    )
    tutor_inactive = view.tutor_listing_state in _INACTIVE_LISTINGS
    if viewer.party == "tutor" and view.tutor_listing_state not in _ACCEPT_LISTINGS:
        actions.discard("accept")
    if viewer.party in ("student", "tutor") and can_post_note(
        effective,
        ends_at=view.ends_at,
        now=now,
        blocked=view.blocked,
        tutor_inactive=tutor_inactive,
        frozen=view.notes_frozen,
    ):
        actions.add("post_note")
    if viewer.party == "tutor" and tutor_inactive:
        actions -= _TUTOR_WRITE_ACTIONS
    return [action for action in ACTION_ORDER if action in actions]


def build_booking_dto(
    view: BookingRow,
    *,
    viewer: Actor,
    now: datetime,
    student_shared: bool | None,
    areas: AreaCatalogue | None = None,
) -> BookingDTO:
    """``BookingDTO`` of ``view`` for ``viewer`` at ``now`` (the app clock: display only).

    ``student_shared`` is T14's grant predicate for the tutor viewer and is dropped for every
    other viewer.
    """
    catalogue = areas if areas is not None else load_tutoring_areas()
    as_student = viewer.party == "student"
    as_tutor = viewer.party == "tutor"
    effective = effective_state(view.state, starts_at=view.starts_at, ends_at=view.ends_at, now=now)
    shows_place = viewer.party in _VIEWERS and view.state in _LINK_STATES
    cancel_reason = view.cancel_reason
    if as_tutor and view.cancelled_by_party in _SYSTEM_PARTIES:
        cancel_reason = TUTOR_SYSTEM_CANCEL_TEXT
    cancelled_late = (
        view.state == "cancelled"
        and view.cancelled_by_party is not None
        and view.cancelled_at is not None
        and is_late_cancel(
            cancelled_by=view.cancelled_by_party,
            cancelled_at=view.cancelled_at,
            starts_at=view.starts_at,
        )
    )
    review: dict[str, object] | None = None
    if as_student and view.review is not None:
        review = {
            "reviewId": str(view.review.review_id),
            "stars": view.review.stars,
            "textState": view.review.text_state,
            "editableUntil": iso_instant(review_edit_deadline(view.review.created_at)),
        }
    reviews_open = as_student and view.state == "completed"
    return BookingDTO.model_validate(
        {
            "bookingId": str(view.id),
            "tutor": tutor_card_dto(view.tutor, catalogue),
            "student": {
                "studentId": str(view.student_id),
                "displayName": student_label(view.student_display_name, view.student_id),
            },
            "requestedBy": _party_for(viewer, view.requested_by_party),
            "subject": {"code": view.subject_code, "name": view.subject_name},
            "mode": view.mode,
            "startsAt": iso_instant(view.starts_at),
            "endsAt": iso_instant(view.ends_at),
            "effectiveState": effective,
            "area": area_ref_dto(view.tutor.area_code, catalogue),
            "meetingLink": view.meeting_link if shows_place else None,
            "locationDetail": view.location_detail if shows_place else None,
            "otherModeNote": view.other_mode_note,
            "declineReason": view.decline_reason,
            "cancelReason": cancel_reason,
            "cancelledBy": _party_for(viewer, view.cancelled_by_party),
            "cancelledLate": cancelled_late,
            "completedBy": _party_for(viewer, view.completed_by_party),
            "notesFrozen": view.notes_frozen,
            "allowedActions": _actions(view, viewer, now=now, effective=effective),
            "review": review,
            "reviewOpensAt": iso_instant(review_open_at(view.ends_at)) if reviews_open else None,
            "studentShared": student_shared if as_tutor else None,
            "createdAt": iso_instant(view.created_at),
        }
    )


def build_bookings_page_dto(
    rows: Sequence[BookingRow],
    *,
    viewer: Actor,
    now: datetime,
    next_cursor: str | None,
    shared_student_ids: Collection[UUID] | None = None,
    areas: AreaCatalogue | None = None,
) -> BookingsPageDTO:
    """S1, T9, PA1: one page; ``shared_student_ids`` is T14's ``student_shared`` set (tutor)."""
    catalogue = areas if areas is not None else load_tutoring_areas()
    shared = shared_student_ids if shared_student_ids is not None else frozenset()
    return BookingsPageDTO(
        items=[
            build_booking_dto(
                row,
                viewer=viewer,
                now=now,
                student_shared=row.student_id in shared if viewer.party == "tutor" else None,
                areas=catalogue,
            )
            for row in rows
        ],
        nextCursor=next_cursor,
    )


def build_note_dto(note: NoteRow) -> NoteDTO:
    """A note for a participant or linked parent: a hidden note keeps its place, never its body."""
    return NoteDTO(
        noteId=str(note.id),
        authorParty=note.author_party,
        authorName=note.author_name,
        body=None if note.hidden else note.body,
        hidden=note.hidden,
        createdAt=iso_instant(note.created_at),
    )


def build_notes_page_dto(page: NotesPage, *, next_cursor: str | None) -> NotesPageDTO:
    """S4, T16, PA3: one page of the thread, oldest first."""
    return NotesPageDTO(
        items=[build_note_dto(note) for note in page.items],
        nextCursor=next_cursor,
        canPost=page.can_post,
    )


def build_slots_dto(view: SlotsView) -> SlotsDTO:
    """SP5: instants in UTC with their offset, the zone named for display ("Cairo time")."""
    return SlotsDTO(
        tutorId=str(view.tutor_id),
        zone=view.zone,
        zoneLabel=zone_label(view.zone),
        durationMinutes=view.duration_minutes,
        windowStart=iso_instant(view.window_start),
        windowEnd=iso_instant(view.window_end),
        slots=[
            SlotDTO(startsAt=iso_instant(start), endsAt=iso_instant(end))
            for start, end in view.slots
        ],
    )


def booking_notices_for(row: BookingRow) -> list[InboxNotice]:
    """The inbox notices of a booking write, to send after its commit; none for a repeat."""
    notice = row.notice
    if notice is None:
        return []
    return booking_notices(
        event=notice.event,
        booking_id=row.id,
        tutor_user_id=row.tutor_user_id,
        tutor_name=public_name(row.tutor.public_first_name, row.tutor.public_last_initial),
        student_user_id=row.student_id,
        student_label=student_label(row.student_display_name, row.student_id),
        linked_parent_ids=notice.linked_parent_ids,
        actor_user_id=notice.actor_user_id,
        late_tutor_cancel=notice.late_tutor_cancel,
    )


def note_notices_for(note: NoteRow) -> list[InboxNotice]:
    """The inbox notices of a new note, to send after its commit. The text never travels."""
    notice = note.notice
    if notice is None:
        return []
    return note_notices(
        note_id=note.id,
        booking_id=note.booking_id,
        author=note.author_party,
        tutor_user_id=notice.tutor_user_id,
        tutor_name=notice.tutor_name,
        student_user_id=notice.student_id,
        student_label=notice.student_label,
        linked_parent_ids=notice.linked_parent_ids,
        posted_at=note.created_at,
        tutor_zone=notice.tutor_zone,
    )


__all__ = [
    "ACTION_ORDER",
    "TUTOR_SYSTEM_CANCEL_TEXT",
    "booking_notices_for",
    "build_booking_dto",
    "build_bookings_page_dto",
    "build_note_dto",
    "build_notes_page_dto",
    "build_slots_dto",
    "note_notices_for",
]
