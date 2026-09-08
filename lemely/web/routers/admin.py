"""Platform-admin console — internal, global endpoints under ``/api/admin``.

Gated at the router level to ``platform_admin`` alone. That is the whole of the
authorization story here, and it is why this router exists separately from
``teacher.py``/``school.py`` rather than as a widening flag on them: every other
staff surface treats ``platform_admin`` as owning nothing (D1.6/D1.10, no
super-role bypass), so the global view has to be a different door, not a wider
one. A bug in this file cannot leak one school's data into another school's
screen, because nothing here is per-school.

X-02's activation decision was the only route that mutated until the schools
surface below (D7.8): platform admins create schools, adjust their quotas, and
create the school_admin accounts that administer them. That surface is still
gated by the same rule as everything else here — it operates on every school
equally rather than a caller-owned subset, because a platform admin does not
*have* schools (D1.6/D1.10, no super-role bypass; see
``lemely.db.school_provisioning_repo`` for why that is a separate module rather
than new methods on :class:`~lemely.db.admin_repo.PlatformAdminService`).
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type
# imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely import __version__
from lemely.db.admin_repo import (
    PlatformAdminService,
    SubscriptionAlreadyDecidedError,
    SubscriptionNotFoundError,
)
from lemely.db.models.enums import Role
from lemely.db.school_provisioning_repo import (
    QuotaBelowAssignedSeatsError,
    SchoolNotFoundError,
    SchoolProvisioningService,
    SchoolSummary,
)
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.runtime.config import Settings
from lemely.web.deps import (
    AuthContext,
    get_boundary_store,
    get_platform_admin_service,
    get_school_provisioning_service,
    get_settings,
    require_role,
)
from lemely.web.schemas_admin import (
    ActivationDecisionDTO,
    ActivationQueueDTO,
    ActivationResultDTO,
    CreateSchoolAdminRequestDTO,
    CreateSchoolAdminResponseDTO,
    CreateSchoolRequestDTO,
    PendingActivationDTO,
    PipelineHealthDTO,
    PlatformCountsDTO,
    PlatformOverviewDTO,
    SchoolAdminSummaryDTO,
    SchoolListDTO,
    SchoolSummaryDTO,
    SignupDTO,
    SubjectCoverageDTO,
    SystemHealthDTO,
    UpdateSchoolRequestDTO,
)

# Gating at the router level means every current and future admin route inherits
# the 401-then-403 guard by construction, exactly as `school.py` does for
# school_admin. No route in this file may be reached by any other role,
# `school_admin` included — a school admin administers their school, not the
# platform.
router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_role(Role.platform_admin))],
)

# How many recent signups X-01 shows. Small on purpose: this is a "what just
# happened" list a human scans, not a user directory, and the console has no
# pagination to hang a larger number off.
_RECENT_SIGNUP_LIMIT = 10

# Where X-03's reader can find the accuracy numbers that do not exist at runtime.
# Prose in a DTO rather than a fabricated figure — see `schemas_admin.py`.
_MARKING_ACCURACY_NOTE = (
    "Marking accuracy is measured by the accuracy harness against the golden "
    "fixture set, not by this service. Run the harness and read reports/ for the "
    "current figures."
)

# Length (in bytes of entropy) of a generated one-time school_admin password.
# Identical to `school.py`'s `_TEMP_PASSWORD_ENTROPY_BYTES` — same credential
# handling as `invite_teacher`, because the reason for it is the same: no email
# provider exists in v1 (D7.6) to deliver anything else.
_TEMP_PASSWORD_ENTROPY_BYTES = 24


@router.get("/admin/overview", response_model=PlatformOverviewDTO)
def platform_overview(
    service: Annotated[PlatformAdminService, Depends(get_platform_admin_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlatformOverviewDTO:
    """Return X-01: global counts, health, signups.

    ``databaseReachable`` is reported as ``True`` only because the counts above
    it were produced by a query in the same request. It is an observation, not a
    separate ping that could pass while the real query fails.

    Carries no spend figure (DS3): the web process keeps no cost ledger, and the
    guard on Gemini spend is a Google Cloud billing budget on the deployed
    service, not this endpoint.
    """
    counts = service.counts()
    return PlatformOverviewDTO(
        counts=PlatformCountsDTO(
            students=counts.students,
            parents=counts.parents,
            teachers=counts.teachers,
            schoolAdmins=counts.school_admins,
            platformAdmins=counts.platform_admins,
            schools=counts.schools,
            classes=counts.classes,
            papersMarkedTotal=counts.papers_marked_total,
            papersMarkedLast24Hours=counts.papers_marked_last_24_hours,
            papersMarkedLast7Days=counts.papers_marked_last_7_days,
            openReviewItems=counts.open_review_items,
            uploadsByStatus=counts.uploads_by_status,
        ),
        health=SystemHealthDTO(
            databaseReachable=True,
            geminiKeyConfigured=settings.gemini_api_key is not None,
            version=__version__,
        ),
        recentSignups=[
            SignupDTO(
                userId=str(row.user_id),
                email=row.email,
                displayName=row.display_name,
                role=row.role.value,
                createdAt=row.created_at.isoformat(),
            )
            for row in service.recent_signups(_RECENT_SIGNUP_LIMIT)
        ],
    )


@router.get("/admin/activations", response_model=ActivationQueueDTO)
def activation_queue(
    service: Annotated[PlatformAdminService, Depends(get_platform_admin_service)],
) -> ActivationQueueDTO:
    """Return X-02: every subscription awaiting a manual decision, oldest first."""
    return ActivationQueueDTO(
        pending=[
            PendingActivationDTO(
                subscriptionId=str(row.subscription_id),
                userId=str(row.user_id),
                email=row.email,
                displayName=row.display_name,
                role=row.role.value,
                planCode=row.plan_code,
                planName=row.plan_name,
                priceMinor=row.price_minor,
                currency=row.currency,
                requestedAt=row.requested_at.isoformat(),
            )
            for row in service.pending_activations()
        ]
    )


@router.post("/admin/activations/{subscription_id}/activate", response_model=ActivationResultDTO)
def activate_subscription(
    subscription_id: uuid.UUID,
    body: ActivationDecisionDTO,
    service: Annotated[PlatformAdminService, Depends(get_platform_admin_service)],
) -> ActivationResultDTO:
    """Activate a pending subscription, recording the note.

    A subscription that has already been decided is a **409**, not an overwrite:
    two admins working one queue is the ordinary case here.
    """
    return _decide(service, subscription_id, activate=True, note=body.note)


@router.post("/admin/activations/{subscription_id}/reject", response_model=ActivationResultDTO)
def reject_subscription(
    subscription_id: uuid.UUID,
    body: ActivationDecisionDTO,
    service: Annotated[PlatformAdminService, Depends(get_platform_admin_service)],
) -> ActivationResultDTO:
    """Reject a pending subscription, recording the note.

    The row lands on ``rejected``, not ``cancelled`` — the platform declining a
    request and a subscriber ending one are different events (migration ``0019``).
    """
    return _decide(service, subscription_id, activate=False, note=body.note)


def _decide(
    service: PlatformAdminService,
    subscription_id: uuid.UUID,
    *,
    activate: bool,
    note: str | None,
) -> ActivationResultDTO:
    """Shared error mapping for the two decision routes."""
    try:
        status = service.decide_activation(subscription_id, activate=activate, note=note)
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriptionAlreadyDecidedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ActivationResultDTO(subscriptionId=str(subscription_id), status=status.value)


@router.get("/admin/pipeline", response_model=PipelineHealthDTO)
def pipeline_health(
    service: Annotated[PlatformAdminService, Depends(get_platform_admin_service)],
    boundaries: Annotated[GradeBoundaryStore, Depends(get_boundary_store)],
) -> PipelineHealthDTO:
    """Return X-03: corpus coverage, boundary reliance, ingestion outcomes."""
    health = service.pipeline_health(
        exact_boundary_keys=boundaries.exact_key_count,
        subject_default_boundary_keys=boundaries.subject_default_count,
    )
    return PipelineHealthDTO(
        subjects=[
            SubjectCoverageDTO(
                subjectCode=subject.subject_code,
                papers=subject.papers,
                papersWithScheme=subject.papers_with_scheme,
                papersWithoutScheme=subject.papers_without_scheme,
            )
            for subject in health.subjects
        ],
        boundarySourceCounts=health.boundary_source_counts,
        exactBoundaryKeys=health.exact_boundary_keys,
        subjectDefaultBoundaryKeys=health.subject_default_boundary_keys,
        uploadsByStatus=health.uploads_by_status,
        recentFailedUploadIds=[str(upload_id) for upload_id in health.recent_failed_uploads],
        markingAccuracyNote=_MARKING_ACCURACY_NOTE,
    )


# ── Schools (D7.8, spec §1.1) ───────────────────────────────────────────────
#
# The account graph's missing first link: before these four routes, no
# production code path created a `School` row or a `school_admin` account, so
# `POST /api/school/teachers/invite` — the only teacher-creation path D1.7
# allows — was unreachable in any real deployment. See
# `lemely.db.school_provisioning_repo` for the full account of why this is a
# separate service module rather than new methods on `PlatformAdminService`.


def _school_summary_to_dto(summary: SchoolSummary) -> SchoolSummaryDTO:
    """Convert a service :class:`SchoolSummary` into its wire DTO."""
    return SchoolSummaryDTO(
        schoolId=str(summary.school_id),
        name=summary.name,
        seatQuota=summary.seat_quota,
        seatsAssigned=summary.seats_assigned,
        seatsAvailable=summary.seats_available,
        admins=[
            SchoolAdminSummaryDTO(
                userId=str(admin.user_id), email=admin.email, displayName=admin.display_name
            )
            for admin in summary.admins
        ],
    )


@router.get("/admin/schools", response_model=SchoolListDTO)
def list_schools(
    service: Annotated[SchoolProvisioningService, Depends(get_school_provisioning_service)],
) -> SchoolListDTO:
    """Return every school on the platform, with quota, seat usage and admins.

    No school id is supplied and none is needed: a platform admin has no
    tenant to scope to (D1.6/D1.10), so this is every school there is, not a
    caller-owned subset — the same "no tenant scope at all" property
    :class:`~lemely.db.admin_repo.PlatformAdminService` already documents for
    the rest of this router.
    """
    return SchoolListDTO(schools=[_school_summary_to_dto(s) for s in service.list_schools()])


@router.post("/admin/schools", response_model=SchoolSummaryDTO)
def create_school(
    body: CreateSchoolRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.platform_admin))],
    service: Annotated[SchoolProvisioningService, Depends(get_school_provisioning_service)],
) -> SchoolSummaryDTO:
    """Create a school with an initial seat quota — the missing first link (spec §1.1).

    ``createdBy`` is not a wire field; the school's ``created_by`` column is
    stamped from the authenticated caller so the schema records who
    provisioned each tenant, the first path ever to write to that column with
    a real, identified admin rather than a fixture.
    """
    summary = service.create_school(body.name, body.seatQuota, created_by=auth.user_id)
    return _school_summary_to_dto(summary)


@router.patch("/admin/schools/{school_id}", response_model=SchoolSummaryDTO)
def update_school(
    school_id: uuid.UUID,
    body: UpdateSchoolRequestDTO,
    service: Annotated[SchoolProvisioningService, Depends(get_school_provisioning_service)],
) -> SchoolSummaryDTO:
    """Rename a school and/or change its seat quota.

    A quota lowered below the seats already assigned is a **409** naming both
    numbers, never a silent accept that would leave usage over capacity
    (Task 12's own test for this).
    """
    try:
        summary = service.update_school(school_id, name=body.name, seat_quota=body.seatQuota)
    except SchoolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QuotaBelowAssignedSeatsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _school_summary_to_dto(summary)


@router.post("/admin/schools/{school_id}/admins", response_model=CreateSchoolAdminResponseDTO)
def create_school_admin(
    school_id: uuid.UUID,
    body: CreateSchoolAdminRequestDTO,
    service: Annotated[SchoolProvisioningService, Depends(get_school_provisioning_service)],
) -> CreateSchoolAdminResponseDTO:
    """Create a school_admin account and bind it to ``school_id`` as staff.

    Account and membership are written together, in one service call: a
    school_admin with no membership administers nothing and meets an empty
    console, which D4.10 found indistinguishable on screen from a broken one.

    Same credential handling as ``POST /api/school/teachers/invite``: no email
    provider exists in v1 (D7.6), so an omitted password is generated once
    here and returned once in ``temporaryPassword`` for the platform admin to
    convey out of band.
    """
    generated = body.password is None
    password = body.password or secrets.token_urlsafe(_TEMP_PASSWORD_ENTROPY_BYTES)
    try:
        result = service.create_school_admin(
            school_id, body.email, password, display_name=body.displayName
        )
    except SchoolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CreateSchoolAdminResponseDTO(
        userId=str(result.user_id),
        membershipId=str(result.membership_id),
        email=result.email,
        temporaryPassword=password if generated else None,
    )
