"""FastAPI routers for the Lemely web backend.

Each router is mounted by :func:`lemely.web.app.create_app`. Keeping the router
modules independent means the teacher and student portal workers can build out
their endpoints without ever editing ``app.py``.
"""

from __future__ import annotations

from lemely.web.routers import invites, meta, student, teacher

__all__ = ["invites", "meta", "student", "teacher"]
