"""FastAPI application factory for the Lemely web backend.

:func:`create_app` wires the portal routers (meta, auth, teacher, student,
school), all mounted under ``/api``. Portal workers extend ``routers/teacher.py``
and ``routers/student.py`` in place — this factory never needs to change when new
endpoints are added.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lemely import __version__
from lemely.runtime.errors import EmptyGradeBoundaryStoreError
from lemely.web.deps import get_settings, get_sweeper
from lemely.web.routers import (
    admin,
    announcements,
    auth,
    classes,
    client_errors,
    exam_calendar,
    flashcards,
    friends,
    invites,
    leaderboard,
    me,
    meta,
    notifications,
    parent,
    placement,
    practice,
    quiz,
    reference,
    review,
    school,
    student,
    student_announcements,
    student_classes,
    study_plan,
    teacher,
    xp,
)
from lemely.web.scheduled_notifications import run_sweeper

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the notification sweeper on startup and stop it on shutdown (spec §4).

    One asyncio task for the process. It is not started when
    ``settings.notifications.sweeper_enabled`` is false — the suite sets that
    so no test races a background task — and the settings are read here, at
    startup, rather than at import so a test can change the env and rebuild
    the app. Shutdown sets the stop event and waits for the loop to return:
    a pass in flight finishes (its rows are locked in its own transaction),
    the loop sees the event, and the task exits. Starlette runs this only
    inside ``with TestClient(app)`` / a real server, never for a bare
    ``TestClient(app)``, which is why every pre-existing test is unaffected.
    """
    settings = get_settings()
    stop = asyncio.Event()
    task: asyncio.Task[None] | None = None
    if settings.notifications.sweeper_enabled:
        task = asyncio.create_task(
            run_sweeper(
                get_sweeper(),
                poll_seconds=settings.notifications.sweep_poll_seconds,
                stop=stop,
            ),
            name="notification-sweeper",
        )
        log.info(
            "notification sweeper started (every %ss)", settings.notifications.sweep_poll_seconds
        )
    try:
        yield
    finally:
        if task is not None:
            stop.set()
            await task


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application.

    Includes the meta/health router, the auth router, and the (initially empty)
    teacher and student portal routers so portal workers never edit this module.
    """
    app = FastAPI(
        title="Lemely API",
        description="Backend for the Lemely Teacher and Student portals.",
        # Sourced from the installed package metadata, never hand-edited: a
        # literal here silently drifts from pyproject.toml (it sat at 0.1.0
        # through five phases). An editable install needs `pip install -e .`
        # after a version bump before this reports the new number.
        version=__version__,
        lifespan=_lifespan,
    )
    app.include_router(meta.router)
    app.include_router(reference.router)
    app.include_router(client_errors.router)
    app.include_router(auth.router)
    app.include_router(teacher.router)
    app.include_router(classes.router)
    app.include_router(review.router)
    app.include_router(quiz.router)
    app.include_router(quiz.student_router)
    app.include_router(placement.router)
    app.include_router(practice.router)
    app.include_router(flashcards.router)
    app.include_router(study_plan.router)
    app.include_router(leaderboard.router)
    app.include_router(xp.router)
    app.include_router(friends.router)
    app.include_router(student_announcements.router)
    app.include_router(student_classes.router)
    app.include_router(exam_calendar.router)
    app.include_router(notifications.router)
    app.include_router(student.router)
    app.include_router(school.router)
    app.include_router(admin.router)
    app.include_router(invites.router)
    app.include_router(parent.router)
    app.include_router(me.router)
    app.include_router(announcements.router)

    @app.exception_handler(EmptyGradeBoundaryStoreError)
    async def _thresholds_not_ingested(
        _request: Request, exc: EmptyGradeBoundaryStoreError
    ) -> JSONResponse:
        """Answer 503, not 500, when the threshold table has never been ingested.

        Every grading surface builds a ``GradeBoundaryStore`` of its own
        (``routers/student.py``, ``routers/parent.py``, ``db/review_repo.py``,
        ``web/services/grading.py``), so this is handled once here rather than
        at each of those call sites. Refusing is the intended behaviour — a
        boundary the exam board never published is not a grade — but a bare 500
        told an operator only that something threw. The cause is a deployed
        environment where ``alembic upgrade head`` ran and
        ``scripts/ingest_thresholds.py`` did not, which is unavailability.

        The exception is repr'd into the message rather than left to
        ``exc_info``: the stdlib-to-structlog bridge in
        ``lemely.runtime.logging`` forwards only ``record.getMessage()``, so a
        deployed log would otherwise carry no cause at all (same reason as
        ``routers/meta.py``'s health record).
        """
        logging.getLogger(__name__).error("grade thresholds are not ingested: %r", exc)
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Grade boundaries are not available: this database has no verified "
                    "component_thresholds rows. Run `python scripts/ingest_thresholds.py` "
                    "against it."
                )
            },
        )

    return app


__all__ = ["create_app"]
