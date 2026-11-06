"""Tests for ``tests/tutoring_app.py`` (T00): route flattening and router mounting.

``tests/tutoring_app.py`` lets a tutoring route task mount its own routers in a
test without editing ``lemely/web/app.py``, which is a hot file owned by the
lead. These tests prove the two helpers against the real application factory.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from lemely.web import create_app
from lemely.web.routers import me
from tests.tutoring_app import app_with_routers, flatten_routes

_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_PROBE_PREFIX = "/api/_t00_probe"


def _pairs(routes: list[APIRoute]) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in routes
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }


def _count(routes: list[APIRoute], method: str, path: str) -> int:
    return sum(1 for route in routes if route.path == path and method in route.methods)


def _probe_router() -> APIRouter:
    router = APIRouter(prefix=_PROBE_PREFIX)

    @router.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return router


def test_flatten_finds_every_included_route() -> None:
    app = create_app()
    flat = flatten_routes(app.router)

    # Non-vacuity: the authz matrix enumerates 169 routes on 2026-10-25, so a
    # flatten that only saw the docs routes (the failure this helper exists to
    # prevent) or a handful of routers cannot reach this floor.
    assert len(flat) >= 150, len(flat)
    assert all(isinstance(route, APIRoute) for route in flat)
    plain = [route for route in app.routes if isinstance(route, APIRoute)]
    assert len(flat) > len(plain)

    # The expected side is derived independently: FastAPI's own OpenAPI
    # document lists every schema-visible route without walking routers.
    schema_pairs = {
        (verb.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for verb in item
        if verb.upper() in _VERBS
    }
    assert len(schema_pairs) >= 150, len(schema_pairs)
    assert schema_pairs <= _pairs(flat), sorted(schema_pairs - _pairs(flat))[:5]


def test_flatten_accepts_a_plain_router() -> None:
    routes = flatten_routes(_probe_router())
    assert [(route.path, sorted(route.methods)) for route in routes] == [
        (f"{_PROBE_PREFIX}/ping", ["GET"])
    ]


def test_app_with_routers_mounts_once_and_is_idempotent() -> None:
    router = _probe_router()
    path = f"{_PROBE_PREFIX}/ping"

    app = app_with_routers(router)
    assert _count(flatten_routes(app.router), "GET", path) == 1
    assert TestClient(app).get(path).json() == {"ok": "yes"}

    # The same router twice in one call still mounts a single copy.
    twice = app_with_routers(router, router)
    assert _count(flatten_routes(twice.router), "GET", path) == 1

    # No leakage between apps: a fresh factory call does not carry the probe.
    assert _count(flatten_routes(create_app().router), "GET", path) == 0

    # A router the application already mounts is a no-op, which is what makes
    # a task's test keep passing after the lead mounts its router in app.py.
    assert flatten_routes(me.router), "me.router must have routes for this case to mean anything"
    baseline = len(flatten_routes(create_app().router))
    assert len(flatten_routes(app_with_routers(me.router).router)) == baseline


def test_app_with_routers_mounts_a_new_router_next_to_an_existing_one() -> None:
    baseline = len(flatten_routes(create_app().router))
    app = app_with_routers(me.router, _probe_router())
    assert len(flatten_routes(app.router)) == baseline + 1


def test_app_with_routers_refuses_a_router_that_half_overlaps_the_app() -> None:
    first = flatten_routes(me.router)[0]
    verb = sorted(first.methods - {"HEAD", "OPTIONS"})[0]

    def endpoint() -> dict[str, str]:
        return {}

    half = APIRouter()
    half.add_api_route(first.path, endpoint, methods=[verb])
    half.add_api_route("/api/_t00_half/new", endpoint, methods=["GET"])

    with pytest.raises(ValueError, match="partially"):
        app_with_routers(half)
