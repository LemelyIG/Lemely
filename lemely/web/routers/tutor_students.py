"""T19 and T20: the students who share their progress with the caller (SPEC §b.2 "Tutor", ADR-T02).

``TEACHER`` + the caller's own tutor profile, resolved from ``auth.user_id``
(``deps_tutoring.require_tutor_profile``, O1): a teacher without one gets 404
``no_tutor_profile``, and no route here takes a tutor id. The grant lookup is
keyed on that profile only (O18), and the class roster is never consulted (O14):
a class teacher sees a student here only through a grant, and a grant opens no
teacher route.

* **T19** lists the caller's students with a valid grant, newest grant first
  (``grantedAt DESC, grantId``): the student's label, the grant date and the
  number of upcoming sessions, no analytics. Its repository call writes one
  ``list`` audit row per student on the page before it reads their names (O3).
* **T20** checks the grant and writes the ``detail`` audit row in one transaction
  that commits before any of the student's data is read
  (``TutorGrantRepository.require_valid_grant``). An ended grant answers one 403
  ``access_ended`` whatever ended it (SC-11); no grant ever for this pair, or an
  unknown id, answers one 404 (no existence oracle). The detail is the teacher
  builder's output through the tutor projection (``student_detail_view``, SPEC
  §e.2): days, not times, in the tutor's zone; no question ids; no teacher
  acknowledgements.
* **The grant date is a day.** Both routes send ``grantedAt`` as the grant's
  calendar day in the tutor's zone (``YYYY-MM-DD``, like every tutor-projection
  timestamp), never the instant: the hour a student shared is theirs (ID-9,
  F30-4).
* **Fail closed.** When the audit row cannot be written the request fails with
  a 500 and an empty body: no read without its record (SPEC §b.4 point 3).

Built with :class:`~lemely.web.tutoring_http.TutoringRoute` (``private, no-store``).
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI reads the path parameter type at runtime
from datetime import UTC, datetime
from typing import Annotated, Final

import structlog
from fastapi import APIRouter, Depends, Query, Response

from lemely.core.history import HistoryStoreProtocol  # noqa: TC001 - FastAPI resolves it
from lemely.core.keyset import CursorError
from lemely.db.student_profile_repo import (
    StudentProfileService,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.tutor_grant_repo import (
    MAX_PAGE_SIZE,
    AccessEnded,
    AuditUnavailable,
    NoGrant,
    TutorGrantRepository,
    TutorStudentKey,
    parse_tutor_students_cursor,
    tutor_students_cursor,
)
from lemely.db.tutor_profile_repo import TutorProfileRow  # noqa: TC001 - FastAPI resolves it
from lemely.web.deps import get_history_store, get_student_profile_service
from lemely.web.deps_tutoring import require_tutor_profile
from lemely.web.routers.student_tutor_access import DEFAULT_PAGE_SIZE, get_tutor_grant_repo
from lemely.web.schemas_tutoring import (
    TutorStudentDetailDTO,
    TutorStudentItemDTO,
    TutorStudentPageDTO,
)
from lemely.web.student_detail_view import build_student_detail_for_tutor, tutor_zone_day
from lemely.web.tutoring_http import TutoringRoute, iso_instant, tutoring_error

log = structlog.get_logger(__name__)

#: The T19 cursor tag (O21).
STUDENTS_ENDPOINT: Final = "tutor_students"

router = APIRouter(prefix="/api/tutor", tags=["tutoring"], route_class=TutoringRoute)


def _decode_cursor(cursor: str | None) -> TutorStudentKey | None:
    if cursor is None:
        return None
    try:
        return parse_tutor_students_cursor(cursor, STUDENTS_ENDPOINT)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


def _audit_failed(route: str, profile: TutorProfileRow) -> Response:
    """The fail-closed answer: a 500 with no body, so nothing read leaves without its record."""
    log.exception("tutor_access_audit_failed", route=route, tutor_profile_id=str(profile.id))
    return Response(status_code=500)


@router.get("/students", response_model=TutorStudentPageDTO)
def list_students(
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
    repo: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> TutorStudentPageDTO | Response:
    """T19: students sharing their progress with the caller; one ``list`` audit row each."""
    after = _decode_cursor(cursor)
    try:
        page = repo.students_page(profile.id, after, limit)
    except AuditUnavailable:
        return _audit_failed("T19", profile)
    return TutorStudentPageDTO(
        items=[
            TutorStudentItemDTO(
                studentId=str(item.student_id),
                displayName=item.display_name,
                grantId=str(item.grant_id),
                grantedAt=tutor_zone_day(item.granted_at, profile.zone),
                upcomingSessions=item.upcoming_sessions,
            )
            for item in page.items
        ],
        nextCursor=(
            tutor_students_cursor(STUDENTS_ENDPOINT, page.next_key)
            if page.next_key is not None
            else None
        ),
    )


@router.get("/students/{student_id}", response_model=TutorStudentDetailDTO)
def student_detail(
    student_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
    repo: Annotated[TutorGrantRepository, Depends(get_tutor_grant_repo)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> TutorStudentDetailDTO | Response:
    """T20: one granted student's progress, recorded in their access log before it is read."""
    try:
        access = repo.require_valid_grant(profile.id, student_id)
    except NoGrant as exc:
        raise tutoring_error(404, "not_found", "Student not found.") from exc
    except AccessEnded as exc:
        raise tutoring_error(
            403, "access_ended", "This student's progress is no longer shared with you."
        ) from exc
    except AuditUnavailable:
        return _audit_failed("T20", profile)
    # Only now, with the read recorded and committed, is any of the student's data loaded.
    history = history_store.load(str(student_id))
    targets = profile_service.target_grades_for(student_id)
    detail = build_student_detail_for_tutor(
        student_id=student_id,
        display_name=access.student_label,
        history=history,
        now=datetime.now(UTC),
        targets=targets,
        zone=profile.zone,
    )
    return TutorStudentDetailDTO(
        detail=detail,
        grantId=str(access.grant.id),
        grantedAt=tutor_zone_day(access.grant.created_at, profile.zone),
        accessRecordedAt=iso_instant(access.accessed_at),
    )


__all__ = ["STUDENTS_ENDPOINT", "router"]
