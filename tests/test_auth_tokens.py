"""Tests for self-signed Supabase-compatible access tokens (mint/decode)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from lemely.auth.tokens import decode_token, mint_otp_token
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
