"""Fully hermetic AuthService tests (fake GoTrue + mirror + mock SMS).

The D7 signup/verification/password-reset tests further down this file stay
hermetic too: :class:`~tests.auth_fakes.FakeAuthTokenService` and
:class:`~tests.auth_fakes.FakeEmailProvider` stand in for the real
Postgres-backed :class:`~lemely.db.auth_token_repo.AuthTokenService` and a
real :class:`~lemely.auth.email.EmailProvider`, exactly as
:class:`~tests.auth_fakes.FakeDeviceRegistry` already stands in for
:class:`~lemely.db.device_repo.DeviceRegistry` here. ``AuthTokenService``'s
own Postgres guarantees (hashing, locking, expiry) are proven separately in
``tests/test_auth_token_repo.py``; what these tests prove is
``AuthService``'s orchestration on top of it.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from lemely.auth.otp import OtpChannel, OtpStore
from lemely.auth.service import AuthService, DeviceContext
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token
from lemely.db.auth_token_repo import TokenAlreadyUsed
from lemely.db.models.enums import AuthTokenPurpose, Role
from lemely.runtime.config import Settings
from lemely.runtime.errors import AuthError
from tests.auth_fakes import (
    FakeAuthTokenService,
    FakeDeviceRegistry,
    FakeEmailProvider,
    FakeGoTrueBackend,
    FakeUserMirror,
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _service(
    clock: _Clock,
    *,
    email: FakeEmailProvider | None = None,
    tokens: FakeAuthTokenService | None = None,
    device_registry: FakeDeviceRegistry | None = None,
) -> tuple[AuthService, FakeUserMirror, Settings]:
    settings = Settings()
    mirror = FakeUserMirror()
    otp_store = OtpStore(
        clock=clock,
        rng=random.Random(42),
        ttl_seconds=settings.auth.otp_ttl_seconds,
        max_attempts=settings.auth.otp_max_attempts,
        code_length=settings.auth.otp_length,
        # `resend_verification` now issues a fresh email-channel code
        # alongside the link (spec §4.4/DS15) on the SAME frozen `clock` a
        # test's own signup already used to issue one for the same address a
        # moment earlier; the store's default 30s resend cooldown would
        # otherwise raise `OtpRateLimitError` for a same-tick resend. That
        # cooldown is proven independently in `tests/test_otp.py`, so
        # disabling it here does not weaken anything this file tests.
        min_resend_seconds=0,
    )
    service = AuthService(
        gotrue=FakeGoTrueBackend(),
        mirror=mirror,
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
        device_registry=device_registry,
        email=email,
        tokens=tokens,
    )
    return service, mirror, settings


def test_signup_mirrors_user_and_returns_token() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, mirror, settings = _service(clock)
    result = service.signup(
        "teacher@example.com",
        "hunter2pw",
        Role.teacher,
        display_name="Ms T",
    )
    assert result.role is Role.teacher
    assert result.user_id in mirror.rows
    row = mirror.rows[result.user_id]
    assert row.email == "teacher@example.com"
    assert row.role is Role.teacher
    assert row.display_name == "Ms T"
    # D1.5: the backend mints its own self-signed HS256 token (GoTrue's is
    # discarded), so it must decode under the shared secret with the right claims.
    claims = decode_token(result.access_token, settings)
    assert claims.sub == str(result.user_id)
    assert claims.aud == settings.supabase.jwt_audience
    assert claims.app_role == Role.teacher.value
    assert claims.email == "teacher@example.com"


def test_login_returns_valid_token_for_all_roles() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, _, settings = _service(clock)
    signed = service.signup("admin@example.com", "pw-admin-1", Role.platform_admin)
    result = service.login("admin@example.com", "pw-admin-1")
    assert result.role is Role.platform_admin
    assert result.user_id == signed.user_id
    # D1.5: login mints a self-signed HS256 token; GoTrue's ES256 token is not forwarded.
    claims = decode_token(result.access_token, settings)
    assert claims.sub == str(result.user_id)
    assert claims.app_role == Role.platform_admin.value


def test_login_bad_password_raises() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, _, _ = _service(clock)
    service.signup("s@example.com", "correct-pw", Role.student)
    with pytest.raises(AuthError):
        service.login("s@example.com", "wrong-pw")


def test_parent_otp_flow_mints_self_signed_token(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, mirror, settings = _service(clock)
    phone = "+201112223334"

    with caplog.at_level(logging.INFO, logger="lemely.auth.sms"):
        service.request_otp(phone)
    # The mock SMS logs the code; recover it from the log record for the test.
    logged = [r.getMessage() for r in caplog.records if "Mock SMS" in r.getMessage()]
    assert logged, "expected the mock SMS provider to log the code"
    code = logged[-1].split()[-1]

    result = service.verify_otp(phone, code)
    assert result.role is Role.parent

    claims = decode_token(result.access_token, settings)
    assert claims.app_role == "parent"
    assert claims.phone == phone
    assert claims.sub == str(result.user_id)
    # The parent user was mirrored with the phone number.
    assert mirror.rows[result.user_id].phone == phone


class _DeliveringSmsProvider:
    """Stands in for a real SMS gateway: it *does* deliver out of band."""

    delivers_out_of_band = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_code(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))


def test_request_otp_returns_the_code_only_for_a_non_delivering_provider() -> None:
    """D3.16: the §G-05 dev affordance is gated on the provider, not an env string.

    The mock logs but delivers nothing, so the API is the only way to obtain the
    code and ``request_otp`` hands it back. Swap in a provider that really
    delivers and the same call returns ``None`` — no live code crosses the wire.
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, _, _ = _service(clock)
    phone = "+201117778889"

    mock_code = service.request_otp(phone)
    assert mock_code is not None
    # It is the real challenge, not a decorative string: it verifies.
    assert service.verify_otp(phone, mock_code).role is Role.parent

    real_provider = _DeliveringSmsProvider()
    service._sms = real_provider
    assert service.request_otp("+201110001112") is None
    # ...and the provider still received it — only the *return* is withheld.
    assert real_provider.sent and len(real_provider.sent[-1][1]) > 0


def test_otp_verify_wrong_code_raises() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, _, _ = _service(clock)
    phone = "+201110000000"
    service.request_otp(phone)
    with pytest.raises(AuthError):
        service.verify_otp(phone, "000000-wrong")


def test_otp_verify_expired_raises() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, _, settings = _service(clock)
    phone = "+201119999999"
    service.request_otp(phone)
    clock.advance(settings.auth.otp_ttl_seconds + 1)
    with pytest.raises(AuthError):
        service.verify_otp(phone, "123456")


def test_otp_reuses_existing_parent_row() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, mirror, _ = _service(clock)
    phone = "+201115556667"

    # Pre-mirror a parent with this phone (e.g. created earlier).
    import uuid

    parent_id = uuid.uuid4()
    mirror.upsert(parent_id, email="existing@parents.local", role=Role.parent, phone=phone)

    service.request_otp(phone)
    # Fetch the just-issued code via the store, deterministically.
    result = _verify_with_current_code(service, phone)
    assert result.user_id == parent_id  # reused existing row, no new id


def _verify_with_current_code(service: AuthService, phone: str) -> object:
    # Brute a small space is unnecessary: read from the store directly.
    store = service._otp_store  # test-only introspection of the injected store
    challenge = store._challenges[(OtpChannel.phone, phone)]
    return service.verify_otp(phone, challenge.code)


# ─────────────────────────────────────────────────────────────────────────
# D7: teacher signup, email verification, password reset (plan Task 8)
# ─────────────────────────────────────────────────────────────────────────


def test_signup_admits_a_teacher() -> None:
    """D7.1: teacher is now self-service; the service must not refuse it.

    ``AuthService.signup`` has never itself restricted which ``Role`` it will
    create — the self-service allowlist lives one layer up, in the router's
    ``_SELF_SERVICE_SIGNUP_ROLES`` — so this pins the *absence* of a
    service-level role gate as a deliberate decision (an authenticated admin
    flow, e.g. the seat/invite services, calls this exact method to create
    teacher and school_admin accounts too) rather than something a future
    refactor could silently break.
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, mirror, _ = _service(clock)

    result = service.signup(
        "newteacher@example.com", "hunter2pw", Role.teacher, accepted_terms=True
    )

    assert result.role is Role.teacher
    assert mirror.rows[result.user_id].role is Role.teacher


def test_signup_stamps_terms_accepted_at() -> None:
    """D7.11: consent is recorded, not merely collected — in both directions.

    A signup that ticked the G-03 box gets a real timestamp; one that did not
    gets ``None``. Only asserting the first direction would leave "always
    stamp `now()` regardless of the flag" indistinguishable from "record
    consent that was actually given", which is the whole point of D7.11.
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, mirror, _ = _service(clock)

    accepted = service.signup(
        "consented@example.com", "hunter2pw", Role.student, accepted_terms=True
    )
    assert mirror.rows[accepted.user_id].terms_accepted_at is not None

    declined = service.signup(
        "declined@example.com", "hunter2pw", Role.student, accepted_terms=False
    )
    assert mirror.rows[declined.user_id].terms_accepted_at is None


def test_signup_mints_and_sends_a_verification_token() -> None:
    """A new account leaves signup with a live verification token.

    "Live" is proven the same way the OTP tests prove a code is real rather
    than decorative: by actually redeeming it and checking the effect lands.
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    email = FakeEmailProvider()
    tokens = FakeAuthTokenService(clock=clock)
    service, mirror, _ = _service(clock, email=email, tokens=tokens)

    result = service.signup(
        "newstudent@example.com", "hunter2pw", Role.student, accepted_terms=True
    )

    assert email.sent_verifications, "expected a verification email to have been sent"
    sent_email, sent_link, sent_code = email.sent_verifications[-1]
    assert sent_email == "newstudent@example.com"
    assert result.verification_dev_link == sent_link
    assert result.verification_dev_code == sent_code

    token = sent_link.rsplit("/", 1)[-1]
    assert service.verify_email(token) == result.user_id
    assert mirror.rows[result.user_id].email_verified_at is not None


def test_signup_returns_the_dev_link_only_when_the_provider_does_not_deliver() -> None:
    """D3.16 applied to email. Assert BOTH directions - a provider with
    delivers_out_of_band=True must yield None, or the rule is decorative.
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))

    mock_email = FakeEmailProvider(delivers_out_of_band=False)
    mock_service, _, _ = _service(clock, email=mock_email, tokens=FakeAuthTokenService(clock=clock))
    mock_result = mock_service.signup(
        "mocked@example.com", "hunter2pw", Role.student, accepted_terms=True
    )
    assert mock_result.verification_dev_link is not None
    assert mock_result.verification_dev_code is not None

    real_email = FakeEmailProvider(delivers_out_of_band=True)
    real_service, _, _ = _service(clock, email=real_email, tokens=FakeAuthTokenService(clock=clock))
    real_result = real_service.signup(
        "delivered@example.com", "hunter2pw", Role.student, accepted_terms=True
    )
    assert real_result.verification_dev_link is None
    assert real_result.verification_dev_code is None
    # ...and the provider still received it - only the *return* is withheld,
    # mirroring test_request_otp_returns_the_code_only_for_a_non_delivering_provider.
    assert real_email.sent_verifications


def test_verify_email_sets_email_verified_at() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    tokens = FakeAuthTokenService(clock=clock)
    service, mirror, _ = _service(clock, tokens=tokens)
    signed_up = service.signup("verifyme@example.com", "hunter2pw", Role.student)
    assert mirror.rows[signed_up.user_id].email_verified_at is None

    token = tokens.mint(signed_up.user_id, AuthTokenPurpose.email_verification)
    verified_user_id = service.verify_email(token)

    assert verified_user_id == signed_up.user_id
    assert mirror.rows[signed_up.user_id].email_verified_at is not None


def test_verify_email_with_an_unknown_token_raises_auth_error() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, _, _ = _service(clock, tokens=FakeAuthTokenService(clock=clock))
    with pytest.raises(AuthError):
        service.verify_email("this-token-was-never-minted")


def test_request_password_reset_for_an_unknown_address_does_not_raise() -> None:
    """Anti-enumeration: the caller cannot tell whether the address exists.
    The service returns normally and mints nothing.
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    tokens = FakeAuthTokenService(clock=clock)
    email = FakeEmailProvider()
    service, _, _ = _service(clock, email=email, tokens=tokens)

    result = service.request_password_reset("nobody-here@example.com")

    assert result is None
    assert not email.sent_resets
    assert not tokens.rows, "nothing should have been minted for an address that does not exist"


def test_request_password_reset_for_a_known_address_mints_and_sends() -> None:
    """The other direction of the anti-enumeration test above: a *known*
    address really does get a live, redeemable reset token.
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    tokens = FakeAuthTokenService(clock=clock)
    email = FakeEmailProvider()
    service, _, _ = _service(clock, email=email, tokens=tokens)
    signed_up = service.signup("knownaddress@example.com", "old-password", Role.student)

    dev_link = service.request_password_reset("knownaddress@example.com")

    assert dev_link is not None
    assert email.sent_resets
    token = dev_link.rsplit("/", 1)[-1]
    service.reset_password(token, "new-password")
    relogged = service.login("knownaddress@example.com", "new-password")
    assert relogged.user_id == signed_up.user_id


def test_request_password_reset_survives_a_send_failure() -> None:
    """A mail-transport failure for a KNOWN address must not surface any
    differently than the clean, empty return for an unknown one - otherwise a
    raised exception here becomes an enumeration side channel (D7's binding
    anti-enumeration rule, extended to delivery failures, not just unknown
    addresses).
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    tokens = FakeAuthTokenService(clock=clock)
    email = FakeEmailProvider(raise_on_send=True)
    service, _, _ = _service(clock, email=email, tokens=tokens)
    service.signup("resetfails@example.com", "hunter2pw", Role.student)

    result = service.request_password_reset("resetfails@example.com")  # must not raise

    assert result is not None  # a token WAS minted; the mock never delivers out of band


def test_reset_password_revokes_outstanding_tokens_and_all_devices() -> None:
    """The reason for a reset may be a compromise, so every session dies."""
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    tokens = FakeAuthTokenService(clock=clock)
    registry = FakeDeviceRegistry()
    service, _, _ = _service(clock, tokens=tokens, device_registry=registry)

    signed_up = service.signup(
        "resetme@example.com",
        "old-password",
        Role.student,
        device=DeviceContext(client_device_id="device-a"),
    )
    service.login(
        "resetme@example.com", "old-password", device=DeviceContext(client_device_id="device-b")
    )
    assert len(registry.active_devices(signed_up.user_id)) == 2

    outstanding_verification = tokens.mint(signed_up.user_id, AuthTokenPurpose.email_verification)
    reset_token = tokens.mint(signed_up.user_id, AuthTokenPurpose.password_reset)

    service.reset_password(reset_token, "new-password")

    assert registry.active_devices(signed_up.user_id) == []
    # revoke_all ran for BOTH purposes: the outstanding verification token is
    # dead too, not just the reset token that was actually redeemed.
    with pytest.raises(TokenAlreadyUsed):
        tokens.redeem(outstanding_verification, AuthTokenPurpose.email_verification)
    with pytest.raises(TokenAlreadyUsed):
        tokens.redeem(reset_token, AuthTokenPurpose.password_reset)
    # The credential really changed.
    with pytest.raises(AuthError):
        service.login("resetme@example.com", "old-password")
    relogged = service.login("resetme@example.com", "new-password")
    assert relogged.user_id == signed_up.user_id


def test_reset_password_with_an_expired_token_raises_auth_error() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    tokens = FakeAuthTokenService(clock=clock)
    service, _, _ = _service(clock, tokens=tokens)
    signed_up = service.signup("expiredreset@example.com", "old-password", Role.student)

    reset_token = tokens.mint(signed_up.user_id, AuthTokenPurpose.password_reset, ttl_seconds=60)
    clock.advance(61)

    with pytest.raises(AuthError):
        service.reset_password(reset_token, "new-password")


def test_signup_survives_a_verification_send_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Binding rule: a verification-send failure must not fail the signup.

    By the time delivery is attempted, ``admin_create_user`` has already
    succeeded — a GoTrue user now exists that this address can never register
    again. An account with no mail sent is recoverable via
    ``resend_verification``; a signup that raises here would strand that
    account with no way back in.
    """
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    email = FakeEmailProvider(raise_on_send=True)
    tokens = FakeAuthTokenService(clock=clock)
    service, mirror, _ = _service(clock, email=email, tokens=tokens)

    with caplog.at_level(logging.ERROR, logger="lemely.auth.service"):
        result = service.signup(
            "willnotgetmail@example.com", "hunter2pw", Role.student, accepted_terms=True
        )

    assert result.user_id in mirror.rows
    assert any("willnotgetmail@example.com" in r.getMessage() for r in caplog.records)


def test_resend_verification_mints_and_sends_a_fresh_token() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    tokens = FakeAuthTokenService(clock=clock)
    email = FakeEmailProvider()
    service, _, _ = _service(clock, email=email, tokens=tokens)
    signed_up = service.signup("resendme@example.com", "hunter2pw", Role.student)
    email.sent_verifications.clear()  # ignore signup's own send

    dev_link, dev_code = service.resend_verification(signed_up.user_id)

    assert dev_link is not None
    assert dev_code is not None
    assert email.sent_verifications
    token = dev_link.rsplit("/", 1)[-1]
    assert service.verify_email(token) == signed_up.user_id


def test_resend_verification_for_an_unknown_user_raises_auth_error() -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=UTC))
    service, _, _ = _service(clock, tokens=FakeAuthTokenService(clock=clock))
    with pytest.raises(AuthError):
        service.resend_verification(uuid.uuid4())


# ── Email verification by code (spec §4.4/DS15) ─────────────────────────────
#
# The two fixtures below build the exact same collaborators as `_service()`
# above (a wall clock rather than the frozen `_Clock`, since none of these
# tests need to fast-forward time), differing only in the email provider's
# `delivers_out_of_band` — the single knob D3.16 gates `devCode` on. Both
# share one builder so the (already-accepted — see `_service()` above)
# Fake-vs-Protocol mypy gap is a single call site, not two.


def _service_with_otp_store(
    *, delivers_out_of_band: bool
) -> tuple[AuthService, FakeEmailProvider, OtpStore]:
    settings = Settings()
    mirror = FakeUserMirror()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(11),
        ttl_seconds=settings.auth.otp_ttl_seconds,
        email_ttl_seconds=settings.auth.email_otp_ttl_seconds,
        max_attempts=5,
        code_length=settings.auth.otp_length,
        # `resend_verification` issues a fresh email-channel code, and without
        # this the store's resend-cooldown would raise `OtpRateLimitError` for
        # a same-instant re-issue — a guarantee this file leaves to
        # `tests/test_otp.py`, not what these tests are about.
        min_resend_seconds=0,
    )
    email = FakeEmailProvider(delivers_out_of_band=delivers_out_of_band)
    service = AuthService(
        gotrue=FakeGoTrueBackend(),
        mirror=mirror,  # type: ignore[arg-type]
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
        email=email,
        tokens=FakeAuthTokenService(),  # type: ignore[arg-type]
    )
    return service, email, otp_store


@pytest.fixture
def service_with_email() -> tuple[AuthService, FakeEmailProvider, OtpStore]:
    """AuthService wired with a NON-delivering email provider (the mock case)."""
    return _service_with_otp_store(delivers_out_of_band=False)


@pytest.fixture
def service_with_delivering_email() -> tuple[AuthService, FakeEmailProvider, OtpStore]:
    """Same as :func:`service_with_email`, but the provider DOES deliver (D3.16)."""
    return _service_with_otp_store(delivers_out_of_band=True)


def test_signup_issues_link_and_code_and_returns_both_dev_values(
    service_with_email: tuple[AuthService, FakeEmailProvider, OtpStore],
) -> None:
    service, email_provider, otp_store = service_with_email
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    assert result.verification_dev_link is not None
    assert result.verification_dev_code is not None
    assert email_provider.sent_verifications == [
        ("s@example.com", result.verification_dev_link, result.verification_dev_code)
    ]


def test_verify_email_code_stamps_verified_and_is_single_use(
    service_with_email: tuple[AuthService, FakeEmailProvider, OtpStore],
) -> None:
    service, _e, _o = service_with_email
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    assert result.verification_dev_code is not None
    assert service.verify_email_code(result.user_id, result.verification_dev_code) == result.user_id
    with pytest.raises(AuthError):
        service.verify_email_code(result.user_id, result.verification_dev_code)


def test_wrong_code_five_times_locks(
    service_with_email: tuple[AuthService, FakeEmailProvider, OtpStore],
) -> None:
    service, _e, _o = service_with_email
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    assert result.verification_dev_code is not None
    for _ in range(5):
        with pytest.raises(AuthError):
            service.verify_email_code(result.user_id, "000000")
    with pytest.raises(AuthError, match=r"no_challenge|locked_out"):
        service.verify_email_code(result.user_id, result.verification_dev_code)


def test_link_still_verifies_after_code_was_used(
    service_with_email: tuple[AuthService, FakeEmailProvider, OtpStore],
) -> None:
    """The two credentials are independent; verification is idempotent (spec §4.4)."""
    service, _e, _o = service_with_email
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    assert result.verification_dev_code is not None
    assert result.verification_dev_link is not None
    service.verify_email_code(result.user_id, result.verification_dev_code)
    token = result.verification_dev_link.rsplit("/", 1)[1]
    assert service.verify_email(token) == result.user_id  # no error, same user


def test_dev_code_is_none_when_provider_delivers(
    service_with_delivering_email: tuple[AuthService, FakeEmailProvider, OtpStore],
) -> None:
    """D3.16 applied to the code: a real provider never leaks it back through the API."""
    service, email_provider, _o = service_with_delivering_email
    assert email_provider.delivers_out_of_band is True
    result = service.signup("s@example.com", "pw-123456", Role.student, accepted_terms=True)
    assert result.verification_dev_link is None
    assert result.verification_dev_code is None
    ((_addr, _link, code),) = email_provider.sent_verifications
    assert len(code) == 6  # it was still issued and handed to the provider
