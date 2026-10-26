"""Platform-admin tutor approval routes A1-A4 (SPEC §b.2 "Platform admin", §a.3, SC-6, SC-22/23).

``platform_admin`` only, on every route (no super-role: a ``school_admin`` is
refused like everyone else). Built with ``TutoringRoute``, so every response is
``private, no-store`` whatever its status.

* **A1** ``GET /api/admin/tutors``: the X-04 queue, one listing state at a time
  (default ``pending_review``), oldest submission first, keyset-paged with a
  cursor bound to that state. ``emailDelivery`` says whether tutoring mail
  really leaves (``provider``) or is recorded as skipped (``mock``, SC-6).
* **A2** ``GET /api/admin/tutors/{tutor_id}``: X-05's application. The only
  route that issues evidence URLs: 300 s (``tutor_evidence_signed_url_ttl_seconds``),
  ``Content-Disposition: attachment`` (SC-22), each one logged as an
  ``evidence_open`` row in the same transaction; if the log cannot be written
  the request fails and no URL leaves (SC-23). A file the backend cannot sign
  is listed with ``signedUrl: null`` and logs nothing.
* **A3** approve, or reinstate a suspended tutor (to ``listed`` if approved
  before, else back to ``pending_review``: the lead's ruling on decision row 5a);
  **A4** reject, with a note the tutor reads. Both answer with the A2 shape and
  ``signedUrl: null`` on every file (only A2 issues URLs; T04 hand-off), and tell
  the tutor through the inbox after the commit (D5.9 §1); the email was queued
  inside the decision's transaction.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Final, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.core.keyset import CursorError
from lemely.core.tutor_directory import public_name
from lemely.db.models.enums import Role, TutorListingState
from lemely.db.notification_repo import NotificationService  # noqa: TC001 - FastAPI resolves it
from lemely.db.session import get_sessionmaker
from lemely.db.tutor_approval_repo import (
    AdminTutorFacts,
    ApprovalError,
    ApprovalOutcome,
    IllegalApprovalTransitionError,
    NoteRequiredError,
    NoteTooLongError,
    QueueKey,
    TutorApprovalRepository,
    TutorNotFoundError,
    parse_queue_cursor,
    queue_cursor,
)
from lemely.db.tutor_evidence_repo import (
    IssuedEvidence,
    StoredEvidence,
    TutorEvidenceRepository,
)
from lemely.db.tutor_profile_repo import TutorProfileRepository  # noqa: TC001 - FastAPI resolves it
from lemely.io.evidence_files import attachment_disposition
from lemely.io.storage import StorageBackend  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import (
    AuthContext,
    get_notification_service,
    get_push_transport,
    get_settings,
    get_storage_backend,
    require_role,
)
from lemely.web.deps_tutoring import get_tutor_profile_repo, get_tutoring_areas
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.routers.tutor_evidence import get_tutor_evidence_repo
from lemely.web.schemas_tutoring_admin import (
    AdminApprovalEventDTO,
    AdminApproveDTO,
    AdminEvidenceDTO,
    AdminNoteDTO,
    AdminTutorDetailDTO,
    AdminTutorItemDTO,
    AdminTutorPageDTO,
)
from lemely.web.tutoring_email import email_delivery_mode
from lemely.web.tutoring_http import (
    TutoringRoute,
    iso_instant,
    profile_fields,
    subject_ref_dtos,
    tutoring_error,
)
from lemely.web.tutoring_notify import listing_notices, send_after_commit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.db.tutor_profile_repo import OwnProfileView

router = APIRouter(prefix="/api/admin/tutors", tags=["tutoring"], route_class=TutoringRoute)
log = structlog.get_logger(__name__)

require_platform_admin: Final = require_role(Role.platform_admin)

ListingStateLit = Literal["draft", "pending_review", "listed", "rejected", "suspended", "closed"]

_STATUS: Final[dict[type[ApprovalError], int]] = {
    TutorNotFoundError: 404,
    IllegalApprovalTransitionError: 409,
    NoteRequiredError: 422,
    NoteTooLongError: 422,
}


def get_tutor_approval_repo() -> TutorApprovalRepository:
    """A :class:`TutorApprovalRepository` on the process-wide sessionmaker (cheap; not cached)."""
    return TutorApprovalRepository(get_sessionmaker(get_settings()))


def _http(exc: ApprovalError) -> HTTPException:
    return tutoring_error(_STATUS.get(type(exc), 409), exc.code, exc.message)


def _not_found() -> HTTPException:
    return _http(TutorNotFoundError("Tutor not found."))


def _evidence(issued: Sequence[IssuedEvidence]) -> list[AdminEvidenceDTO]:
    return [
        AdminEvidenceDTO(
            evidenceId=str(item.evidence.id),
            filename=item.evidence.filename,
            contentType=item.evidence.content_type,
            sizeBytes=item.evidence.size_bytes,
            description=item.evidence.description,
            uploadedAt=iso_instant(item.evidence.uploaded_at),
            signedUrl=item.signed_url,
        )
        for item in issued
    ]


def _detail(
    view: OwnProfileView,
    facts: AdminTutorFacts,
    evidence: Sequence[IssuedEvidence],
    areas: AreaCatalogue,
) -> AdminTutorDetailDTO:
    return AdminTutorDetailDTO.model_validate(
        {
            **profile_fields(view.profile, areas),
            "listingState": view.listing_state.value,
            "paused": view.paused,
            "indexable": view.indexable,
            "submittedAt": iso_instant(view.submitted_at) if view.submitted_at else None,
            "reviewNote": view.review_note,
            "evidence": _evidence(evidence),
            "reReviewRequired": False,
            "accountEmail": facts.account_email,
            "history": [
                AdminApprovalEventDTO(
                    decision=entry.decision.value,
                    documentsSeen=entry.documents_seen,
                    note=entry.note,
                    createdAt=iso_instant(entry.created_at),
                )
                for entry in facts.history
            ],
            "openReports": facts.open_reports,
        }
    )


def _detail_without_urls(
    tutor_id: uuid.UUID,
    profiles: TutorProfileRepository,
    approvals: TutorApprovalRepository,
    evidence: TutorEvidenceRepository,
    areas: AreaCatalogue,
) -> AdminTutorDetailDTO:
    """The A2 shape with ``signedUrl: null`` everywhere and no access row (A3, A4)."""
    view = profiles.own_profile(tutor_id)
    facts = approvals.admin_facts(tutor_id)
    if view is None or facts is None:  # pragma: no cover - profiles are never deleted (SC-21)
        raise _not_found()
    unsigned = [
        IssuedEvidence(evidence=item, signed_url=None) for item in evidence.list_stored(tutor_id)
    ]
    return _detail(view, facts, unsigned, areas)


def _tell_tutor(
    outcome: ApprovalOutcome, service: NotificationService, transport: NotificationTransport
) -> None:
    if outcome.notify_tutor:
        send_after_commit(
            listing_notices(
                approval_event_id=outcome.event_id,
                tutor_user_id=outcome.tutor_user_id,
                decision=outcome.decision,
            ),
            service=service,
            transport=transport,
        )


@router.get("", response_model=AdminTutorPageDTO)
def list_tutors(
    _auth: Annotated[AuthContext, Depends(require_platform_admin)],
    approvals: Annotated[TutorApprovalRepository, Depends(get_tutor_approval_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[ListingStateLit, Query()] = "pending_review",
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> AdminTutorPageDTO:
    """A1: one page of tutor profiles in ``state``, oldest submission first."""
    listing_state = TutorListingState(state)
    after: QueueKey | None = None
    if cursor is not None:
        try:
            after = parse_queue_cursor(cursor, listing_state)
        except CursorError as exc:
            raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc
    page = approvals.queue(listing_state, after=after, limit=limit)
    return AdminTutorPageDTO(
        items=[
            AdminTutorItemDTO(
                tutorId=str(item.tutor_id),
                publicName=public_name(item.public_first_name, item.public_last_initial),
                subjects=subject_ref_dtos(item.subjects),
                submittedAt=iso_instant(item.submitted_at) if item.submitted_at else None,
            )
            for item in page.items
        ],
        nextCursor=queue_cursor(listing_state, page.next_key) if page.next_key else None,
        emailDelivery=email_delivery_mode(settings),
    )


@router.get("/{tutor_id}", response_model=AdminTutorDetailDTO)
def tutor_detail(
    tutor_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    profiles: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    approvals: Annotated[TutorApprovalRepository, Depends(get_tutor_approval_repo)],
    evidence: Annotated[TutorEvidenceRepository, Depends(get_tutor_evidence_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
) -> AdminTutorDetailDTO:
    """A2: the application, with 300 s attachment links to the evidence, each one logged."""
    view = profiles.own_profile(tutor_id)
    facts = approvals.admin_facts(tutor_id)
    if view is None or facts is None:
        raise _not_found()
    bucket = settings.storage.tutor_evidence_bucket
    ttl = settings.storage.tutor_evidence_signed_url_ttl_seconds

    def sign(item: StoredEvidence) -> str | None:
        try:
            return storage.create_signed_url(
                bucket, item.storage_path, ttl, disposition=attachment_disposition(item.filename)
            )
        except Exception as exc:
            # Signing failed, so no URL is issued and nothing is logged for this file.
            log.warning("tutor_evidence_sign_failed", evidence_id=str(item.id), error=str(exc))
            return None

    # Last, so that nothing after the URLs are logged can fail the response (SC-23).
    issued = evidence.issue_admin_urls(tutor_id, admin_user_id=uuid.UUID(auth.user_id), sign=sign)
    return _detail(view, facts, issued, areas)


@router.post("/{tutor_id}/approve", response_model=AdminTutorDetailDTO)
def approve_tutor(
    tutor_id: uuid.UUID,
    body: AdminApproveDTO,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    profiles: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    approvals: Annotated[TutorApprovalRepository, Depends(get_tutor_approval_repo)],
    evidence: Annotated[TutorEvidenceRepository, Depends(get_tutor_evidence_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> AdminTutorDetailDTO:
    """A3: approve a ``pending_review`` profile, or reinstate a ``suspended`` one."""
    try:
        outcome = approvals.approve(
            tutor_id,
            admin_user_id=uuid.UUID(auth.user_id),
            documents_seen=body.documentsSeen,
            note=body.note,
        )
    except ApprovalError as exc:
        raise _http(exc) from exc
    _tell_tutor(outcome, service, transport)
    return _detail_without_urls(tutor_id, profiles, approvals, evidence, areas)


@router.post("/{tutor_id}/reject", response_model=AdminTutorDetailDTO)
def reject_tutor(
    tutor_id: uuid.UUID,
    body: AdminNoteDTO,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    profiles: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    approvals: Annotated[TutorApprovalRepository, Depends(get_tutor_approval_repo)],
    evidence: Annotated[TutorEvidenceRepository, Depends(get_tutor_evidence_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> AdminTutorDetailDTO:
    """A4: reject a ``pending_review`` profile; the note is required and shown to the tutor."""
    try:
        outcome = approvals.reject(tutor_id, admin_user_id=uuid.UUID(auth.user_id), note=body.note)
    except ApprovalError as exc:
        raise _http(exc) from exc
    _tell_tutor(outcome, service, transport)
    return _detail_without_urls(tutor_id, profiles, approvals, evidence, areas)


__all__ = ["get_tutor_approval_repo", "require_platform_admin", "router"]
