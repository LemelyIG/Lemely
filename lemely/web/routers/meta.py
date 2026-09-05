"""Meta / health endpoints under ``/api``."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.runtime.config import Settings
from lemely.runtime.errors import EmptyGradeBoundaryStoreError
from lemely.web.deps import get_boundary_store, get_settings
from lemely.web.schemas import HealthDTO, StorageHealthDTO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

#: Whether the last boundary read raised. Health is probe traffic -- a liveness
#: check polling every few seconds against a down database would otherwise emit
#: one full *traceback* per poll, indefinitely. So the traceback is logged on
#: the transition into failure only. Every failing poll still logs a one-line
#: warning, because ``docs/deployment.md`` tells operators to use that line to
#: tell "database unreachable" apart from "ingest never ran" -- suppressing it
#: entirely would delete the signal the docs point at, and an operator who
#: starts reading logs mid-outage would find nothing.
#:
#: Per-process state. The backend is pinned to one instance
#: (``docs/deployment.md`` §5.1), but a multi-worker uvicorn would suppress
#: per worker, which is the intended granularity anyway.
_boundary_read_failing = False


def _note_boundaries_readable() -> None:
    """Clear the failure flag once the store can be read again.

    Called from both non-raising paths. A store that raises
    ``EmptyGradeBoundaryStoreError`` was still *read* successfully -- the
    database answered, it just has no verified rows -- so this must reset
    there too. Resetting only on full success left the flag stuck: an outage
    that recovered into a not-yet-ingested database kept the flag ``True``,
    and a genuinely new, different failure afterwards was then never logged
    at all.
    """
    global _boundary_read_failing
    if _boundary_read_failing:
        logger.info("health: grade boundaries readable again")
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
    them: a database that cannot be read logs ``health: could not read grade
    boundaries from the database`` on every failing poll, a missing ingest
    logs nothing.

    One limit worth knowing: ``get_boundary_store`` is ``lru_cache``'d, so
    once boundaries have loaded this endpoint stops touching the database
    entirely. It therefore reports a *startup* database problem, not one that
    begins after the first successful read — for that, watch the routes that
    actually query.
    """
    global _boundary_read_failing
    try:
        get_boundary_store()
        grade_boundaries_loaded = True
        _note_boundaries_readable()
    except EmptyGradeBoundaryStoreError:
        # The database answered; it just has no verified rows. That is a
        # successful read, so the failure flag must clear here too.
        _note_boundaries_readable()
        grade_boundaries_loaded = False
    except Exception as exc:
        # The store reads ``component_thresholds`` now, so an unreachable or
        # broken database lands here too. Health must still answer 200: a 500
        # tells an operator only "something is wrong", whereas
        # ``gradeBoundariesLoaded: false`` plus the logged exception names it.
        #
        # Deliberately broader than SQLAlchemyError. ``_percentages`` raises
        # ValueError on a non-positive max_mark and would raise TypeError on a
        # non-numeric value inside the ``thresholds`` JSONB, and neither is a
        # SQLAlchemyError -- a corrupt payload must degrade this endpoint to
        # "false", not take it down.
        #
        # The traceback goes out once per outage; the one-line warning goes
        # out every poll, so the signal the docs point operators at is always
        # present in a recent log window.
        #
        # The exception is repr'd into the *message* rather than left to
        # ``exc_info`` alone: the app's stdlib-to-structlog bridge
        # (``lemely.runtime.logging``) forwards only ``record.getMessage()``
        # and drops ``exc_info``, so a bare ``logger.exception`` reaches a
        # deployed log as a string with no exception type at all -- and
        # telling `OperationalError` from a corrupt-JSONB `TypeError` is the
        # entire point of this record.
        if _boundary_read_failing:
            logger.warning("health: could not read grade boundaries from the database: %r", exc)
        else:
            logger.exception("health: could not read grade boundaries from the database: %r", exc)
            _boundary_read_failing = True
        grade_boundaries_loaded = False
    return HealthDTO(
        apiKeyConfigured=settings.gemini_api_key is not None,
        gradeBoundariesLoaded=grade_boundaries_loaded,
        # Read straight off Settings, never by constructing a backend: the
        # deploy smoke test greps this, and a health route that dialled GCS
        # would fail exactly when it is most needed. Guarded by
        # `test_health_reports_storage_backend_without_touching_it`.
        storage=StorageHealthDTO(backend=settings.storage.backend, bucket=settings.storage.bucket),
    )
