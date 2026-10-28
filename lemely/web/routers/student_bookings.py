"""S1-S5, S14, S15: a student's own sessions, their notes and the safety notice (SPEC §b.2).

``STUDENT`` only, every route on the caller's own bookings: the service scopes each read and
write to ``booking.student_id = auth.user_id`` (O5), so anyone else's booking is the same 404 as
an unknown id. Built with :class:`~lemely.web.tutoring_http.TutoringRoute` (``private,
no-store`` on every status).

* **S1** pages the caller's bookings, ``when=upcoming`` (live, ending after the split, earliest
  first) or ``past`` (the rest, latest first). The split is fixed by the first page and carried
  in the cursor, whose tag names this list and its ``when`` (O21). Two statements whatever the
  page size (SPEC §e.3).
* **S2** one booking; **S3** cancels it: a request until its start, an accepted session only
  until 24 hours before (row 18: 409 ``cancel_window_closed`` after that; only the tutor may
  cancel inside the window). A repeat is a 200 that tells nobody.
* **S4** the thread, oldest first, with ``canPost``; **S5** a note by the booking's student
  while ``core.booking.can_post_note`` holds and once the safety notice is read (O9, O26).
* **S14** the 48-hour claim: ``completed`` once the session has been awaiting an outcome for 48
  hours with none from the tutor (SC-17, O23).
* **S15** records that the student read the safety notice; the first instant is kept. It uses
  S12/S13's provider and DTO (``student_tutoring_settings``, T20), so one dependency override
  serves all three routes.

Every write sends its inbox notices after the service's commit (D5.9 §1): the tutor and the
linked parents, never the student who acted.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from lemely.db.booking_repo import (
    MAX_PAGE_SIZE,
    Actor,
    BookingRefused,
    BookingService,
    When,
)
from lemely.db.models.enums import Role
from lemely.db.notification_repo import (
    NotificationService,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.tutoring_preferences_repo import (
    TutoringPreferencesRepository,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.booking_view import (
    build_bookings_page_dto,
    build_note_dto,
    build_notes_page_dto,
    note_notices_for,
)
from lemely.web.deps import (
    AuthContext,
    get_notification_service,
    get_push_transport,
    require_role,
)
from lemely.web.deps_tutoring import get_tutoring_areas
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.routers.student_tutoring_settings import (
    get_tutoring_preferences_repo,
    tutoring_settings_dto,
)
from lemely.web.routers.tutoring_booking import (
    DEFAULT_PAGE_SIZE,
    apply_transition,
    booking_error,
    booking_not_found,
    booking_response,
    bookings_endpoint,
    decode_bookings_cursor,
    decode_notes_cursor,
    display_now,
    get_booking_service,
    next_bookings_cursor,
    next_notes_cursor,
)
from lemely.web.schemas_tutoring import (
    BookingDTO,
    BookingReasonDTO,
    BookingsPageDTO,
    NoteCreateDTO,
    NoteDTO,
    NotesPageDTO,
    TutoringSettingsDTO,
)
from lemely.web.tutoring_http import TutoringRoute
from lemely.web.tutoring_notify import send_after_commit

#: The S1 cursor tag (with ``when`` appended) and the S4 one; PA1, PA3, T9 and T16 have their own.
LIST_ENDPOINT: Final = "student_bookings"
NOTES_ENDPOINT: Final = "student_booking_notes"

require_student: Final = require_role(Role.student)

router = APIRouter(prefix="/api/student", tags=["tutoring"], route_class=TutoringRoute)


def _student(auth: AuthContext) -> Actor:
    return Actor(user_id=uuid.UUID(auth.user_id), party="student")


# ---------------------------------------------------------------------------
# S1, S2
# ---------------------------------------------------------------------------


@router.get("/bookings", response_model=BookingsPageDTO)
def list_bookings(
    auth: Annotated[AuthContext, Depends(require_student)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    when: Annotated[When, Query()],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> BookingsPageDTO:
    """S1: the caller's upcoming or past sessions."""
    viewer = _student(auth)
    endpoint = bookings_endpoint(LIST_ENDPOINT, when)
    after = decode_bookings_cursor(cursor, endpoint)
    page = service.list_for_student(viewer.user_id, when=when, after=after, limit=limit)
    return build_bookings_page_dto(
        page.items,
        viewer=viewer,
        now=display_now(),
        next_cursor=next_bookings_cursor(page.next_key, endpoint),
        areas=areas,
    )


@router.get("/bookings/{booking_id}", response_model=BookingDTO)
def get_booking(
    booking_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> BookingDTO:
    """S2: one of the caller's sessions."""
    viewer = _student(auth)
    row = service.get_for_viewer(booking_id, viewer)
    if row is None:
        raise booking_not_found()
    return booking_response(row, viewer, areas)


# ---------------------------------------------------------------------------
# S3, S14
# ---------------------------------------------------------------------------


@router.post("/bookings/{booking_id}/cancel", response_model=BookingDTO)
def cancel_booking(
    booking_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
    body: BookingReasonDTO | None = None,
) -> BookingDTO:
    """S3: cancel a request, or an accepted session more than 24 hours ahead."""
    viewer = _student(auth)
    row = apply_transition(
        service,
        booking_id=booking_id,
        actor=viewer,
        action="cancel",
        reason=body.reason if body is not None else None,
        notifications=notifications,
        transport=transport,
    )
    return booking_response(row, viewer, areas)


@router.post("/bookings/{booking_id}/complete", response_model=BookingDTO)
def complete_booking(
    booking_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> BookingDTO:
    """S14: mark a session completed 48 hours after it ended, if the tutor has not."""
    viewer = _student(auth)
    row = apply_transition(
        service,
        booking_id=booking_id,
        actor=viewer,
        action="complete",
        reason=None,
        notifications=notifications,
        transport=transport,
    )
    return booking_response(row, viewer, areas)


# ---------------------------------------------------------------------------
# S4, S5
# ---------------------------------------------------------------------------


@router.get("/bookings/{booking_id}/notes", response_model=NotesPageDTO)
def list_notes(
    booking_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> NotesPageDTO:
    """S4: the session's notes, oldest first."""
    after = decode_notes_cursor(cursor, NOTES_ENDPOINT)
    page = service.list_notes(
        booking_id=booking_id, viewer=_student(auth), after=after, limit=limit
    )
    if page is None:
        raise booking_not_found()
    return build_notes_page_dto(page, next_cursor=next_notes_cursor(page.next_key, NOTES_ENDPOINT))


@router.post("/bookings/{booking_id}/notes", status_code=201, response_model=NoteDTO)
def post_note(
    booking_id: uuid.UUID,
    body: NoteCreateDTO,
    auth: Annotated[AuthContext, Depends(require_student)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> NoteDTO:
    """S5: a note on one of the caller's sessions; the tutor is told, without the text."""
    try:
        note = service.post_note(booking_id=booking_id, actor=_student(auth), body=body.body)
    except BookingRefused as exc:
        raise booking_error(exc) from exc
    send_after_commit(note_notices_for(note), service=notifications, transport=transport)
    return build_note_dto(note)


# ---------------------------------------------------------------------------
# S15
# ---------------------------------------------------------------------------


@router.post("/tutoring-safety-notice", response_model=TutoringSettingsDTO)
def acknowledge_safety_notice(
    auth: Annotated[AuthContext, Depends(require_student)],
    preferences: Annotated[TutoringPreferencesRepository, Depends(get_tutoring_preferences_repo)],
) -> TutoringSettingsDTO:
    """S15: the student read the safety notice; a repeat keeps the first instant."""
    return tutoring_settings_dto(preferences.acknowledge_safety_notice(uuid.UUID(auth.user_id)))


__all__ = [
    "LIST_ENDPOINT",
    "NOTES_ENDPOINT",
    "require_student",
    "router",
]
