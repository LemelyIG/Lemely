"""Live integration test against the real local GoTrue + Postgres.

Skips cleanly (never fails) when any of the following is true, so CI stays green
until a Supabase service block is added:

* GoTrue is unreachable at ``supabase.url``.
* The service-role or anon key is absent from settings (read from the env vars
  ``LEMELY_SUPABASE__SERVICE_ROLE_KEY`` / ``LEMELY_SUPABASE__ANON_KEY``).
* Postgres is unreachable (mirrors ``_server_reachable`` in test_db_schema.py).

Secrets are never hardcoded — the keys come only from the environment.
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from lemely.auth.gotrue import HttpGoTrueBackend
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token
from lemely.db.models.enums import Role
from lemely.db.session import dispose_engine, session_scope
from lemely.runtime.config import Settings


def _gotrue_reachable(url: str) -> bool:
    try:
        resp = httpx.get(f"{url.rstrip('/')}/auth/v1/health", timeout=2.0)
    except httpx.HTTPError:
        return False
    return resp.status_code < 500


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


def _live_settings() -> Settings | None:
    service_key = os.environ.get("LEMELY_SUPABASE__SERVICE_ROLE_KEY")
    anon_key = os.environ.get("LEMELY_SUPABASE__ANON_KEY")
    if not service_key or not anon_key:
        return None
    settings = Settings()
    settings = settings.model_copy(
        update={
            "supabase": settings.supabase.model_copy(
                update={
                    "service_role_key": SecretStr(service_key),
                    "anon_key": SecretStr(anon_key),
                }
            )
        }
    )
    return settings


@pytest.fixture
def live_service() -> AuthService:
    settings = _live_settings()
    if settings is None:
        pytest.skip("Supabase service-role/anon keys not set in environment")
    if not _gotrue_reachable(settings.supabase.url):
        pytest.skip("local GoTrue not reachable")
    if not _server_reachable(settings.database.url):
        pytest.skip("local Postgres not reachable")

    from lemely.auth.mirror import DbUserMirror

    dispose_engine()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(),
    )
    return AuthService(
        gotrue=HttpGoTrueBackend(settings),
        mirror=DbUserMirror(settings),
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
    )


def _cleanup(settings: Settings, user_id: uuid.UUID) -> None:
    with session_scope(settings) as session:
        session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def test_live_signup_and_login(live_service: AuthService) -> None:
    settings = _live_settings()
    assert settings is not None
    email = f"live-{uuid.uuid4().hex[:10]}@example.com"
    password = "live-test-pw-123456"

    result = live_service.signup(email, password, Role.student)
    try:
        claims = decode_token(result.access_token, settings)
        assert claims.sub == str(result.user_id)
        assert claims.aud == settings.supabase.jwt_audience

        login = live_service.login(email, password)
        assert login.user_id == result.user_id
        login_claims = decode_token(login.access_token, settings)
        assert login_claims.sub == str(result.user_id)
    finally:
        _cleanup(settings, result.user_id)
