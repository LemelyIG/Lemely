"""T8: the tutor's preview of their own profile (SPEC §b.2 "Tutor", §a.4b; T-21).

``GET /api/tutor/profile/preview`` is ``TEACHER`` + the caller's own profile,
resolved from ``auth.user_id`` (``deps_tutoring.require_tutor_profile``, O1): a
teacher without one gets 404 ``no_tutor_profile`` (ADR-T01), and the route takes
no tutor id. It is a read, so a suspended or closed tutor may still call it.

The response is S-34 as students see it: ``profile`` is the ``TutorProfileDTO``
SP2 builds (``tutoring_http.profile_fields``), in any listing state; ``outcomes``
is the ``OutcomesDTO`` SP4 builds (``tutoring_outcomes.outcomes_dto``), present
only while the profile is ``listed`` (paused or not) or ``pending_review``, and
``None`` otherwise (ID-7: a rejected, suspended or closed tutor, or a draft,
gets no figures). The figures are computed live, as for SP4, and the tutor sees
exactly what a student would: the outcome rules give the tutor no extra view
(ADR-T04). Built with :class:`~lemely.web.tutoring_http.TutoringRoute`
(``private, no-store``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.db.tutor_outcomes_repo import (
    TutorOutcomesRepository,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.tutor_profile_repo import TutorProfileRow  # noqa: TC001 - FastAPI resolves it
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps_tutoring import get_tutoring_areas, require_tutor_profile
from lemely.web.routers.tutoring_outcomes import get_tutor_outcomes_repo, outcomes_dto
from lemely.web.schemas_tutoring import TutorPreviewDTO
from lemely.web.tutoring_http import TutoringRoute, tutor_profile_dto, tutoring_error

router = APIRouter(prefix="/api/tutor", tags=["tutoring"], route_class=TutoringRoute)


@router.get("/profile/preview", response_model=TutorPreviewDTO)
def get_preview(
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
    repo: Annotated[TutorOutcomesRepository, Depends(get_tutor_outcomes_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> TutorPreviewDTO:
    """T8: the caller's profile as students see it, with figures while listed or in review."""
    preview = repo.preview(profile.id)
    if preview is None:  # pragma: no cover - profiles are never deleted (SPEC §a, SC-21)
        raise tutoring_error(404, "no_tutor_profile", "You do not have a tutor profile yet.")
    return TutorPreviewDTO(
        profile=tutor_profile_dto(preview.profile, areas),
        outcomes=outcomes_dto(preview.outcomes) if preview.outcomes is not None else None,
    )


__all__ = ["router"]
