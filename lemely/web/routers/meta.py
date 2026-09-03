"""Meta / health endpoints under ``/api``."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.runtime.config import Settings
from lemely.runtime.errors import EmptyGradeBoundaryStoreError
from lemely.web.deps import get_boundary_store, get_settings
from lemely.web.schemas import HealthDTO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

#: Whether the last boundary read failed. Health is probe traffic -- a liveness
#: check polling every few seconds against a down database would otherwise emit
#: one full traceback per poll, indefinitely. The traceback is worth having
#: once, so it is logged on the transition into failure and again on recovery;
#: the polls in between are silent.
_boundary_read_failing = False


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

    ``false`` therefore has two causes, and only the backend log separates
    them: an unreachable or unqueryable database logs ``health: could not read
    grade boundaries from the database``, a missing ingest does not.
    """
    global _boundary_read_failing
    try:
        get_boundary_store()
        grade_boundaries_loaded = True
        if _boundary_read_failing:
            logger.info("health: grade boundaries readable again")
            _boundary_read_failing = False
    except EmptyGradeBoundaryStoreError:
        grade_boundaries_loaded = False
    except Exception:
        # The store reads ``component_thresholds`` now, so an unreachable or
        # broken database lands here too. Health must still answer 200: a 500
        # tells an operator only "something is wrong", whereas
        # ``gradeBoundariesLoaded: false`` plus the logged exception names it.
        #
        # Deliberately broader than SQLAlchemyError. ``_percentages`` raises
        # ValueError on a non-positive max_mark and would raise TypeError on a
        # non-numeric value inside the ``thresholds`` JSONB, and neither is a
        # SQLAlchemyError -- a corrupt payload must degrade this endpoint to
        # "false", not take it down. Nothing here is recovered from or
        # rethrown, so a swallowed programming error still reaches the log.
        if not _boundary_read_failing:
            logger.exception("health: could not read grade boundaries from the database")
            _boundary_read_failing = True
        grade_boundaries_loaded = False
    return HealthDTO(
        apiKeyConfigured=settings.gemini_api_key is not None,
        gradeBoundariesLoaded=grade_boundaries_loaded,
    )
