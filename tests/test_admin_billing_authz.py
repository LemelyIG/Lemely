"""Every admin billing route is platform_admin only (spec §7), discovered, not listed.

The routes come from the live application (``/api/admin/billing`` prefix, every method), so a
route a later lane adds is covered here with no edit. ``tests/test_authz_matrix_complete.py``
stays the explicit registry; this file proves the guard by request and by wiring, close to the
change, and pins that the nine catalogue routes exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.runtime.config import Settings
from lemely.web import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_auth_context,
    get_settings,
)
from tests.test_authz_matrix_complete import _concrete, _wired_guard
from tests.tutoring_app import flatten_routes

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

PREFIX = "/api/admin/billing"
CATALOGUE_ROUTES = {
    ("GET", f"{PREFIX}/catalogue"),
    ("POST", f"{PREFIX}/tiers"),
    ("PUT", f"{PREFIX}/tiers/{{plan_tier_id}}"),
    ("POST", f"{PREFIX}/tiers/{{plan_tier_id}}/sync"),
    ("POST", f"{PREFIX}/packs"),
    ("PUT", f"{PREFIX}/packs/{{credit_pack_id}}"),
    ("POST", f"{PREFIX}/rates"),
    ("POST", f"{PREFIX}/estimators"),
    ("PUT", f"{PREFIX}/free-allowances"),
}
_HIDDEN = {"HEAD", "OPTIONS"}
BILLING_ROUTES = [
    route for route in flatten_routes(create_app().router) if route.path.startswith(PREFIX)
]
ROUTES = sorted(
    (method, route.path)
    for route in BILLING_ROUTES
    for method in route.methods
    if method not in _HIDDEN
)
NON_ADMIN_ROLES = ("student", "parent", "teacher", "school_admin")


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    data = Settings().model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    settings = Settings.model_validate(data)
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    return application


def test_the_catalogue_routes_are_mounted() -> None:
    assert set(ROUTES) >= CATALOGUE_ROUTES


def test_every_billing_route_is_wired_to_platform_admin_alone() -> None:
    assert BILLING_ROUTES
    for route in BILLING_ROUTES:
        assert _wired_guard(route) == frozenset({"platform_admin"}), route.path


def test_the_parent_router_itself_carries_the_platform_admin_guard() -> None:
    """Handlers that also take ``AdminAuth`` would hide a dropped router-level guard.

    The routes that only read (``GET /catalogue``) and every lane route rely on the router's
    own dependency, so it is pinned on its own, not just through each route's wiring.
    """
    from lemely.web.routers import admin_billing

    guards = [d.dependency for d in admin_billing.router.dependencies]
    assert len(guards) == 1
    guard = guards[0]
    assert guard is not None
    cells = dict(zip(guard.__code__.co_freevars, guard.__closure__ or (), strict=True))
    assert cells["allowed_values"].cell_contents == frozenset({"platform_admin"})


@pytest.mark.parametrize(("method", "path"), ROUTES, ids=str)
def test_anonymous_caller_is_401(app: FastAPI, method: str, path: str) -> None:
    assert TestClient(app).request(method, _concrete(path)).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "role"),
    [(m, p, r) for m, p in ROUTES for r in NON_ADMIN_ROLES],
    ids=str,
)
def test_every_other_role_is_403(app: FastAPI, method: str, path: str, role: str) -> None:
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id="u1", role=role)
    assert TestClient(app).request(method, _concrete(path), json={}).status_code == 403


@pytest.mark.parametrize(("method", "path"), ROUTES, ids=str)
def test_a_teacher_assistant_acting_for_a_lead_is_403(app: FastAPI, method: str, path: str) -> None:
    """An assistant's platform role is ``teacher``; the acting header never widens it."""
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id="assistant-1", role="teacher"
    )
    resp = TestClient(app).request(
        method,
        _concrete(path),
        json={},
        headers={ACTING_TEACHER_HEADER: "6f7f0b0e-6a3b-4a5e-9a3c-1d2e3f4a5b6c"},
    )
    assert resp.status_code == 403
