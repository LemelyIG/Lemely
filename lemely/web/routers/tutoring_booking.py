"""SP5 and SP6: a tutor's bookable slots and a booking request (SPEC §b.2 ``STUDENT_OR_PARENT``).

Both routes are behind a verified email (SC-15) and built with
:class:`~lemely.web.tutoring_http.TutoringRoute`, so every response is ``private, no-store``.

* **SP5** serves ``core.booking.bookable_slots`` for the window ``from`` (a tutor-zone date from
  today) plus ``days`` (1 to 28, default 14, ending no later than today + 28 days), at one of the
  allowed durations, minus the tutor's active bookings (``BookingService.slots``). A student's
  view also hides a tutor in an active block with them; parents hold no blocks (O11).
* **SP6** asks for a session: a student for themselves (``studentId`` absent or their own id, else
  403 ``not_self``), or a parent for a child linked to them now (403 ``not_linked``; 404 for no
  such child; O6). The service re-checks the link under its lock, with every other guard, inside
  the write transaction (SPEC §a.4b). A parent never sends a first note (422
  ``note_not_allowed_for_parent``); the student's first note is written in the request's own
  transaction, never through ``post_note``.
* **Hidden tutors (O11, SPEC §i.7).** An unknown, unlisted, paused, suspended, closed or blocked
  tutor (either block direction) gets SP2's own 404 body (``tutoring_http.tutor_not_found``), so
  nobody learns that a tutor exists but is hidden, or that the tutor blocked them. The service
  still raises ``tutor_not_listed`` and ``blocked``; they are mapped here.
* **Notices (D5.9 §1, SPEC §b.4).** The service queues the emails inside its transaction; after
  it commits, the inbox notices go out through ``send_after_commit``, whose failures are logged
  and never undo the request.

This module also holds what the family booking routers (``student_bookings``,
``parent_bookings``) share: the service provider, the error mapping, the cursor tags (each
list's tag carries its ``when``, so an upcoming cursor never pages the past list, O21), the
transition step and the parent's per-call link check.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.core.keyset import CursorError
from lemely.db.booking_repo import (
    Actor,
    BookingRefused,
    BookingService,
    bookings_cursor,
    notes_cursor,
    parse_bookings_cursor,
    parse_notes_cursor,
)
from lemely.db.class_repo import ClassService  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.db.models.enums import Role
from lemely.db.notification_repo import (
    NotificationService,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.parent_repo import ParentLinkService  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.db.session import get_sessionmaker
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.booking_view import booking_notices_for, build_booking_dto, build_slots_dto
from lemely.web.deps import (
    AuthContext,
    get_class_service,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
    get_settings,
    require_verified_email,
)
from lemely.web.deps_tutoring import get_tutoring_areas, require_student_or_parent
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.schemas_tutoring import BookingCreateDTO, BookingDTO, SlotsDTO
from lemely.web.tutoring_http import TutoringRoute, tutor_not_found, tutoring_error
from lemely.web.tutoring_notify import send_after_commit

if TYPE_CHECKING:
    from lemely.core.booking import Action
    from lemely.db.booking_repo import BookingRow, BookingsKey, NotesKey, When

#: SP5's ``days`` when the caller sends none (SPEC §b.2).
DEFAULT_SLOT_DAYS: Final = 14
#: SPEC §0 "Paging": ``limit`` defaults to 20.
DEFAULT_PAGE_SIZE: Final = 20
#: The service refusals that mean "a tutor this caller may not see" (SPEC §i.7).
_HIDDEN_TUTOR_CODES: Final = frozenset({"tutor_not_listed", "blocked"})

router = APIRouter(prefix="/api", tags=["tutoring"], route_class=TutoringRoute)


@lru_cache(maxsize=1)
def get_booking_service() -> BookingService:
    """The process-wide :class:`BookingService`."""
    return BookingService(get_sessionmaker(get_settings()))


# ---------------------------------------------------------------------------
# Shared by the family booking routers
# ---------------------------------------------------------------------------


def booking_error(exc: BookingRefused) -> HTTPException:
    """A service refusal as the route sends it: its status and ``{"code", "message"}``."""
    return tutoring_error(exc.status, exc.code, exc.message)


def booking_not_found() -> HTTPException:
    """The one 404 for a booking the caller may not see (O5, O7): the service's own body."""
    return booking_error(BookingRefused("not_found", 404))


def hidden_tutor_error(exc: BookingRefused) -> HTTPException:
    """SP5/SP6: a tutor hidden from the caller is SP2's 404; anything else as refused."""
    if exc.code in _HIDDEN_TUTOR_CODES:
        return tutor_not_found()
    return booking_error(exc)


def bookings_endpoint(base: str, when: When) -> str:
    """A booking list's cursor tag: the list and its ``when`` (O21)."""
    return f"{base}:{when}"


def decode_bookings_cursor(cursor: str | None, endpoint: str) -> BookingsKey | None:
    """The page start from a client cursor; 422 ``invalid_cursor`` for anything not minted here."""
    if cursor is None:
        return None
    try:
        return parse_bookings_cursor(cursor, endpoint)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


def next_bookings_cursor(key: BookingsKey | None, endpoint: str) -> str | None:
    return bookings_cursor(endpoint, key) if key is not None else None


def decode_notes_cursor(cursor: str | None, endpoint: str) -> NotesKey | None:
    """The thread position from a client cursor; 422 ``invalid_cursor`` for anything else."""
    if cursor is None:
        return None
    try:
        return parse_notes_cursor(cursor, endpoint)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


def next_notes_cursor(key: NotesKey | None, endpoint: str) -> str | None:
    return notes_cursor(endpoint, key) if key is not None else None


def display_now() -> datetime:
    """The app clock, for display fields only (effective state, allowed actions; SPEC §0)."""
    return datetime.now(UTC)


def booking_response(row: BookingRow, viewer: Actor, areas: AreaCatalogue) -> BookingDTO:
    """``row`` as ``viewer`` may read it, at the app clock (display only)."""
    return build_booking_dto(
        row, viewer=viewer, now=display_now(), student_shared=None, areas=areas
    )


def apply_transition(
    service: BookingService,
    *,
    booking_id: uuid.UUID,
    actor: Actor,
    action: Action,
    reason: str | None,
    notifications: NotificationService,
    transport: NotificationTransport,
) -> BookingRow:
    """S3, S14, PA4, PA5: the service's compare-and-set, then the notices after its commit.

    An idempotent repeat returns the row with no notice, so nobody is told twice.
    """
    try:
        row = service.transition(booking_id=booking_id, actor=actor, action=action, reason=reason)
    except BookingRefused as exc:
        raise booking_error(exc) from exc
    send_after_commit(booking_notices_for(row), service=notifications, transport=transport)
    return row


def require_linked_child(
    links: ParentLinkService,
    classes: ClassService,
    *,
    parent_id: uuid.UUID,
    child_id: uuid.UUID,
) -> None:
    """O7: ``child_id`` is linked to ``parent_id`` at this moment, checked on every call.

    Through ``ParentLinkService.get_child`` (the single ``parent_child_links`` query, F32). A
    child who exists but is not linked is 403 ``not_linked``; no such user is 404, the existing
    parent routes' split (SPEC §0 "Errors").
    """
    if links.get_child(parent_id, child_id) is not None:
        return
    if classes.user_exists(child_id):
        raise booking_error(BookingRefused("not_linked", 403))
    raise tutoring_error(404, "not_found", "Child not found.")


# ---------------------------------------------------------------------------
# SP5
# ---------------------------------------------------------------------------


@router.get("/tutors/{tutor_id}/slots", response_model=SlotsDTO)
def tutor_slots(
    tutor_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student_or_parent)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    start: Annotated[date, Query(alias="from")],
    duration_minutes: Annotated[int, Query(alias="durationMinutes")],
    days: Annotated[int, Query()] = DEFAULT_SLOT_DAYS,
) -> SlotsDTO:
    """SP5: the open slots of a listed, unpaused tutor the caller is not blocked from."""
    viewer = uuid.UUID(auth.user_id)
    try:
        view = service.slots(
            tutor_id,
            start=start,
            days=days,
            duration_minutes=duration_minutes,
            student_id=viewer if auth.role == Role.student.value else None,
        )
    except BookingRefused as exc:
        if exc.code == "not_found":
            raise tutor_not_found() from exc
        raise hidden_tutor_error(exc) from exc
    return build_slots_dto(view)


# ---------------------------------------------------------------------------
# SP6
# ---------------------------------------------------------------------------


def _requester(
    auth: AuthContext,
    student_id_text: str | None,
    links: ParentLinkService,
    classes: ClassService,
) -> tuple[Actor, uuid.UUID | None]:
    """The acting party and the booking's subject as sent (O6).

    A student's ``studentId`` must be their own (the service refuses another with
    ``not_self``; a malformed one can be nobody's own id). A parent's names a child linked to
    them now; without one the service answers 422 ``student_required``.
    """
    caller = uuid.UUID(auth.user_id)
    named: uuid.UUID | None = None
    if student_id_text is not None:
        try:
            named = uuid.UUID(student_id_text)
        except ValueError as exc:
            if auth.role == Role.student.value:
                raise booking_error(BookingRefused("not_self", 403)) from exc
            raise tutoring_error(404, "not_found", "Child not found.") from exc
    if auth.role == Role.student.value:
        return Actor(user_id=caller, party="student"), named
    if named is not None:
        require_linked_child(links, classes, parent_id=caller, child_id=named)
    return Actor(user_id=caller, party="parent", child_id=named), named


@router.post("/bookings", status_code=201, response_model=BookingDTO)
def create_booking(
    body: BookingCreateDTO,
    auth: Annotated[AuthContext, Depends(require_student_or_parent)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    links: Annotated[ParentLinkService, Depends(get_parent_link_service)],
    classes: Annotated[ClassService, Depends(get_class_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> BookingDTO:
    """SP6: request a session for oneself (student) or a linked child (parent)."""
    try:
        tutor_id = uuid.UUID(body.tutorId)
    except ValueError as exc:  # no tutor can have this id: the same answer as an unknown one
        raise tutor_not_found() from exc
    try:
        starts_at = datetime.fromisoformat(body.startsAt)
    except ValueError as exc:
        raise booking_error(BookingRefused("invalid_starts_at", 422)) from exc
    requester, student_id = _requester(auth, body.studentId, links, classes)
    try:
        row = service.create(
            requester=requester,
            tutor_profile_id=tutor_id,
            student_id=student_id,
            subject_code=body.subjectCode,
            mode=body.mode,
            starts_at=starts_at,
            duration_minutes=body.durationMinutes,
            other_mode_note=body.otherModeNote,
            first_note=body.firstNote,
        )
    except BookingRefused as exc:
        raise hidden_tutor_error(exc) from exc
    send_after_commit(booking_notices_for(row), service=notifications, transport=transport)
    return booking_response(row, requester, areas)


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_SLOT_DAYS",
    "apply_transition",
    "booking_error",
    "booking_not_found",
    "booking_response",
    "bookings_endpoint",
    "decode_bookings_cursor",
    "decode_notes_cursor",
    "display_now",
    "get_booking_service",
    "hidden_tutor_error",
    "next_bookings_cursor",
    "next_notes_cursor",
    "require_linked_child",
    "router",
]
