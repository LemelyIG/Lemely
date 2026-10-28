"""Logged-in directory SP1-SP2 for students and parents (SPEC §b.2 ``STUDENT_OR_PARENT``).

SP1 is P1 plus the availability filter (``day``, ``timeOfDay``: "Usually
available", tutor-zone wall clock) and the block anti-join: a student never sees
a tutor with whom an active block exists in either direction; parents hold no
blocks (O11). SP2 is the full logged-in profile, behind a verified email
(SC-15, PP-2), and answers one identical 404 when the tutor is unlisted, paused
or blocked.

Built with :class:`~lemely.web.tutoring_http.TutoringRoute`, so every response
is ``private, no-store``. Later tasks add SP3-SP6 in their own routers (PLAN
§1.4 #1); the paths do not change.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from lemely.db.tutor_directory_repo import (
    MAX_PAGE_SIZE,
    DirectoryFilters,
    TutorDirectoryRepository,
    directory_cursor,
)
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import AuthContext, require_verified_email
from lemely.web.deps_tutoring import (
    get_tutor_directory_repo,
    get_tutoring_areas,
    logged_in_directory_filters,
    require_student_or_parent,
)
from lemely.web.schemas_tutoring import DirectoryPageDTO, TutorProfileDTO
from lemely.web.tutoring_http import (
    TutoringRoute,
    decode_directory_cursor,
    facets_dto,
    tutor_card_dto,
    tutor_not_found,
    tutor_profile_dto,
)

#: The SP1 cursor tag: distinct from P1's, so neither list accepts the other's cursor (O21).
DIRECTORY_ENDPOINT: Final = "tutors"
_DEFAULT_PAGE_SIZE: Final = 20

router = APIRouter(prefix="/api", tags=["tutoring"], route_class=TutoringRoute)


@router.get("/tutors", response_model=DirectoryPageDTO)
def list_tutors(
    auth: Annotated[AuthContext, Depends(require_student_or_parent)],
    filters: Annotated[DirectoryFilters, Depends(logged_in_directory_filters)],
    repo: Annotated[TutorDirectoryRepository, Depends(get_tutor_directory_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> DirectoryPageDTO:
    """SP1: the directory for the caller, with availability filters and blocks applied."""
    after = decode_directory_cursor(cursor, DIRECTORY_ENDPOINT)
    page = repo.list_for_viewer(
        uuid.UUID(auth.user_id), auth.role, filters, after=after, limit=limit
    )
    return DirectoryPageDTO(
        items=[tutor_card_dto(card, areas) for card in page.items],
        nextCursor=(
            directory_cursor(DIRECTORY_ENDPOINT, page.next_key)
            if page.next_key is not None
            else None
        ),
        facets=facets_dto(page.facets, areas) if page.facets is not None else None,
    )


@router.get("/tutors/{tutor_id}", response_model=TutorProfileDTO)
def get_tutor(
    tutor_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student_or_parent)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    repo: Annotated[TutorDirectoryRepository, Depends(get_tutor_directory_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> TutorProfileDTO:
    """SP2: the logged-in profile; 404 unless listed, unpaused and unblocked."""
    view = repo.profile_for_viewer(tutor_id, uuid.UUID(auth.user_id), auth.role)
    if view is None:
        raise tutor_not_found()
    return tutor_profile_dto(view, areas)


__all__ = ["DIRECTORY_ENDPOINT", "router"]
