"""Dependencies shared by the tutoring routers (PLAN §1.4 #4; SPEC §b.2, ADR-T01).

* **Tutor-profile guards.** Every ``/api/tutor/*`` route resolves the caller's
  profile from ``auth.user_id`` through :func:`require_tutor_profile` (O1): a
  teacher without one gets 404 ``no_tutor_profile`` (ADR-T01 action 3), and no
  tutor route ever takes a tutor id. Write routes use
  :func:`require_writable_tutor_profile`, which also refuses a suspended or
  closed profile with 409 ``tutor_suspended`` / ``tutor_closed`` (SPEC §a.4b,
  CB-7). The repository re-checks the state inside its write transaction, so this
  guard is the fast answer, not the only one.
* **Guards by role.** :data:`require_teacher` and :data:`require_student_or_parent`
  are ``require_role`` closures, so ``tests/test_authz_matrix_complete.py`` reads
  their role sets out of each route's dependency tree.
* **Directory filters** for P1 and SP1, parsed and validated once.
* **Providers.** Each repository is a process-wide, lazily built singleton
  (the ``lru_cache`` pattern of ``lemely.web.deps``); tests override them through
  ``app.dependency_overrides``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal  # noqa: TC003 - FastAPI reads the query type at runtime
from functools import lru_cache
from typing import Annotated, Final

from fastapi import Depends, Query

from lemely.core.tutor_directory import TimeOfDay  # noqa: TC001 - FastAPI reads it at runtime
from lemely.db.models.enums import Role, TutorListingState
from lemely.db.session import get_sessionmaker
from lemely.db.tutor_directory_repo import DirectoryFilters, TutorDirectoryRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository, TutorProfileRow
from lemely.io.tutoring_areas import AreaCatalogue, load_tutoring_areas
from lemely.web.deps import AuthContext, get_settings, require_role
from lemely.web.schemas_tutoring import TutoringModeLit  # noqa: TC001 - FastAPI reads it at runtime
from lemely.web.tutoring_http import tutoring_error

require_teacher: Final = require_role(Role.teacher)
require_student_or_parent: Final = require_role(Role.student, Role.parent)

#: ``subjects.code`` and ``tutor_profiles.area_code`` are short codes; bound the filter text.
_MAX_CODE_LENGTH: Final = 40
_MIN_DAY: Final = 1
_MAX_DAY: Final = 7


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_tutor_profile_repo() -> TutorProfileRepository:
    """The process-wide :class:`TutorProfileRepository`."""
    return TutorProfileRepository(get_sessionmaker(get_settings()))


@lru_cache(maxsize=1)
def get_tutor_directory_repo() -> TutorDirectoryRepository:
    """The process-wide :class:`TutorDirectoryRepository`."""
    return TutorDirectoryRepository(get_sessionmaker(get_settings()))


def get_tutoring_areas() -> AreaCatalogue:
    """The bundled tutoring area catalogue (cached by its loader)."""
    return load_tutoring_areas()


def reset_tutoring_singletons() -> None:
    """Clear this module's cached providers (``deps.reset_singletons`` does not know them)."""
    get_tutor_profile_repo.cache_clear()
    get_tutor_directory_repo.cache_clear()


# ---------------------------------------------------------------------------
# Tutor-profile guards (O1, CB-7)
# ---------------------------------------------------------------------------


def require_tutor_profile(
    auth: Annotated[AuthContext, Depends(require_teacher)],
    repo: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
) -> TutorProfileRow:
    """The caller's own tutor profile, or 404 ``no_tutor_profile``."""
    profile = repo.for_user(uuid.UUID(auth.user_id))
    if profile is None:
        raise tutoring_error(
            404, "no_tutor_profile", "You do not have a tutor profile yet. Create one first."
        )
    return profile


def require_writable_tutor_profile(
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
) -> TutorProfileRow:
    """The caller's profile, refused with 409 when it is suspended or closed."""
    if profile.listing_state is TutorListingState.suspended:
        raise tutoring_error(409, "tutor_suspended", "Your tutor profile is suspended.")
    if profile.listing_state is TutorListingState.closed:
        raise tutoring_error(409, "tutor_closed", "Your tutor profile is closed.")
    return profile


# ---------------------------------------------------------------------------
# Directory filters (P1, SP1)
# ---------------------------------------------------------------------------


def public_directory_filters(
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    subject: Annotated[str | None, Query(min_length=1, max_length=_MAX_CODE_LENGTH)] = None,
    mode: Annotated[list[TutoringModeLit] | None, Query()] = None,
    area: Annotated[str | None, Query(min_length=1, max_length=_MAX_CODE_LENGTH)] = None,
    min_rating: Annotated[
        Decimal | None,
        Query(alias="minRating", ge=1, le=5, multiple_of=0.5),
    ] = None,
) -> DirectoryFilters:
    """P1's filters: ``subject``, ``mode`` (repeatable, OR), ``area``, ``minRating``.

    ``minRating`` is 1.0 to 5.0 in steps of 0.5. ``area`` must be a catalogue
    code (it is never free text); an unknown ``subject`` simply matches nobody.
    """
    if area is not None and areas.get(area) is None:
        raise tutoring_error(422, "invalid_area", "Choose an area from the list.")
    return DirectoryFilters(
        subject=subject,
        modes=frozenset(mode or ()),
        area=area,
        min_rating=min_rating,
    )


def logged_in_directory_filters(
    base: Annotated[DirectoryFilters, Depends(public_directory_filters)],
    day: Annotated[list[int] | None, Query()] = None,
    time_of_day: Annotated[list[TimeOfDay] | None, Query(alias="timeOfDay")] = None,
) -> DirectoryFilters:
    """SP1's filters: P1's plus ``day`` (repeatable 1-7) and ``timeOfDay`` (repeatable)."""
    days = frozenset(day or ())
    if any(not _MIN_DAY <= value <= _MAX_DAY for value in days):
        raise tutoring_error(422, "invalid_day", "Days are 1 (Monday) to 7 (Sunday).")
    return DirectoryFilters(
        subject=base.subject,
        modes=base.modes,
        area=base.area,
        min_rating=base.min_rating,
        days=days,
        times=frozenset(time_of_day or ()),
    )


__all__ = [
    "get_tutor_directory_repo",
    "get_tutor_profile_repo",
    "get_tutoring_areas",
    "logged_in_directory_filters",
    "public_directory_filters",
    "require_student_or_parent",
    "require_teacher",
    "require_tutor_profile",
    "require_writable_tutor_profile",
    "reset_tutoring_singletons",
]
