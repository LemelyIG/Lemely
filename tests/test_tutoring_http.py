"""The tutoring route classes (SPEC §b.2 legend as amended by PLAN P12, §b.5, SC-26, SC-18).

Every non-PUBLIC tutoring route sends ``Cache-Control: private, no-store`` on
**every** status, including the 401 from the token check, an ``HTTPException``
raised by a handler and FastAPI's own 422; P1-P3 send ``public, max-age=60``
and ``X-Robots-Tag: noindex``. One route class sets each, so these tests mount
probe routers built with the classes and compare them with a control router
built with FastAPI's plain ``APIRoute`` (proof the header comes from the class).
"""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers import tutor_profile, tutoring_directory, tutoring_public
from lemely.web.tutoring_http import PublicTutoringRoute, TutoringRoute
from tests.tutoring_app import app_with_routers, flatten_routes


class _Body(BaseModel):
    count: int


def _probe_router(prefix: str, route_class: type[APIRoute]) -> APIRouter:
    router = APIRouter(prefix=prefix, route_class=route_class)

    @router.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/auth")
    def needs_auth(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> dict[str, str]:
        return {"user": auth.user_id}

    @router.get("/missing")
    def missing() -> dict[str, str]:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Gone."})

    @router.get("/conflict")
    def conflict() -> dict[str, str]:
        raise HTTPException(status_code=409, detail={"code": "tutor_suspended", "message": "No."})

    @router.get("/typed")
    def typed(n: int) -> dict[str, int]:
        return {"n": n}

    @router.post("/body", status_code=201)
    def body(payload: _Body) -> dict[str, int]:
        return {"count": payload.count}

    return router


_CASES = [
    ("GET", "/ok", None, 200),
    ("GET", "/auth", None, 401),
    ("GET", "/missing", None, 404),
    ("GET", "/conflict", None, 409),
    ("GET", "/typed?n=abc", None, 422),
    ("POST", "/body", {"count": "many"}, 422),
    ("POST", "/body", {"count": 3}, 201),
]


def _client() -> TestClient:
    app = app_with_routers(
        _probe_router("/api/probe-private", TutoringRoute),
        _probe_router("/api/probe-public", PublicTutoringRoute),
        _probe_router("/api/probe-plain", APIRoute),
    )
    return TestClient(app)


@pytest.mark.parametrize(("method", "path", "json", "status"), _CASES)
def test_tutoring_route_sets_no_store_on_2xx_401_404_409_and_422(
    method: str, path: str, json: dict[str, object] | None, status: int
) -> None:
    client = _client()
    private = client.request(method, f"/api/probe-private{path}", json=json)
    plain = client.request(method, f"/api/probe-plain{path}", json=json)

    assert private.status_code == plain.status_code == status
    assert private.headers.get("cache-control") == "private, no-store"
    assert "x-robots-tag" not in private.headers
    # The class adds one header and changes nothing else.
    assert private.json() == plain.json()
    assert private.headers.get("www-authenticate") == plain.headers.get("www-authenticate")
    assert "cache-control" not in plain.headers


def test_tutoring_route_keeps_the_401_challenge() -> None:
    response = _client().get("/api/probe-private/auth")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(("method", "path", "json", "status"), _CASES)
def test_public_tutoring_route_sets_public_max_age_and_noindex(
    method: str, path: str, json: dict[str, object] | None, status: int
) -> None:
    client = _client()
    public = client.request(method, f"/api/probe-public{path}", json=json)
    plain = client.request(method, f"/api/probe-plain{path}", json=json)

    assert public.status_code == plain.status_code == status
    assert public.headers.get("cache-control") == "public, max-age=60"
    assert public.headers.get("x-robots-tag") == "noindex"
    assert public.json() == plain.json()


def test_route_class_overrides_a_handler_supplied_cache_header() -> None:
    router = APIRouter(prefix="/api/probe-override", route_class=TutoringRoute)

    @router.get("/cached")
    def cached() -> dict[str, str]:
        raise HTTPException(status_code=404, headers={"Cache-Control": "public, max-age=3600"})

    response = TestClient(app_with_routers(router)).get("/api/probe-override/cached")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"


def test_every_t06_router_uses_its_tutoring_route_class() -> None:
    public = flatten_routes(tutoring_public.router)
    private = flatten_routes(tutoring_directory.router) + flatten_routes(tutor_profile.router)
    assert all(type(route) is PublicTutoringRoute for route in public)
    assert all(type(route) is TutoringRoute for route in private)
    # Non-vacuity: P1-P3, SP1-SP2 and T1-T5 (SPEC §b.2).
    assert (len(public), len(private)) == (3, 7)
    assert not issubclass(PublicTutoringRoute, TutoringRoute)
