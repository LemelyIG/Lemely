"""Announcement compose/list/delete endpoints (``/api/teacher/announcements/*``).

T-12's backend prerequisite (P3.8 chunk a, D3.14). Gated to the
teacher/school_admin pair — narrower than the usual staff triple
(``teacher.py``/``classes.py``/``review.py``'s ``platform_admin``-inclusive
gate): there is no "platform admin posts an announcement" scenario, and
:class:`~lemely.db.announcement_repo.AnnouncementService` never needs to
handle that role. Row-level ownership (which classes/schools a caller may
target, who authored a given row) is enforced inside the service, which
delegates every tenancy question to
:class:`~lemely.db.class_repo.ClassService` — this router runs no ownership
query of its own.

**This module used to say it delivered nothing to a student. That is no
longer true and the sentence is corrected rather than left standing.** Phase 5
built both halves MISSION §4 assigned it: the student read surface lives on
:mod:`lemely.web.routers.student_announcements` (P5.5 chunk B), and P5.6 chunk
C2b added the notification seam below — ``create`` now fans out one
``announcement`` notification per student in each written row's audience,
after the rows have committed and wrapped so that no delivery failure can
reach the composing teacher.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException

from lemely.db.announcement_repo import (
    AnnouncementError,
    AnnouncementNotFoundError,
    AnnouncementOwnershipError,
    AnnouncementRow,
    AnnouncementService,
    AnnouncementValidationError,
)
from lemely.db.models.enums import NotificationType, Role
from lemely.db.notification_repo import (
    NotificationService,  # noqa: TC001 - FastAPI resolves this at runtime
)
from lemely.web.deps import (
    AuthContext,
    get_announcement_service,
    get_notification_service,
    get_push_transport,
    require_role,
)
from lemely.web.notify import notify_safely

# ``NotificationService`` above and ``NotificationTransport`` here are
# **runtime** imports with a reasoned ``noqa``, not TYPE_CHECKING ones, and
# ruff's TC001 wants the opposite: FastAPI resolves every ``Annotated[...]``
# parameter through pydantic, and with ``from __future__ import annotations``
# a type-checking-only name leaves an unresolvable ForwardRef — the route then
# raises PydanticUserError on its *first request* rather than at import, which
# is a much later and more confusing place to find out (P5.6 chunk C1).
from lemely.web.push import NotificationTransport  # noqa: TC001 - resolved at runtime
from lemely.web.schemas_announcements import (
    AnnouncementCreateRequestDTO,
    AnnouncementCreateResponseDTO,
    AnnouncementDTO,
    AnnouncementListDTO,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

log = structlog.get_logger(__name__)

_STAFF_ROLES = (Role.teacher, Role.school_admin)

router = APIRouter(
    prefix="/api/teacher/announcements",
    dependencies=[Depends(require_role(*_STAFF_ROLES))],
)


# ---------------------------------------------------------------------------
# Error mapping.
# ---------------------------------------------------------------------------


def _raise_for(exc: AnnouncementError) -> NoReturn:
    """Map an :class:`AnnouncementError` subclass to the matching :class:`HTTPException`."""
    if isinstance(exc, AnnouncementNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, AnnouncementOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, AnnouncementValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


def _parse_publish_at(value: str | None) -> datetime | None:
    """Parse an optional ISO 8601 ``publishAt`` string, 422-ing on malformed input."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid publishAt: {value!r}") from exc


# ---------------------------------------------------------------------------
# DTO conversion.
# ---------------------------------------------------------------------------


def _row_to_dto(row: AnnouncementRow) -> AnnouncementDTO:
    return AnnouncementDTO(
        announcementId=str(row.announcement_id),
        authorId=str(row.author_id),
        schoolId=str(row.school_id) if row.school_id else None,
        classId=str(row.class_id) if row.class_id else None,
        title=row.title,
        body=row.body,
        publishAt=row.publish_at.isoformat() if row.publish_at else None,
        createdAt=row.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


@router.post("", response_model=AnnouncementCreateResponseDTO)
def create_announcement(
    body: AnnouncementCreateRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[AnnouncementService, Depends(get_announcement_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    push_transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> AnnouncementCreateResponseDTO:
    """Compose an announcement: one row per selected class, plus a school-wide row.

    ``schoolWide: true`` from a ``teacher`` caller is a 403 (D3.14 §3:
    school-wide is ``school_admin``-only). A malformed (non-UUID) id anywhere
    in ``classIds``/``schoolId``, or a malformed ``publishAt``, is a clean
    422. A class the caller does not own is a 403 and, per
    :meth:`~lemely.db.announcement_repo.AnnouncementService.create`, **nothing
    is written** — a partial fan-out across the classes the caller does own
    cannot silently succeed.
    """
    publish_at = _parse_publish_at(body.publishAt)
    try:
        rows = service.create(
            auth.user_id,
            auth.role,
            title=body.title,
            body=body.body,
            class_ids=body.classIds,
            school_wide=body.schoolWide,
            school_id=body.schoolId,
            publish_at=publish_at,
        )
    except AnnouncementError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _notify_audience(service, notifications, push_transport, rows)
    return AnnouncementCreateResponseDTO(announcements=[_row_to_dto(row) for row in rows])


def _notify_audience(
    service: AnnouncementService,
    notifications: NotificationService,
    transport: NotificationTransport,
    rows: Sequence[AnnouncementRow],
) -> None:
    """Tell each row's audience, after the rows are already written (P5.6 chunk C2b).

    Runs at the router layer after ``service.create`` has committed, exactly
    like ``award_xp_safely`` and the ``grade_ready`` seam: the announcement
    exists and stays existing whatever happens here (D5.9 §1). ``notify_safely``
    already swallows per-recipient failures, but the **audience lookup** is a
    query of our own and sits outside it, so the whole loop is wrapped — a
    teacher must never see a 500 for a post that went out fine.

    D5.9 §6 fixes this seam's idempotency on the pair
    ``(announcement_id, user_id)``, and the **column value is the announcement
    id alone** because migration 0018's unique index is already
    ``(user_id, type, dedupe_key)`` — the recipient half of the pair comes
    from the index, not from the string. Concatenating the user id in as well
    was the first cut here and it is *not* wrong, merely redundant; it was
    removed because the comment justifying it ("otherwise the first student
    notified suppresses everyone else") is false, and an inversion proved it
    false: with the suffix dropped, every enrolled student is still notified.
    A comment the code disproves is worse than no comment.

    Fan-out is sequential and unbatched. A class is tens of students and a
    school is hundreds, not millions; a queue is the right answer at a scale
    this build does not have, and inventing one now would add an unproven
    moving part to a path whose failure is already harmless.
    """
    try:
        for row in rows:
            for recipient in service.student_recipients(row):
                notify_safely(
                    notifications,
                    transport,
                    user_id=recipient,
                    type=NotificationType.announcement,
                    title="New announcement",
                    # The title the teacher wrote is the pointer. The body is
                    # deliberately not forwarded: it can be long, and the
                    # notification's job is to send the student to the post,
                    # not to be the post (D5.9 §2).
                    body=row.title,
                    payload={"announcementId": str(row.announcement_id)},
                    dedupe_key=str(row.announcement_id),
                    seam="announcement",
                )
    except Exception:
        log.exception("announcement_fanout_failed", announcement_count=len(rows))


@router.get("", response_model=AnnouncementListDTO)
def list_announcements(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[AnnouncementService, Depends(get_announcement_service)],
) -> AnnouncementListDTO:
    """List every announcement the caller has authored, newest first."""
    rows = service.list_for_author(auth.user_id)
    return AnnouncementListDTO(announcements=[_row_to_dto(row) for row in rows])


@router.delete("/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[AnnouncementService, Depends(get_announcement_service)],
) -> None:
    """Delete one announcement. Author-scoped.

    Deleting an announcement authored by someone else is a 403, never a
    silent no-op; a non-UUID id is a 422; an unknown id is a 404.
    """
    try:
        service.delete(auth.user_id, announcement_id)
    except AnnouncementError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["router"]
