"""R1 ``POST /api/tutoring/reports``: a student, parent or tutor reports something (SPEC §b.2).

``TUTORING_PARTY`` (student, parent, teacher; SPEC §c.1): ``school_admin`` and
``platform_admin`` are refused by the guard. **No verified-email gate**: a report is a safety
path (SPEC §b.2 R1, the SC-15 exception). Built with ``TutoringRoute``, so every response is
``private, no-store`` whatever its status.

* 201 with a :class:`~lemely.web.schemas_tutoring.ReportReceiptDTO` (the report's id and when
  it was filed) and nothing else: the answer never says whether a block exists or what the
  report changed (SC-11).
* 404 ``not_found``, one body for an unknown target and for one the caller may not see
  (O12, O19; the rule is in ``lemely.db.tutoring_reports_repo``).
* 409 ``report_exists``: the caller already has an open report on that target.
* 422: a ``targetId`` that is not a UUID (``invalid_target``), ``details`` longer than 1000
  characters (``text_too_long``), or FastAPI's own for an unknown ``targetType`` or ``reason``.
* 429 ``too_many_requests``: more than 20 reports in 24 hours (SC-15).

A ``safety_concern`` on a booking or a note freezes that booking's notes in the filing
transaction (SC-10). After the commit, every platform admin gets the fixed-copy
``tutoring_report`` notice for a ``safety_concern`` (SPEC §b.4); a failed notice is logged and
never fails the report (D5.9 §1).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Annotated, Final

from fastapi import APIRouter, Depends

from lemely.db.models.enums import ReportReason, ReportTargetType, Role
from lemely.db.notification_repo import NotificationService  # noqa: TC001 - FastAPI resolves it
from lemely.db.session import get_sessionmaker
from lemely.db.tutoring_reports_repo import (
    Reporter,
    ReporterParty,
    ReportRefused,
    TutoringReportsRepository,
)
from lemely.web.deps import (
    AuthContext,
    get_notification_service,
    get_push_transport,
    get_settings,
    require_role,
)
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.schemas_tutoring import ReportCreateDTO, ReportReceiptDTO
from lemely.web.tutoring_http import TutoringRoute, iso_instant, tutoring_error
from lemely.web.tutoring_notify import report_notices, send_after_commit

router = APIRouter(prefix="/api/tutoring/reports", tags=["tutoring"], route_class=TutoringRoute)

#: SPEC §c.1 ``TUTORING_PARTY``: everyone a tutoring session involves.
require_tutoring_party: Final = require_role(Role.student, Role.parent, Role.teacher)

#: A teacher reports as the tutor (``tutoring_reports.reporter_party``).
_PARTY: Final[dict[Role, ReporterParty]] = {
    Role.student: "student",
    Role.parent: "parent",
    Role.teacher: "tutor",
}


@lru_cache(maxsize=1)
def get_tutoring_reports_repo() -> TutoringReportsRepository:
    """The process-wide :class:`TutoringReportsRepository` (shared with the A9-A11 router)."""
    return TutoringReportsRepository(get_sessionmaker(get_settings()))


def _target_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise tutoring_error(
            422, "invalid_target", "Choose what to report from the page you were on."
        ) from exc


@router.post("", response_model=ReportReceiptDTO, status_code=201)
def file_report(
    body: ReportCreateDTO,
    auth: Annotated[AuthContext, Depends(require_tutoring_party)],
    repo: Annotated[TutoringReportsRepository, Depends(get_tutoring_reports_repo)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> ReportReceiptDTO:
    """R1: file a report on a target the caller can see; a receipt, then the admins' notice."""
    reporter = Reporter(user_id=uuid.UUID(auth.user_id), party=_PARTY[Role(auth.role)])
    target_id = _target_id(body.targetId)
    try:
        filed = repo.file(
            reporter,
            target_type=ReportTargetType(body.targetType),
            target_id=target_id,
            reason=ReportReason(body.reason),
            details=body.details,
        )
    except ReportRefused as exc:
        raise tutoring_error(exc.status, exc.code, exc.message) from exc
    send_after_commit(
        report_notices(
            report_id=filed.report_id, reason=filed.reason, admin_user_ids=filed.admin_user_ids
        ),
        service=service,
        transport=transport,
    )
    return ReportReceiptDTO(reportId=str(filed.report_id), createdAt=iso_instant(filed.created_at))


__all__ = ["get_tutoring_reports_repo", "require_tutoring_party", "router"]
