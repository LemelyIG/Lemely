"""S8-S11: a student's data grants and the log of tutor reads (SPEC §b.2 "Student", ADR-T02).

``STUDENT`` only; a parent reads the same facts, read-only, through PA6/PA7 (T20's
routers), never here (decision row 4: the student alone grants and revokes).

* **S8** lists the caller's grants, live ones first, then ended ones, newest first
  (at most 200), each with its status from ``core.tutor_grants.grant_status`` and
  the names of the caller's classes the tutor also teaches (SC-2e, student only).
* **S9** (verified email, SC-15) creates a grant, or returns the live one with 200.
  The tutor must be listed and not paused, with no active block either way (O11).
  An unknown, unlisted, paused, suspended, closed or blocked tutor (either block
  direction) gets SP2's own 404 (``tutoring_http.tutor_not_found``), so S9 never
  tells a student that a tutor exists but is hidden, or that the tutor blocked
  them (lead decision at the T14 review; it replaces the 409 ``tutor_not_listed``
  and ``blocked`` of SPEC §b.2 rev 3). The linked parents' email is queued inside
  the grant's transaction; after it commits the tutor and every linked parent get
  an inbox notice (``tutoring_notify.grant_notices``), and a failure there is
  logged and never fails the grant (D5.9 section 1).
* **S10** revokes the caller's own grant (O5: anyone else's is the same 404 as an
  unknown id). It is idempotent; the first revoke tells the tutor, in generic
  words, that access ended (SC-11). Effective on the tutor's next read.
* **S11** pages the caller's own access log, newest first, optionally for one
  tutor. Entries carry no id (ID-5); the cursor is tagged with this list (O21).

This module also holds what the grant routes share (T19/T20 here, PA6/PA7 later):
the repository provider :func:`get_tutor_grant_repo` and the DTO builders
:func:`grant_dto` and :func:`access_log_entry_dto`. Built with
:class:`~lemely.web.tutoring_http.TutoringRoute` (``private, no-store``).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from lemely.core.keyset import CursorError
from lemely.db.models.enums import GrantRevokeReason, Role
from lemely.db.notification_repo import (
    NotificationService,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.session import get_sessionmaker
from lemely.db.tutor_grant_repo import (
    MAX_PAGE_SIZE,
    AccessLogKey,
    GrantError,
    GrantNotFound,
    TutorGrantRepository,
    TutorNotFound,
    access_log_cursor,
    parse_access_log_cursor,
)
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import (
    AuthContext,
    get_notification_service,
    get_push_transport,
    get_settings,
    require_role,
    require_verified_email,
)
from lemely.web.deps_tutoring import get_tutoring_areas
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.schemas_tutoring import (
    AccessLogEntryDTO,
    AccessLogPageDTO,
    GrantCreateDTO,
    GrantDTO,
    GrantsDTO,
)
from lemely.web.tutoring_http import (
    TutoringRoute,
    iso_instant,
    tutor_card_dto,
    tutor_not_found,
    tutoring_error,
)
from lemely.web.tutoring_notify import grant_notices, send_after_commit

if TYPE_CHECKING:
    from lemely.db.tutor_grant_repo import AccessLogEntry, GrantView

#: The S11 cursor tag (O21); PA7 and T19 have their own.
ACCESS_LOG_ENDPOINT: Final = "student_tutor_access_log"
DEFAULT_PAGE_SIZE: Final = 20

require_student: Final = require_role(Role.student)

router = APIRouter(prefix="/api/student", tags=["tutoring"], route_class=TutoringRoute)


@lru_cache(maxsize=1)
def get_tutor_grant_repo() -> TutorGrantRepository:
    """The process-wide :class:`TutorGrantRepository`."""
    return TutorGrantRepository(get_sessionmaker(get_settings()))


# ---------------------------------------------------------------------------
# Shared by the grant routes
# ---------------------------------------------------------------------------


def grant_dto(
    view: GrantView, areas: AreaCatalogue, *, viewer: Literal["student", "parent"]
) -> GrantDTO:
    """One grant as its student sees it, or (read-only) a linked parent.

    ``alsoTeachesClasses`` is the student's own information about their classes
    (SC-2e) and is always empty for a parent (SPEC §b.3).
    """
    grant = view.grant
    return GrantDTO.model_validate(
        {
            "grantId": str(grant.id),
            "tutor": tutor_card_dto(view.tutor, areas),
            "createdAt": iso_instant(grant.created_at),
            "revokedAt": iso_instant(grant.revoked_at) if grant.revoked_at is not None else None,
            "status": view.status,
            "scope": grant.scope,
            "alsoTeachesClasses": list(view.also_teaches_classes) if viewer == "student" else [],
        }
    )


def access_log_entry_dto(entry: AccessLogEntry) -> AccessLogEntryDTO:
    """One tutor read: who (by profile id and the name they had then), what, when. No id."""
    return AccessLogEntryDTO(
        tutorId=str(entry.tutor_profile_id) if entry.tutor_profile_id is not None else None,
        tutorName=entry.tutor_name,
        action=entry.action,
        accessedAt=iso_instant(entry.accessed_at),
    )


def decode_access_log_cursor(cursor: str | None, endpoint: str) -> AccessLogKey | None:
    """The page start from a client cursor; 422 ``invalid_cursor`` for anything not minted here."""
    if cursor is None:
        return None
    try:
        return parse_access_log_cursor(cursor, endpoint)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


def next_access_log_cursor(key: AccessLogKey | None, endpoint: str) -> str | None:
    return access_log_cursor(endpoint, key) if key is not None else None


def grant_http_error(exc: GrantError) -> HTTPException:
    """Map a repository refusal on S9/S10 to its status and body.

    Every S9 refusal (``TutorNotFound`` and its not-listed and blocked subclasses)
    is SP2's one 404 (O11), whatever the reason.
    """
    if isinstance(exc, TutorNotFound):
        return tutor_not_found()
    if isinstance(exc, GrantNotFound):
        return tutoring_error(404, exc.code, "Grant not found.")
    raise exc


def _view(repo: TutorGrantRepository, student_id: uuid.UUID, grant_id: uuid.UUID) -> GrantView:
    view = repo.grant_view(student_id, grant_id)
    if view is None:  # the grant was just written or read for this student
        raise RuntimeError(f"grant {grant_id} vanished for its own student")
    return view


# ---------------------------------------------------------------------------
# S8-S11
# ---------------------------------------------------------------------------


@router.get("/tutor-grants", response_model=GrantsDTO)
def list_grants(
    auth: Annotated[AuthContext, Depends(require_student)],
    repo: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> GrantsDTO:
    """S8: the caller's grants, live first, then ended, newest first."""
    views = repo.grants_for_student(uuid.UUID(auth.user_id))
    return GrantsDTO(items=[grant_dto(view, areas, viewer="student") for view in views])


@router.post("/tutor-grants", status_code=201, response_model=GrantDTO)
def create_grant(
    body: GrantCreateDTO,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_student)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    repo: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> GrantDTO:
    """S9: share the caller's progress with one tutor; 200 with the live grant if one exists."""
    student_id = uuid.UUID(auth.user_id)
    try:
        tutor_id = uuid.UUID(body.tutorId)
    except ValueError as exc:  # no tutor can have this id: the same answer as an unknown one
        raise tutor_not_found() from exc
    try:
        outcome = repo.create(student_id, tutor_id)
    except GrantError as exc:
        raise grant_http_error(exc) from exc
    if outcome.created:
        notice = outcome.notice
        send_after_commit(
            grant_notices(
                event="created",
                grant_id=outcome.grant.id,
                tutor_user_id=notice.tutor_user_id,
                tutor_name=notice.tutor_name,
                student_user_id=student_id,
                student_label=notice.student_label,
                linked_parent_ids=notice.linked_parent_ids,
            ),
            service=service,
            transport=transport,
        )
    else:
        response.status_code = 200
    return grant_dto(_view(repo, student_id, outcome.grant.id), areas, viewer="student")


@router.post("/tutor-grants/{grant_id}/revoke", response_model=GrantDTO)
def revoke_grant(
    grant_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student)],
    repo: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> GrantDTO:
    """S10: stop sharing; a repeat is a 200 that changes and sends nothing."""
    student_id = uuid.UUID(auth.user_id)
    try:
        outcome = repo.revoke(student_id, grant_id)
    except GrantError as exc:
        raise grant_http_error(exc) from exc
    if outcome.revoked_now:
        notice = outcome.notice
        send_after_commit(
            grant_notices(
                event="ended",
                grant_id=outcome.grant.id,
                tutor_user_id=notice.tutor_user_id,
                tutor_name=notice.tutor_name,
                student_user_id=student_id,
                student_label=notice.student_label,
                linked_parent_ids=notice.linked_parent_ids,
                ended_reason=GrantRevokeReason.student,
            ),
            service=service,
            transport=transport,
        )
    return grant_dto(_view(repo, student_id, outcome.grant.id), areas, viewer="student")


@router.get("/tutor-access-log", response_model=AccessLogPageDTO)
def access_log(
    auth: Annotated[AuthContext, Depends(require_student)],
    repo: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    tutor_id: Annotated[uuid.UUID | None, Query(alias="tutorId")] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> AccessLogPageDTO:
    """S11: every tutor read of the caller's data, newest first."""
    after = decode_access_log_cursor(cursor, ACCESS_LOG_ENDPOINT)
    page = repo.access_log_page(
        uuid.UUID(auth.user_id), tutor_id=tutor_id, cursor=after, limit=limit
    )
    return AccessLogPageDTO(
        items=[access_log_entry_dto(entry) for entry in page.items],
        nextCursor=next_access_log_cursor(page.next_key, ACCESS_LOG_ENDPOINT),
    )


__all__ = [
    "ACCESS_LOG_ENDPOINT",
    "DEFAULT_PAGE_SIZE",
    "access_log_entry_dto",
    "decode_access_log_cursor",
    "get_tutor_grant_repo",
    "grant_dto",
    "grant_http_error",
    "next_access_log_cursor",
    "require_student",
    "router",
]
