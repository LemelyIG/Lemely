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
C2b added the notification seam — ``create`` fans out one ``announcement``
notification per student in each written row's audience, after the rows have
committed and wrapped so that no delivery failure can reach the composing
teacher. The push-delivery spec (§1) moved that fan-out to
:mod:`lemely.web.scheduled_notifications`, shared with the sweeper: a row
whose ``publish_at`` is still ahead is **not** notified here, and is claimed
by the sweeper at that moment instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn

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
from lemely.db.models.enums import Role
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

# ``NotificationService`` above and ``NotificationTransport`` here are
# **runtime** imports with a reasoned ``noqa``, not TYPE_CHECKING ones, and
# ruff's TC001 wants the opposite: FastAPI resolves every ``Annotated[...]``
# parameter through pydantic, and with ``from __future__ import annotations``
# a type-checking-only name leaves an unresolvable ForwardRef — the route then
# raises PydanticUserError on its *first request* rather than at import, which
# is a much later and more confusing place to find out (P5.6 chunk C1).
from lemely.web.push import NotificationTransport  # noqa: TC001 - resolved at runtime
from lemely.web.scheduled_notifications import deliver_announcements_now
from lemely.web.schemas_announcements import (
    AnnouncementCreateRequestDTO,
    AnnouncementCreateResponseDTO,
    AnnouncementDTO,
    AnnouncementListDTO,
)

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
    deliver_announcements_now(service, notifications, push_transport, rows)
    return AnnouncementCreateResponseDTO(announcements=[_row_to_dto(row) for row in rows])


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
