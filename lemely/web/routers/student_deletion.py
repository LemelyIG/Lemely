"""Student paper deletion endpoints (design ``2026-09-22-paper-deletion-design.md``, §8).

A new router file, mirroring :mod:`lemely.web.routers.student_self_review`:
thin, its own DTOs, no growth of ``student.py``. Every rule lives in
:class:`~lemely.db.deletion_repo.PaperDeletionService`; this module only maps
its errors to status codes and its views to DTOs.

Identity is **always** ``auth.user_id``. A caller-supplied ``attempt_id`` that
does not exist, is malformed, or belongs to someone else is a 404 with the
same fixed body in every case — matching every other student route, so the
route is not an existence oracle for another student's attempts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse

from lemely.core.deletion import RETENTION_DAYS
from lemely.db.class_repo import ClassService  # noqa: TC001 - FastAPI resolves this at runtime
from lemely.db.deletion_repo import (
    DeletedPaper,
    DeletedPaperSummary,
    PaperDeletionError,
    PaperDeletionService,
    PaperNotDeletableError,
    PaperNotFoundError,
    PaperNotRestorableError,
)
from lemely.db.models.enums import NotificationType, Role
from lemely.db.notification_repo import NotificationService  # noqa: TC001 - resolved at runtime
from lemely.web.deps import (
    AuthContext,
    get_class_service,
    get_notification_service,
    get_paper_deletion_service,
    get_push_transport,
    require_role,
)
from lemely.web.notify import notify_safely
from lemely.web.push import NotificationTransport  # noqa: TC001 - resolved at runtime
from lemely.web.schemas_student_deletion import DeletedPaperDTO, DeletedPapersDTO

if TYPE_CHECKING:
    import uuid

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/student/attempts")


def _raise_for(exc: PaperDeletionError) -> NoReturn:
    """Map a deletion/restore error to its status.

    The 404 body is fixed at ``"No such paper"`` for not-yours and not-found
    alike, so the route is not an existence oracle for another student's
    attempts — the same rule the self-review routes follow.

    The D8 hold's flat 409 (:class:`PaperNotDeletableError`) is handled by the
    caller, not here: it carries ``deletableFrom`` as a sibling of ``detail``,
    which ``HTTPException(detail=dict)`` cannot produce (that nests the whole
    dict under ``"detail"``). This function never sees that case.

    :class:`PaperNotRestorableError` is a 410: the window has closed (or, for
    an attempt not deleted together with its upload, never opened one it can
    walk back through), and there is nothing left to undo.
    """
    if isinstance(exc, PaperNotFoundError):
        raise HTTPException(status_code=404, detail="No such paper") from exc
    if isinstance(exc, PaperNotRestorableError):
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


def _hold_response(exc: PaperNotDeletableError) -> JSONResponse:
    """The D8 hold's flat 409 body: the message and, when there is one, a date.

    ``deletableFrom`` is present only for an integrity hold (D8) and absent
    for a non-deletable (e.g. quiz) attempt, which can never become
    deletable. The reason itself never appears in either case: D8's hold
    exists because of an integrity finding, and QUALITY-BAR.md makes
    integrity teacher-only — "you can't delete this because it was flagged
    for plagiarism" is precisely the accusation that rule forbids. The word
    "review" is absent too — an ordinary low-confidence review does not
    block deletion, so naming review here would be both a leak and a lie.
    """
    content: dict[str, object] = {"detail": str(exc)}
    if exc.deletable_from is not None:
        content["deletableFrom"] = exc.deletable_from.isoformat()
    return JSONResponse(status_code=409, content=content)


def _deleted_dto(row: DeletedPaperSummary) -> DeletedPaperDTO:
    return DeletedPaperDTO(
        attemptId=str(row.attempt_id),
        paperLabel=row.paper_label,
        subjectCode=row.subject_code,
        deletedAt=row.deleted_at,
        restoreDeadline=row.restore_deadline,
    )


@router.get("/deleted", response_model=DeletedPapersDTO)
def list_deleted(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PaperDeletionService, Depends(get_paper_deletion_service)],
) -> DeletedPapersDTO:
    """The caller's still-restorable deletions, one row per upload (R7).

    Declared ahead of ``/{attempt_id}`` in this module (and takes no path
    parameter of its own) so the literal segment ``deleted`` can never be
    captured as an ``attempt_id`` by a route on this router.
    """
    rows = service.list_deleted(auth.user_id)
    return DeletedPapersDTO(
        papers=[_deleted_dto(row) for row in rows], retentionDays=RETENTION_DAYS
    )


def _notify_withdrawn_reviewers(
    notification_service: NotificationService,
    push_transport: NotificationTransport,
    *,
    deletion_service: PaperDeletionService,
    class_service: ClassService,
    student_id: str,
    result: DeletedPaper,
) -> None:
    """Tell each withdrawn item's teacher(s), without ever saying why (D10).

    Runs after the delete has committed, wrapped, and never raises: a
    notification failure must never turn an already-successful deletion into
    an error response (D5.9 §1) — the same rule
    :func:`~lemely.web.routers.student._alert_teachers_and_parents` follows.

    The recipient is the item's ``assigned_teacher_id`` when one is set,
    otherwise every teacher the deleting student has (review amendments
    2026-09-24, R7-R10): the deleting student is *always* the caller here, so
    :meth:`~lemely.db.class_repo.ClassService.teachers_for_student` is called
    on ``student_id``, never on a value read back off the withdrawn item.

    The dedupe key carries ``result.deleted_at``: a delete → restore →
    delete cycle is two real withdrawals and must notify twice, exactly as
    ``dedupe_key`` for ``grade_ready``/``at_risk_alert`` carries whatever
    makes one real event distinct from the next.

    The body names the paper and says a review item is gone — never why.
    QUALITY-BAR.md makes an integrity finding teacher-only in the sense of
    "never shown to the student it is about"; that is not lifted by the item
    being withdrawn, and the ordinary case (a student deleting old work with
    no integrity finding at all) has no reason to report either, so naming
    one here would as often be a lie as a leak. There is deliberately no
    deep link into the payload: the withdrawn item 403s if opened, so the
    payload carries ids for record only.
    """
    try:
        if not result.withdrawn_item_ids:
            return
        student_name = class_service.display_name_for(student_id)
        assigned = deletion_service.assigned_teachers_for(result.withdrawn_item_ids)
        default_recipients: list[uuid.UUID] | None = None
        for item_id in result.withdrawn_item_ids:
            teacher_id = assigned.get(item_id)
            if teacher_id is not None:
                recipients: list[uuid.UUID] = [teacher_id]
            else:
                if default_recipients is None:
                    default_recipients = class_service.teachers_for_student(student_id)
                recipients = default_recipients
            for recipient in recipients:
                notify_safely(
                    notification_service,
                    push_transport,
                    user_id=recipient,
                    type=NotificationType.review_withdrawn,
                    title="A review item was withdrawn",
                    body=(
                        f"{student_name} deleted {result.paper_label}, so the "
                        "question you had to review is gone."
                    ),
                    dedupe_key=f"review_withdrawn:{item_id}:{result.deleted_at.isoformat()}",
                    payload={
                        "reviewItemId": str(item_id),
                        "attemptId": str(result.attempt_id),
                        "studentId": str(student_id),
                    },
                    seam="review_withdrawn",
                )
    except Exception:
        log.exception("review_withdrawn_notify_failed", attempt_id=str(result.attempt_id))


@router.delete("/{attempt_id}", status_code=204)
def delete_attempt(
    attempt_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PaperDeletionService, Depends(get_paper_deletion_service)],
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
    push_transport: Annotated[NotificationTransport, Depends(get_push_transport)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
) -> Response:
    """Soft-delete ``attempt_id``'s upload and every attempt sharing it (R7).

    204 on success. A malformed id (including the literal ``"deleted"``, were
    it ever routed here) reaches :class:`PaperDeletionService` unvalidated and
    comes back as the same fixed 404 as any other not-found id — never a 422,
    which would otherwise distinguish "not a UUID" from "not yours" and hand
    a caller an existence oracle.

    On success, every teacher whose open review item this deletion withdrew
    is told, **after** the delete has committed (:func:`_notify_withdrawn_reviewers`)
    — a notification failure never undoes the deletion the student asked for.
    """
    try:
        result = service.delete(auth.user_id, attempt_id)
    except PaperDeletionError as exc:
        if isinstance(exc, PaperNotDeletableError):
            return _hold_response(exc)
        _raise_for(exc)
    _notify_withdrawn_reviewers(
        notification_service,
        push_transport,
        class_service=class_service,
        student_id=auth.user_id,
        result=result,
        deletion_service=service,
    )
    return Response(status_code=204)


@router.post("/{attempt_id}/restore", status_code=204)
def restore_attempt(
    attempt_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PaperDeletionService, Depends(get_paper_deletion_service)],
) -> Response:
    """Undo the deletion of ``attempt_id``'s upload within the retention window.

    204 on success. 404 if the id is not the caller's or was never deleted;
    410 once the restore window has closed.
    """
    try:
        service.restore(auth.user_id, attempt_id)
    except PaperDeletionError as exc:
        _raise_for(exc)
    return Response(status_code=204)


__all__ = ["router"]
