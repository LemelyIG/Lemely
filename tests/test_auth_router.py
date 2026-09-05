"""FastAPI TestClient coverage of the /api/auth/* endpoints (hermetic)."""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lemely.auth.cooldown import CooldownStore
from lemely.auth.otp import OtpChannel, OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token, mint_access_token
from lemely.db.models.enums import Role
from lemely.runtime.config import Settings
from lemely.runtime.errors import AuthError
from lemely.web.app import create_app
from lemely.web.deps import (
    get_auth_service,
    get_device_registry,
    get_resend_verification_cooldown_store,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
    reset_singletons,
)
from tests.auth_fakes import FakeDeviceRegistry, FakeGoTrueBackend, FakeUserMirror


def _override_cooldowns(app: FastAPI, settings: Settings) -> None:
    """Override both D7.12 cooldown dependencies with fresh in-memory stores.

    Spec §4.4 moved ``get_signup_and_reset_cooldown_store`` /
    ``get_resend_verification_cooldown_store`` onto ``DbCooldownStore``
    (Postgres-backed) in production. Left unoverridden, every
    ``/auth/signup``, ``/auth/verify-email/resend`` or
    ``/auth/password-reset/request`` call this hermetic suite makes would
    stamp the real dev database's ``auth_cooldowns`` table — and, unlike the
    old in-memory ``CooldownStore`` that ``reset_singletons()`` rebuilt fresh
    for every test, that stamp is durable: it outlives the fixture teardown
    and throttles (429) whichever *later* test in the same run reuses the
    same email, exactly as ``test_signup_duplicate_returns_400``'s own
    comment already documents for ``get_user_mirror``. A fresh
    :class:`~lemely.auth.cooldown.CooldownStore` per fixture invocation
    restores that same fresh-per-test isolation.

    Each store is built once, here, and captured by the override lambda's
    closure — **not** constructed inside the lambda. FastAPI re-invokes a
    dependency override on every request with no caching of its own, so a
    lambda that builds ``CooldownStore(...)`` in its own body would hand out
    a brand-new, empty store to every request rather than one store shared
    across the whole test: cooldown would silently never trigger *within* a
    test, only (correctly, but for the wrong reason) look isolated *between*
    tests. Capturing one instance here is what makes it isolated between
    tests while still persisting within one.
    """
    signup_cooldown = CooldownStore(
        clock=lambda: datetime.now(UTC),
        min_seconds=settings.auth.signup_and_reset_cooldown_seconds,
    )
    resend_cooldown = CooldownStore(
        clock=lambda: datetime.now(UTC),
        min_seconds=settings.auth.resend_verification_cooldown_seconds,
    )
    app.dependency_overrides[get_signup_and_reset_cooldown_store] = lambda: signup_cooldown
    app.dependency_overrides[get_resend_verification_cooldown_store] = lambda: resend_cooldown


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
    # Issue #10: /auth/signup now reads the mirror directly (a read-only
    # duplicate-address pre-check gating whether D7.12's cooldown applies at
    # all — see routers/auth.py's `signup` docstring). Override it to the
    # SAME mirror `service` is built on, or this app would fall back to the
    # real, unoverridden DbUserMirror against a database these hermetic tests
    # never touch — which would see every address as unclaimed forever and
    # make `test_signup_duplicate_returns_400`'s second call spuriously 429.
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    _override_cooldowns(app, settings)
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
        json={
            "email": "s@example.com",
            "password": "pw-123456",
            "role": "student",
            "acceptedTerms": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "student"
    assert body["accessToken"]
    assert body["userId"]


@pytest.mark.parametrize("role", ["school_admin", "platform_admin"])
def test_signup_elevated_role_forbidden(
    context: tuple[TestClient, AuthService, Settings], role: str
) -> None:
    # D1.7, revised in scope but not in spirit by D7.1 (which admits `teacher`
    # to self-service signup — see `_SELF_SERVICE_SIGNUP_ROLES`'s own comment
    # in `lemely/web/routers/auth.py`, and `test_web_auth.py`'s
    # `test_signup_elevated_role_still_forbidden`, the fuller, house-style
    # version of this test). `school_admin`/`platform_admin` remain
    # unobtainable by an anonymous caller: requesting either must be a 403 so
    # signup can never be a privilege-escalation path (anonymous caller
    # POSTing role="platform_admin" to mint an admin token).
    client, _, _ = context
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": f"{role}@example.com",
            "password": "pw-123456",
            "role": role,
            "acceptedTerms": True,
        },
    )
    assert resp.status_code == 403, resp.text


def test_signup_duplicate_returns_400(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, _, _ = context
    payload = {
        "email": "dup@example.com",
        "password": "pw-123456",
        "role": "student",
        "acceptedTerms": True,
    }
    assert client.post("/api/auth/signup", json=payload).status_code == 200
    resp = client.post("/api/auth/signup", json=payload)
    assert resp.status_code == 400


def test_login_endpoint(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, _, _ = context
    client.post(
        "/api/auth/signup",
        json={
            "email": "l@example.com",
            "password": "pw-abcdef",
            "role": "student",
            "acceptedTerms": True,
        },
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
        json={
            "email": "w@example.com",
            "password": "right-pw-1",
            "role": "student",
            "acceptedTerms": True,
        },
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
    code = service._otp_store._challenges[(OtpChannel.phone, phone)].code

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


# ── Refresh ───────────────────────────────────────────────────────────────────
#
# The regression these exist for: access tokens expire after an hour, and before
# this endpoint existed nothing renewed them. Every request past that point came
# back 401 "Invalid access token: Signature has expired", which the SPA rendered
# verbatim on screen while its route guard — which only checks that *a* session
# object is in localStorage — kept happily rendering the portal around it.


@pytest.fixture
def refreshable() -> Iterator[tuple[TestClient, AuthService, Settings, FakeDeviceRegistry]]:
    """A client whose auth service registers devices, so refresh tokens are minted.

    ``access_token_ttl_seconds`` is floored at 60 by config, so tests that need an
    already-expired access token mint one directly with an explicit past ``now``
    rather than waiting.
    """
    settings = Settings()
    mirror = FakeUserMirror()
    registry = FakeDeviceRegistry()
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
        device_registry=registry,  # type: ignore[arg-type]
    )
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_device_registry] = lambda: registry
    # See the `context` fixture above for why this override is required now.
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    _override_cooldowns(app, settings)
    client = TestClient(app)
    try:
        yield client, service, settings, registry
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def _signup(client: TestClient, email: str = "r@example.com") -> dict[str, str]:
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "pw-123456",
            "role": "student",
            "deviceId": "device-A",
            "acceptedTerms": True,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_signin_hands_back_a_refresh_token(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    client, _, _, _ = refreshable
    assert _signup(client)["refreshToken"]


def test_refresh_returns_a_usable_new_access_token(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    client, _, settings, _ = refreshable
    body = _signup(client)

    resp = client.post("/api/auth/refresh", json={"refreshToken": body["refreshToken"]})

    assert resp.status_code == 200, resp.text
    renewed = resp.json()
    claims = decode_token(renewed["accessToken"], settings)
    assert claims.sub == body["userId"]
    assert claims.app_role == "student"
    # Not rotated: the client keeps the token it already has (two tabs refreshing
    # concurrently must not be able to invalidate each other).
    assert renewed["refreshToken"] == body["refreshToken"]


def test_refresh_works_once_the_access_token_has_already_expired(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    # The actual bug: an expired access token 401s, and the refresh that is
    # supposed to rescue it must not itself depend on that dead credential.
    client, _, settings, _ = refreshable
    body = _signup(client)
    dead = mint_access_token(
        user_id=uuid.UUID(body["userId"]),
        settings=settings,
        app_role="student",
        provider="email",
        now=datetime.now(UTC) - timedelta(hours=3),
    )
    with pytest.raises(AuthError, match="expired"):
        decode_token(dead, settings)

    resp = client.post(
        "/api/auth/refresh",
        json={"refreshToken": body["refreshToken"]},
        headers={"Authorization": f"Bearer {dead}"},
    )

    assert resp.status_code == 200, resp.text
    assert decode_token(resp.json()["accessToken"], settings).sub == body["userId"]


def test_a_refresh_token_cannot_be_used_as_a_bearer_token(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    # It outlives the access token by a month, so if it also authenticated
    # requests it would quietly become a month-long access token.
    client, _, _, _ = refreshable
    body = _signup(client)

    resp = client.get(
        "/api/me/profile", headers={"Authorization": f"Bearer {body['refreshToken']}"}
    )

    # 401 specifically, not 404: the route exists and rejected the credential.
    assert resp.status_code == 401, resp.text


def test_refresh_is_refused_after_the_device_is_signed_out(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    client, _, _, registry = refreshable
    body = _signup(client)
    session_id = next(iter(registry.rows))
    assert registry.revoke(uuid.UUID(body["userId"]), session_id) is True

    resp = client.post("/api/auth/refresh", json={"refreshToken": body["refreshToken"]})

    assert resp.status_code == 401, resp.text


def test_refresh_is_refused_once_a_newer_login_supersedes_it(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    client, _, _, _ = refreshable
    first = _signup(client)
    second = client.post(
        "/api/auth/login",
        json={"email": "r@example.com", "password": "pw-123456", "deviceId": "device-A"},
    ).json()
    assert second["refreshToken"] != first["refreshToken"]

    stale = client.post("/api/auth/refresh", json={"refreshToken": first["refreshToken"]})
    fresh = client.post("/api/auth/refresh", json={"refreshToken": second["refreshToken"]})

    assert stale.status_code == 401, stale.text
    assert fresh.status_code == 200, fresh.text


def test_refresh_reflects_a_role_changed_since_sign_in(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    # A refresh token lives for a month. If the role were read out of it rather
    # than out of `public.users`, a demoted account would keep its old powers for
    # that entire month.
    client, service, settings, _ = refreshable
    body = _signup(client)
    mirror = service._mirror
    mirror.rows[uuid.UUID(body["userId"])].role = Role.teacher

    resp = client.post("/api/auth/refresh", json={"refreshToken": body["refreshToken"]})

    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "teacher"
    assert decode_token(resp.json()["accessToken"], settings).app_role == "teacher"


@pytest.mark.parametrize(
    "token",
    ["", "not-a-jwt", "a.b.c"],
    ids=["empty", "garbage", "jwt-shaped-garbage"],
)
def test_malformed_refresh_token_is_401_not_500(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry], token: str
) -> None:
    client, _, _, _ = refreshable
    resp = client.post("/api/auth/refresh", json={"refreshToken": token})
    assert resp.status_code == 401, resp.text
