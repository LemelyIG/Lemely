"""HTTP-boundary tests for the four new account-lifecycle auth routes (D7).

Complements ``tests/test_auth_router.py`` (signup/login/refresh/OTP, unchanged
in shape by this issue) and ``tests/test_auth_service.py`` (the service-level
proof of every business rule these routes are a thin HTTP layer over). This
file is the focused, readable proof that ``/verify-email``,
``/verify-email/resend``, ``/password-reset/request`` and
``/password-reset/confirm`` exist at their documented paths, carry their
documented guard (three PUBLIC, one AUTH_ANY), map domain errors to the
right status code, and enforce D7.12's cooldowns end to end over real DTOs.

``tests/test_authz_matrix_complete.py`` is the exhaustive, generated proof
that every route here carries its declared guard against every role; this
file proves the four routes actually do what they are for — mirroring
``tests/test_web_invites.py``'s own division of labour for the same reason.

Hermetic throughout: :class:`~lemely.auth.service.AuthService` is built on
the fakes in ``tests/auth_fakes.py`` (no Postgres, no GoTrue network, no
Gemini), and the two D7.12 cooldown stores are the *real*
:class:`~lemely.auth.cooldown.CooldownStore` singletons wired by
``deps.py`` — a wall-clock, in-process store needs no double to behave
correctly in a test that runs in milliseconds.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.db.models.enums import Role
from lemely.runtime.config import Settings
from lemely.web.app import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_auth_service,
    get_auth_token_service,
    get_resend_verification_cooldown_store,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
    reset_singletons,
)
from tests.auth_fakes import (
    FakeAuthTokenService,
    FakeEmailProvider,
    FakeGoTrueBackend,
    FakeUserMirror,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def context() -> Iterator[tuple[TestClient, AuthService, FakeUserMirror]]:
    """A hermetic client wired to fake GoTrue/mirror/email/token collaborators.

    Mirrors ``tests/test_auth_router.py``'s own ``context`` fixture, extended
    with the two D7.6/D7.7 collaborators (``email``, ``tokens``) so signup
    actually mints a verification token and the three redemption/resend
    routes have something real to exercise — a hermetic ``AuthService`` built
    *without* them would make every one of D7's new routes raise "not
    configured" regardless of what token it was handed, which would prove
    nothing about the routes themselves.

    The two cooldown stores are deliberately **not** overridden: they are
    real, in-process, wall-clock ``CooldownStore`` singletons (``deps.py``),
    and ``reset_singletons()`` in the teardown gives every test a fresh one —
    exactly the discipline ``test_auth_router.py``'s own fixture already
    applies to the singletons it does not override either.

    ``get_user_mirror`` **is** overridden, to the same ``mirror`` instance
    ``service`` is built on: the signup route now reads the mirror directly
    (a read-only duplicate-address pre-check that decides whether the
    cooldown applies at all — see ``routers/auth.py``'s ``signup`` docstring)
    and it must see the exact rows ``AuthService.signup`` itself just wrote,
    not the real, unoverridden ``DbUserMirror`` this app would otherwise
    build against a database these hermetic tests never touch.
    """
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
        email=FakeEmailProvider(),
        tokens=FakeAuthTokenService(),
    )
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    client = TestClient(app)
    try:
        yield client, service, mirror
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def _signup(
    client: TestClient, *, email: str, role: str = "student", accepted_terms: bool = True
) -> dict[str, object]:
    payload: dict[str, object] = {"email": email, "password": "pw-123456", "role": role}
    if accepted_terms is not None:
        payload["acceptedTerms"] = accepted_terms
    resp = client.post("/api/auth/signup", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _seed_account(service: AuthService, *, email: str) -> None:
    """Create an account directly through the service, bypassing the HTTP route.

    D7.12's per-email cooldown store is shared by ``/auth/signup`` and
    ``/auth/password-reset/request`` (see
    ``AuthSettings.signup_and_reset_cooldown_seconds``), and it is enforced
    in the *router*, not in :class:`AuthService`. Seeding a
    "this account already exists" fixture through the HTTP signup endpoint
    would therefore stamp that shared cooldown for ``email``, and an
    immediately-following HTTP request to ``password-reset/request`` for the
    *same* address — exactly what the round-trip tests below need to do —
    would spuriously 429 on a window this setup step opened, not the
    behaviour under test. Calling the service directly seeds the identical
    account with none of that side effect.
    """
    service.signup(email, "pw-123456", Role.student, accepted_terms=True)


# ── POST /api/auth/signup: acceptedTerms + teacher self-service (D7.1/D7.11) ──


def test_signup_as_teacher_returns_a_token(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """D7.1. The counterpart to ``test_signup_elevated_role_still_forbidden``."""
    client, _, _ = context
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": "t@example.com",
            "password": "pw-123456",
            "role": "teacher",
            "acceptedTerms": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "teacher"


def test_signup_elevated_role_still_forbidden(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """D1.7 item 1 survives D7.1. This test must never be deleted.

    Assert both remaining elevated roles explicitly - school_admin and
    platform_admin - so widening the allow-list again cannot pass silently.
    """
    client, _, _ = context
    for role in ("school_admin", "platform_admin"):
        resp = client.post(
            "/api/auth/signup",
            json={
                "email": f"{role}@example.com",
                "password": "pw-123456",
                "role": role,
                "acceptedTerms": True,
            },
        )
        assert resp.status_code == 403, (role, resp.text)


def test_signup_without_accepted_terms_is_rejected(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """D7.11: consent is required, and required server-side - a client-side
    checkbox the API does not enforce would be decorative. No default on the
    DTO field means an absent key is a 422, never a silently-assumed False.
    """
    client, _, _ = context
    resp = client.post(
        "/api/auth/signup",
        json={"email": "noterms@example.com", "password": "pw-123456", "role": "student"},
    )
    assert resp.status_code == 422, resp.text


def test_signup_within_cooldown_is_429(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """D7.12, mirroring ``test_otp_resend_within_cooldown_returns_429``.

    Pre-stamps the shared cooldown store directly rather than via a first
    signup call: the router's duplicate-address carve-out (see
    ``routers/auth.py``'s ``signup`` docstring and
    ``test_signup_duplicate_email_is_400_not_429_even_when_retried`` below)
    means a repeat signup of an address that already succeeded is a
    structural 400 forever, never throttled — so the only way to observe a
    429 for a genuinely unclaimed address is a same-email retry that lands
    *inside* the window a prior attempt already opened, exactly as pinning it
    this way proves: the cooldown, not "was this a duplicate", is what fires.
    """
    client, _, _ = context
    email = "cooldown@example.com"
    get_signup_and_reset_cooldown_store().check_and_stamp(email)

    resp = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "pw-123456",
            "role": "student",
            "acceptedTerms": True,
        },
    )

    assert resp.status_code == 429, resp.text


def test_signup_duplicate_email_is_400_not_429_even_when_retried(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """The cooldown must never mask the duplicate-address conflict.

    A duplicate signup mints nothing and sends nothing, so D7.12's cooldown —
    which exists to throttle paths that DO — must not consume it. A caller
    who already has an account for this address must see the same
    actionable 400 every time, not a 429 that gives them no way forward: they
    cannot "wait out" a window for an address that will never become
    available to them. Retried three times to rule out a one-shot fluke.
    """
    client, _, _ = context
    payload = {
        "email": "already-mine@example.com",
        "password": "pw-123456",
        "role": "student",
        "acceptedTerms": True,
    }
    first = client.post("/api/auth/signup", json=payload)
    assert first.status_code == 200, first.text

    for attempt in range(3):
        again = client.post("/api/auth/signup", json=payload)
        assert again.status_code == 400, (attempt, again.text)


def test_signup_returns_a_dev_link_only_for_the_offline_provider(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """D3.16 applied to email (D7.6): the fixture's provider does not deliver
    out of band, so the freshly minted verification link rides back on the
    response — the same rule ``OtpRequestResponseDTO.devCode`` already proves
    for the OTP flow, now proven for signup's ``devLink``."""
    client, _, _ = context
    body = _signup(client, email="devlink@example.com")
    assert body["devLink"] is not None
    assert body["devLink"].startswith("/verify-email/")


# ── POST /api/auth/verify-email ─────────────────────────────────────────────


def test_verify_email_with_a_bad_token_is_400(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    client, _, _ = context
    resp = client.post("/api/auth/verify-email", json={"token": "not-a-real-token"})
    assert resp.status_code == 400, resp.text


def test_verify_email_with_the_signup_dev_link_marks_the_account_verified(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """The happy path the four negative-path tests above assume works.

    Extracts the plaintext token from the ``devLink`` (``/verify-email/{token}``,
    spec §4.4) exactly as the frontend route would, redeems it, and checks the
    mirror directly for ``email_verified_at`` — the fact D7.5's gate reads.
    """
    client, _, mirror = context
    body = _signup(client, email="verifyme@example.com")
    token = str(body["devLink"]).removeprefix("/verify-email/")

    resp = client.post("/api/auth/verify-email", json={"token": token})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "verified"
    user = mirror.get_by_id(uuid.UUID(str(body["userId"])))
    assert user is not None
    assert user.email_verified_at is not None


# ── POST /api/auth/verify-email/resend ──────────────────────────────────────


def test_resend_verification_requires_a_session(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """401 unauthenticated: resend names no address, so it must be told who
    the caller is by their token rather than by a body field an attacker
    could fill with someone else's address."""
    client, _, _ = context
    resp = client.post("/api/auth/verify-email/resend")
    assert resp.status_code == 401, resp.text
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_resend_verification_with_a_session_returns_a_fresh_dev_link(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    client, _, _ = context
    body = _signup(client, email="resend@example.com")
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(body["userId"]), role="student"
    )

    resp = client.post("/api/auth/verify-email/resend")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "sent"
    assert resp.json()["devLink"].startswith("/verify-email/")
    assert resp.json()["devLink"] != body["devLink"], "resend must mint a FRESH token"


def test_resend_verification_within_cooldown_is_429(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """D7.12's per-user resend cooldown, the authenticated counterpart of
    ``test_signup_within_cooldown_is_429``."""
    client, _, _ = context
    body = _signup(client, email="resend-cooldown@example.com")
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(body["userId"]), role="student"
    )

    first = client.post("/api/auth/verify-email/resend")
    assert first.status_code == 200, first.text
    second = client.post("/api/auth/verify-email/resend")
    assert second.status_code == 429, second.text


# ── POST /api/auth/password-reset/request ───────────────────────────────────


def test_password_reset_request_is_200_for_an_unknown_address(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """Anti-enumeration at the HTTP boundary. A 404 here would be an oracle."""
    client, _, _ = context
    resp = client.post("/api/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "sent"
    assert body["devLink"] is None, "nothing was minted for an address that does not exist"


def test_password_reset_request_for_a_known_address_returns_a_dev_link(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    client, service, _ = context
    _seed_account(service, email="forgot@example.com")

    resp = client.post("/api/auth/password-reset/request", json={"email": "forgot@example.com"})

    assert resp.status_code == 200, resp.text
    dev_link = resp.json()["devLink"]
    assert dev_link is not None
    assert dev_link.startswith("/reset/")


def test_password_reset_request_within_cooldown_is_429(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """D7.12's per-email cooldown, shared with signup — see
    ``AuthSettings.signup_and_reset_cooldown_seconds``."""
    client, _, _ = context
    email = "reset-cooldown@example.com"
    first = client.post("/api/auth/password-reset/request", json={"email": email})
    assert first.status_code == 200, first.text
    second = client.post("/api/auth/password-reset/request", json={"email": email})
    assert second.status_code == 429, second.text


# ── POST /api/auth/password-reset/confirm ───────────────────────────────────


def test_password_reset_confirm_with_a_bad_token_is_400(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    client, _, _ = context
    resp = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "newPassword": "new-pw-123456"},
    )
    assert resp.status_code == 400, resp.text


def test_password_reset_confirm_sets_a_working_new_password(
    context: tuple[TestClient, AuthService, FakeUserMirror],
) -> None:
    """The full G-06 round trip: request, redeem, then log in with the new
    credential — and never with the old one."""
    client, service, _ = context
    _seed_account(service, email="reset-flow@example.com")
    reset_body = client.post(
        "/api/auth/password-reset/request", json={"email": "reset-flow@example.com"}
    ).json()
    token = str(reset_body["devLink"]).removeprefix("/reset/")

    confirm = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "newPassword": "brand-new-pw-1"},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "reset"

    old_password_login = client.post(
        "/api/auth/login",
        json={"email": "reset-flow@example.com", "password": "pw-123456"},
    )
    assert old_password_login.status_code == 401

    new_password_login = client.post(
        "/api/auth/login",
        json={"email": "reset-flow@example.com", "password": "brand-new-pw-1"},
    )
    assert new_password_login.status_code == 200, new_password_login.text

    # Redeeming the same reset token twice is refused - it is single-use.
    reused = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "newPassword": "yet-another-pw"},
    )
    assert reused.status_code == 400


# ── deps.py wiring sanity (mandatory cross-cutting requirement #2) ─────────


def test_reset_singletons_clears_the_three_new_auth_singletons() -> None:
    """``reset_singletons``'s docstring promises to clear *every* cached
    singleton. D7.7/D7.12 added three: the token service and the two cooldown
    stores ``get_auth_service`` is wired with. Calling it must not raise, and
    must actually evict a populated cache for each."""
    get_auth_token_service()
    get_signup_and_reset_cooldown_store()
    get_resend_verification_cooldown_store()
    assert get_auth_token_service.cache_info().currsize == 1
    assert get_signup_and_reset_cooldown_store.cache_info().currsize == 1
    assert get_resend_verification_cooldown_store.cache_info().currsize == 1

    reset_singletons()

    assert get_auth_token_service.cache_info().currsize == 0
    assert get_signup_and_reset_cooldown_store.cache_info().currsize == 0
    assert get_resend_verification_cooldown_store.cache_info().currsize == 0


def test_get_auth_service_wires_email_and_tokens_collaborators() -> None:
    """Pins the wiring ``get_auth_service``'s own docstring now describes:
    a real :class:`~lemely.auth.email.MockEmailProvider` and a real, DB-backed
    :class:`~lemely.db.auth_token_repo.AuthTokenService` — not the ``None``
    defaults every hermetic test elsewhere in this file substitutes."""
    from lemely.auth.email import MockEmailProvider
    from lemely.db.auth_token_repo import AuthTokenService

    reset_singletons()
    try:
        service = get_auth_service()
        assert isinstance(service._email, MockEmailProvider)
        assert isinstance(service._tokens, AuthTokenService)
    finally:
        reset_singletons()
