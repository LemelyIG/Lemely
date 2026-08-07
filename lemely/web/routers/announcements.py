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

**Nothing here delivers an announcement to a student.** There is no
student-facing announcement surface and no notification send path — MISSION
§4 puts both in Phase 5. This module ships compose/list/delete only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn

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
from lemely.web.deps import AuthContext, get_announcement_service, require_role
from lemely.web.schemas_announcements import (
    AnnouncementCreateRequestDTO,
    AnnouncementCreateResponseDTO,
    AnnouncementDTO,
    AnnouncementListDTO,
)

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
