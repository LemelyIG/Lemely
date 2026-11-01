"""B1-B3: a student's and a tutor's blocks (SPEC §b.2 "Safety", §a.2, §a.4b; O13, O28, SC-11).

``STUDENT_OR_TEACHER`` on all three (parents hold no blocks, O-18). Built with
``TutoringRoute``, so every response is ``private, no-store`` whatever its status.

* **B1** ``GET /api/tutoring/blocks``: the caller's active blocks (``BlocksDTO``).
* **B2** ``POST /api/tutoring/blocks``: a student sends ``tutorId`` (a profile id, never a
  ``users.id``, SC-19), a tutor ``studentId``; the other field, both, neither or a malformed id
  is 422 ``invalid_counterpart``. 201 with the new block; 200, untouched, when it is already
  active; 404 for anything the caller may not block (O13; for a student, SP2's own body); 409
  ``tutor_suspended`` / ``tutor_closed`` for an inactive tutor (CB-7).
* **B3** ``DELETE /api/tutoring/blocks/{counterpart_id}``: 204, also when already lifted; 404
  unless the caller holds a block row for that counterpart (O28). Restores nothing.

A teacher without a tutor profile holds no blocks: 404 ``no_tutor_profile`` on all three
(ADR-T01 action 3). Every answer is the same whether or not the other side blocked the caller
(SC-11): nothing here reads the other side's row.

**Notices (SPEC §b.4, §i.8 (c); D5.9 §1).** After the commit, :func:`sweep_notices` turns the
sweep into inbox rows: each cancelled session to every party and linked parent except the
blocker; each ended grant to the tutor in generic words ("access ended", SC-11), and, when the
tutor blocked, to the student as the same "can no longer see your progress" a suspension or a
close sends, so a student cannot tell a tutor's block from either. :func:`sweep_notices` serves
the sanction routes too (``admin_tutor_sanctions``).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Response

from lemely.db.models.enums import NotificationType, Role
from lemely.db.notification_repo import NotificationService  # noqa: TC001 - FastAPI resolves it
from lemely.db.session import get_sessionmaker
from lemely.db.tutor_profile_repo import TutorProfileRepository  # noqa: TC001 - FastAPI resolves it
from lemely.db.tutoring_blocks_repo import (
    BlockCaller,
    BlockError,
    BlockView,
    TutoringBlocksRepository,
)
from lemely.web.deps import (
    AuthContext,
    get_notification_service,
    get_push_transport,
    get_settings,
    require_role,
)
from lemely.web.deps_tutoring import get_tutor_profile_repo
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.schemas_tutoring import BlockCreateDTO, BlockDTO, BlocksDTO
from lemely.web.tutoring_http import TutoringRoute, iso_instant, tutor_not_found, tutoring_error
from lemely.web.tutoring_notify import (
    InboxNotice,
    booking_notices,
    grant_notices,
    send_after_commit,
)

if TYPE_CHECKING:
    from lemely.db.tutoring_sweeps import SweepResult

router = APIRouter(prefix="/api/tutoring/blocks", tags=["tutoring"], route_class=TutoringRoute)

require_student_or_teacher: Final = require_role(Role.student, Role.teacher)

_FIELD_MESSAGE: Final = {
    "student": "Send the tutor's id as tutorId, and nothing else.",
    "tutor": "Send the student's id as studentId, and nothing else.",
}


@lru_cache(maxsize=1)
def get_block_repo() -> TutoringBlocksRepository:
    """The process-wide :class:`TutoringBlocksRepository`."""
    return TutoringBlocksRepository(get_sessionmaker(get_settings()))


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------


def _student_access_ended(
    *, grant_id: uuid.UUID, student_user_id: uuid.UUID, tutor_name: str
) -> InboxNotice:
    """The student's "can no longer see your progress" notice for a grant the tutor's block ended.

    Word for word what ``grant_notices`` sends for a suspension or a close (SPEC §b.4, §i.8
    (c)). ``tests/test_web_tutoring_blocks.py`` pins it, through the routes, to the notice a real
    suspension sends.
    """
    return InboxNotice(
        user_id=student_user_id,
        type=NotificationType.tutor_access,
        title="Progress sharing ended",
        body=f"{tutor_name} can no longer see your progress.",
        payload={"grantId": str(grant_id)},
        dedupe_key=f"grant:{grant_id}:ended",
        seam="tutoring_grant",
    )


def sweep_notices(
    result: SweepResult,
    *,
    actor_user_id: uuid.UUID | None,
    tell_tutor_of_cancellations: bool,
    tell_student_of_grant_end: bool,
) -> list[InboxNotice]:
    """The after-commit notices of a sweep (SPEC §b.4); fixed copy, names only.

    ``actor_user_id`` (the blocker; ``None`` for a sanction) is told nothing.
    ``tell_tutor_of_cancellations`` is false for a sanction: the tutor is told the listing
    decision instead, as the cancellation emails are not sent to them either.
    ``tell_student_of_grant_end`` adds the student's "can no longer see your progress" where
    ``grant_notices`` has none (a tutor's block); a suspension and a close already carry it.
    """
    notices: list[InboxNotice] = []
    for booking in result.cancelled:
        notices.extend(
            notice
            for notice in booking_notices(
                event="cancelled",
                booking_id=booking.booking_id,
                tutor_user_id=result.tutor_user_id,
                tutor_name=result.tutor_name,
                student_user_id=booking.student_id,
                student_label=booking.student_label,
                linked_parent_ids=booking.linked_parent_ids,
                actor_user_id=actor_user_id,
            )
            if tell_tutor_of_cancellations or notice.user_id != result.tutor_user_id
        )
    for grant in result.revoked:
        ended = grant_notices(
            event="ended",
            grant_id=grant.grant_id,
            tutor_user_id=result.tutor_user_id,
            tutor_name=result.tutor_name,
            student_user_id=grant.student_id,
            student_label=grant.student_label,
            linked_parent_ids=(),
            ended_reason=result.revoke_reason,
        )
        if tell_student_of_grant_end and all(n.user_id != grant.student_id for n in ended):
            ended.append(
                _student_access_ended(
                    grant_id=grant.grant_id,
                    student_user_id=grant.student_id,
                    tutor_name=result.tutor_name,
                )
            )
        notices.extend(notice for notice in ended if notice.user_id != actor_user_id)
    return notices


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _caller(auth: AuthContext, profiles: TutorProfileRepository) -> BlockCaller:
    """The caller as B1-B3 see them; a teacher without a tutor profile is 404 (ADR-T01)."""
    user_id = uuid.UUID(auth.user_id)
    if Role(auth.role) is Role.student:
        return BlockCaller(user_id=user_id, party="student")
    profile = profiles.for_user(user_id)
    if profile is None:
        raise tutoring_error(
            404, "no_tutor_profile", "You do not have a tutor profile yet. Create one first."
        )
    return BlockCaller(user_id=user_id, party="tutor", tutor_profile_id=profile.id)


def _counterpart(caller: BlockCaller, body: BlockCreateDTO) -> uuid.UUID:
    """The one id B2 takes from this caller's role (SC-19); anything else is 422."""
    wanted, other = (
        (body.tutorId, body.studentId)
        if caller.party == "student"
        else (body.studentId, body.tutorId)
    )
    if wanted is None or other is not None:
        raise tutoring_error(422, "invalid_counterpart", _FIELD_MESSAGE[caller.party])
    try:
        return uuid.UUID(wanted)
    except ValueError as exc:
        raise tutoring_error(422, "invalid_counterpart", _FIELD_MESSAGE[caller.party]) from exc


def _not_blockable(caller: BlockCaller) -> HTTPException:
    """One 404 per role, whatever the reason (PP-6, SC-11): SP2's body for a student."""
    if caller.party == "student":
        return tutor_not_found()
    return tutoring_error(404, "not_found", "Student not found.")


def _block_dto(view: BlockView) -> BlockDTO:
    return BlockDTO(
        counterpartId=str(view.counterpart_id),
        displayName=view.display_name,
        createdAt=iso_instant(view.active_since),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=BlocksDTO)
def list_blocks(
    auth: Annotated[AuthContext, Depends(require_student_or_teacher)],
    profiles: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    repo: Annotated[TutoringBlocksRepository, Depends(get_block_repo)],
) -> BlocksDTO:
    """B1: the caller's active blocks, the most recent first."""
    caller = _caller(auth, profiles)
    return BlocksDTO(items=[_block_dto(view) for view in repo.active_blocks(caller)])


@router.post("", response_model=BlockDTO, status_code=201)
def create_block(
    body: BlockCreateDTO,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_student_or_teacher)],
    profiles: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    repo: Annotated[TutoringBlocksRepository, Depends(get_block_repo)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> BlockDTO:
    """B2: block the counterpart; the sweep runs in the same transaction, notices after it."""
    caller = _caller(auth, profiles)
    counterpart = _counterpart(caller, body)
    try:
        outcome = repo.block(caller, counterpart)
    except BlockError as exc:
        if exc.status == 404:
            raise _not_blockable(caller) from exc
        raise tutoring_error(exc.status, exc.code, exc.message) from exc
    if outcome.sweep is not None:
        send_after_commit(
            sweep_notices(
                outcome.sweep,
                actor_user_id=caller.user_id,
                tell_tutor_of_cancellations=True,
                tell_student_of_grant_end=caller.party == "tutor",
            ),
            service=service,
            transport=transport,
        )
    if not outcome.created:
        response.status_code = 200
    return _block_dto(outcome.block)


@router.delete("/{counterpart_id}", status_code=204)
def delete_block(
    counterpart_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student_or_teacher)],
    profiles: Annotated[TutorProfileRepository, Depends(get_tutor_profile_repo)],
    repo: Annotated[TutoringBlocksRepository, Depends(get_block_repo)],
) -> Response:
    """B3: lift the caller's block; a tutor profile id from a student, a student id from a tutor."""
    caller = _caller(auth, profiles)
    try:
        repo.unblock(caller, counterpart_id)
    except BlockError as exc:
        raise tutoring_error(exc.status, exc.code, "Block not found.") from exc
    return Response(status_code=204)


__all__ = ["get_block_repo", "require_student_or_teacher", "router", "sweep_notices"]
