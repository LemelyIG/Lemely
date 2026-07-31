"""Dependency singletons and auth stub for the FastAPI backend.

Provides lazily-constructed, process-wide singletons for :class:`Settings`,
:class:`HistoryStore`, and :class:`GeminiClient`, plus a no-op authentication
stub. FastAPI ``Depends(...)`` wrappers make these injectable into routers and
overridable in tests via ``app.dependency_overrides``.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from functools import lru_cache

from lemely.auth.gotrue import HttpGoTrueBackend
from lemely.auth.mirror import DbUserMirror
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.io.gemini import GeminiClient
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import Settings, load_settings


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


class AuthContext:
    """Minimal authenticated-caller context.

    This is a stub: the real portals will populate ``user_id`` / ``role`` from a
    session or bearer token. For now every request resolves to an anonymous
    caller so route signatures can already depend on it.
    """

    __slots__ = ("role", "user_id")

    def __init__(self, user_id: str = "anonymous", role: str = "anonymous") -> None:
        """Initialise the context with an optional user id and role."""
        self.user_id = user_id
        self.role = role


def get_auth_context() -> AuthContext:
    """No-op auth dependency — always returns an anonymous :class:`AuthContext`."""
    return AuthContext()


def reset_singletons() -> None:
    """Clear all cached singletons. Intended for tests that swap settings."""
    get_settings.cache_clear()
    get_history_store.cache_clear()
    get_gemini_client.cache_clear()
    get_auth_service.cache_clear()
