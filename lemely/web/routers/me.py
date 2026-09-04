"""``/api/me`` endpoints — settings shared by every authenticated role.

Notification preferences (G-12, P3.6 chunk B) and the generic profile GET
are reachable by **any** authenticated role — that work is identical
whichever role the caller has. The student-onboarding routes added in P4.3
chunk B (D4.5) live in this same router, rather than a new file, because
they are still ``/api/me/*`` settings — but they are gated
``require_role(Role.student)`` since onboarding is a student-only concept
(a teacher/parent has no ``student_profiles`` row to view or edit).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely.auth.mirror import UserMirror
from lemely.db.device_repo import MAX_DEVICES, DeviceRegistry
from lemely.db.models.enums import Role, SessionMonth
from lemely.db.notification_prefs_repo import (
    UNSET,
    NotificationPreferencesRow,
    NotificationPreferencesService,
    _UnsetType,
)
from lemely.db.student_profile_repo import (
    ConfidenceRatingRow,
    StudentProfileNotFoundError,
    StudentProfileRow,
    StudentProfileService,
    StudentProfileValidationError,
    SubjectEnrolmentRow,
)
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_device_registry,
    get_notification_prefs_service,
    get_student_profile_service,
    get_user_mirror,
    require_role,
)
from lemely.web.devices import to_device_dto
from lemely.web.schemas_devices import (
    DeviceListDTO,
    DeviceRevokedDTO,
)
from lemely.web.schemas_me import (
    NotificationPreferencesDTO,
    NotificationPreferencesUpdateDTO,
    ProfileDTO,
)
from lemely.web.schemas_student_profile import (
    ConfidenceRatingDTO,
    ConfidenceRatingsUpdateDTO,
    EnrolmentListRequestDTO,
    StudentProfileDTO,
    StudentProfileUpdateDTO,
    StudentProfileWithEnrolmentsDTO,
    SubjectEnrolmentDTO,
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
    return ProfileDTO(
        displayName=user.display_name,
        email=user.email,
        role=user.role.value,
        emailVerified=user.email_verified_at is not None,
    )


# ---------------------------------------------------------------------------
# Student onboarding profile (P4.3 chunk B, D4.5)
# ---------------------------------------------------------------------------


def _profile_to_dto(row: StudentProfileRow) -> StudentProfileDTO:
    return StudentProfileDTO(
        qualificationLevel=row.qualification_level.value if row.qualification_level else None,
        gradeLevel=row.grade_level,
        schoolName=row.school_name,
        hasExternalLessons=row.has_external_lessons,
        weeklyStudyHours=row.weekly_study_hours,
        onboardingCompletedAt=row.onboarding_completed_at,
        leaderboardOptOut=row.leaderboard_opt_out,
    )


def _rating_to_dto(row: ConfidenceRatingRow) -> ConfidenceRatingDTO:
    return ConfidenceRatingDTO(topic=row.topic, rating=row.rating)


def _enrolment_to_dto(
    row: SubjectEnrolmentRow, ratings: list[ConfidenceRatingRow]
) -> SubjectEnrolmentDTO:
    return SubjectEnrolmentDTO(
        subjectCode=row.subject_code,
        qualificationLevel=row.qualification_level.value if row.qualification_level else None,
        targetGrade=row.target_grade,
        sessionMonth=row.session_month.value if row.session_month else None,
        sessionYear=row.session_year,
        papers=list(row.papers),
        confidenceRatings=[_rating_to_dto(r) for r in ratings],
    )


def _session_month_from_dto(value: str | None) -> SessionMonth | None:
    if value is None:
        return None
    try:
        return SessionMonth(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown session month: {value!r}") from exc


@router.get("/student-profile", response_model=StudentProfileWithEnrolmentsDTO)
def get_student_profile(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> StudentProfileWithEnrolmentsDTO:
    """Return the caller's onboarding profile plus every subject enrolment.

    Deliberately uses :meth:`~StudentProfileService.get_or_create_profile`
    (a write on a GET) rather than a read-only variant: unlike
    ``get_notification_preferences`` (an absent row reads honestly as "every
    type enabled"), an onboarding profile screen needs a real row to PATCH
    against and to attach enrolments to — there is no meaningful
    "all-defaults" onboarding state to render instead. Identity is always
    ``auth.user_id``, never a caller-supplied id — there is no student-id
    path parameter on this router, so cross-student access is structurally
    impossible, not just permission-checked.
    """
    profile = service.get_or_create_profile(auth.user_id)
    enrolments = service.list_enrolments(auth.user_id)
    dtos = [
        _enrolment_to_dto(
            enrolment, service.list_confidence_ratings(auth.user_id, enrolment.subject_code)
        )
        for enrolment in enrolments
    ]
    return StudentProfileWithEnrolmentsDTO(profile=_profile_to_dto(profile), enrolments=dtos)


@router.patch("/student-profile", response_model=StudentProfileDTO)
def patch_student_profile(
    payload: StudentProfileUpdateDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> StudentProfileDTO:
    """Partially update the caller's onboarding profile scalar fields.

    Only fields present in the request body are changed (``payload.model_fields_set``,
    the same mechanism ``put_notification_preferences`` uses); an omitted
    field is left as-is, an explicit ``null`` clears it (every field here is
    skippable per S-02) -- except ``leaderboardOptOut``, which is not
    nullable on the model (D5.1 §9): an explicit ``null`` for it is a 422,
    not a silent no-op or a coerced ``False``.
    """
    provided = payload.model_fields_set
    leaderboard_opt_out: bool | _UnsetType = UNSET
    if "leaderboardOptOut" in provided:
        if payload.leaderboardOptOut is None:
            raise HTTPException(
                status_code=422,
                detail="leaderboardOptOut cannot be null; omit it to leave unchanged",
            )
        leaderboard_opt_out = payload.leaderboardOptOut
    try:
        row = service.update_profile(
            auth.user_id,
            qualification_level=(
                payload.qualificationLevel if "qualificationLevel" in provided else UNSET
            ),
            grade_level=payload.gradeLevel if "gradeLevel" in provided else UNSET,
            school_name=payload.schoolName if "schoolName" in provided else UNSET,
            has_external_lessons=(
                payload.hasExternalLessons if "hasExternalLessons" in provided else UNSET
            ),
            weekly_study_hours=(
                payload.weeklyStudyHours if "weeklyStudyHours" in provided else UNSET
            ),
            leaderboard_opt_out=leaderboard_opt_out,
        )
    except StudentProfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _profile_to_dto(row)


@router.put("/student-profile/enrolments", response_model=list[SubjectEnrolmentDTO])
def put_student_profile_enrolments(
    payload: EnrolmentListRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> list[SubjectEnrolmentDTO]:
    """Upsert every enrolment in the request body. Enrolments not mentioned are untouched.

    This is an upsert-each-item operation, not a full-replace-the-set
    operation: the UI spec's onboarding screen submits whichever subjects
    the student is editing, and a full-replace semantic would silently
    delete any subject's enrolment (and, cascading, its confidence ratings)
    the moment a client's payload merely omitted it — the exact failure mode
    ``delete_enrolment`` requires an explicit, separate call for. Within one
    enrolment object, every field is the full desired state for that
    subject (not a patch) — an explicit ``null`` on ``qualificationLevel``/
    ``targetGrade``/``sessionMonth``/``sessionYear`` clears it.
    """
    results: list[SubjectEnrolmentDTO] = []
    try:
        for item in payload.enrolments:
            enrolment = service.upsert_enrolment(
                auth.user_id,
                item.subjectCode,
                target_grade=item.targetGrade,
                session_month=_session_month_from_dto(item.sessionMonth),
                session_year=item.sessionYear,
                qualification_level=item.qualificationLevel,
            )
            enrolment = service.set_enrolment_papers(
                auth.user_id, item.subjectCode, item.papers or []
            )
            ratings = service.list_confidence_ratings(auth.user_id, item.subjectCode)
            results.append(_enrolment_to_dto(enrolment, ratings))
    except StudentProfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return results


@router.put(
    "/student-profile/enrolments/{subject_code}/confidence-ratings",
    response_model=list[ConfidenceRatingDTO],
)
def put_student_profile_confidence_ratings(
    subject_code: str,
    payload: ConfidenceRatingsUpdateDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> list[ConfidenceRatingDTO]:
    """Full-replace the topic->rating map for one subject's enrolment.

    404 if the caller has no enrolment for ``subject_code`` — ratings hang
    off an enrolment by FK, so there is nothing to rate until the subject is
    enrolled.
    """
    try:
        rows = service.set_confidence_ratings(auth.user_id, subject_code, payload.ratings)
    except StudentProfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StudentProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_rating_to_dto(r) for r in rows]


@router.post("/student-profile/complete-onboarding", response_model=StudentProfileDTO)
def post_complete_onboarding(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> StudentProfileDTO:
    """Mark the caller's onboarding as complete (``onboarding_completed_at = now``)."""
    row = service.mark_onboarding_complete(auth.user_id)
    return _profile_to_dto(row)


# -- Devices (G-11) --------------------------------------------------------
#
# Role-agnostic, like the notification preferences above: every role signs in on
# a device and every role is subject to the same 3-device limit (D1.11). The
# caller's own id is always the token's ``sub`` — no route here takes a user id,
# so one account cannot read or revoke another's sessions.


@router.get("/devices", response_model=DeviceListDTO)
def list_devices(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    devices: Annotated[DeviceRegistry, Depends(get_device_registry)],
) -> DeviceListDTO:
    """List the caller's signed-in devices, most recently active first."""
    rows = devices.active_devices(auth.user_id)
    return DeviceListDTO(
        devices=[to_device_dto(row, current_session_id=auth.session_id) for row in rows],
        maxDevices=MAX_DEVICES,
    )


@router.delete("/devices/{device_id}", response_model=DeviceRevokedDTO)
def revoke_device(
    device_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    devices: Annotated[DeviceRegistry, Depends(get_device_registry)],
) -> DeviceRevokedDTO:
    """Sign one of the caller's devices out (idempotent).

    A device id that does not exist, is already revoked, or belongs to another
    account all answer ``removed: false`` rather than a 404 — otherwise the route
    would report whether an id exists on somebody else's account. A malformed id
    is the same answer for the same reason. Revoking the caller's **own** device
    is allowed and is simply "sign out this browser": the liveness check in
    :func:`~lemely.web.deps.get_auth_context` turns the very next request into a
    401 with no special case here, and ``wasCurrent`` tells the client to stop
    using the token now instead of discovering it then.
    """
    was_current = auth.session_id is not None and device_id == auth.session_id
    try:
        removed = devices.revoke(auth.user_id, device_id)
    except ValueError:
        removed = False
    return DeviceRevokedDTO(removed=removed, wasCurrent=was_current and removed)


__all__ = ["router"]
