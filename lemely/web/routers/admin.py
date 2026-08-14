"""Platform-admin console — internal, global endpoints under ``/api/admin``.

Gated at the router level to ``platform_admin`` alone. That is the whole of the
authorization story here, and it is why this router exists separately from
``teacher.py``/``school.py`` rather than as a widening flag on them: every other
staff surface treats ``platform_admin`` as owning nothing (D1.6/D1.10, no
super-role bypass), so the global view has to be a different door, not a wider
one. A bug in this file cannot leak one school's data into another school's
screen, because nothing here is per-school.

The one route that mutates is X-02's activation decision. Everything else is a
read of counted facts.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type
# imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

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
from lemely.io.cost_ledger import CostLedger
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.runtime.config import Settings
from lemely.web.deps import (
    get_boundary_store,
    get_platform_admin_service,
    get_settings,
    require_role,
)
from lemely.web.schemas_admin import (
    ActivationDecisionDTO,
    ActivationQueueDTO,
    ActivationResultDTO,
    PendingActivationDTO,
    PipelineHealthDTO,
    PlatformCountsDTO,
    PlatformOverviewDTO,
    SignupDTO,
    SpendDTO,
    SubjectCoverageDTO,
    SystemHealthDTO,
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


@router.get("/admin/overview", response_model=PlatformOverviewDTO)
def platform_overview(
    service: Annotated[PlatformAdminService, Depends(get_platform_admin_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlatformOverviewDTO:
    """Return X-01: global counts, spend against the ceiling, health, signups.

    ``databaseReachable`` is reported as ``True`` only because the counts above
    it were produced by a query in the same request. It is an observation, not a
    separate ping that could pass while the real query fails.
    """
    counts = service.counts()
    ledger = CostLedger(settings.paths.output_dir / "gemini_spend.json")
    cumulative = ledger.total()
    ceiling = settings.gemini.total_usd_ceiling
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
        spend=SpendDTO(
            cumulativeUsd=round(cumulative, 4),
            ceilingUsd=ceiling,
            remainingUsd=None if ceiling is None else round(max(0.0, ceiling - cumulative), 4),
            thresholdsUsd=list(settings.gemini.usd_warning_thresholds),
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
