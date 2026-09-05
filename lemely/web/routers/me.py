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
from io import BytesIO
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image

from lemely.auth.mirror import UserMirror
from lemely.db.device_repo import MAX_DEVICES, DeviceRegistry
from lemely.db.models.enums import Role, SessionMonth
from lemely.db.models.users import User
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
from lemely.io.storage import StorageBackend
from lemely.runtime.config import Settings
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_device_registry,
    get_notification_prefs_service,
    get_settings,
    get_storage_backend,
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
from lemely.web.upload_utils import check_upload_cap

router = APIRouter(prefix="/api/me")
log = structlog.get_logger(__name__)

# Avatar content types this build accepts, mapped to the extension the stored
# object path carries — derived from the *sniffed* content type, never the
# caller-supplied filename (mirrors ``lemely.web.upload_utils.safe_upload_name``'s
# refusal to trust client-controlled names for anything but display).
_AVATAR_CONTENT_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

# The Pillow-reported format each declared content type must actually sniff
# as — a mismatch (e.g. real GIF bytes declared ``image/png``) is rejected
# even though it decodes cleanly: it would otherwise be stored under an
# extension that lies about what the bytes are.
_AVATAR_PIL_FORMATS: dict[str, str] = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/webp": "WEBP",
}

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


def _require_user_id(auth: AuthContext) -> uuid.UUID:
    """Parse ``auth.user_id`` (the token ``sub``) as a UUID, or raise 422.

    Shared by every ``/api/me/profile`` and ``/api/me/avatar`` route — should
    not occur against a real token, but the mirror lookup requires a real
    :class:`uuid.UUID`, not the bare string :class:`AuthContext` carries.
    """
    try:
        return uuid.UUID(auth.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Malformed user id.") from exc


def _avatar_url_for(user: User, settings: Settings, storage: StorageBackend) -> str | None:
    """Sign a fresh, time-limited URL for ``user``'s avatar, or ``None``.

    ``None`` both when no avatar is set (``avatar_path is None``) and when
    storage cannot be reached to sign one — the profile read (and the sidebar
    it backs) must never 500 just because object storage is unavailable.

    Catches ``Exception`` broadly rather than just
    :class:`~lemely.runtime.errors.ExternalServiceError`: a misconfigured
    Supabase service-role key raises :class:`~lemely.runtime.errors.AuthError`,
    and a misconfigured GCS credential can raise a plain google-auth error —
    neither is this helper's caller's problem, since its whole contract is
    "never fail the profile read".
    """
    if user.avatar_path is None:
        return None
    try:
        return storage.create_signed_url(
            settings.storage.avatar_bucket,
            user.avatar_path,
            settings.storage.signed_url_ttl_seconds,
        )
    except Exception as exc:  # this helper's contract is "never fail the profile read".
        log.warning("avatar_signed_url_failed", user_id=str(user.id), error=str(exc))
        return None


def _profile_dto(user: User, settings: Settings, storage: StorageBackend) -> ProfileDTO:
    """Build the ``ProfileDTO`` every ``/api/me/profile``-family route returns."""
    return ProfileDTO(
        displayName=user.display_name,
        email=user.email,
        role=user.role.value,
        emailVerified=user.email_verified_at is not None,
        avatarUrl=_avatar_url_for(user, settings, storage),
    )


@router.get("/profile", response_model=ProfileDTO)
def get_profile(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
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
    user_id = _require_user_id(auth)
    user = mirror.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No profile found for this account.")
    return _profile_dto(user, settings, storage)


# ---------------------------------------------------------------------------
# Avatar (profile picture): any authenticated role.
# ---------------------------------------------------------------------------


@router.post("/avatar", response_model=ProfileDTO)
async def upload_avatar(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    image: Annotated[UploadFile, File()],
) -> ProfileDTO:
    """Set the authenticated caller's profile picture (every role, like ``get_profile``).

    Accepts only ``image/png``, ``image/jpeg``, or ``image/webp`` by the
    upload's declared content type (415 otherwise), caps the body at
    ``settings.storage.avatar_max_bytes`` (413 over), and confirms the bytes
    actually decode as an image with Pillow (422 on failure) — a client that
    lies about the content type does not get to write an arbitrary blob into
    the avatars bucket under an image content type. An image that decodes
    cleanly but sniffs as a *different* format than the declared content type
    (e.g. real GIF bytes declared ``image/png``) is also rejected (415),
    rather than stored under an extension that lies about the bytes. An
    image whose declared dimensions are absurdly large for its byte size —
    Pillow's decompression-bomb guard — is a 422, not an unhandled 500: unlike
    a plain corrupt/truncated file (``OSError``/``ValueError``), Pillow raises
    :class:`PIL.Image.DecompressionBombError` for that case, which subclasses
    ``Exception`` directly rather than either of those. The object path is
    server-generated (``{user_id}/{uuid4().hex}.{ext}``, inside the avatars
    bucket), never derived from the client's filename, and namespaced by the
    caller's own id so one account can never overwrite another's avatar.

    Returns the same :class:`ProfileDTO` shape as ``GET /api/me/profile`` so
    the client can replace its cached profile with the response body directly.
    """
    content_type = image.content_type or ""
    ext = _AVATAR_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(
            status_code=415,
            detail="Only PNG, JPEG, or WEBP images are accepted.",
        )

    data = await image.read()
    check_upload_cap(data, max_bytes=settings.storage.avatar_max_bytes)

    try:
        with Image.open(BytesIO(data)) as img:
            sniffed_format = img.format
            img.verify()
    except Image.DecompressionBombError as exc:
        raise HTTPException(status_code=422, detail="Image dimensions are too large.") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Upload is not a valid image.") from exc

    if sniffed_format != _AVATAR_PIL_FORMATS[content_type]:
        raise HTTPException(
            status_code=415,
            detail="Image content does not match its declared content type.",
        )

    user_id = _require_user_id(auth)
    object_path = f"{user_id}/{uuid.uuid4().hex}.{ext}"
    storage.upload(settings.storage.avatar_bucket, object_path, data, image.content_type)
    mirror.set_avatar_path(user_id, object_path)

    user = mirror.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No profile found for this account.")
    return _profile_dto(user, settings, storage)


@router.delete("/avatar", response_model=ProfileDTO)
def delete_avatar(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> ProfileDTO:
    """Clear the authenticated caller's profile picture.

    Only clears the ``users.avatar_path`` pointer — the object itself is left
    in storage. :class:`~lemely.io.storage.StorageBackend` has no delete
    operation (P2.5 never needed one), so there is nothing to call here; the
    orphaned object is simply never referenced by a signed URL again.
    """
    user_id = _require_user_id(auth)
    mirror.set_avatar_path(user_id, None)

    user = mirror.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No profile found for this account.")
    return _profile_dto(user, settings, storage)


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
