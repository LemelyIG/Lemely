"""``/api/me`` endpoints — settings shared by every authenticated role.

Currently just notification preferences (G-12, P3.6 chunk B). Unlike the
rest of the portal routers, which are role-scoped
(``routers/teacher.py``, ``routers/student.py``, ``routers/parent.py``), this
router is reachable by **any** authenticated role — storing a notification
preference is the same work whichever role the caller has, and P5 (not this
chunk) owns turning a stored preference into an actual delivered/suppressed
notification.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely.auth.mirror import UserMirror
from lemely.db.models.enums import Role
from lemely.db.notification_prefs_repo import (
    UNSET,
    NotificationPreferencesRow,
    NotificationPreferencesService,
)
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_notification_prefs_service,
    get_user_mirror,
)
from lemely.web.schemas_me import (
    NotificationPreferencesDTO,
    NotificationPreferencesUpdateDTO,
    ProfileDTO,
)

router = APIRouter(prefix="/api/me")

# G-12: "teacher/at-risk alerts (teacher and parent only)". Every other role's
# GET has the field forced to null, and a PUT that supplies it (true or
# false) is rejected outright rather than silently ignored.
_AT_RISK_ALERT_ROLES = frozenset({Role.teacher.value, Role.parent.value})


def _to_dto(row: NotificationPreferencesRow, *, role: str) -> NotificationPreferencesDTO:
    """Convert a preferences row to its DTO, nulling ``atRiskAlert`` by role."""
    return NotificationPreferencesDTO(
        gradeReady=row.grade_ready,
        announcement=row.announcement,
        streakWarning=row.streak_warning,
        studyPlanReminder=row.study_plan_reminder,
        atRiskAlert=row.at_risk_alert if role in _AT_RISK_ALERT_ROLES else None,
        quietHoursStart=row.quiet_hours_start,
        quietHoursEnd=row.quiet_hours_end,
    )


@router.get("/notification-preferences", response_model=NotificationPreferencesDTO)
def get_notification_preferences(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[NotificationPreferencesService, Depends(get_notification_prefs_service)],
) -> NotificationPreferencesDTO:
    """Return the authenticated caller's notification preferences.

    Gated only by ``get_auth_context`` (any authenticated role) rather than
    ``require_role`` — the read is identical for every role, only
    ``atRiskAlert``'s visibility differs. Identity is always ``auth.user_id``,
    never a caller-supplied id (D1.6). A caller with no stored row reads as
    all-defaults; this never creates one.
    """
    row = service.get(auth.user_id)
    return _to_dto(row, role=auth.role)


def _required_bool(value: bool | None, *, field: str) -> bool:
    """Narrow an optional DTO bool to a concrete ``bool``.

    The DTO field type is ``bool | None`` only so ``model_fields_set`` can
    tell "omitted" apart from "sent"; once a field is known to have been
    sent, an explicit ``null`` is invalid input (every toggle column is
    ``NOT NULL``), not a "clear this field" instruction — unlike the
    quiet-hours pair, which legitimately clears via ``null``.
    """
    if value is None:
        raise HTTPException(status_code=422, detail=f"{field} cannot be null.")
    return value


@router.put("/notification-preferences", response_model=NotificationPreferencesDTO)
def put_notification_preferences(
    payload: NotificationPreferencesUpdateDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[NotificationPreferencesService, Depends(get_notification_prefs_service)],
) -> NotificationPreferencesDTO:
    """Partially update the authenticated caller's notification preferences.

    Only fields present in the request body are changed — an omitted field is
    left as-is; an explicit ``null`` on the quiet-hours pair clears that
    bound (``payload.model_fields_set`` is how "omitted" and "explicitly
    sent" are told apart). ``atRiskAlert`` is teacher/parent only (G-12): any
    other role supplying it at all — ``true`` or ``false`` — is a 422, never
    silently dropped. Setting exactly one of the quiet-hours pair is also a
    422 (enforced by the service).
    """
    provided = payload.model_fields_set
    if "atRiskAlert" in provided and auth.role not in _AT_RISK_ALERT_ROLES:
        raise HTTPException(
            status_code=422,
            detail="atRiskAlert is only settable for the teacher and parent roles.",
        )

    try:
        row = service.set(
            auth.user_id,
            grade_ready=(
                _required_bool(payload.gradeReady, field="gradeReady")
                if "gradeReady" in provided
                else UNSET
            ),
            announcement=(
                _required_bool(payload.announcement, field="announcement")
                if "announcement" in provided
                else UNSET
            ),
            streak_warning=(
                _required_bool(payload.streakWarning, field="streakWarning")
                if "streakWarning" in provided
                else UNSET
            ),
            study_plan_reminder=(
                _required_bool(payload.studyPlanReminder, field="studyPlanReminder")
                if "studyPlanReminder" in provided
                else UNSET
            ),
            at_risk_alert=(
                _required_bool(payload.atRiskAlert, field="atRiskAlert")
                if "atRiskAlert" in provided
                else UNSET
            ),
            quiet_hours_start=payload.quietHoursStart if "quietHoursStart" in provided else UNSET,
            quiet_hours_end=payload.quietHoursEnd if "quietHoursEnd" in provided else UNSET,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_dto(row, role=auth.role)


@router.get("/profile", response_model=ProfileDTO)
def get_profile(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
) -> ProfileDTO:
    """Return the authenticated caller's real identity (P3.7 chunk B).

    Backs the teacher-portal sidebar, which previously hardcoded a name and
    department ("Mr H. Sabry / Physics dept · CAIE") with no data source at
    all. Gated only by ``get_auth_context`` (any authenticated role), same as
    ``get_notification_preferences`` — the lookup is identical whichever role
    the caller has. Identity is always ``auth.user_id`` (the token ``sub``),
    never a caller-supplied id (D1.6).

    ``displayName`` is read from the mirrored ``public.users`` row, not the
    token's ``email`` claim — the token claim can be stale or absent, and a
    display name has no token claim at all. It is returned exactly as stored,
    including ``None`` (:attr:`~lemely.db.models.users.User.display_name` is
    nullable): the caller renders that absence honestly rather than the route
    inventing a fallback name.

    A malformed (non-UUID) ``user_id`` is a clean 422 — should not occur
    against a real token, but the mirror lookup requires a real
    :class:`uuid.UUID`, not the bare string ``AuthContext.user_id`` carries.
    A user id that decodes but matches no mirrored row (should not occur for
    a token that validated against the same mirror) is a 404 rather than a
    500 or a fabricated profile.
    """
    try:
        user_id = uuid.UUID(auth.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Malformed user id.") from exc
    user = mirror.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No profile found for this account.")
    return ProfileDTO(displayName=user.display_name, email=user.email, role=user.role.value)


__all__ = ["router"]
