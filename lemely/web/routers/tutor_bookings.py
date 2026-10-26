"""T9-T17: a tutor's bookings and their notes (SPEC §b.2 "Tutor", §a.3, §a.4b, §b.4).

``TEACHER`` + the caller's own tutor profile, resolved from ``auth.user_id``
(``deps_tutoring.require_tutor_profile``, O1): a teacher without one gets 404
``no_tutor_profile`` on every route here, and no route takes a tutor id.

* **Own bookings only (O4).** Every read and write is scoped by the booking service to the
  caller's profile; another tutor's booking answers the same 404 as an unknown id.
* **Reads.** T9 lists the caller's bookings, ``when=upcoming|past`` (required) and optionally
  one *effective* state (SPEC §a.3, filtered by its shared SQL predicate, never the stored
  column). T10 returns one booking. T16 pages its notes, oldest first. Each list's cursor is
  tagged with that list (O21): T9's tag carries ``when`` and ``state``, because a keyset
  position means something else under another order or filter.
* **Writes (T11-T15, T17)** use :func:`~lemely.web.deps_tutoring.require_writable_tutor_profile`:
  a suspended or closed profile is refused with 409 ``tutor_suspended`` / ``tutor_closed``
  before any booking is read (CB-7); the service checks it again inside its transaction. Every
  rule of the state machine (accept guards, the meeting-link allowlist, the place, row 18's late
  cancel reason, ``not_ended``, the notes table) is the booking service's, refused with
  :class:`~lemely.db.booking_repo.BookingRefused` and sent as ``tutoring_error(status, code,
  message)``. Unlike the family routes, a tutor accepting on an unlisted profile reads
  ``tutor_not_listed`` (in the tutor's own words): the tutor is told about their own profile,
  never about a hidden tutor. A tutor is never told *who* ended a pair's access: when the
  student blocked, the tutor learns nothing about the block. T21's sweep cancels the pair's
  open requests in the block's own transaction, so a blocked pair's accept is normally
  unreachable; the service's ``access_ended`` refusal is the backstop for a request that
  survives (it names no one).
* **After the commit (D5.9 §1).** The email rows were queued inside the change's transaction;
  the inbox notices are sent here, after it, with ``send_after_commit``. A failing inbox write
  is logged and never turns the committed change into an error.
* **``studentShared`` (F13)** is the grant predicate
  (``TutorGrantRepository.student_shared``, one statement per page). It is *not* T20's gate and
  writes no ``tutor_access_audit`` row: knowing a grant exists is not reading the student's data.

The ``BookingDTO`` serialisation for the tutor viewer (no ``parent`` or ``system`` party, a
system reason read as "Cancelled", no review, meeting details only after accept) is
:mod:`lemely.web.booking_view`'s. Built with :class:`~lemely.web.tutoring_http.TutoringRoute`
(``private, no-store`` on every status).
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI reads the path parameter type at runtime
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.core.keyset import CursorError
from lemely.db.booking_repo import (
    MAX_PAGE_SIZE,
    AcceptDetails,
    Actor,
    BookingRefused,
    BookingService,
    BookingsKey,
    NotesKey,
    When,
    bookings_cursor,
    notes_cursor,
    parse_bookings_cursor,
    parse_notes_cursor,
)
from lemely.db.notification_repo import (
    NotificationService,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.session import get_sessionmaker
from lemely.db.tutor_grant_repo import (
    TutorGrantRepository,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.tutor_profile_repo import TutorProfileRow  # noqa: TC001 - FastAPI resolves it
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.booking_view import (
    booking_notices_for,
    build_booking_dto,
    build_bookings_page_dto,
    build_note_dto,
    build_notes_page_dto,
    note_notices_for,
)
from lemely.web.deps import get_notification_service, get_push_transport, get_settings
from lemely.web.deps_tutoring import (
    get_tutoring_areas,
    require_tutor_profile,
    require_writable_tutor_profile,
)
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.routers.student_tutor_access import DEFAULT_PAGE_SIZE, get_tutor_grant_repo
from lemely.web.schemas_tutoring import (
    BookingAcceptDTO,
    BookingDTO,
    BookingReasonDTO,
    BookingsPageDTO,
    EffectiveStateLit,
    NoteCreateDTO,
    NoteDTO,
    NotesPageDTO,
)
from lemely.web.tutoring_http import TutoringRoute, tutoring_error
from lemely.web.tutoring_notify import send_after_commit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.core.booking import Action
    from lemely.db.booking_repo import BookingRow

#: The T9 cursor tag's stem; the full tag adds ``when`` and the state filter (O21).
BOOKINGS_ENDPOINT: Final = "tutor_bookings"
#: The T16 cursor tag (O21): S4's and PA3's cursors are refused here and vice versa.
NOTES_ENDPOINT: Final = "tutor_booking_notes"

router = APIRouter(prefix="/api/tutor", tags=["tutoring"], route_class=TutoringRoute)


@lru_cache(maxsize=1)
def get_booking_service() -> BookingService:
    """The process-wide :class:`BookingService` the tutor's booking routes use."""
    return BookingService(get_sessionmaker(get_settings()))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _viewer(profile: TutorProfileRow) -> Actor:
    """The caller as the booking service scopes and serialises them: the profile's own user."""
    return Actor(user_id=profile.user_id, party="tutor")


def _now() -> datetime:
    return datetime.now(UTC)


def _refused(exc: BookingRefused) -> HTTPException:
    return tutoring_error(exc.status, exc.code, exc.message)


def _booking_not_found() -> HTTPException:
    """The one 404 for a booking the caller may not see: the service's own ``not_found`` body."""
    return tutoring_error(404, "not_found", "Booking not found.")


def _invalid_cursor() -> HTTPException:
    return tutoring_error(422, "invalid_cursor", "This page link is not valid.")


def bookings_endpoint(when: When, state: EffectiveStateLit | None) -> str:
    """T9's cursor tag for one list: its order (``when``) and its filter (``state``)."""
    return f"{BOOKINGS_ENDPOINT}:{when}:{state or 'any'}"


def _decode_bookings_cursor(cursor: str | None, endpoint: str) -> BookingsKey | None:
    if cursor is None:
        return None
    try:
        return parse_bookings_cursor(cursor, endpoint)
    except CursorError as exc:
        raise _invalid_cursor() from exc


def _decode_notes_cursor(cursor: str | None) -> NotesKey | None:
    if cursor is None:
        return None
    try:
        return parse_notes_cursor(cursor, NOTES_ENDPOINT)
    except CursorError as exc:
        raise _invalid_cursor() from exc


def _shared(
    grants: TutorGrantRepository, profile: TutorProfileRow, rows: Sequence[BookingRow]
) -> set[uuid.UUID]:
    """The page's students with a valid grant to the caller: the predicate, no audit row (F13)."""
    return grants.student_shared(profile.id, list(dict.fromkeys(row.student_id for row in rows)))


def _booking_dto(
    row: BookingRow,
    profile: TutorProfileRow,
    grants: TutorGrantRepository,
    areas: AreaCatalogue,
) -> BookingDTO:
    return build_booking_dto(
        row,
        viewer=_viewer(profile),
        now=_now(),
        student_shared=row.student_id in _shared(grants, profile, [row]),
        areas=areas,
    )


def _transition(
    *,
    booking_id: uuid.UUID,
    action: Action,
    profile: TutorProfileRow,
    bookings: BookingService,
    grants: TutorGrantRepository,
    areas: AreaCatalogue,
    service: NotificationService,
    transport: NotificationTransport,
    reason: str | None = None,
    accept: AcceptDetails | None = None,
) -> BookingDTO:
    """T11-T15: apply ``action`` for the caller, tell the others after the commit, answer."""
    try:
        row = bookings.transition(
            booking_id=booking_id,
            actor=_viewer(profile),
            action=action,
            reason=reason,
            accept=accept,
        )
    except BookingRefused as exc:
        raise _refused(exc) from exc
    send_after_commit(booking_notices_for(row), service=service, transport=transport)
    return _booking_dto(row, profile, grants, areas)


# ---------------------------------------------------------------------------
# T9, T10
# ---------------------------------------------------------------------------


@router.get("/bookings", response_model=BookingsPageDTO)
def list_bookings(
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    grants: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    when: Annotated[When, Query()],
    state: Annotated[EffectiveStateLit | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> BookingsPageDTO:
    """T9: the caller's bookings, upcoming (soonest first) or past (latest first)."""
    endpoint = bookings_endpoint(when, state)
    after = _decode_bookings_cursor(cursor, endpoint)
    page = bookings.list_for_tutor(profile.id, when=when, state=state, after=after, limit=limit)
    return build_bookings_page_dto(
        page.items,
        viewer=_viewer(profile),
        now=_now(),
        next_cursor=(
            bookings_cursor(endpoint, page.next_key) if page.next_key is not None else None
        ),
        shared_student_ids=_shared(grants, profile, page.items),
        areas=areas,
    )


@router.get("/bookings/{booking_id}", response_model=BookingDTO)
def get_booking(
    booking_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    grants: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> BookingDTO:
    """T10: one of the caller's bookings, with ``studentShared``."""
    row = bookings.get_for_viewer(booking_id, _viewer(profile))
    if row is None:
        raise _booking_not_found()
    return _booking_dto(row, profile, grants, areas)


# ---------------------------------------------------------------------------
# T11-T15
# ---------------------------------------------------------------------------


@router.post("/bookings/{booking_id}/accept", response_model=BookingDTO)
def accept_booking(
    booking_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    grants: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
    body: BookingAcceptDTO | None = None,
) -> BookingDTO:
    """T11: accept a request; a virtual session needs an allowlisted link, in person a place."""
    details = body or BookingAcceptDTO()
    return _transition(
        booking_id=booking_id,
        action="accept",
        profile=profile,
        bookings=bookings,
        grants=grants,
        areas=areas,
        service=service,
        transport=transport,
        accept=AcceptDetails(
            meeting_link=details.meetingLink, location_detail=details.locationDetail
        ),
    )


@router.post("/bookings/{booking_id}/decline", response_model=BookingDTO)
def decline_booking(
    booking_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    grants: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
    body: BookingReasonDTO | None = None,
) -> BookingDTO:
    """T12: decline a request, optionally with a reason the family reads."""
    return _transition(
        booking_id=booking_id,
        action="decline",
        profile=profile,
        bookings=bookings,
        grants=grants,
        areas=areas,
        service=service,
        transport=transport,
        reason=body.reason if body is not None else None,
    )


@router.post("/bookings/{booking_id}/cancel", response_model=BookingDTO)
def cancel_booking(
    booking_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    grants: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
    body: BookingReasonDTO | None = None,
) -> BookingDTO:
    """T13: cancel an accepted session; inside 24 h of the start only with a reason (row 18)."""
    return _transition(
        booking_id=booking_id,
        action="cancel",
        profile=profile,
        bookings=bookings,
        grants=grants,
        areas=areas,
        service=service,
        transport=transport,
        reason=body.reason if body is not None else None,
    )


@router.post("/bookings/{booking_id}/complete", response_model=BookingDTO)
def complete_booking(
    booking_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    grants: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> BookingDTO:
    """T14: record that the session took place; only once it has ended (SC-17)."""
    return _transition(
        booking_id=booking_id,
        action="complete",
        profile=profile,
        bookings=bookings,
        grants=grants,
        areas=areas,
        service=service,
        transport=transport,
    )


@router.post("/bookings/{booking_id}/no-show", response_model=BookingDTO)
def mark_no_show(
    booking_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    grants: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> BookingDTO:
    """T15: record that the student did not come; only once the session has ended."""
    return _transition(
        booking_id=booking_id,
        action="no_show",
        profile=profile,
        bookings=bookings,
        grants=grants,
        areas=areas,
        service=service,
        transport=transport,
    )


# ---------------------------------------------------------------------------
# T16, T17
# ---------------------------------------------------------------------------


@router.get("/bookings/{booking_id}/notes", response_model=NotesPageDTO)
def list_notes(
    booking_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> NotesPageDTO:
    """T16: the booking's notes, oldest first; ``canPost`` follows the notes table (§a.3)."""
    after = _decode_notes_cursor(cursor)
    page = bookings.list_notes(
        booking_id=booking_id, viewer=_viewer(profile), after=after, limit=limit
    )
    if page is None:
        raise _booking_not_found()
    return build_notes_page_dto(
        page,
        next_cursor=(
            notes_cursor(NOTES_ENDPOINT, page.next_key) if page.next_key is not None else None
        ),
    )


@router.post("/bookings/{booking_id}/notes", status_code=201, response_model=NoteDTO)
def post_note(
    booking_id: uuid.UUID,
    body: NoteCreateDTO,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> NoteDTO:
    """T17: a note from the tutor while the notes table allows it (O9); never a contact detail."""
    try:
        note = bookings.post_note(booking_id=booking_id, actor=_viewer(profile), body=body.body)
    except BookingRefused as exc:
        raise _refused(exc) from exc
    send_after_commit(note_notices_for(note), service=service, transport=transport)
    return build_note_dto(note)


__all__ = [
    "BOOKINGS_ENDPOINT",
    "NOTES_ENDPOINT",
    "bookings_endpoint",
    "get_booking_service",
    "router",
]
