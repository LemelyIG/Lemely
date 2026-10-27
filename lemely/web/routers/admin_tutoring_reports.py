"""A9-A11: the platform admin's report queue, report detail and resolution (SPEC §b.2, X-07).

``PLATFORM_ADMIN`` only (``admin_tutors.require_platform_admin``); built with ``TutoringRoute``,
so every response is ``private, no-store`` whatever its status. The rules live in
``lemely.db.tutoring_reports_repo``; this module maps them to HTTP and sends the notices.

* **A9** ``GET /api/admin/tutoring/reports``: one ``state`` at a time (default ``open``), safety
  concerns first, then oldest first (SC-10), keyset-paged with a cursor bound to that state
  (422 ``invalid_cursor`` otherwise, O21).
* **A10** ``GET /api/admin/tutoring/reports/{report_id}``: the report, the tutor its target
  belongs to and that tutor's listing state, the snapshot (through the §i.4 allowlist) and, for
  a booking or note target, the booking summary (no meeting link; the in-person place and the
  tutor's own words on the booking) and the whole notes thread, hidden notes included, a
  student named by party. The only admin path to notes (O15): each such view writes one
  ``report_thread_view`` row first, and a failed write fails the request with no body (SC-23).
  404 ``not_found``.
* **A11** ``POST /api/admin/tutoring/reports/{report_id}/resolve``: one of the five
  resolutions and an optional note (admin-internal, at most 1000 characters, 422
  ``note_too_long``). 404, 409 ``already_resolved`` or ``resolution_not_applicable``; an action
  that already happened (a tutor already suspended or closed, a session the platform already
  cancelled, content already down) is 200 ``actioned`` with nothing more done and no notice. It
  answers with the resolved report and **no** note text (``notes: []``, and no ``body`` in a
  note target's snapshot): O15 keeps notes to A10, whose views are logged; a screen that keeps
  showing the thread reads A10 again. After the commit: a cancelled or completed session tells
  its parties (``booking_view.booking_notices_for``); a ``tutor_suspended`` resolution that ran
  the sweep sends A5's notices (``listing_notices(..., listed=False)`` and
  ``tutoring_blocks.sweep_notices``). No notice carries the admin's note.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Query

from lemely.core.keyset import CursorError
from lemely.db.models.enums import ReportResolution, ReportState
from lemely.db.notification_repo import NotificationService  # noqa: TC001 - FastAPI resolves it
from lemely.db.tutoring_reports_repo import (
    MAX_PAGE_SIZE,
    ReportDetail,
    ReportItem,
    ReportRefused,
    ReportsKey,
    TutoringReportsRepository,
    parse_reports_cursor,
    reports_cursor,
)
from lemely.web.booking_view import booking_notices_for
from lemely.web.deps import AuthContext, get_notification_service, get_push_transport
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.routers.admin_tutors import require_platform_admin
from lemely.web.routers.tutoring_blocks import sweep_notices
from lemely.web.routers.tutoring_reports import get_tutoring_reports_repo
from lemely.web.schemas_tutoring_admin import (
    ReportDetailDTO,
    ReportItemDTO,
    ReportPageDTO,
    ReportResolveDTO,
)
from lemely.web.tutoring_http import TutoringRoute, iso_instant, tutoring_error
from lemely.web.tutoring_notify import InboxNotice, listing_notices, send_after_commit

router = APIRouter(
    prefix="/api/admin/tutoring/reports", tags=["tutoring"], route_class=TutoringRoute
)

#: SPEC §0 "Paging": default page size.
DEFAULT_PAGE_SIZE: Final = 20


def _decode_cursor(cursor: str | None, state: ReportState) -> ReportsKey | None:
    if cursor is None:
        return None
    try:
        return parse_reports_cursor(cursor, state)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


def _item_fields(item: ReportItem) -> dict[str, object]:
    """The ``ReportItemDTO`` fields of one report."""
    return {
        "reportId": str(item.report_id),
        "targetType": item.target_type.value,
        "reason": item.reason.value,
        "state": item.state.value,
        "createdAt": iso_instant(item.created_at),
    }


def _detail_dto(detail: ReportDetail) -> ReportDetailDTO:
    """A10/A11's DTO; the snapshot is already filtered through the §i.4 allowlist."""
    summary = detail.booking
    return ReportDetailDTO.model_validate(
        {
            **_item_fields(detail.item),
            "reporterParty": detail.reporter_party,
            "details": detail.details,
            "tutorId": str(detail.tutor_profile_id),
            "tutorName": detail.tutor_name,
            "tutorListingState": detail.tutor_listing_state.value,
            "snapshot": dict(detail.snapshot),
            "bookingSummary": (
                None
                if summary is None
                else {
                    "bookingId": str(summary.booking_id),
                    "subject": {"code": summary.subject_code, "name": summary.subject_name},
                    "mode": summary.mode,
                    "startsAt": iso_instant(summary.starts_at),
                    "endsAt": iso_instant(summary.ends_at),
                    "effectiveState": summary.effective_state,
                    "completedBy": summary.completed_by,
                    "notesFrozen": summary.notes_frozen,
                    "declineReason": summary.decline_reason,
                    "cancelReason": summary.cancel_reason,
                    "locationDetail": summary.location_detail,
                    "otherModeNote": summary.other_mode_note,
                }
            ),
            "notes": [
                {
                    "noteId": str(note.note_id),
                    "authorParty": note.author_party,
                    "authorName": note.author_name,
                    "body": note.body,
                    "hidden": note.hidden,
                    "createdAt": iso_instant(note.created_at),
                }
                for note in detail.notes
            ],
            "resolution": None if detail.resolution is None else detail.resolution.value,
            "resolutionNote": detail.resolution_note,
            "resolvedAt": None if detail.resolved_at is None else iso_instant(detail.resolved_at),
        }
    )


@router.get("", response_model=ReportPageDTO)
def report_queue(
    _auth: Annotated[AuthContext, Depends(require_platform_admin)],
    repo: Annotated[TutoringReportsRepository, Depends(get_tutoring_reports_repo)],
    state: Annotated[Literal["open", "dismissed", "actioned"], Query()] = "open",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ReportPageDTO:
    """A9: the reports in ``state``, safety concerns first, then oldest first."""
    wanted = ReportState(state)
    page = repo.queue(wanted, after=_decode_cursor(cursor, wanted), limit=limit)
    return ReportPageDTO(
        items=[ReportItemDTO.model_validate(_item_fields(item)) for item in page.items],
        nextCursor=None if page.next_key is None else reports_cursor(wanted, page.next_key),
    )


@router.get("/{report_id}", response_model=ReportDetailDTO)
def report_detail(
    report_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    repo: Annotated[TutoringReportsRepository, Depends(get_tutoring_reports_repo)],
) -> ReportDetailDTO:
    """A10: one report with its snapshot and, for a booking or note target, the logged thread."""
    detail = repo.detail_for_admin(report_id, admin_user_id=uuid.UUID(auth.user_id))
    if detail is None:
        raise tutoring_error(404, "not_found", "Report not found.")
    return _detail_dto(detail)


@router.post("/{report_id}/resolve", response_model=ReportDetailDTO)
def resolve_report(
    report_id: uuid.UUID,
    body: ReportResolveDTO,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    repo: Annotated[TutoringReportsRepository, Depends(get_tutoring_reports_repo)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> ReportDetailDTO:
    """A11: resolve an open report; its effects commit together, the notices follow."""
    try:
        outcome = repo.resolve(
            report_id,
            admin_user_id=uuid.UUID(auth.user_id),
            resolution=ReportResolution(body.resolution),
            note=body.note,
        )
    except ReportRefused as exc:
        raise tutoring_error(exc.status, exc.code, exc.message) from exc
    notices: list[InboxNotice] = []
    if outcome.booking_change is not None:
        notices.extend(booking_notices_for(outcome.booking_change))
    sweep = outcome.sweep
    if sweep is not None:
        if sweep.approval_event_id is None or sweep.decision is None:  # pragma: no cover
            raise RuntimeError("a suspension always records its approval event")
        notices.extend(
            listing_notices(
                approval_event_id=sweep.approval_event_id,
                tutor_user_id=sweep.tutor_user_id,
                decision=sweep.decision,
                listed=False,
            )
        )
        notices.extend(
            sweep_notices(
                sweep,
                actor_user_id=None,
                tell_tutor_of_cancellations=False,
                tell_student_of_grant_end=True,
            )
        )
    send_after_commit(notices, service=service, transport=transport)
    return _detail_dto(outcome.detail)


__all__ = ["DEFAULT_PAGE_SIZE", "router"]
