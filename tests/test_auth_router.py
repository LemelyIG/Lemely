"""FastAPI TestClient coverage of the /api/auth/* endpoints (hermetic)."""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token
from lemely.runtime.config import Settings
from lemely.web.app import create_app
from lemely.web.deps import get_auth_service, reset_singletons
from tests.auth_fakes import FakeGoTrueBackend, FakeUserMirror


@pytest.fixture
def context() -> Iterator[tuple[TestClient, AuthService, Settings]]:
    settings = Settings()
    mirror = FakeUserMirror()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(7),
        ttl_seconds=settings.auth.otp_ttl_seconds,
        max_attempts=settings.auth.otp_max_attempts,
        code_length=settings.auth.otp_length,
    )
    service = AuthService(
        gotrue=FakeGoTrueBackend(),
        mirror=mirror,
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
    )
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    client = TestClient(app)
    try:
        yield client, service, settings
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def test_signup_endpoint(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, _, _ = context
    resp = client.post(
        "/api/auth/signup",
        json={"email": "s@example.com", "password": "pw-123456", "role": "student"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "student"
    assert body["accessToken"]
    assert body["userId"]


@pytest.mark.parametrize("role", ["teacher", "school_admin", "platform_admin"])
def test_signup_elevated_role_forbidden(
    context: tuple[TestClient, AuthService, Settings], role: str
) -> None:
    # D1.7: self-service signup may only mint a student account. Requesting any
    # privileged role must be a 403 so signup can never be a privilege-escalation
    # path (anonymous caller POSTing role="platform_admin" to mint an admin token).
    client, _, _ = context
    resp = client.post(
        "/api/auth/signup",
        json={"email": f"{role}@example.com", "password": "pw-123456", "role": role},
    )
    assert resp.status_code == 403, resp.text


def test_signup_duplicate_returns_400(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, _, _ = context
    payload = {"email": "dup@example.com", "password": "pw-123456", "role": "student"}
    assert client.post("/api/auth/signup", json=payload).status_code == 200
    resp = client.post("/api/auth/signup", json=payload)
    assert resp.status_code == 400


def test_login_endpoint(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, _, _ = context
    client.post(
        "/api/auth/signup",
        json={"email": "l@example.com", "password": "pw-abcdef", "role": "student"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "l@example.com", "password": "pw-abcdef"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "student"


def test_login_wrong_password_returns_401(
    context: tuple[TestClient, AuthService, Settings],
) -> None:
    client, _, _ = context
    client.post(
        "/api/auth/signup",
        json={"email": "w@example.com", "password": "right-pw-1", "role": "student"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "w@example.com", "password": "bad-pw-1"},
    )
    assert resp.status_code == 401


def test_otp_request_and_verify(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, service, settings = context
    phone = "+201234500000"
    resp = client.post("/api/auth/otp/request", json={"phone": phone})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "sent"

    # Recover the code from the store (test-only introspection).
    code = service._otp_store._challenges[phone].code

    verify = client.post("/api/auth/otp/verify", json={"phone": phone, "code": code})
    assert verify.status_code == 200, verify.text
    token = verify.json()["accessToken"]
    claims = decode_token(token, settings)
    assert claims.app_role == "parent"
    assert claims.phone == phone


def test_otp_request_surfaces_the_dev_code_for_the_offline_mock_provider(
    context: tuple[TestClient, AuthService, Settings],
) -> None:
    """§G-05's developer affordance, end to end over the wire (D3.16).

    The whole point is that the flow is testable without an SMS provider, so the
    assertion is not "a field is present" but "the field's value logs a parent in".
    """
    client, _, _ = context
    phone = "+201234533333"
    resp = client.post("/api/auth/otp/request", json={"phone": phone})
    assert resp.status_code == 200, resp.text
    dev_code = resp.json()["devCode"]
    assert dev_code, "the offline mock provider is the only source of the code"

    verify = client.post("/api/auth/otp/verify", json={"phone": phone, "code": dev_code})
    assert verify.status_code == 200, verify.text
    assert verify.json()["role"] == "parent"


def test_otp_verify_wrong_code_returns_401(
    context: tuple[TestClient, AuthService, Settings],
) -> None:
    client, _, _ = context
    phone = "+201234511111"
    client.post("/api/auth/otp/request", json={"phone": phone})
    resp = client.post("/api/auth/otp/verify", json={"phone": phone, "code": "999999"})
    assert resp.status_code == 401


def test_otp_resend_within_cooldown_returns_429(
    context: tuple[TestClient, AuthService, Settings],
) -> None:
    # The default resend cooldown (>0s) throttles a rapid second request for the
    # same phone; the two calls here land well inside the window → 429, not 500.
    client, _, _ = context
    phone = "+201234522222"
    first = client.post("/api/auth/otp/request", json={"phone": phone})
    assert first.status_code == 200, first.text
    second = client.post("/api/auth/otp/request", json={"phone": phone})
    assert second.status_code == 429, second.text
