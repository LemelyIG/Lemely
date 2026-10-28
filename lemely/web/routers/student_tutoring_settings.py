"""S12, S13: a student's own tutoring settings (SPEC §b.2 "Student", §a.2, PLAN P30).

``STUDENT`` only, keyed on ``auth.user_id``: the row is the student's alone (SPEC
§a.5), so neither route takes an id and a parent can neither read nor change it.

* **S12** reads the caller's settings. A student who never saved any reads the
  defaults of :class:`~lemely.db.tutoring_preferences_repo.TutoringPreferencesRepository`
  (counted in outcome figures, decision row 8), and the read writes nothing.
* **S13** sets the outcome-figure opt-out. ``outcomePrefChangedAt`` moves only when
  the stored value changes, in the repository's one upsert: that instant starts the
  90-day hold on the tutor's figures (SC-13d), so saving the same choice again
  does not restart it. The safety-notice acknowledgement (S15) is left alone.

The repository comes from this module's own provider,
:func:`get_tutoring_preferences_repo`. Built with
:class:`~lemely.web.tutoring_http.TutoringRoute` (``private, no-store`` on every
status, PLAN P12).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends

from lemely.db.models.enums import Role
from lemely.db.session import get_sessionmaker
from lemely.db.tutoring_preferences_repo import TutoringPreferencesRepository
from lemely.web.deps import AuthContext, get_settings, require_role
from lemely.web.schemas_tutoring import TutoringSettingsDTO, TutoringSettingsUpdateDTO
from lemely.web.tutoring_http import TutoringRoute, iso_instant

if TYPE_CHECKING:
    from lemely.db.tutoring_preferences_repo import TutoringPreferences

require_student: Final = require_role(Role.student)

router = APIRouter(prefix="/api/student", tags=["tutoring"], route_class=TutoringRoute)


@lru_cache(maxsize=1)
def get_tutoring_preferences_repo() -> TutoringPreferencesRepository:
    """The process-wide :class:`TutoringPreferencesRepository`."""
    return TutoringPreferencesRepository(get_sessionmaker(get_settings()))


def tutoring_settings_dto(preferences: TutoringPreferences) -> TutoringSettingsDTO:
    """The student's three settings, instants as API instants (SPEC §0 "Times")."""
    changed_at = preferences.outcome_pref_changed_at
    acknowledged_at = preferences.safety_notice_acknowledged_at
    return TutoringSettingsDTO(
        outcomeStatsOptOut=preferences.outcome_stats_opt_out,
        outcomePrefChangedAt=iso_instant(changed_at) if changed_at is not None else None,
        safetyNoticeAcknowledgedAt=(
            iso_instant(acknowledged_at) if acknowledged_at is not None else None
        ),
    )


@router.get("/tutoring-settings", response_model=TutoringSettingsDTO)
def read_tutoring_settings(
    auth: Annotated[AuthContext, Depends(require_student)],
    repo: Annotated[TutoringPreferencesRepository, Depends(get_tutoring_preferences_repo)],
) -> TutoringSettingsDTO:
    """S12: the caller's settings, or the defaults when they never saved any."""
    return tutoring_settings_dto(repo.get(uuid.UUID(auth.user_id)))


@router.put("/tutoring-settings", response_model=TutoringSettingsDTO)
def update_tutoring_settings(
    body: TutoringSettingsUpdateDTO,
    auth: Annotated[AuthContext, Depends(require_student)],
    repo: Annotated[TutoringPreferencesRepository, Depends(get_tutoring_preferences_repo)],
) -> TutoringSettingsDTO:
    """S13: opt out of (or back into) tutors' outcome figures."""
    return tutoring_settings_dto(
        repo.set_opt_out(uuid.UUID(auth.user_id), value=body.outcomeStatsOptOut)
    )


__all__ = [
    "get_tutoring_preferences_repo",
    "require_student",
    "router",
    "tutoring_settings_dto",
]
