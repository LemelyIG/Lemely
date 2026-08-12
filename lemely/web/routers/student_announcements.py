"""Student announcement endpoints (``/api/student/announcements``, P5.5 chunk B).

Until this router existed a student could not see an announcement at all —
:mod:`lemely.web.routers.announcements` mounts only at
``/api/teacher/announcements`` and exposes only POST/GET/DELETE, so every
notice a teacher wrote reached nobody. That is the Phase-3 limitation
"students cannot see announcements"; this is the read half of closing it.

A new router file, mirroring :mod:`lemely.web.routers.leaderboard` and
:mod:`lemely.web.routers.friends`: thin, its own DTOs, no growth of
``student.py``. It adds no announcement logic of its own — audience
resolution (class enrolment **or** a non-revoked school ``Seat``, D5.4),
``publish_at`` scheduling, and receipt idempotency all belong to
:class:`~lemely.db.announcement_repo.AnnouncementService` (P5.5 chunk A).

It composes the **same** ``AnnouncementService`` singleton the teacher router
uses (``deps.get_announcement_service``) rather than constructing a second
one. Two instances would carry two clocks, and the clock is what decides
whether a scheduled announcement is published yet — a student and their
teacher must never disagree about that.

Identity is **always** ``auth.user_id``. There is no caller-supplied user id
anywhere on this router: the list, the count and the receipt are each keyed on
the token's ``sub``, so one student can neither read another's announcements
nor mark them read on their behalf. That is structural, not merely
permission-checked — the same property that made P5.4 chunk B safe.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.db.announcement_repo import (
    DEFAULT_STUDENT_LIMIT,
    AnnouncementNotFoundError,
    AnnouncementService,
)
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, get_announcement_service, require_role
from lemely.web.schemas_announcements_student import (
    AnnouncementReadReceiptDTO,
    StudentAnnouncementDTO,
    StudentAnnouncementsPageDTO,
    UnreadAnnouncementCountDTO,
)

if TYPE_CHECKING:
    from lemely.db.announcement_repo import StudentAnnouncementRow

router = APIRouter(
    prefix="/api/student/announcements",
    dependencies=[Depends(require_role(Role.student))],
)


def _to_dto(row: StudentAnnouncementRow) -> StudentAnnouncementDTO:
    announcement = row.announcement
    scope: Literal["class", "school"] = "class" if announcement.class_id is not None else "school"
    return StudentAnnouncementDTO(
        announcementId=str(announcement.announcement_id),
        scope=scope,
        classId=str(announcement.class_id) if announcement.class_id is not None else None,
        schoolId=str(announcement.school_id) if announcement.school_id is not None else None,
        title=announcement.title,
        body=announcement.body,
        # The effective publication time, matching the service's ordering key:
        # the scheduled moment when the author set one, the creation time
        # otherwise. See StudentAnnouncementDTO.publishedAt for why only one
        # time field crosses the wire.
        publishedAt=announcement.publish_at or announcement.created_at,
        readAt=row.read_at,
        authorId=str(announcement.author_id),
    )


@router.get("", response_model=StudentAnnouncementsPageDTO)
def list_announcements(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[AnnouncementService, Depends(get_announcement_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_STUDENT_LIMIT,
) -> StudentAnnouncementsPageDTO:
    """S-28: the announcements this student may read, newest first.

    An empty list is a **successful** response and always honest — a student
    with no classes and no school seat has no audience, which is a true
    "nothing has been posted to you", not an error and not a 404.

    Future-dated announcements are absent because the service excludes them,
    not because this route filters: scheduling is a property of the student
    view everywhere, so a teacher's scheduled post cannot leak early through
    some other reader.
    """
    rows = service.list_for_student(auth.user_id, limit=limit)
    return StudentAnnouncementsPageDTO(announcements=[_to_dto(row) for row in rows])


@router.get("/unread-count", response_model=UnreadAnnouncementCountDTO)
def unread_count(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[AnnouncementService, Depends(get_announcement_service)],
) -> UnreadAnnouncementCountDTO:
    """The number of published, unread announcements in this student's scope.

    Separate from :func:`list_announcements` on purpose: this is the true
    count over the whole scope, whereas the page above is ``LIMIT``-ed, so a
    badge derived from the page length would stop counting at the page size
    and quietly under-report.
    """
    return UnreadAnnouncementCountDTO(unreadCount=service.unread_count_for_student(auth.user_id))


@router.post("/{announcement_id}/read", response_model=AnnouncementReadReceiptDTO)
def mark_announcement_read(
    announcement_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[AnnouncementService, Depends(get_announcement_service)],
) -> AnnouncementReadReceiptDTO:
    """Record that the caller read this announcement. Idempotent.

    Returns 200, not 201, and does so on the second call too: the receipt is a
    fact about the student that either already holds or is being established,
    and a client re-opening a notice must not have to distinguish the two. The
    returned ``readAt`` is the original first-read time on a repeat call.

    Raises:
        HTTPException: 404 when the announcement does not exist, is not in
            this student's scope, or is not published yet — deliberately
            **one** response for all three (the service collapses them). A
            student able to tell "exists but not yours" from "does not exist"
            could enumerate other classes' announcement ids by watching which
            error came back. 422 for a malformed ``announcement_id``.
    """
    try:
        read_at = service.mark_read(auth.user_id, announcement_id)
    except AnnouncementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Echo the *canonical* id, never the raw path string. ``uuid.UUID`` accepts
    # uppercase hex, braces and a ``urn:uuid:`` prefix, so the string the client
    # sent can differ from the row's actual id; returning it verbatim would hand
    # back a receipt whose id does not match the one in the list response, and a
    # client keying its unread state on that id would never clear the notice.
    # The parse cannot fail here — ``mark_read`` has already accepted it.
    return AnnouncementReadReceiptDTO(
        announcementId=str(uuid.UUID(announcement_id)), readAt=read_at
    )


__all__ = ["router"]
