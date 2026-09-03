"""FastAPI application factory for the Lemely web backend.

:func:`create_app` wires the portal routers (meta, auth, teacher, student,
school), all mounted under ``/api``. Portal workers extend ``routers/teacher.py``
and ``routers/student.py`` in place — this factory never needs to change when new
endpoints are added.
"""

from __future__ import annotations

from fastapi import FastAPI

from lemely import __version__
from lemely.runtime.budget_notify import register_budget_ntfy
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


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application.

    Includes the meta/health router, the auth router, and the (initially empty)
    teacher and student portal routers so portal workers never edit this module.
    """
    register_budget_ntfy()
    app = FastAPI(
        title="Lemely API",
        description="Backend for the Lemely Teacher and Student portals.",
        # Sourced from the installed package metadata, never hand-edited: a
        # literal here silently drifts from pyproject.toml (it sat at 0.1.0
        # through five phases). An editable install needs `pip install -e .`
        # after a version bump before this reports the new number.
        version=__version__,
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
    return app


__all__ = ["create_app"]
