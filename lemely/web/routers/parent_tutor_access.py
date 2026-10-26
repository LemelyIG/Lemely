"""PA6, PA7: a linked parent's read-only view of the child's grants and tutor reads (SPEC §b.2).

``PARENT`` only. Decision row 16 i lets a linked parent see who their child shares
progress with and which tutors looked, read-only: the student alone grants and
revokes (row 4), so this module has no write route.

* **The link (O7, O22).** Every call re-checks the link through
  ``ParentLinkService.get_child`` (never a join of its own, F32) before anything of
  the child's is read, in :func:`require_linked_child`; both routes then key every
  read on that child id alone. A user who exists but is not linked to the caller is
  403 ``not_linked``; an id no user has is 404 ``not_found``. That is the split of
  ``routers/parent.py`` (SPEC §b.2 "200, 403, 404"): it tells a parent whether a
  random 122-bit id belongs to some user, and nothing about that user's data.
* **PA6** is S8's list for the child (live first, then ended, newest first, at most
  200) through S8's own builder with ``viewer="parent"``: ``alsoTeachesClasses`` is
  the student's own information about their classes and is always empty here
  (SPEC §b.3), and the class lookup is not run (``include_classes=False``).
* **PA7** is S11's log for the child, newest first, optionally for one tutor,
  keyset-paged under its own cursor tag (O21). SPEC §e.3: the link check plus one
  statement.
* **No audit row.** ``tutor_access_audit`` records tutor reads only; a parent's
  reads on PA6/PA7 write nothing (SPEC §b.2, O22).

Built with :class:`~lemely.web.tutoring_http.TutoringRoute` (``private, no-store``
on every status, PLAN P12).
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI reads the path parameter type at runtime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from lemely.db.class_repo import ClassService  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.db.models.enums import Role
from lemely.db.parent_repo import ParentLinkService  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.db.tutor_grant_repo import MAX_PAGE_SIZE, TutorGrantRepository
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import AuthContext, get_class_service, get_parent_link_service, require_role
from lemely.web.deps_tutoring import get_tutoring_areas
from lemely.web.routers.student_tutor_access import (
    DEFAULT_PAGE_SIZE,
    access_log_entry_dto,
    decode_access_log_cursor,
    get_tutor_grant_repo,
    grant_dto,
    next_access_log_cursor,
)
from lemely.web.schemas_tutoring import AccessLogPageDTO, GrantsDTO
from lemely.web.tutoring_http import TutoringRoute, tutoring_error

#: The PA7 cursor tag (O21); S11 and T19 have their own.
ACCESS_LOG_ENDPOINT: Final = "parent_tutor_access_log"

require_parent: Final = require_role(Role.parent)

router = APIRouter(prefix="/api/parent", tags=["tutoring"], route_class=TutoringRoute)


def require_linked_child(
    auth: Annotated[AuthContext, Depends(require_parent)],
    child_id: uuid.UUID,
    links: Annotated[ParentLinkService, Depends(get_parent_link_service)],
    users: Annotated[ClassService, Depends(get_class_service)],
) -> uuid.UUID:
    """The path's child, when linked to the caller now; else 403 ``not_linked`` or 404.

    Runs on every PA6/PA7 call, after the role guard and before any read (O7).
    """
    child = links.get_child(auth.user_id, child_id)
    if child is not None:
        return child.child_id
    if users.user_exists(child_id):
        raise tutoring_error(403, "not_linked", "This child is not linked to your account.")
    raise tutoring_error(404, "not_found", "Child not found.")


@router.get("/children/{child_id}/tutor-grants", response_model=GrantsDTO)
def child_tutor_grants(
    child: Annotated[uuid.UUID, Depends(require_linked_child)],
    repo: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> GrantsDTO:
    """PA6: the child's grants as S8 lists them, without the child's class names."""
    views = repo.grants_for_student(child, include_classes=False)
    return GrantsDTO(items=[grant_dto(view, areas, viewer="parent") for view in views])


@router.get("/children/{child_id}/tutor-access-log", response_model=AccessLogPageDTO)
def child_tutor_access_log(
    child: Annotated[uuid.UUID, Depends(require_linked_child)],
    repo: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    tutor_id: Annotated[uuid.UUID | None, Query(alias="tutorId")] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> AccessLogPageDTO:
    """PA7: every tutor read of the child's data, newest first."""
    after = decode_access_log_cursor(cursor, ACCESS_LOG_ENDPOINT)
    page = repo.access_log_page(child, tutor_id=tutor_id, cursor=after, limit=limit)
    return AccessLogPageDTO(
        items=[access_log_entry_dto(entry) for entry in page.items],
        nextCursor=next_access_log_cursor(page.next_key, ACCESS_LOG_ENDPOINT),
    )


__all__ = [
    "ACCESS_LOG_ENDPOINT",
    "require_linked_child",
    "require_parent",
    "router",
]
