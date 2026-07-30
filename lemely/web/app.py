"""FastAPI application factory for the Lemely web backend.

:func:`create_app` wires the three portal routers (meta, teacher, student), all
mounted under ``/api``. Portal workers extend ``routers/teacher.py`` and
``routers/student.py`` in place — this factory never needs to change when new
endpoints are added.
"""

from __future__ import annotations

from fastapi import FastAPI

from lemely.web.routers import meta, student, teacher


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application.

    Includes the meta/health router and the (initially empty) teacher and
    student portal routers so portal workers never edit this module.
    """
    app = FastAPI(
        title="Lemely API",
        description="Backend for the Lemely Teacher and Student portals.",
        version="0.1.0",
    )
    app.include_router(meta.router)
    app.include_router(teacher.router)
    app.include_router(student.router)
    return app


__all__ = ["create_app"]
