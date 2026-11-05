"""A5 suspend and A12 close (SPEC §b.2 "Platform admin", §a.3, §a.4b, §b.4; SC-3, SC-21).

``platform_admin`` only, like A1-A4 (``admin_tutors.require_platform_admin``); built with
``TutoringRoute`` (``private, no-store`` on every status).

* **A5** ``POST /api/admin/tutors/{tutor_id}/suspend`` (``AdminNoteDTO``): from ``listed``,
  ``pending_review`` or ``rejected``; anything else 409 ``illegal_transition``. The note is
  shown to the tutor (SPEC §a.2).
* **A12** ``POST /api/admin/tutors/{tutor_id}/close`` (``AdminNoteDTO``): from anything but
  ``closed`` (409 ``already_closed``; irreversible in v1, SC-21). The note is admin-internal.

Both run ``TutoringSweeps.sanction``: one transaction that cancels every future session,
revokes every live grant, removes school-less enrolments, moves the listing, records the
approval event and queues the tutor's email (SPEC §a.3, §b.4). 404 for an unknown tutor, 422
``note_too_long`` past 2000 characters; a refusal writes nothing. They answer with the A2 shape
(``signedUrl: null`` on every file: only A2 issues links). After the commit the tutor gets the
listing notice (``listing_notices(..., listed=False)``) and one generic "access ended" per
grant; each student whose grant ended reads "can no longer see your progress"; each student and
linked parent the cancellation (``tutoring_blocks.sweep_notices``). No notice carries the note.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends

from lemely.db.notification_repo import NotificationService  # noqa: TC001 - FastAPI resolves it
from lemely.db.session import get_sessionmaker
from lemely.db.tutor_approval_repo import (
    ApprovalError,
    IllegalApprovalTransitionError,
    NoteTooLongError,
    TutorApprovalRepository,
    TutorNotFoundError,
)
from lemely.db.tutor_evidence_repo import (
    TutorEvidenceRepository,  # noqa: TC001 - FastAPI resolves it
)
from lemely.db.tutor_profile_repo import TutorProfileRepository  # noqa: TC001 - FastAPI resolves it
from lemely.db.tutoring_sweeps import AlreadyClosedError, TutoringSweeps
from lemely.io.tutoring_areas import AreaCatalogue  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import AuthContext, get_notification_service, get_push_transport, get_settings
from lemely.web.deps_tutoring import get_tutor_profile_repo, get_tutoring_areas
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.routers.admin_tutors import (
    _detail_without_urls,
    get_tutor_approval_repo,
    require_platform_admin,
)
from lemely.web.routers.tutor_evidence import get_tutor_evidence_repo
from lemely.web.routers.tutoring_blocks import sweep_notices
from lemely.web.schemas_tutoring_admin import AdminNoteDTO, AdminTutorDetailDTO
from lemely.web.tutoring_http import TutoringRoute, tutoring_error
from lemely.web.tutoring_notify import listing_notices, send_after_commit

if TYPE_CHECKING:
    from lemely.db.tutoring_sweeps import SanctionReason

router = APIRouter(prefix="/api/admin/tutors", tags=["tutoring"], route_class=TutoringRoute)

_STATUS: Final[dict[type[ApprovalError], int]] = {
    TutorNotFoundError: 404,
    IllegalApprovalTransitionError: 409,
    AlreadyClosedError: 409,
    NoteTooLongError: 422,
}


@lru_cache(maxsize=1)
def get_tutoring_sweeps() -> TutoringSweeps:
    """The process-wide :class:`TutoringSweeps`."""
    return TutoringSweeps(get_sessionmaker(get_settings()))


def _sanction(
    tutor_id: uuid.UUID,
    reason: SanctionReason,
    note: str | None,
    *,
    auth: AuthContext,
    sweeps: TutoringSweeps,
    service: NotificationService,
    transport: NotificationTransport,
) -> None:
    """Run the sanction, then tell everyone it touched (after the commit, D5.9 §1)."""
    try:
        result = sweeps.sanction(
            tutor_id, reason=reason, admin_user_id=uuid.UUID(auth.user_id), note=note
        )
    except ApprovalError as exc:
        raise tutoring_error(_STATUS.get(type(exc), 409), exc.code, exc.message) from exc
    if result.approval_event_id is None or result.decision is None:  # pragma: no cover
        raise RuntimeError("a sanction always records its approval event")
    send_after_commit(
        [
            *listing_notices(
                approval_event_id=result.approval_event_id,
                tutor_user_id=result.tutor_user_id,
                decision=result.decision,
                listed=False,
            ),
            *sweep_notices(
                result,
                actor_user_id=None,
                tell_tutor_of_cancellations=False,
                tell_student_of_grant_end=True,
            ),
        ],
        service=service,
        transport=transport,
    )


@router.post("/{tutor_id}/suspend", response_model=AdminTutorDetailDTO)
def suspend_tutor(
    tutor_id: uuid.UUID,
    body: AdminNoteDTO,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    sweeps: Annotated[TutoringSweeps, Depends(get_tutoring_sweeps)],
    profiles: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    approvals: Annotated[TutorApprovalRepository, Depends(get_tutor_approval_repo)],
    evidence: Annotated[TutorEvidenceRepository, Depends(get_tutor_evidence_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> AdminTutorDetailDTO:
    """A5: suspend a ``listed``, ``pending_review`` or ``rejected`` tutor and sweep their pairs."""
    _sanction(
        tutor_id,
        "tutor_suspended",
        body.note,
        auth=auth,
        sweeps=sweeps,
        service=service,
        transport=transport,
    )
    return _detail_without_urls(tutor_id, profiles, approvals, evidence, areas)


@router.post("/{tutor_id}/close", response_model=AdminTutorDetailDTO)
def close_tutor(
    tutor_id: uuid.UUID,
    body: AdminNoteDTO,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    sweeps: Annotated[TutoringSweeps, Depends(get_tutoring_sweeps)],
    profiles: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    approvals: Annotated[TutorApprovalRepository, Depends(get_tutor_approval_repo)],
    evidence: Annotated[TutorEvidenceRepository, Depends(get_tutor_evidence_repo)],
    areas: Annotated[AreaCatalogue, Depends(get_tutoring_areas)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> AdminTutorDetailDTO:
    """A12: close a tutor profile for good, with the same sweep as a suspension."""
    _sanction(
        tutor_id,
        "tutor_closed",
        body.note,
        auth=auth,
        sweeps=sweeps,
        service=service,
        transport=transport,
    )
    return _detail_without_urls(tutor_id, profiles, approvals, evidence, areas)


__all__ = ["get_tutoring_sweeps", "router"]
