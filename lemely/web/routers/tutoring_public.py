"""Public tutoring routes P1-P3: the directory, the card, the areas (SPEC §b.2 "Public").

No authentication. What leaves here is the minimal public card of decision-log
row 5b and nothing else (SPEC §a.5 "Nothing else, ever"): name and initial,
headline, subjects, modes, city-level area, the rating pair, and on P2 alone the
tutor's ``indexable`` choice (row 17), which the edge worker reads to decide
whether a card page may be indexed (§b.5). There is no availability filter here
(row 5b); the logged-in directory has it.

Every route is built with :class:`~lemely.web.tutoring_http.PublicTutoringRoute`
(``public, max-age=60`` and ``X-Robots-Tag: noindex``). P2 answers one identical
404 for every tutor that is not listed and unpaused (PP-6), so the worker's
lookup learns nothing a visitor could not (O31).
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI reads the path parameter type at runtime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from lemely.core.keyset import CursorError
from lemely.db.tutor_directory_repo import (
    MAX_PAGE_SIZE,
    DirectoryFilters,
    DirectoryKey,
    TutorDirectoryRepository,
    directory_cursor,
    parse_directory_cursor,
)
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps_tutoring import (
    get_tutor_directory_repo,
    get_tutoring_areas,
    public_directory_filters,
)
from lemely.web.schemas_tutoring import (
    AreaListDTO,
    AreaRefDTO,
    PublicDirectoryPageDTO,
    PublicTutorCardDTO,
)
from lemely.web.tutoring_http import (
    PublicTutoringRoute,
    facets_dto,
    public_tutor_card_dto,
    tutor_card_dto,
    tutor_not_found,
    tutoring_error,
)

#: The P1 cursor tag: a P1 cursor is refused on any other list (O21).
PUBLIC_DIRECTORY_ENDPOINT: Final = "public_tutors"
_DEFAULT_PAGE_SIZE: Final = 20

router = APIRouter(prefix="/api/public", tags=["tutoring"], route_class=PublicTutoringRoute)


def decode_directory_cursor(cursor: str | None, endpoint: str) -> DirectoryKey | None:
    """The page start from a client cursor; 422 ``invalid_cursor`` for anything not minted here."""
    if cursor is None:
        return None
    try:
        return parse_directory_cursor(cursor, endpoint)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


@router.get("/tutors", response_model=PublicDirectoryPageDTO)
def list_public_tutors(
    filters: Annotated[DirectoryFilters, Depends(public_directory_filters)],
    repo: Annotated[TutorDirectoryRepository, Depends(get_tutor_directory_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> PublicDirectoryPageDTO:
    """P1: listed, unpaused tutors by Bayesian rank; ``facets`` on the first page only."""
    after = decode_directory_cursor(cursor, PUBLIC_DIRECTORY_ENDPOINT)
    page = repo.list_public(filters, after=after, limit=limit)
    return PublicDirectoryPageDTO(
        items=[tutor_card_dto(card, areas) for card in page.items],
        nextCursor=(
            directory_cursor(PUBLIC_DIRECTORY_ENDPOINT, page.next_key)
            if page.next_key is not None
            else None
        ),
        facets=facets_dto(page.facets, areas) if page.facets is not None else None,
    )


@router.get("/tutors/{tutor_id}", response_model=PublicTutorCardDTO)
def get_public_tutor(
    tutor_id: uuid.UUID,
    repo: Annotated[TutorDirectoryRepository, Depends(get_tutor_directory_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> PublicTutorCardDTO:
    """P2: the public card and ``indexable``; one 404 for every hidden tutor."""
    card = repo.public_card(tutor_id)
    if card is None:
        raise tutor_not_found()
    return public_tutor_card_dto(card, areas)


@router.get("/tutoring-areas", response_model=AreaListDTO)
def list_tutoring_areas(
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> AreaListDTO:
    """P3: every area in ``lemely/data/tutoring_areas.json``, in file order (F13)."""
    return AreaListDTO(items=[AreaRefDTO(code=area.code, name=area.name) for area in areas.areas])


__all__ = ["PUBLIC_DIRECTORY_ENDPOINT", "decode_directory_cursor", "router"]
