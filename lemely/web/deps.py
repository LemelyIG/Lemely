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
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lemely.auth.gotrue import HttpGoTrueBackend
from lemely.auth.mirror import DbUserMirror
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.class_repo import ClassService
from lemely.db.device_repo import DeviceRegistry
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models.enums import Role
from lemely.db.review_repo import ReviewService
from lemely.db.seat_repo import SeatService
from lemely.db.session import get_sessionmaker
from lemely.db.upload_repo import StudentUploadRepository
from lemely.io.gemini import GeminiClient
from lemely.io.storage import HttpStorageBackend, StorageBackend
from lemely.runtime.config import Settings, load_settings
from lemely.runtime.errors import AuthError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from lemely.core.history import HistoryStoreProtocol


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton."""
    return load_settings()


@lru_cache(maxsize=1)
def get_history_store() -> HistoryStoreProtocol:
    """Return the process-wide Postgres-backed student-history store (D1.8/D1.9).

    The web/product surface persists history in the DB; the return type is the
    structural :class:`HistoryStoreProtocol` so tests can override this with an
    in-tmp JSON store double without touching Postgres.
    """
    return DbHistoryStore(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_gemini_client() -> GeminiClient:
    """Return the process-wide :class:`GeminiClient` singleton."""
    return GeminiClient(get_settings())


@lru_cache(maxsize=1)
def get_attempt_repo() -> AttemptRepository:
    """Return the process-wide :class:`AttemptRepository` singleton (P2.1).

    Persists the full self-mark :class:`AccuracyReport` (attempt + per-question
    results + weaknesses + review-queue rows). Tests override this with a repo
    bound to a throwaway Postgres database.
    """
    return AttemptRepository(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_student_upload_repo() -> StudentUploadRepository:
    """Return the process-wide :class:`StudentUploadRepository` singleton (P2.1).

    Owns the student :class:`Upload` rows that feed the self-mark flow. Tests
    override this with a repo bound to a throwaway Postgres database.
    """
    return StudentUploadRepository(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    """Return the process-wide :class:`StorageBackend` singleton (P2.5).

    Wired with the real HTTP client against Supabase Storage. Tests override
    this with an in-memory ``FakeStorageBackend`` double (``tests/storage_fakes.py``).
    """
    return HttpStorageBackend(get_settings())


@lru_cache(maxsize=1)
def get_device_registry() -> DeviceRegistry:
    """Return the process-wide device/session registry singleton (D1.11).

    Wraps the DB session factory; constructing it opens no connection (the engine
    is lazy), so injecting it into :func:`get_auth_context` keeps the hermetic
    auth-dependency suite offline — a DB read only happens for a token that
    actually carries a ``session_id`` claim.
    """
    return DeviceRegistry(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    """Return the process-wide :class:`AuthService` singleton.

    Wired with the real GoTrue HTTP backend, the DB-backed user mirror, the mock
    SMS provider, an OTP store using a wall-clock and the default RNG, and the
    device registry that enforces the 3-device limit (D1.11). Tests override this
    dependency with a service built on the fake seams.
    """
    settings = get_settings()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.SystemRandom(),
        ttl_seconds=settings.auth.otp_ttl_seconds,
        max_attempts=settings.auth.otp_max_attempts,
        code_length=settings.auth.otp_length,
        min_resend_seconds=settings.auth.otp_min_resend_seconds,
    )
    return AuthService(
        gotrue=HttpGoTrueBackend(settings),
        mirror=DbUserMirror(settings),
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
        device_registry=get_device_registry(),
    )


class AuthServiceStudentCreator:
    """Real :class:`~lemely.db.seat_repo.StudentAccountCreator` over :class:`AuthService`.

    A seat invite admin-creates the student through the same GoTrue-backed signup
    path anonymous students use, pinned to :attr:`Role.student` (elevated roles are
    never mintable via a seat invite). Returns the mirrored ``public.users`` id so
    :class:`SeatService` can bind the seat to it.
    """

    def __init__(self, auth_service: AuthService) -> None:
        """Wrap an :class:`AuthService` used to create student identities."""
        self._auth = auth_service

    def create_student(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> uuid.UUID:
        """Create a student account and return its ``public.users`` id."""
        return self._auth.signup(email, password, Role.student, display_name=display_name).user_id


@lru_cache(maxsize=1)
def get_seat_service() -> SeatService:
    """Return the process-wide :class:`SeatService` singleton.

    Wired with the DB session factory and an :class:`AuthServiceStudentCreator`
    that provisions invited students through the real GoTrue signup path. Tests
    override this dependency with a service built on a fake account creator and a
    throwaway Postgres database.
    """
    return SeatService(
        get_sessionmaker(get_settings()),
        AuthServiceStudentCreator(get_auth_service()),
    )


@lru_cache(maxsize=1)
def get_class_service() -> ClassService:
    """Return the process-wide :class:`ClassService` singleton (D3.1).

    Wired with the DB session factory alone — unlike :class:`SeatService`,
    class ownership/enrolment needs no account-creation seam, so there is no
    GoTrue dependency here at all. Tests override this dependency with a
    service built on a throwaway Postgres database.
    """
    return ClassService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_review_service() -> ReviewService:
    """Return the process-wide :class:`ReviewService` singleton (P3.4).

    Wired with the DB session factory and the same :class:`ClassService`
    singleton the class routes use, so review-queue tenancy composes the
    identical ``list_classes``/``roster`` calls every other student-scoped
    teacher route relies on (D3.1) — never a second, independently-derived
    notion of "the caller's students". Tests override this dependency with a
    service built on a throwaway Postgres database.
    """
    return ReviewService(get_sessionmaker(get_settings()), get_class_service())


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
    devices: Annotated[DeviceRegistry, Depends(get_device_registry)],
) -> AuthContext:
    """Validate the ``Authorization: Bearer`` token and return the caller.

    Decodes the token (HS256, shared ``jwt_secret``) via
    :func:`~lemely.auth.tokens.decode_token`, then requires a recognised platform
    role in ``app_metadata.role``. Any failure — missing header, bad signature,
    expired, wrong audience, missing/unknown role — is a 401 so no route ever
    serves an unauthenticated or role-less caller.

    When the token carries a ``session_id`` claim (D1.11), a single indexed DB
    read confirms that device row is still live; an evicted or unknown session is
    a 401. Tokens without a ``session_id`` (hermetic tests, seat-invite signups)
    skip the check entirely, preserving the fully-offline validation path.

    Raises:
        HTTPException: 401 when the token is absent or fails validation, or when
            its session has been invalidated.
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
    if claims.session_id is not None and not devices.is_session_live(claims.session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session has been signed out",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthContext(
        user_id=claims.sub,
        role=claims.app_role,
        email=claims.email,
        phone=claims.phone,
    )


def require_role(*allowed: Role) -> Callable[[AuthContext], AuthContext]:
    """Build a dependency that authenticates then role-gates the caller.

    The returned dependency runs :func:`get_auth_context` first (so an absent or
    invalid token is a 401), then rejects any authenticated caller whose platform
    role is not in ``allowed`` with a 403. On success it returns the
    :class:`AuthContext` unchanged so handlers still read ``auth.user_id`` — the
    row-level ownership key — from it.

    Least privilege: each portal's routes name exactly the roles allowed to reach
    them; there is no implicit super-role. Cross-tenant reads are prevented at the
    data layer by keying on ``auth.user_id`` (a student can only ever load their
    own bucket), not by trusting any caller-supplied id.
    """
    allowed_values = frozenset(role.value for role in allowed)

    def _guard(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
        if auth.role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role is not permitted to access this resource",
            )
        return auth

    return _guard


def reset_singletons() -> None:
    """Clear all cached singletons. Intended for tests that swap settings."""
    get_settings.cache_clear()
    get_history_store.cache_clear()
    get_gemini_client.cache_clear()
    get_attempt_repo.cache_clear()
    get_student_upload_repo.cache_clear()
    get_storage_backend.cache_clear()
    get_device_registry.cache_clear()
    get_auth_service.cache_clear()
    get_seat_service.cache_clear()
    get_class_service.cache_clear()
    get_review_service.cache_clear()
