"""Fully hermetic AuthService tests (fake GoTrue + mirror + mock SMS)."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta

import pytest

from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token
from lemely.db.models.enums import Role
from lemely.runtime.config import Settings
from lemely.runtime.errors import AuthError
from tests.auth_fakes import FakeGoTrueBackend, FakeUserMirror


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _service(clock: _Clock) -> tuple[AuthService, FakeUserMirror, Settings]:
    settings = Settings()
    mirror = FakeUserMirror()
    otp_store = OtpStore(
        clock=clock,
        rng=random.Random(42),
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
    challenge = store._challenges[phone]
    return service.verify_otp(phone, challenge.code)
