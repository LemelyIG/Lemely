"""Tests for self-signed Supabase-compatible access tokens (mint/decode)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from lemely.auth.tokens import (
    decode_refresh_token,
    decode_token,
    mint_access_token,
    mint_otp_token,
    mint_refresh_token,
    refresh_audience,
)
from lemely.runtime.config import Settings
from lemely.runtime.errors import AuthError


def _settings() -> Settings:
    return Settings()


def test_mint_decode_round_trip() -> None:
    settings = _settings()
    uid = uuid.uuid4()
    token = mint_otp_token(
        user_id=uid,
        settings=settings,
        app_role="parent",
        phone="+201234567890",
        email="p@example.com",
    )
    claims = decode_token(token, settings)
    assert claims.sub == str(uid)
    assert claims.aud == settings.supabase.jwt_audience
    assert claims.role == "authenticated"
    assert claims.app_role == "parent"
    assert claims.phone == "+201234567890"
    assert claims.email == "p@example.com"


def test_expired_token_rejected() -> None:
    settings = _settings()
    past = datetime.now(UTC) - timedelta(hours=2)
    token = mint_otp_token(
        user_id=uuid.uuid4(),
        settings=settings,
        app_role="parent",
        ttl_seconds=60,
        now=past,
    )
    with pytest.raises(AuthError):
        decode_token(token, settings)


def test_tampered_token_rejected() -> None:
    settings = _settings()
    token = mint_otp_token(user_id=uuid.uuid4(), settings=settings, app_role="parent")
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    with pytest.raises(AuthError):
        decode_token(tampered, settings)


def test_bad_secret_rejected() -> None:
    settings = _settings()
    # Sign with a different secret, decode with the configured one.
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": settings.supabase.jwt_audience,
        "role": "authenticated",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    forged = jwt.encode(payload, "not-the-real-secret", algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(forged, settings)


def test_missing_required_claim_rejected() -> None:
    settings = _settings()
    secret = settings.supabase.jwt_secret.get_secret_value()
    # Valid signature + audience, but no `role`/`sub` claims.
    payload = {
        "aud": settings.supabase.jwt_audience,
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(token, settings)


def test_wrong_audience_rejected() -> None:
    settings = _settings()
    secret = settings.supabase.jwt_secret.get_secret_value()
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": "some-other-audience",
        "role": "authenticated",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(token, settings)


def test_access_token_ttl_comes_from_settings() -> None:
    """The access-token lifetime is configuration, not a literal in the minter."""
    settings = Settings.model_validate({"auth": {"access_token_ttl_seconds": 120}})
    issued = datetime.now(UTC)
    token = mint_access_token(
        user_id=uuid.uuid4(),
        settings=settings,
        app_role="student",
        provider="email",
        now=issued,
    )
    claims = decode_token(token, settings)
    assert claims.exp == int((issued + timedelta(seconds=120)).timestamp())


# -- Refresh tokens ---------------------------------------------------------


def _refresh(settings: Settings, **overrides: object) -> str:
    kwargs: dict[str, object] = {
        "user_id": uuid.uuid4(),
        "settings": settings,
        "session_id": uuid.uuid4(),
        "token_id": str(uuid.uuid4()),
    }
    kwargs.update(overrides)
    return mint_refresh_token(**kwargs)  # type: ignore[arg-type]


def test_refresh_mint_decode_round_trip() -> None:
    settings = _settings()
    uid, sid, jti = uuid.uuid4(), uuid.uuid4(), str(uuid.uuid4())
    token = mint_refresh_token(user_id=uid, settings=settings, session_id=sid, token_id=jti)
    claims = decode_refresh_token(token, settings)
    assert claims.sub == str(uid)
    assert claims.session_id == str(sid)
    assert claims.token_id == jti


def test_refresh_token_is_not_accepted_as_an_access_token() -> None:
    """The security hinge: a refresh token must never authenticate a request.

    It is minted under a distinct audience, so the access-token validator that
    every route depends on rejects it outright rather than reading its ``sub``.
    """
    settings = _settings()
    token = _refresh(settings)
    with pytest.raises(AuthError):
        decode_token(token, settings)


def test_access_token_is_not_accepted_as_a_refresh_token() -> None:
    """And the converse — an access token cannot be redeemed for a new one."""
    settings = _settings()
    token = mint_access_token(
        user_id=uuid.uuid4(), settings=settings, app_role="student", provider="email"
    )
    with pytest.raises(AuthError):
        decode_refresh_token(token, settings)


def test_expired_refresh_token_rejected() -> None:
    settings = _settings()
    token = _refresh(settings, ttl_seconds=60, now=datetime.now(UTC) - timedelta(hours=2))
    with pytest.raises(AuthError):
        decode_refresh_token(token, settings)


def test_refresh_token_ttl_comes_from_settings() -> None:
    settings = Settings.model_validate({"auth": {"refresh_token_ttl_seconds": 900}})
    issued = datetime.now(UTC)
    token = _refresh(settings, now=issued)
    claims = decode_refresh_token(token, settings)
    assert claims.exp == int((issued + timedelta(seconds=900)).timestamp())


def test_refresh_token_without_session_binding_rejected() -> None:
    """A refresh token with no ``session_id`` has no device row to revoke.

    Nothing mints one, but a forger holding the shared secret must not be able
    to hand-roll a session-less token that would bypass the liveness check.
    """
    settings = _settings()
    secret = settings.supabase.jwt_secret.get_secret_value()
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": refresh_audience(settings),
        "typ": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_refresh_token(token, settings)


def test_refresh_token_signed_with_wrong_secret_rejected() -> None:
    settings = _settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": refresh_audience(settings),
        "typ": "refresh",
        "jti": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "exp": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    }
    forged = jwt.encode(payload, "not-the-real-secret", algorithm="HS256")
    with pytest.raises(AuthError):
        decode_refresh_token(forged, settings)
