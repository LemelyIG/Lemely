"""Mount tutoring routers in a test without touching ``lemely/web/app.py``.

``lemely/web/app.py`` and ``tests/test_authz_matrix_complete.py`` are hot files
the lead owns; a route task must not edit them, even uncommitted. Its tests build
the application through :func:`app_with_routers` instead, which adds the task's
router to a fresh ``create_app()`` and does nothing once the lead has mounted it.

:func:`flatten_routes` is the ``original_router`` recursion of
``test_authz_matrix_complete._flatten``: FastAPI keeps an included router as a
wrapper, so ``app.routes`` alone lists only the docs routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.routing import APIRoute

from lemely.web import create_app

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

_HIDDEN_METHODS = frozenset({"HEAD", "OPTIONS"})


def flatten_routes(router: object) -> list[APIRoute]:
    """Every ``APIRoute`` reachable from ``router``, through included routers."""
    found: list[APIRoute] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            found.append(route)
        else:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                found.extend(flatten_routes(inner))
    return found


def _pairs(router: object) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in flatten_routes(router)
        for method in route.methods
        if method not in _HIDDEN_METHODS
    }


def app_with_routers(*routers: APIRouter) -> FastAPI:
    """A fresh ``create_app()`` with each router mounted unless it already is.

    A router counts as mounted when every one of its ``(method, path)`` pairs is
    already served by the application, which is what makes a task's test keep
    passing after the lead adds ``include_router`` to ``app.py``. A router that
    overlaps the application in only some pairs is a mistake (FastAPI would let
    the first match win) and raises ``ValueError``.
    """
    app = create_app()
    for router in routers:
        wanted = _pairs(router)
        present = wanted & _pairs(app.router)
        if wanted and present == wanted:
            continue
        if present:
            raise ValueError(f"router is partially mounted already: {sorted(present)}")
        app.include_router(router)
    return app
