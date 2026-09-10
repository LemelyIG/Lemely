"""Student home-screen widget endpoint (``GET /api/student/widget``, packet A5).

Backs the manifest ``widgets`` member (``vite/manifest.ts``) and the Adaptive
Card template at ``public/widgets/streak.json``. A new thin router in the
shape of ``lemely.web.routers.xp``/``lemely.web.routers.study_plan``: its own
DTOs, no growth of ``student.py``.

**``nextSession`` is the earliest not-yet-completed session across every
subject the caller is enrolled in, this week only.** ``StudyPlanService.
get_current`` only ever returns the current week's persisted plan (or
``None`` if none has been generated) — it never generates one itself — so
this route does not search history or future weeks; a home-screen widget
answers "what's next", not "show me everything". No plan generated for a
subject, a generated-but-refused plan (``available: False``, empty
``sessions``), or a plan whose only sessions are already completed all
contribute nothing, and the caller sees ``nextSession: None`` rather than an
error — "nothing scheduled yet" is a well-formed state to render, the same
rule ``study_plan.py``'s own router follows for "no plan generated yet".
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.db.models.enums import Role

# FastAPI resolves every ``Annotated[...]`` parameter through pydantic, so
# these three service classes must be runtime imports — under
# ``TYPE_CHECKING`` they leave an unresolvable ``ForwardRef`` and the route
# raises ``PydanticUserError`` on its first request rather than at import
# (see ``xp.py``'s own comment for the same trap).
from lemely.db.student_profile_repo import StudentProfileService  # noqa: TC001
from lemely.db.study_plan_repo import StudyPlanService  # noqa: TC001
from lemely.db.xp_repo import XpService  # noqa: TC001
from lemely.web.deps import (
    AuthContext,
    get_student_profile_service,
    get_study_plan_service,
    get_xp_service,
    require_role,
)
from lemely.web.schemas_widget import StudentWidgetDTO, WidgetNextSessionDTO

router = APIRouter(prefix="/api/student/widget", dependencies=[Depends(require_role(Role.student))])


def _next_session(
    user_id: str,
    subject_codes: list[str],
    study_plan_service: StudyPlanService,
) -> WidgetNextSessionDTO | None:
    """The earliest incomplete session across this week's plans for every enrolled subject."""
    earliest: WidgetNextSessionDTO | None = None
    earliest_date = None
    for subject_code in subject_codes:
        plan = study_plan_service.get_current(user_id, subject_code)
        if plan is None:
            continue
        for session in plan.sessions:
            if session.completed_at is not None:
                continue
            if earliest_date is None or session.date < earliest_date:
                earliest_date = session.date
                earliest = WidgetNextSessionDTO(
                    title=session.topic,
                    startsAt=datetime.combine(session.date, time.min, tzinfo=UTC).isoformat(),
                )
    return earliest


@router.get("", response_model=StudentWidgetDTO)
def get_student_widget(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    xp_service: Annotated[XpService, Depends(get_xp_service)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
    study_plan_service: Annotated[StudyPlanService, Depends(get_study_plan_service)],
) -> StudentWidgetDTO:
    """The caller's own streak and next study session — never another student's.

    Takes no parameters at all, mirroring ``xp.py``'s ``get_xp_profile``:
    identity is structurally ``auth.user_id``.
    """
    profile = xp_service.profile(auth.user_id)
    subject_codes = [row.subject_code for row in profile_service.list_enrolments(auth.user_id)]
    return StudentWidgetDTO(
        streak=profile.streak.current_length,
        nextSession=_next_session(auth.user_id, subject_codes, study_plan_service),
    )


__all__ = ["router"]
