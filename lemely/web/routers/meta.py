"""Meta / health endpoints under ``/api``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.runtime.config import Settings
from lemely.runtime.errors import EmptyGradeBoundaryStoreError
from lemely.web.deps import get_boundary_store, get_settings
from lemely.web.schemas import HealthDTO

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthDTO)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthDTO:
    """Return service health, API-key configuration, and grade-boundary readiness.

    ``gradeBoundariesLoaded`` is the operational half of C1's fix
    (``lemely.io.grade_boundaries``): a fresh or unseeded database has zero
    verified ``component_thresholds`` rows, and ``GradeBoundaryStore``
    construction now raises :class:`EmptyGradeBoundaryStoreError` rather than
    inventing a global default. This endpoint stays a 200 either way — a
    health check that itself 500s is a worse signal than a flag naming the
    exact gap — so an operator (or a deploy step's own smoke test) can see
    "migrations ran, ``scripts/ingest_thresholds.py`` never did" before a
    student is graded against nothing.
    """
    try:
        get_boundary_store()
        grade_boundaries_loaded = True
    except EmptyGradeBoundaryStoreError:
        grade_boundaries_loaded = False
    return HealthDTO(
        apiKeyConfigured=settings.gemini_api_key is not None,
        gradeBoundariesLoaded=grade_boundaries_loaded,
    )
