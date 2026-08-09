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
from lemely.auth.mirror import DbUserMirror, UserMirror
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token
from lemely.db.announcement_repo import AnnouncementService
from lemely.db.at_risk_repo import AtRiskAckService
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.class_repo import ClassService
from lemely.db.device_repo import DeviceRegistry
from lemely.db.flashcard_repo import FlashcardService
from lemely.db.history_repo import DbHistoryStore
from lemely.db.leaderboard_repo import LeaderboardService
from lemely.db.models.enums import Role
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.placement_repo import PlacementService
from lemely.db.practice_repo import PracticeService
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_marking_repo import QuizMarkingService
from lemely.db.quiz_repo import QuizService
from lemely.db.quiz_results_repo import QuizResultsService
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.db.review_repo import ReviewService
from lemely.db.seat_repo import SeatService
from lemely.db.session import get_sessionmaker
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.study_plan_repo import StudyPlanService
from lemely.db.upload_repo import StudentUploadRepository
from lemely.db.xp_repo import XpService
from lemely.io.flashcard_generation import FlashcardGenerator
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


@lru_cache(maxsize=1)
def get_question_bank_service() -> QuestionBankService:
    """Return the process-wide :class:`QuestionBankService` singleton (P3.5 chunk B).

    Wired with the DB session factory alone — the bank's visibility
    predicate takes caller/school ids as call arguments, so this service
    needs no per-request context injected here. Tests override this
    dependency with a service built on a throwaway Postgres database.
    """
    return QuestionBankService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_quiz_service() -> QuizService:
    """Return the process-wide :class:`QuizService` singleton (P3.5 chunk D).

    Wired with the DB session factory and the same :class:`ClassService`/
    :class:`QuestionBankService` singletons every other teacher-portal
    service composes, so quiz tenancy and bank visibility never diverge from
    what the rest of the teacher portal already enforces (D3.1/D3.6 §1.3).
    Tests override this dependency with a service built on a throwaway
    Postgres database.
    """
    return QuizService(
        get_sessionmaker(get_settings()), get_class_service(), get_question_bank_service()
    )


@lru_cache(maxsize=1)
def get_quiz_results_service() -> QuizResultsService:
    """Return the process-wide :class:`QuizResultsService` singleton (P3.5 chunk F2).

    Wired with the same :class:`QuizService` and :class:`ClassService`
    singletons every other teacher-portal route composes: T-10's ownership
    decision *is* :meth:`~lemely.db.quiz_repo.QuizService.get_quiz`'s and its
    roster *is* :meth:`~lemely.db.class_repo.ClassService.roster`'s, so a
    results view can never be reachable by a caller who could not already
    open the quiz and the class. Tests override this dependency with a
    service built on a throwaway Postgres database.
    """
    return QuizResultsService(
        get_sessionmaker(get_settings()), get_quiz_service(), get_class_service()
    )


@lru_cache(maxsize=1)
def get_quiz_taking_service() -> QuizTakingService:
    """Return the process-wide :class:`QuizTakingService` singleton (P3.5 chunk E).

    Wired with the DB session factory and the same :class:`ClassService`
    singleton every other portal service composes, so student quiz scoping
    uses the identical :meth:`~lemely.db.class_repo.ClassService.enrolled_class_ids`
    seam every other route would (D3.1-style discipline) — never a second,
    independently-derived notion of "which classes is this student in". The
    clock is left at its default (real UTC now); tests override this
    dependency with a service built on an injected fake clock and a
    throwaway Postgres database.
    """
    return QuizTakingService(get_sessionmaker(get_settings()), get_class_service())


@lru_cache(maxsize=1)
def get_quiz_marking_service() -> QuizMarkingService:
    """Return the process-wide :class:`QuizMarkingService` singleton (P3.5 chunk F1).

    Wired with the DB session factory, the same :class:`AttemptRepository`
    singleton the student self-mark route (``lemely.web.routers.student``)
    persists through — so a quiz mark and a past-paper mark share the exact
    same writer, ``docs/quiz-model.md`` §4.4 — and the process-wide
    :class:`~lemely.io.gemini.GeminiClient`. Tests override this dependency
    with a service built on a throwaway Postgres database and a stubbed
    Gemini client (never a live call — the budget is hard-capped).
    """
    return QuizMarkingService(
        get_sessionmaker(get_settings()), get_attempt_repo(), get_gemini_client()
    )


@lru_cache(maxsize=1)
def get_placement_service() -> PlacementService:
    """Return the process-wide :class:`PlacementService` singleton (P4.4 chunk B-4).

    Wired with the DB session factory alone: unlike :class:`QuizTakingService`,
    placement ownership needs no ``ClassService`` seam — a placement
    assignment is always direct-to-student (D4.6 §1). Tests override this
    dependency with a service built on a throwaway Postgres database.
    """
    return PlacementService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_practice_service() -> PracticeService:
    """Return the process-wide :class:`PracticeService` singleton (P4.5).

    Wired with the DB session factory alone, mirroring
    :func:`get_placement_service` — a practice assignment is always
    direct-to-student, so no ``ClassService`` seam is needed. Tests override
    this dependency with a service built on a throwaway Postgres database.
    """
    return PracticeService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_study_plan_service() -> StudyPlanService:
    """Return the process-wide :class:`StudyPlanService` singleton (P4.7 chunk C).

    Wired with the DB session factory alone, mirroring
    :func:`get_placement_service`/:func:`get_practice_service` — every
    signal the service reads (weakness, placement, confidence, bank/deck
    availability) lives in the same database, and nothing on this path calls
    Gemini. Tests override this dependency with a service built on a
    throwaway Postgres database.
    """
    return StudyPlanService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_flashcard_service() -> FlashcardService:
    """Return the process-wide :class:`FlashcardService` singleton (P4.6 chunk C).

    Wired with the DB session factory **and** the process-wide
    :class:`~lemely.io.gemini.GeminiClient` via a
    :class:`~lemely.io.flashcard_generation.FlashcardGenerator` — unlike
    :func:`get_practice_service`, this service has one method
    (``generate_deck``) that calls the model. The generator is a constructor
    argument rather than something the service builds, so tests override this
    dependency with a throwaway Postgres database and a stubbed generator and
    never make a billed call (MISSION §8; D4.3's suite-wide guard would raise
    if they tried).
    """
    return FlashcardService(
        get_sessionmaker(get_settings()), FlashcardGenerator(get_gemini_client())
    )


@lru_cache(maxsize=1)
def get_xp_service() -> XpService:
    """Return the process-wide :class:`XpService` singleton (P5.2 chunk B).

    Wired with the DB session factory alone, mirroring
    :func:`get_study_plan_service`/:func:`get_placement_service` — the clock
    and streak-day zone are left at their defaults (real UTC now,
    ``Africa/Cairo``); tests override this dependency with a service built on
    an injected fake clock and a throwaway Postgres database. Composed with
    each of the four award call sites only through
    :func:`~lemely.web.xp_awards.award_xp_safely`, never called directly from
    a repo service (D5.1: awarding is a router-layer concern, not nested
    inside another service's own transaction).
    """
    return XpService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_leaderboard_service() -> LeaderboardService:
    """Return the process-wide :class:`LeaderboardService` singleton (P5.3 chunk B).

    Wired with the DB session factory alone, mirroring :func:`get_xp_service`
    — the clock and week-boundary zone are left at their defaults (real UTC
    now, ``Africa/Cairo``). Tests override this dependency with a service
    built on an injected fake clock and a throwaway Postgres database.
    """
    return LeaderboardService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_at_risk_ack_service() -> AtRiskAckService:
    """Return the process-wide :class:`AtRiskAckService` singleton (P3.4b/D3.5).

    Wired with the DB session factory and the same :class:`ClassService`
    singleton every other student-scoped teacher service uses, so
    acknowledgement tenancy composes the identical ``list_classes``/``roster``
    calls (D3.1) — never a second, independently-derived notion of "the
    caller's students". Tests override this dependency with a service built
    on a throwaway Postgres database.
    """
    return AtRiskAckService(get_sessionmaker(get_settings()), get_class_service())


@lru_cache(maxsize=1)
def get_parent_link_service() -> ParentLinkService:
    """Return the process-wide :class:`ParentLinkService` singleton (P3.6 chunk A).

    Wired with the DB session factory alone — mirrors :func:`get_class_service`:
    parent-link lookups need no account-creation seam or composed service.
    Tests override this dependency with a service built on a throwaway
    Postgres database.
    """
    return ParentLinkService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_notification_prefs_service() -> NotificationPreferencesService:
    """Return the process-wide :class:`NotificationPreferencesService` singleton (P3.6 chunk B).

    Wired with the DB session factory alone — mirrors :func:`get_parent_link_service`:
    preference lookups need no account-creation seam or composed service.
    Tests override this dependency with a service built on a throwaway
    Postgres database.
    """
    return NotificationPreferencesService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_student_profile_service() -> StudentProfileService:
    """Return the process-wide :class:`StudentProfileService` singleton (P4.3 chunk B).

    Wired with the DB session factory alone — mirrors :func:`get_notification_prefs_service`:
    a student's profile has no cross-tenant ownership question (tenancy is
    just ``auth.user_id == row.user_id``, enforced at the router layer), so
    this service needs no composed service or account-creation seam. The
    clock is left at its default (real UTC now); tests override this
    dependency with a service built on an injected fake clock and a
    throwaway Postgres database.
    """
    return StudentProfileService(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_announcement_service() -> AnnouncementService:
    """Return the process-wide :class:`AnnouncementService` singleton (P3.8 chunk a).

    Wired with the DB session factory and the same :class:`ClassService`
    singleton every other class-scoped teacher service composes, so
    announcement tenancy (which classes/schools a caller may target) can
    never diverge from what the rest of the teacher portal already enforces
    (D3.1). Tests override this dependency with a service built on a
    throwaway Postgres database.
    """
    return AnnouncementService(get_sessionmaker(get_settings()), get_class_service())


@lru_cache(maxsize=1)
def get_user_mirror() -> UserMirror:
    """Return the process-wide :class:`UserMirror` singleton (P3.7 chunk B).

    Backs ``GET /api/me/profile``.

    The same :class:`DbUserMirror` :func:`get_auth_service` already wires into
    :class:`~lemely.auth.service.AuthService` — a standalone dependency here so
    a route that only needs a plain user lookup (real ``display_name``/
    ``email``/``role``, never a caller-supplied claim) doesn't have to pull in
    the whole auth service. Tests override this dependency with a mirror bound
    to a throwaway Postgres database.
    """
    return DbUserMirror(get_settings())


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
    get_parent_link_service.cache_clear()
    get_notification_prefs_service.cache_clear()
    get_user_mirror.cache_clear()
    get_review_service.cache_clear()
    get_at_risk_ack_service.cache_clear()
    get_question_bank_service.cache_clear()
    get_quiz_service.cache_clear()
    get_quiz_taking_service.cache_clear()
    get_quiz_marking_service.cache_clear()
    get_announcement_service.cache_clear()
    get_student_profile_service.cache_clear()
    get_xp_service.cache_clear()
    get_leaderboard_service.cache_clear()
