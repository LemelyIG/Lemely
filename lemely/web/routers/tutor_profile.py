"""Tutor profile routes T1-T5 (SPEC §b.2 "Tutor": ``TEACHER`` + caller owns a profile).

The tutor's own profile only (O1): every route resolves it from ``auth.user_id``
through ``deps_tutoring.require_tutor_profile`` and none takes a tutor id. A
teacher without a profile gets 404 ``no_tutor_profile`` everywhere except T2
(ADR-T01). T3, T4 and T5 are write routes, refused with 409
``tutor_suspended`` / ``tutor_closed`` for a suspended or closed profile (CB-7);
T4 also needs a verified email (403 ``email_unverified``), checked after the
profile so a teacher without one always reads 404.

Validation, moderation and the listing transitions live in
:mod:`lemely.db.tutor_profile_repo`; this module maps its errors to HTTP and
serialises :class:`~lemely.web.schemas_tutoring.TutorOwnProfileDTO`. Built with
:class:`~lemely.web.tutoring_http.TutoringRoute` (``private, no-store``).
Evidence (T6, T7) and the preview (T8) live in their own routers (PLAN §1.4 #1).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends, HTTPException

from lemely.core.booking import AvailabilityRule
from lemely.db.tutor_profile_repo import (
    UNSET,
    EmailUnverifiedError,
    IllegalTransitionError,
    IncompleteProfileError,
    NotATeacherError,
    ProfileChanges,
    ProfileExistsError,
    ProfileFields,
    ProfileNotFoundError,
    ProfileValidationError,
    TutorClosedError,
    TutorProfileError,
    TutorProfileRepository,
    TutorProfileRow,
    TutorSuspendedError,
)
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import AuthContext, require_verified_email
from lemely.web.deps_tutoring import (
    get_tutor_profile_repo,
    get_tutoring_areas,
    require_teacher,
    require_tutor_profile,
    require_writable_tutor_profile,
)
from lemely.web.schemas_tutoring import (
    AvailabilityReplaceDTO,
    AvailabilityRuleDTO,
    EvidenceDTO,
    TutorOwnProfileDTO,
    TutorProfileCreateDTO,
    TutorProfileUpdateDTO,
)
from lemely.web.tutoring_http import TutoringRoute, iso_instant, profile_fields, tutoring_error

if TYPE_CHECKING:
    from collections.abc import Mapping

router = APIRouter(prefix="/api/tutor", tags=["tutoring"], route_class=TutoringRoute)

#: HTTP status of each repository refusal (the code travels in the error).
_STATUS: Final[Mapping[type[TutorProfileError], int]] = {
    ProfileNotFoundError: 404,
    NotATeacherError: 403,
    EmailUnverifiedError: 403,
    ProfileExistsError: 409,
    TutorSuspendedError: 409,
    TutorClosedError: 409,
    IllegalTransitionError: 409,
    IncompleteProfileError: 409,
    ProfileValidationError: 422,
}


def _http(exc: TutorProfileError) -> HTTPException:
    status = _STATUS.get(type(exc), 409)
    if isinstance(exc, EmailUnverifiedError):
        # The shape ``require_verified_email`` uses, so clients match one marker.
        return HTTPException(status_code=status, detail={"code": exc.code})
    return tutoring_error(status, exc.code, exc.message)


def _own_profile_dto(
    repo: TutorProfileRepository,
    areas: AreaCatalogue,
    profile_id: uuid.UUID,
    *,
    re_review_required: bool = False,
) -> TutorOwnProfileDTO:
    view = repo.own_profile(profile_id)
    if view is None:  # pragma: no cover - profiles are never deleted (SPEC §a, SC-21)
        raise tutoring_error(404, "no_tutor_profile", "You do not have a tutor profile yet.")
    return TutorOwnProfileDTO.model_validate(
        {
            **profile_fields(view.profile, areas),
            "listingState": view.listing_state.value,
            "paused": view.paused,
            "indexable": view.indexable,
            "submittedAt": iso_instant(view.submitted_at) if view.submitted_at else None,
            "reviewNote": view.review_note,
            "evidence": [
                EvidenceDTO(
                    evidenceId=str(item.id),
                    filename=item.filename,
                    contentType=item.content_type,
                    sizeBytes=item.size_bytes,
                    description=item.description,
                    uploadedAt=iso_instant(item.uploaded_at),
                )
                for item in view.evidence
            ],
            "reReviewRequired": re_review_required,
        }
    )


@router.get("/profile", response_model=TutorOwnProfileDTO)
def get_own_profile(
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
    repo: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> TutorOwnProfileDTO:
    """T1: the caller's profile in any listing state (a suspended tutor can still read it)."""
    return _own_profile_dto(repo, areas, profile.id)


@router.post("/profile", status_code=201, response_model=TutorOwnProfileDTO)
def create_profile(
    body: TutorProfileCreateDTO,
    auth: Annotated[AuthContext, Depends(require_teacher)],
    repo: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> TutorOwnProfileDTO:
    """T2: create a ``draft`` profile (``indexable`` true by default, row 17)."""
    fields = ProfileFields(
        public_first_name=body.publicFirstName,
        public_last_initial=body.publicLastInitial,
        headline=body.headline,
        bio=body.bio,
        qualification_note=body.qualificationNote,
        subject_codes=tuple(body.subjectCodes),
        offers_virtual=body.offersVirtual,
        offers_in_person=body.offersInPerson,
        offers_other=body.offersOther,
        other_mode_note=body.otherModeNote,
        area_code=body.areaCode,
    )
    try:
        row = repo.create(uuid.UUID(auth.user_id), fields)
    except TutorProfileError as exc:
        raise _http(exc) from exc
    return _own_profile_dto(repo, areas, row.id)


@router.patch("/profile", response_model=TutorOwnProfileDTO)
def update_profile(
    body: TutorProfileUpdateDTO,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    repo: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> TutorOwnProfileDTO:
    """T3: edit; ``reReviewRequired`` is true when the edit sent a listed profile to review."""
    given = body.model_fields_set
    changes = ProfileChanges(
        public_first_name=body.publicFirstName if "publicFirstName" in given else UNSET,
        public_last_initial=body.publicLastInitial if "publicLastInitial" in given else UNSET,
        headline=body.headline if "headline" in given else UNSET,
        bio=body.bio if "bio" in given else UNSET,
        qualification_note=body.qualificationNote if "qualificationNote" in given else UNSET,
        subject_codes=(
            (tuple(body.subjectCodes) if body.subjectCodes is not None else None)
            if "subjectCodes" in given
            else UNSET
        ),
        offers_virtual=body.offersVirtual if "offersVirtual" in given else UNSET,
        offers_in_person=body.offersInPerson if "offersInPerson" in given else UNSET,
        offers_other=body.offersOther if "offersOther" in given else UNSET,
        other_mode_note=body.otherModeNote if "otherModeNote" in given else UNSET,
        area_code=body.areaCode if "areaCode" in given else UNSET,
        paused=body.paused if "paused" in given else UNSET,
        indexable=body.indexable if "indexable" in given else UNSET,
    )
    try:
        row, re_review = repo.update(profile.id, changes)
    except TutorProfileError as exc:
        raise _http(exc) from exc
    return _own_profile_dto(repo, areas, row.id, re_review_required=re_review)


@router.post("/profile/submit", response_model=TutorOwnProfileDTO)
def submit_profile(
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    repo: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> TutorOwnProfileDTO:
    """T4: submit a draft or rejected profile for review."""
    try:
        row = repo.submit(profile.id)
    except TutorProfileError as exc:
        raise _http(exc) from exc
    return _own_profile_dto(repo, areas, row.id)


@router.put("/profile/availability", response_model=list[AvailabilityRuleDTO])
def replace_availability(
    body: AvailabilityReplaceDTO,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    repo: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
) -> list[AvailabilityRuleDTO]:
    """T5: replace the weekly availability (0 to 42 rules, tutor-zone wall clock)."""
    rules = [
        AvailabilityRule(
            iso_weekday=rule.isoWeekday, start_minute=rule.startMinute, end_minute=rule.endMinute
        )
        for rule in body.rules
    ]
    try:
        stored = repo.replace_availability(profile.id, rules)
    except TutorProfileError as exc:
        raise _http(exc) from exc
    return [
        AvailabilityRuleDTO(
            isoWeekday=rule.iso_weekday, startMinute=rule.start_minute, endMinute=rule.end_minute
        )
        for rule in stored
    ]


__all__ = ["router"]
