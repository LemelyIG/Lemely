"""The access gate (``[access] allowed_email_domains``): matching, settings, every enforcement path.

While Lemely is not launched, only verified accounts on an allowed email domain may sign up, log
in or call an authenticated route. Everything here is hermetic (in-memory GoTrue, mirror and OTP
store, no database), and each guard has a test that goes red when the guard is removed: the red
proofs are recorded in the report that shipped this file.

Sections: pure matching, settings parsing, the auth service flows, the HTTP surface (signup,
login, refresh, the central dependency, ``/api/access/config``), and the route-table walk that
proves no authenticated route can bypass the dependency.
"""

from __future__ import annotations

import random
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import pytest
from fastapi import Depends, FastAPI, Security
from fastapi.testclient import TestClient

from lemely.auth.cooldown import CooldownStore
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService, DeviceContext
from lemely.auth.tokens import mint_access_token
from lemely.core.access import email_domain, is_allowed_email, normalise_domain
from lemely.db.models.enums import Role
from lemely.runtime.config import AccessSettings, Settings
from lemely.runtime.errors import AccessRestrictedError
from lemely.web.app import create_app
from lemely.web.deps import (
    ALLOW_UNVERIFIED_SCOPE,
    AuthContext,
    get_auth_context,
    get_auth_service,
    get_device_registry,
    get_resend_verification_cooldown_store,
    get_settings,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
    require_role,
    reset_singletons,
)
from tests.auth_fakes import (
    FakeAuthTokenService,
    FakeDeviceRegistry,
    FakeEmailProvider,
    FakeGoTrueBackend,
    FakeUserMirror,
)
from tests.test_authz_matrix_complete import EXPECTED, PUBLIC, ROUTES, _concrete, _flatten, _walk

if TYPE_CHECKING:
    from collections.abc import Iterator

ALLOWED = ["lemelyig.com"]
NOW = datetime.now(UTC)


# ── Pure matching ────────────────────────────────────────────────────────────

ACCEPTED = [
    "a@lemelyig.com",
    "A@Lemelyig.COM",  # case-insensitive
    "  a@lemelyig.com  ",  # trimmed
    "first.last+tag@lemelyig.com",
]
REFUSED = [
    "x@sub.lemelyig.com",  # subdomain
    "x@lemelyig.com.evil.com",  # suffix lookalike
    "x@evil-lemelyig.com",  # prefix lookalike
    "x@lemelyig.co",  # sibling TLD
    "x@lemelyig.com.",  # trailing dot
    "x@.lemelyig.com",  # leading dot
    "x@lemelyig",  # single label
    "x@@lemelyig.com",  # double at
    '"x@lemelyig.com"@evil.com',  # quoted local part, last @ is evil.com
    'x@evil.com"@lemelyig.com',  # quote smuggled into the local part
    "x@evil.com,x@lemelyig.com",  # address list
    "x@lemelyig.com evil.com",  # whitespace in the domain
    "x y@lemelyig.com",  # whitespace in the local part
    "x@lem\u0435lyig.com",  # Cyrillic e (U+0435) homoglyph
    "x@lemelyig.c\u043em",  # Cyrillic o (U+043E) homoglyph
    "x@lemely\u0131g.com",  # dotless i (U+0131)
    "x@\uff2c\uff25\uff2d\uff25\uff2c\uff39\uff29\uff27.com",  # full-width letters
    "x@lemelyig.com\u200b",  # zero-width space
    "x\u212a@lemelyig.com",  # Kelvin sign in the local part
    "@lemelyig.com",  # no local part
    "lemelyig.com",  # no @ at all
    "",
    "   ",
]


@pytest.mark.parametrize("address", ACCEPTED)
def test_exact_domain_is_accepted(address: str) -> None:
    assert is_allowed_email(address, ALLOWED)


@pytest.mark.parametrize("address", REFUSED)
def test_lookalikes_and_tricks_are_refused(address: str) -> None:
    assert not is_allowed_email(address, ALLOWED), address


def test_a_missing_address_is_refused() -> None:
    assert not is_allowed_email(None, ALLOWED)


def test_a_kelvin_sign_domain_cannot_fold_onto_an_allowed_ascii_domain() -> None:
    """``str.lower`` maps U+212A onto ASCII ``k``: the ASCII check must run first."""
    assert not is_allowed_email("x@marke\u212a.com", ["markek.com"])
    assert is_allowed_email("x@markek.com", ["markek.com"])


def test_the_configured_list_is_normalised_too() -> None:
    assert is_allowed_email("a@lemelyig.com", ["@LemelyIG.com"])
    assert not is_allowed_email("a@lemelyig.com", ["\u043d\u0435-\u0434\u043e\u043c\u0435\u043d"])
    assert not is_allowed_email("a@lemelyig.com", [])


def test_domain_extraction_uses_the_last_at() -> None:
    assert email_domain("A@Lemelyig.com") == "lemelyig.com"
    assert email_domain('"a@b.com"@evil.com') is None  # the quote makes the local part invalid
    assert normalise_domain(" @Lemelyig.com ") == "lemelyig.com"
    assert normalise_domain("lemelyig") is None


# ── Settings ─────────────────────────────────────────────────────────────────


def test_default_is_open() -> None:
    assert Settings().access.allowed_email_domains == []
    assert not Settings().access.restricted


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("lemelyig.com", ["lemelyig.com"]),
        (" Lemelyig.com , @b.org ", ["lemelyig.com", "b.org"]),
        ('["lemelyig.com"]', ["lemelyig.com"]),
        ("lemelyig.com lemelyig.com", ["lemelyig.com"]),
        ("", []),
        ("   ", []),
    ],
)
def test_env_var_parses(monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]) -> None:
    monkeypatch.setenv("LEMELY_ACCESS__ALLOWED_EMAIL_DOMAINS", raw)
    settings = Settings()
    assert settings.access.allowed_email_domains == expected
    assert settings.access.restricted is bool(expected)


@pytest.mark.parametrize(
    "bad", ["localhost", "not a domain!", "a@b.com", "\u043b\u0435\u043c\u0435\u043b\u0438.com"]
)
def test_a_malformed_domain_fails_loudly_at_startup(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("LEMELY_ACCESS__ALLOWED_EMAIL_DOMAINS", bad)
    with pytest.raises(ValueError, match="not a domain"):
        Settings()


def test_toml_list_loads() -> None:
    settings = Settings.model_validate({"access": {"allowed_email_domains": ["B.org"]}})
    assert settings.access.allowed_email_domains == ["b.org"]
    assert AccessSettings(allowed_email_domains=[]).restricted is False


# ── Auth service flows ───────────────────────────────────────────────────────


def _settings(domains: list[str] | None = None) -> Settings:
    return Settings.model_validate({"access": {"allowed_email_domains": domains or []}})


class _RecordingSms:
    delivers_out_of_band = False

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_code(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))


class _Stack:
    """One set of fakes, with services built on it under open and restricted settings."""

    def __init__(self, domains: list[str]) -> None:
        self.gotrue = FakeGoTrueBackend()
        self.mirror = FakeUserMirror()
        self.devices = FakeDeviceRegistry()
        self.email = FakeEmailProvider()
        self.tokens = FakeAuthTokenService()
        self.sms = _RecordingSms()
        self.otp = OtpStore(
            clock=lambda: datetime.now(UTC),
            rng=random.Random(7),
            ttl_seconds=300,
            max_attempts=5,
            code_length=6,
        )
        self.open_settings = _settings()
        self.settings = _settings(domains)
        self.open = self._service(self.open_settings)
        self.restricted = self._service(self.settings)

    def _service(self, settings: Settings) -> AuthService:
        return AuthService(
            gotrue=self.gotrue,
            mirror=self.mirror,
            sms=self.sms,
            otp_store=self.otp,
            settings=settings,
            device_registry=self.devices,
            email=self.email,
            tokens=self.tokens,
        )


@pytest.fixture
def stack() -> _Stack:
    return _Stack(ALLOWED)


def test_signup_with_a_disallowed_email_creates_nothing(stack: _Stack) -> None:
    with pytest.raises(AccessRestrictedError) as caught:
        stack.restricted.signup("x@example.com", "pw-123456", Role.student)
    assert caught.value.reason == "domain"
    assert stack.gotrue._by_email == {}, "a GoTrue user was created"
    assert stack.mirror.rows == {}, "a users row was created"
    assert stack.devices.rows == {}, "a device was registered"
    assert stack.email.sent_verifications == [], "a verification mail was sent"


def test_signup_with_an_allowed_email_succeeds_unverified(stack: _Stack) -> None:
    result = stack.restricted.signup("Dev@Lemelyig.com", "pw-123456", Role.student)
    row = stack.mirror.rows[result.user_id]
    assert row.email_verified_at is None, "signup must not self-verify"


def test_signup_is_open_when_unrestricted(stack: _Stack) -> None:
    result = stack.open.signup("x@example.com", "pw-123456", Role.student)
    assert result.user_id in stack.mirror.rows


def test_login_is_refused_for_a_disallowed_account_and_mints_no_session(stack: _Stack) -> None:
    stack.open.signup("x@example.com", "pw-123456", Role.student)
    with pytest.raises(AccessRestrictedError):
        stack.restricted.login(
            "x@example.com", "pw-123456", device=DeviceContext(client_device_id="d1")
        )
    assert stack.devices.rows == {}, "a device session was registered for a refused login"


def test_login_works_for_an_allowed_account(stack: _Stack) -> None:
    stack.open.signup("dev@lemelyig.com", "pw-123456", Role.student)
    result = stack.restricted.login("dev@lemelyig.com", "pw-123456")
    assert result.access_token


def test_refresh_is_refused_for_a_disallowed_account(stack: _Stack) -> None:
    signup = stack.open.signup(
        "x@example.com", "pw-123456", Role.student, device=DeviceContext(client_device_id="d1")
    )
    assert signup.refresh_token
    with pytest.raises(AccessRestrictedError):
        stack.restricted.refresh(signup.refresh_token)
    # And the unrestricted service still redeems it, so the refusal is the gate, not a broken token.
    assert stack.open.refresh(signup.refresh_token).access_token


def test_refresh_still_works_for_an_allowed_account(stack: _Stack) -> None:
    signup = stack.open.signup(
        "dev@lemelyig.com", "pw-123456", Role.student, device=DeviceContext(client_device_id="d1")
    )
    assert signup.refresh_token
    assert stack.restricted.refresh(signup.refresh_token).access_token


def test_phone_otp_is_refused_and_creates_no_parent(stack: _Stack) -> None:
    with pytest.raises(AccessRestrictedError):
        stack.restricted.verify_otp("+201001234567", "123456")
    assert stack.mirror.rows == {}, "a phone-only parent was created"
    with pytest.raises(AccessRestrictedError):
        stack.restricted.request_otp("+201001234567")
    assert stack.sms.sent == [], "an SMS was sent to a phone that cannot get in"


def test_phone_otp_login_of_an_allowed_parent_still_works(stack: _Stack) -> None:
    uid = uuid.uuid4()
    stack.mirror.upsert(uid, email="p@lemelyig.com", role=Role.parent, phone="+201001234567")
    # While restricted the code is never handed back by the API: it goes out by SMS only.
    assert stack.restricted.request_otp("+201001234567") is None
    (_, code) = stack.sms.sent[-1]
    assert stack.restricted.verify_otp("+201001234567", code).user_id == uid


def test_parent_signup_code_is_refused_before_any_mail(stack: _Stack) -> None:
    with pytest.raises(AccessRestrictedError):
        stack.restricted.request_parent_signup_code("x@example.com")
    assert stack.email.sent_signup_codes == []
    with pytest.raises(AccessRestrictedError):
        stack.restricted.verify_parent_signup_code("x@example.com", "123456")
    stack.restricted.request_parent_signup_code("p@lemelyig.com")
    assert [e for e, _ in stack.email.sent_signup_codes] == ["p@lemelyig.com"]


# ── HTTP surface ─────────────────────────────────────────────────────────────


def _client(stack: _Stack) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: stack.settings
    app.dependency_overrides[get_auth_service] = lambda: stack.restricted
    app.dependency_overrides[get_user_mirror] = lambda: stack.mirror
    app.dependency_overrides[get_device_registry] = lambda: stack.devices
    signup_cooldown = CooldownStore(clock=lambda: datetime.now(UTC), min_seconds=0)
    resend_cooldown = CooldownStore(clock=lambda: datetime.now(UTC), min_seconds=0)
    app.dependency_overrides[get_signup_and_reset_cooldown_store] = lambda: signup_cooldown
    app.dependency_overrides[get_resend_verification_cooldown_store] = lambda: resend_cooldown
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


@pytest.fixture
def http(stack: _Stack) -> Iterator[TestClient]:
    yield from _client(stack)


def _signup_body(email: str) -> dict[str, object]:
    return {"email": email, "password": "pw-123456", "role": "student", "acceptedTerms": True}


def test_http_signup_disallowed_is_403_access_restricted(http: TestClient, stack: _Stack) -> None:
    resp = http.post("/api/auth/signup", json=_signup_body("x@example.com"))
    assert resp.status_code == 403
    assert resp.json() == {"detail": {"code": "access_restricted", "reason": "domain"}}
    assert stack.mirror.rows == {} and stack.gotrue._by_email == {}


def test_http_signup_of_a_lookalike_is_403(http: TestClient, stack: _Stack) -> None:
    for email in ("x@sub.lemelyig.com", "x@lemelyig.com.evil.com", "x@lemelyig.co"):
        assert http.post("/api/auth/signup", json=_signup_body(email)).status_code == 403, email
    assert stack.mirror.rows == {}


def test_http_signup_allowed_is_200(http: TestClient) -> None:
    resp = http.post("/api/auth/signup", json=_signup_body("dev@lemelyig.com"))
    assert resp.status_code == 200, resp.text


def test_http_parent_signup_with_a_disallowed_email_is_403(http: TestClient, stack: _Stack) -> None:
    resp = http.post(
        "/api/auth/parent/request-code", json={"email": "p@example.com", "inviteCode": "ANYCODE"}
    )
    # Either the access gate (403 access_restricted) or the invite check: never a created account.
    assert resp.status_code in (403, 404), resp.text
    assert stack.mirror.rows == {}


def test_http_login_disallowed_is_403(http: TestClient, stack: _Stack) -> None:
    stack.open.signup("x@example.com", "pw-123456", Role.student)
    resp = http.post("/api/auth/login", json={"email": "x@example.com", "password": "pw-123456"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "access_restricted"


def test_http_refresh_disallowed_is_403(http: TestClient, stack: _Stack) -> None:
    signup = stack.open.signup(
        "x@example.com", "pw-123456", Role.student, device=DeviceContext(client_device_id="d1")
    )
    resp = http.post("/api/auth/refresh", json={"refreshToken": signup.refresh_token})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "access_restricted"


def test_access_config_reports_restricted_without_the_domains(
    http: TestClient, stack: _Stack
) -> None:
    resp = http.get("/api/access/config")
    assert resp.status_code == 200
    assert resp.json() == {"restricted": True}
    assert "lemelyig" not in resp.text
    assert resp.headers["cache-control"] == "no-store"


def test_access_config_is_open_when_unrestricted(stack: _Stack) -> None:
    stack.settings = _settings()
    for client in _client(stack):
        assert client.get("/api/access/config").json() == {"restricted": False}


# ── The central dependency ───────────────────────────────────────────────────

_PROBE_OK = {"ok": True}


def _probe_app(stack: _Stack) -> FastAPI:
    """A tiny app whose routes use the real ``get_auth_context`` in each of its shapes."""
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: stack.settings
    app.dependency_overrides[get_user_mirror] = lambda: stack.mirror
    app.dependency_overrides[get_device_registry] = lambda: stack.devices

    @app.get("/any")
    def any_role(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> dict[str, bool]:
        return _PROBE_OK

    @app.get("/student")
    def student_only(
        auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    ) -> dict[str, bool]:
        return _PROBE_OK

    @app.get("/pending")
    def pending(
        auth: Annotated[AuthContext, Security(get_auth_context, scopes=[ALLOW_UNVERIFIED_SCOPE])],
    ) -> dict[str, bool]:
        return _PROBE_OK

    return app


def _account(
    stack: _Stack, email: str, *, verified: bool, role: Role = Role.student
) -> tuple[uuid.UUID, dict[str, str]]:
    uid = uuid.uuid4()
    stack.mirror.upsert(uid, email=email, role=role)
    if verified:
        stack.mirror.mark_email_verified(uid, verified_at=NOW)
    token = mint_access_token(
        user_id=uid,
        settings=stack.settings,
        app_role=role.value,
        provider="email",
        email=email,
    )
    return uid, {"Authorization": f"Bearer {token}"}


def _status(client: TestClient, path: str, headers: dict[str, str]) -> tuple[int, object]:
    resp = client.get(path, headers=headers)
    return resp.status_code, (resp.json().get("detail") if resp.status_code != 200 else None)


def test_verified_allowed_account_passes_everywhere(stack: _Stack) -> None:
    client = TestClient(_probe_app(stack))
    _, headers = _account(stack, "dev@lemelyig.com", verified=True)
    assert [
        client.get(p, headers=headers).status_code for p in ("/any", "/student", "/pending")
    ] == [
        200,
        200,
        200,
    ]


def test_disallowed_account_is_403_on_every_shape_even_with_a_valid_token(stack: _Stack) -> None:
    client = TestClient(_probe_app(stack))
    _, headers = _account(stack, "x@example.com", verified=True)
    for path in ("/any", "/student", "/pending"):
        assert _status(client, path, headers) == (
            403,
            {"code": "access_restricted", "reason": "domain"},
        ), path


def test_subdomain_and_lookalike_accounts_are_refused(stack: _Stack) -> None:
    client = TestClient(_probe_app(stack))
    for email in ("a@sub.lemelyig.com", "a@lemelyig.com.evil.com", "a@lemelyig.co"):
        _, headers = _account(stack, email, verified=True)
        assert client.get("/any", headers=headers).status_code == 403, email


def test_unverified_allowed_account_is_refused_except_on_the_verification_scope(
    stack: _Stack,
) -> None:
    client = TestClient(_probe_app(stack))
    _, headers = _account(stack, "dev@lemelyig.com", verified=False)
    assert _status(client, "/any", headers) == (
        403,
        {"code": "access_restricted", "reason": "unverified"},
    )
    assert client.get("/student", headers=headers).status_code == 403
    assert client.get("/pending", headers=headers).status_code == 200


def test_the_verification_scope_does_not_waive_the_domain_check(stack: _Stack) -> None:
    client = TestClient(_probe_app(stack))
    _, headers = _account(stack, "x@example.com", verified=False)
    assert client.get("/pending", headers=headers).status_code == 403


def test_a_token_for_a_user_with_no_row_is_refused(stack: _Stack) -> None:
    client = TestClient(_probe_app(stack))
    token = mint_access_token(
        user_id=uuid.uuid4(),
        settings=stack.settings,
        app_role="student",
        provider="email",
        email="dev@lemelyig.com",
    )
    assert client.get("/any", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_the_gate_reads_the_stored_email_not_the_token_claim(stack: _Stack) -> None:
    """A token that *claims* an allowed email is not enough: the stored account decides."""
    client = TestClient(_probe_app(stack))
    uid, _ = _account(stack, "x@example.com", verified=True)
    token = mint_access_token(
        user_id=uid,
        settings=stack.settings,
        app_role="student",
        provider="email",
        email="dev@lemelyig.com",
    )
    assert client.get("/any", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_an_open_session_is_cut_off_immediately(stack: _Stack) -> None:
    client = TestClient(_probe_app(stack))
    uid, headers = _account(stack, "dev@lemelyig.com", verified=True)
    assert client.get("/any", headers=headers).status_code == 200
    stack.mirror.rows[uid].email = "dev@example.com"  # the account stops qualifying
    assert client.get("/any", headers=headers).status_code == 403
    stack.mirror.rows.pop(uid)  # or disappears
    assert client.get("/any", headers=headers).status_code == 403


def test_unauthenticated_is_still_401_not_403(stack: _Stack) -> None:
    client = TestClient(_probe_app(stack))
    assert client.get("/any").status_code == 401


def test_open_access_changes_nothing(stack: _Stack) -> None:
    stack.settings = _settings()
    client = TestClient(_probe_app(stack))
    _, headers = _account(stack, "anyone@example.com", verified=False)
    assert [
        client.get(p, headers=headers).status_code for p in ("/any", "/student", "/pending")
    ] == [
        200,
        200,
        200,
    ]


# ── Route-table walk: no authenticated route bypasses the dependency ─────────

_VERIFY_ROUTES = {
    ("POST", "/api/auth/verify-email/code"),
    ("POST", "/api/auth/verify-email/resend"),
}


def _declared_scopes(dependant: object) -> list[str]:
    """Scopes in effect on this dependant: its own ``Security(...)`` scopes plus its parents'.

    Older FastAPI exposed the union as ``Dependant.oauth_scopes``; newer releases (CI
    installs the newest) keep only ``own_oauth_scopes`` and ``parent_oauth_scopes``.
    """
    own = getattr(dependant, "own_oauth_scopes", None)
    if own is not None:
        return [*(getattr(dependant, "parent_oauth_scopes", None) or []), *own]
    legacy = getattr(dependant, "oauth_scopes", None)
    if legacy is not None:
        return list(legacy)
    raise AssertionError("FastAPI Dependant exposes no scope attribute")


def _gate_dependants(route: object) -> list[object]:
    return [d for d in _walk(route.dependant) if d.call is get_auth_context]  # type: ignore[attr-defined]


def test_every_non_public_route_runs_the_central_gate_and_no_public_route_does() -> None:
    bypass: list[tuple[str, str]] = []
    wrongly_gated: list[tuple[str, str]] = []
    for route in _flatten(create_app().router):
        for method in route.methods - {"HEAD", "OPTIONS"}:
            gated = bool(_gate_dependants(route))
            if EXPECTED[(method, route.path)] == PUBLIC:
                if gated:
                    wrongly_gated.append((method, route.path))
            elif not gated:
                bypass.append((method, route.path))
    assert bypass == [], f"authenticated route(s) that never run get_auth_context: {bypass}"
    assert wrongly_gated == []
    assert len(ROUTES) > 200  # non-vacuous: the walk saw the real surface


def test_only_the_two_verification_routes_waive_the_verified_check() -> None:
    waived = {
        (method, route.path)
        for route in _flatten(create_app().router)
        for method in route.methods - {"HEAD", "OPTIONS"}
        if any(ALLOW_UNVERIFIED_SCOPE in _declared_scopes(d) for d in _gate_dependants(route))
    }
    assert waived == _VERIFY_ROUTES


def test_no_authenticated_route_serves_a_disallowed_caller() -> None:
    """Behavioural sweep over the real route table with a real token of a refused account."""
    stack = _Stack(ALLOWED)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: stack.settings
    app.dependency_overrides[get_user_mirror] = lambda: stack.mirror
    app.dependency_overrides[get_device_registry] = lambda: stack.devices
    client = TestClient(app)
    leaked: list[tuple[str, str, int]] = []
    checked = 0
    try:
        for role in (
            Role.student,
            Role.teacher,
            Role.parent,
            Role.school_admin,
            Role.platform_admin,
        ):
            _, headers = _account(stack, f"{role.value}@example.com", verified=True, role=role)
            for method, path in ROUTES:
                if EXPECTED[(method, path)] == PUBLIC:
                    continue
                resp = client.request(method, _concrete(path), headers=headers)
                checked += 1
                body = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                detail = body.get("detail") if isinstance(body, dict) else None
                is_role_403 = resp.status_code == 403 and detail != {
                    "code": "access_restricted",
                    "reason": "domain",
                }
                if resp.status_code != 403 or is_role_403:
                    leaked.append((method, path, resp.status_code))
    finally:
        app.dependency_overrides.clear()
        reset_singletons()
    assert checked > 1000
    # A role-gated route answers a wrong-role caller 403 *role*; the gate must come first, so
    # every answer for a refused account is the access refusal.
    assert leaked == [], leaked[:10]


# ── Source scan: nothing else decodes a bearer token ─────────────────────────

_PACKAGE = Path(__file__).resolve().parents[1] / "lemely"


_BYPASS_PATTERN = re.compile(
    r"\bdecode_token\(|\bHTTPBearer\(|\bjwt\.decode\(|\bdecode_refresh_token\("
    r"|headers(?:\.get\(|\[)\s*[\"']authorization[\"']"
    r"|Header\(\s*alias\s*=\s*[\"']authorization"
    r"|\bauthorization\s*:\s*(?:Annotated|str)",
    re.IGNORECASE,
)


def test_only_the_central_dependency_decodes_a_bearer_token() -> None:
    allowed = {
        "lemely/auth/tokens.py",
        "lemely/auth/__init__.py",
        "lemely/auth/service.py",  # redeems refresh tokens at /api/auth/refresh (own gate)
        "lemely/web/deps.py",
    }
    pattern = _BYPASS_PATTERN
    offenders = sorted(
        str(path.relative_to(_PACKAGE.parent))
        for path in _PACKAGE.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
        and str(path.relative_to(_PACKAGE.parent)) not in allowed
    )
    assert offenders == [], (
        f"a second bearer-token decode path bypasses the access gate: {offenders}"
    )


# ── No dev links while restricted (M1) ───────────────────────────────────────


def test_dev_links_and_codes_are_stripped_while_access_is_restricted(stack: _Stack) -> None:
    opened = stack.open.signup("a@example.com", "pw-123456", Role.student)
    assert opened.verification_dev_link and opened.verification_dev_code  # the mock hands them back

    restricted = stack.restricted.signup("dev@lemelyig.com", "pw-123456", Role.student)
    assert restricted.verification_dev_link is None
    assert restricted.verification_dev_code is None
    # A resend for accounts that were not just issued a code (the OTP resend cooldown).
    plain, other = uuid.uuid4(), uuid.uuid4()
    stack.mirror.upsert(plain, email="r@lemelyig.com", role=Role.student)
    stack.mirror.upsert(other, email="r@example.com", role=Role.student)
    assert stack.restricted.resend_verification(plain) == (None, None)
    assert stack.open.resend_verification(other) != (None, None)
    assert stack.restricted.request_parent_signup_code("p@lemelyig.com") is None


def test_http_signup_never_returns_a_dev_link_while_restricted(
    http: TestClient,
) -> None:
    body = http.post("/api/auth/signup", json=_signup_body("dev@lemelyig.com")).json()
    assert body.get("devLink") is None
    assert body.get("devCode") is None


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "lemely-backend-staging")


def _startup(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lemely.web.app.get_settings", lambda: settings)
    with TestClient(create_app()):
        pass


def test_a_deployed_restricted_service_with_no_email_provider_refuses_to_start(
    deployed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(RuntimeError, match="no email provider"):
        _startup(_settings(ALLOWED), monkeypatch)


def test_startup_is_fine_with_a_provider_open_access_or_locally(
    deployed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_key = Settings.model_validate(
        {"access": {"allowed_email_domains": ALLOWED}, "email": {"api_key": "re_test"}}
    )
    _startup(with_key, monkeypatch)
    _startup(_settings(), monkeypatch)  # open access: nothing to protect
    monkeypatch.delenv("K_SERVICE")
    _startup(_settings(ALLOWED), monkeypatch)  # a laptop: links are stripped instead


# ── A changed GoTrue email loses its verification (M3) ───────────────────────


class _EmailChangedGoTrue(FakeGoTrueBackend):
    """A GoTrue whose password grant now reports a different address for the same user."""

    def __init__(self, inner: FakeGoTrueBackend, new_email: str) -> None:
        super().__init__()
        self._inner, self._new_email = inner, new_email

    def password_grant(self, email: str, password: str):  # type: ignore[no-untyped-def]
        from lemely.auth.gotrue import GoTrueToken, GoTrueUser

        token = self._inner.password_grant(email, password)
        return GoTrueToken(
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            user=GoTrueUser(id=token.user.id, email=self._new_email),
        )


def _verified_account(stack: _Stack, email: str) -> uuid.UUID:
    result = stack.open.signup(email, "pw-123456", Role.student)
    stack.mirror.mark_email_verified(result.user_id, verified_at=NOW)
    return result.user_id


def test_login_that_changes_the_email_to_another_allowed_address_is_unverified(
    stack: _Stack,
) -> None:
    uid = _verified_account(stack, "old@lemelyig.com")
    service = AuthService(
        gotrue=_EmailChangedGoTrue(stack.gotrue, "new@lemelyig.com"),
        mirror=stack.mirror,
        sms=stack.sms,
        otp_store=stack.otp,
        settings=stack.settings,
    )
    service.login("old@lemelyig.com", "pw-123456")
    row = stack.mirror.rows[uid]
    assert row.email == "new@lemelyig.com"
    assert row.email_verified_at is None, "the old inbox's proof must not cover the new address"
    client = TestClient(_probe_app(stack))
    token = mint_access_token(
        user_id=uid, settings=stack.settings, app_role="student", provider="email"
    )
    headers = {"Authorization": f"Bearer {token}"}
    assert _status(client, "/any", headers) == (
        403,
        {"code": "access_restricted", "reason": "unverified"},
    )


def test_login_that_changes_the_email_to_a_disallowed_domain_is_refused(stack: _Stack) -> None:
    uid = _verified_account(stack, "old@lemelyig.com")
    service = AuthService(
        gotrue=_EmailChangedGoTrue(stack.gotrue, "old@example.com"),
        mirror=stack.mirror,
        sms=stack.sms,
        otp_store=stack.otp,
        settings=stack.settings,
    )
    with pytest.raises(AccessRestrictedError):
        service.login("old@lemelyig.com", "pw-123456")
    assert stack.mirror.rows[uid].email == "old@lemelyig.com", "the row must not be rewritten"


def test_a_case_only_change_keeps_the_verification(stack: _Stack) -> None:
    uid = _verified_account(stack, "old@lemelyig.com")
    stack.mirror.upsert(uid, email="OLD@lemelyig.com", role=Role.student)
    assert stack.mirror.rows[uid].email_verified_at is not None


def test_the_bearer_scan_catches_each_way_around_the_gate() -> None:
    """The scan's own pattern must flag every bypass shape (checked on sample source)."""
    source_pattern = _BYPASS_PATTERN
    for sample in (
        "claims = decode_token(t, s)",
        "jwt.decode(token, key)",
        "decode_refresh_token(t, s)",
        'request.headers.get("Authorization")',
        "request.headers['authorization']",
        'x: str = Header(alias="Authorization")',
        "authorization: str | None = None",
        "authorization: Annotated[str, Header()]",
        "HTTPBearer(auto_error=False)",
    ):
        assert source_pattern.search(sample), sample


def test_a_refused_address_keeps_getting_403_not_429_on_retries(
    http: TestClient, stack: _Stack
) -> None:
    cooldown = CooldownStore(clock=lambda: datetime.now(UTC), min_seconds=600)
    http.app.dependency_overrides[get_signup_and_reset_cooldown_store] = lambda: cooldown  # type: ignore[attr-defined]
    for _ in range(3):
        resp = http.post("/api/auth/signup", json=_signup_body("x@example.com"))
        assert resp.status_code == 403, resp.text
    # An allowed address still meets the cooldown as before (the first signup stamps it).
    assert http.post("/api/auth/signup", json=_signup_body("dev@lemelyig.com")).status_code == 200
