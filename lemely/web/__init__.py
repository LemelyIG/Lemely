"""FastAPI web backend for Lemely — the Teacher and Student portals.

The :func:`lemely.web.app.create_app` factory wires the SSE event bridge, the
dependency singletons, and the portal routers. All routes are served under the
``/api`` prefix, matching the frontend client in ``web/src/lib/api.ts``.
"""

from __future__ import annotations

from lemely.web.app import create_app

__all__ = ["create_app"]
