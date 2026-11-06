"""PA1-PA5: a parent's view of a linked child's sessions (SPEC §b.2 "Parent", §c.3 O7, O8).

``PARENT`` only; the existing ``/api/parent/*`` routes are untouched. Built with
:class:`~lemely.web.tutoring_http.TutoringRoute` (``private, no-store`` on every status).

* **The link, on every call (O7).** Each route first resolves ``child_id`` from the path through
  :func:`child_viewer`, which asks ``ParentLinkService.get_child`` whether the child is linked
  to the caller *now*: 403 ``not_linked`` for a child who exists but is not linked, 404 for no
  such user (the existing parent routes' split, SPEC §0). Nothing is cached, so a parent the
  child unlinked loses every route on the next call. Only then is the booking read, and only
  if it is that child's (``booking.student_id = child_id``, else the one booking 404).
* **Read-only, except the parent's own requests.** PA1-PA3 read (no review fields, SC-12;
  ``canPost`` is always false, O9: parents never write notes). PA4 cancels and PA5 completes
  only a booking this parent requested (O8: 403 ``not_requester``); the service takes the link
  ``FOR SHARE`` under its lock order and refuses an accepted session inside 24 hours of its
  start (row 18: 409 ``cancel_window_closed``).
* **Notices after the commit** (D5.9 §1): the tutor, the child and the other linked parents;
  never the parent who acted.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from lemely.db.booking_repo import (
    MAX_PAGE_SIZE,
    Actor,
    BookingService,
    When,
)
from lemely.db.class_repo import ClassService  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.db.models.enums import Role
from lemely.db.notification_repo import (
    NotificationService,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.parent_repo import ParentLinkService  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.booking_view import build_bookings_page_dto, build_notes_page_dto
from lemely.web.deps import (
    AuthContext,
    get_class_service,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
    require_role,
)
from lemely.web.deps_tutoring import get_tutoring_areas
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.routers.tutoring_booking import (
    DEFAULT_PAGE_SIZE,
    apply_transition,
    booking_not_found,
    booking_response,
    bookings_endpoint,
    decode_bookings_cursor,
    decode_notes_cursor,
    display_now,
    get_booking_service,
    next_bookings_cursor,
    next_notes_cursor,
    require_linked_child,
)
from lemely.web.schemas_tutoring import BookingDTO, BookingReasonDTO, BookingsPageDTO, NotesPageDTO
from lemely.web.tutoring_http import TutoringRoute

#: The PA1 cursor tag (with ``when`` appended) and the PA3 one, distinct from S1's and S4's.
LIST_ENDPOINT: Final = "parent_child_bookings"
NOTES_ENDPOINT: Final = "parent_child_booking_notes"

require_parent: Final = require_role(Role.parent)

router = APIRouter(prefix="/api/parent", tags=["tutoring"], route_class=TutoringRoute)


def child_viewer(
    child_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_parent)],
    links: Annotated[ParentLinkService, Depends(get_parent_link_service)],
    classes: Annotated[ClassService, Depends(get_class_service)],
) -> Actor:
    """The caller as the parent of ``child_id``, after checking the link on this call (O7)."""
    parent_id = uuid.UUID(auth.user_id)
    require_linked_child(links, classes, parent_id=parent_id, child_id=child_id)
    return Actor(user_id=parent_id, party="parent", child_id=child_id)


# ---------------------------------------------------------------------------
# PA1, PA2, PA3
# ---------------------------------------------------------------------------


@router.get("/children/{child_id}/bookings", response_model=BookingsPageDTO)
def list_child_bookings(
    child_id: uuid.UUID,
    viewer: Annotated[Actor, Depends(child_viewer)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    when: Annotated[When, Query()],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> BookingsPageDTO:
    """PA1: the child's upcoming or past sessions."""
    endpoint = bookings_endpoint(LIST_ENDPOINT, when)
    after = decode_bookings_cursor(cursor, endpoint)
    page = service.list_for_child(child_id, when=when, after=after, limit=limit)
    return build_bookings_page_dto(
        page.items,
        viewer=viewer,
        now=display_now(),
        next_cursor=next_bookings_cursor(page.next_key, endpoint),
        areas=areas,
    )


@router.get("/children/{child_id}/bookings/{booking_id}", response_model=BookingDTO)
def get_child_booking(
    booking_id: uuid.UUID,
    viewer: Annotated[Actor, Depends(child_viewer)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> BookingDTO:
    """PA2: one of the child's sessions."""
    row = service.get_for_viewer(booking_id, viewer)
    if row is None:
        raise booking_not_found()
    return booking_response(row, viewer, areas)


@router.get("/children/{child_id}/bookings/{booking_id}/notes", response_model=NotesPageDTO)
def list_child_booking_notes(
    booking_id: uuid.UUID,
    viewer: Annotated[Actor, Depends(child_viewer)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> NotesPageDTO:
    """PA3: the session's notes, oldest first; a parent reads and never posts."""
    after = decode_notes_cursor(cursor, NOTES_ENDPOINT)
    page = service.list_notes(booking_id=booking_id, viewer=viewer, after=after, limit=limit)
    if page is None:
        raise booking_not_found()
    return build_notes_page_dto(page, next_cursor=next_notes_cursor(page.next_key, NOTES_ENDPOINT))


# ---------------------------------------------------------------------------
# PA4, PA5
# ---------------------------------------------------------------------------


@router.post("/children/{child_id}/bookings/{booking_id}/cancel", response_model=BookingDTO)
def cancel_child_booking(
    booking_id: uuid.UUID,
    viewer: Annotated[Actor, Depends(child_viewer)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
    body: BookingReasonDTO | None = None,
) -> BookingDTO:
    """PA4: cancel a session this parent requested, more than 24 hours ahead if accepted."""
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


@router.post("/children/{child_id}/bookings/{booking_id}/complete", response_model=BookingDTO)
def complete_child_booking(
    booking_id: uuid.UUID,
    viewer: Annotated[Actor, Depends(child_viewer)],
    service: Annotated[BookingService, Depends(get_booking_service)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> BookingDTO:
    """PA5: mark a session this parent requested completed, 48 hours after it ended."""
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


__all__ = [
    "LIST_ENDPOINT",
    "NOTES_ENDPOINT",
    "child_viewer",
    "require_parent",
    "router",
]
