"""Tests for the bearer-token auth dependency (``get_auth_context``).

Exercises the real token-validation path that P1.5 puts in front of every
authenticated route: a valid HS256 token yields an :class:`AuthContext`, and
every failure mode (absent header, bad signature, expired, unknown/missing role)
is a 401 — never a silent anonymous fallthrough.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from lemely.auth.tokens import mint_access_token
from lemely.db.models.enums import Role
from lemely.runtime.config import Settings
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_device_registry,
    get_settings,
)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/whoami")
    def whoami(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> dict[str, str | None]:
        return {"user_id": auth.user_id, "role": auth.role, "email": auth.email}

    return TestClient(app)


def _token(settings: Settings, *, role: str = Role.student.value, **kw: object) -> str:
    return mint_access_token(
        user_id=uuid.uuid4(),
        settings=settings,
        app_role=role,
        provider="email",
        **kw,  # type: ignore[arg-type]
    )


def test_valid_token_yields_context(client: TestClient, settings: Settings) -> None:
    uid = uuid.uuid4()
    token = mint_access_token(
        user_id=uid,
        settings=settings,
        app_role=Role.teacher.value,
        provider="email",
        email="t@example.com",
    )
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"user_id": str(uid), "role": "teacher", "email": "t@example.com"}


def test_missing_header_is_401(client: TestClient) -> None:
    resp = client.get("/whoami")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_garbage_token_is_401(client: TestClient) -> None:
    resp = client.get("/whoami", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_wrong_secret_is_401(client: TestClient, settings: Settings) -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": settings.supabase.jwt_audience,
            "role": "authenticated",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            "app_metadata": {"role": Role.student.value},
        },
        "a-different-secret-that-is-also-long-enough-32b",
        algorithm="HS256",
    )
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_expired_token_is_401(client: TestClient, settings: Settings) -> None:
    token = _token(settings, now=datetime.now(UTC) - timedelta(hours=2), ttl_seconds=3600)
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_unknown_role_is_401(client: TestClient, settings: Settings) -> None:
    token = _token(settings, role="sorcerer")
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_missing_role_claim_is_401(client: TestClient, settings: Settings) -> None:
    # A well-signed token that simply carries no app_metadata.role.
    secret = settings.supabase.jwt_secret.get_secret_value()
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": settings.supabase.jwt_audience,
            "role": "authenticated",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        secret,
        algorithm="HS256",
    )
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_all_five_roles_accepted(client: TestClient, settings: Settings) -> None:
    for role in Role:
        token = _token(settings, role=role.value)
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, role
        assert resp.json()["role"] == role.value


# ── Session liveness (D1.11) ─────────────────────────────────────────────────


class _FakeRegistry:
    """A ``DeviceRegistry`` stand-in whose liveness answer is fixed per test."""

    def __init__(self, *, live: bool) -> None:
        self._live = live
        self.checked: list[str] = []

    def is_session_live(self, session_id: str) -> bool:
        self.checked.append(str(session_id))
        return self._live


def _client_with_registry(settings: Settings, registry: _FakeRegistry) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_device_registry] = lambda: registry

    @app.get("/whoami")
    def whoami(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> dict[str, str | None]:
        return {"user_id": auth.user_id, "role": auth.role}

    return TestClient(app)


def test_token_without_session_id_skips_liveness_check(settings: Settings) -> None:
    registry = _FakeRegistry(live=False)  # would 401 if ever consulted
    client = _client_with_registry(settings, registry)
    token = _token(settings)  # no session_id claim
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert registry.checked == []  # offline path preserved


def test_live_session_is_accepted(settings: Settings) -> None:
    registry = _FakeRegistry(live=True)
    client = _client_with_registry(settings, registry)
    sid = uuid.uuid4()
    token = _token(settings, session_id=sid)
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert registry.checked == [str(sid)]


def test_evicted_session_is_401(settings: Settings) -> None:
    registry = _FakeRegistry(live=False)
    client = _client_with_registry(settings, registry)
    sid = uuid.uuid4()
    token = _token(settings, session_id=sid)
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert registry.checked == [str(sid)]
