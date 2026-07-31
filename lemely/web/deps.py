"""Dependency singletons and JWT auth for the FastAPI backend.

Provides lazily-constructed, process-wide singletons for :class:`Settings`,
:class:`HistoryStore`, and :class:`GeminiClient`, plus the real bearer-token
authentication dependency (:func:`get_auth_context`). FastAPI ``Depends(...)``
wrappers make these injectable into routers and overridable in tests via
``app.dependency_overrides``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lemely.auth.gotrue import HttpGoTrueBackend
from lemely.auth.mirror import DbUserMirror
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token
from lemely.db.models.enums import Role
from lemely.io.gemini import GeminiClient
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import Settings, load_settings
from lemely.runtime.errors import AuthError


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton."""
    return load_settings()


@lru_cache(maxsize=1)
def get_history_store() -> HistoryStore:
    """Return the process-wide :class:`HistoryStore`, rooted at ``output_dir/history``."""
    settings = get_settings()
    return HistoryStore(settings.paths.output_dir / "history")


@lru_cache(maxsize=1)
def get_gemini_client() -> GeminiClient:
    """Return the process-wide :class:`GeminiClient` singleton."""
    return GeminiClient(get_settings())


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    """Return the process-wide :class:`AuthService` singleton.

    Wired with the real GoTrue HTTP backend, the DB-backed user mirror, the mock
    SMS provider, and an OTP store using a wall-clock and the default RNG. Tests
    override this dependency with a service built on the fake seams.
    """
    settings = get_settings()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.SystemRandom(),
        ttl_seconds=settings.auth.otp_ttl_seconds,
        max_attempts=settings.auth.otp_max_attempts,
        code_length=settings.auth.otp_length,
    )
    return AuthService(
        gotrue=HttpGoTrueBackend(settings),
        mirror=DbUserMirror(settings),
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
    )


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The authenticated caller, resolved from a validated bearer token.

    ``user_id`` is the token ``sub`` (the mirrored ``public.users`` id); ``role``
    is the platform role from ``app_metadata.role`` (one of :class:`Role`'s
    values). ``email`` / ``phone`` mirror the optional token claims.
    """

    user_id: str
    role: str
    email: str | None = None
    phone: str | None = None


_bearer_scheme = HTTPBearer(auto_error=False, description="Supabase-compatible access token")
_ROLE_VALUES: frozenset[str] = frozenset(role.value for role in Role)


def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthContext:
    """Validate the ``Authorization: Bearer`` token and return the caller.

    Decodes the token (HS256, shared ``jwt_secret``) via
    :func:`~lemely.auth.tokens.decode_token`, then requires a recognised platform
    role in ``app_metadata.role``. Any failure — missing header, bad signature,
    expired, wrong audience, missing/unknown role — is a 401 so no route ever
    serves an unauthenticated or role-less caller.

    Raises:
        HTTPException: 401 when the token is absent or fails validation.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_token(credentials.credentials, settings)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if claims.app_role is None or claims.app_role not in _ROLE_VALUES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is missing a recognised role",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthContext(
        user_id=claims.sub,
        role=claims.app_role,
        email=claims.email,
        phone=claims.phone,
    )


def reset_singletons() -> None:
    """Clear all cached singletons. Intended for tests that swap settings."""
    get_settings.cache_clear()
    get_history_store.cache_clear()
    get_gemini_client.cache_clear()
    get_auth_service.cache_clear()
