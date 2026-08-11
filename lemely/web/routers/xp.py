"""XP profile endpoint (``GET /api/student/xp``, P5.8 chunk A, D5.13).

A new thin router in the shape of P5.3's
:mod:`lemely.web.routers.leaderboard`: its own DTOs, no growth of
``student.py``, and no logic of its own beyond projection. The windows, the
streak resolution and the caps all belong to
:meth:`~lemely.db.xp_repo.XpService.profile` (D5.1); the only decision made
here is the **level**, which D5.1 §10 classed as a display concern and D5.13 §1
fixed as a pure function of total XP living in :mod:`lemely.web.xp_levels`.

**Identity is structurally ``auth.user_id``.** No caller-supplied user id
parameter exists on this route, so one student cannot read another's profile —
a property of the signature rather than a check a later edit could drop.

Student-only at the router level, unlike P5.6's deliberately role-agnostic
notification router: ``at_risk_alert`` genuinely addresses a teacher and a
parent, whereas D5.1 §10 already fixed that XP is awarded to students alone,
so this surface has exactly one intended reader.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.db.models.enums import Role, XpSource

# FastAPI resolves every ``Annotated[...]`` parameter through pydantic, so
# ``XpService`` must be a runtime import — under ``TYPE_CHECKING`` it leaves an
# unresolvable ForwardRef and the route raises ``PydanticUserError`` on its
# *first request* rather than at import (P5.6 chunk C1's trap). ``XpProfile``
# rides along for symmetry rather than splitting one module's names across two
# import blocks.
from lemely.db.xp_repo import XpProfile, XpService  # noqa: TC001 - FastAPI resolves this at runtime
from lemely.web.deps import AuthContext, get_xp_service, require_role
from lemely.web.schemas_xp import (
    StreakDTO,
    XpDayDTO,
    XpProfileDTO,
    XpSourceAmountDTO,
    XpWeekDTO,
)
from lemely.web.xp_levels import progress_for_xp

router = APIRouter(prefix="/api/student/xp", dependencies=[Depends(require_role(Role.student))])


def _profile_to_dto(profile: XpProfile) -> XpProfileDTO:
    """Project the service's profile onto the wire, adding only the level.

    ``bySource`` iterates :class:`~lemely.db.models.enums.XpSource` rather than
    ``profile.week.by_source``'s own key order: the breakdown already
    guarantees all four keys (0 for a source that earned nothing), and driving
    the order from the enum means a chart's bar order is the declaration order
    and cannot vary between two requests.
    """
    level = progress_for_xp(profile.total_xp)
    return XpProfileDTO(
        totalXp=profile.total_xp,
        level=level.level,
        levelStartXp=level.level_start_xp,
        nextLevelXp=level.next_level_xp,
        streak=StreakDTO(
            current=profile.streak.current_length,
            longest=profile.streak.longest_length,
            lastActiveOn=profile.streak.last_active_on,
            freezesAvailable=profile.streak.freezes_available,
        ),
        week=XpWeekDTO(
            start=profile.week_start,
            end=profile.week_end,
            total=profile.week.total,
            bySource=[
                XpSourceAmountDTO(source=source.value, xp=profile.week.by_source[source])
                for source in XpSource
            ],
        ),
        calendar=[XpDayDTO(day=day, xp=xp) for day, xp in sorted(profile.calendar.items())],
        calendarStart=profile.calendar_start,
        calendarEnd=profile.calendar_end,
    )


@router.get("", response_model=XpProfileDTO)
def get_xp_profile(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[XpService, Depends(get_xp_service)],
) -> XpProfileDTO:
    """S-31: the caller's own XP total, level, streak, week and calendar.

    Takes no parameters at all. A student who has never earned XP gets a
    well-formed profile — 0 total, level 1, a zeroed streak with
    ``lastActiveOn: null`` and an empty calendar — never a 404, because "you
    have not started yet" is a state the screen must render rather than an
    error (UI spec §1.4: an empty state is a fact, not a failure).
    """
    return _profile_to_dto(service.profile(auth.user_id))


__all__ = ["router"]
