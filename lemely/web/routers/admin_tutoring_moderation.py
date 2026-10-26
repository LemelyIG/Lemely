"""A6 to A8: the review and reply moderation queue (SPEC §b.2 "Platform admin", §a.3, X-06).

``PLATFORM_ADMIN`` only. A6 lists the texts awaiting a decision, oldest submission
first (an edited review text queues again from its edit): the text, its revision
and nothing else, no reviewer and no booking (SC-12). A7 and A8 approve or reject
one text. A7 carries the revision A6 showed, and a review text edited since is
409 ``text_changed`` (RF-7); replies cannot be edited, so A8 carries none.
Repeating the decision that already holds is a 200 that sends nothing; deciding a
text that is not pending is 409 ``not_pending``. Once the decision has committed,
the author gets a fixed-copy notice (review: the student; reply: the tutor)
through ``tutoring_notify.review_notices``, keyed by the decision's stored
moderation instant; a failure to write it is logged and never fails the action
(D5.9 section 1). Built with :class:`~lemely.web.tutoring_http.TutoringRoute`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Final, Literal

from fastapi import APIRouter, Depends, Query

from lemely.core.keyset import CursorError
from lemely.db.models.enums import Role
from lemely.db.notification_repo import (
    NotificationService,  # noqa: TC001 - FastAPI resolves it at runtime
)
from lemely.db.tutor_review_repo import (
    MAX_PAGE_SIZE,
    ModerationKey,
    ReviewError,
    TutorReviewRepository,
    moderation_cursor,
    parse_moderation_cursor,
)
from lemely.web.deps import AuthContext, get_notification_service, get_push_transport, require_role
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.routers.tutoring_reviews import (
    DEFAULT_PAGE_SIZE,
    get_tutor_review_repo,
    review_http_error,
)
from lemely.web.schemas_tutoring_admin import (
    AdminReplyDTO,
    AdminReviewDTO,
    ModerationItemDTO,
    ModerationPageDTO,
    ReplyModerateDTO,
    ReviewModerateDTO,
)
from lemely.web.tutoring_http import TutoringRoute, iso_instant, tutoring_error
from lemely.web.tutoring_notify import review_notices, send_after_commit

if TYPE_CHECKING:
    from lemely.db.tutor_review_repo import ModerationOutcome

#: The A6 cursor tag (O21).
MODERATION_ENDPOINT: Final = "tutoring_moderation"

require_platform_admin: Final = require_role(Role.platform_admin)

router = APIRouter(prefix="/api/admin/tutoring", tags=["tutoring"], route_class=TutoringRoute)


def _decode_cursor(cursor: str | None) -> ModerationKey | None:
    if cursor is None:
        return None
    try:
        return parse_moderation_cursor(cursor, MODERATION_ENDPOINT)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


def _notify(
    outcome: ModerationOutcome,
    decision: Literal["approved", "rejected"],
    service: NotificationService,
    transport: NotificationTransport,
) -> None:
    """Tell the author after the decision committed; nothing for an idempotent repeat.

    The repository gives a repeat no notice revision, so it has nothing to send.
    """
    if not outcome.changed or outcome.revision is None:
        return
    send_after_commit(
        review_notices(
            kind=outcome.kind,
            target_id=outcome.item_id,
            recipient_user_id=outcome.recipient_user_id,
            outcome=decision,
            revision=outcome.revision,
        ),
        service=service,
        transport=transport,
    )


@router.get("/moderation", response_model=ModerationPageDTO)
def moderation_queue(
    _auth: Annotated[AuthContext, Depends(require_platform_admin)],
    repo: Annotated[TutorReviewRepository, Depends(get_tutor_review_repo)],
    kind: Annotated[Literal["review", "reply", "all"], Query()] = "all",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ModerationPageDTO:
    """A6: review texts and replies awaiting moderation, oldest submission first."""
    page = repo.moderation_page(kind, after=_decode_cursor(cursor), limit=limit)
    return ModerationPageDTO(
        items=[
            ModerationItemDTO(
                kind=item.kind,
                itemId=str(item.item_id),
                text=item.text,
                createdAt=iso_instant(item.created_at),
                revision=item.revision,
            )
            for item in page.items
        ],
        nextCursor=(
            moderation_cursor(MODERATION_ENDPOINT, page.next_key)
            if page.next_key is not None
            else None
        ),
    )


@router.post("/reviews/{review_id}/moderate", response_model=AdminReviewDTO)
def moderate_review(
    review_id: uuid.UUID,
    body: ReviewModerateDTO,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    repo: Annotated[TutorReviewRepository, Depends(get_tutor_review_repo)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> AdminReviewDTO:
    """A7: approve or reject a review's pending text, the version the admin was shown."""
    try:
        outcome = repo.moderate_review(
            review_id, uuid.UUID(auth.user_id), body.decision, revision=body.revision
        )
    except ReviewError as exc:
        raise review_http_error(exc) from exc
    _notify(outcome, body.decision, service, transport)
    return AdminReviewDTO.model_validate(
        {
            "reviewId": str(outcome.item_id),
            "stars": outcome.stars,
            "text": outcome.text,
            "textState": outcome.text_state,
            "createdAt": iso_instant(outcome.created_at),
        }
    )


@router.post("/replies/{reply_id}/moderate", response_model=AdminReplyDTO)
def moderate_reply(
    reply_id: uuid.UUID,
    body: ReplyModerateDTO,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    repo: Annotated[TutorReviewRepository, Depends(get_tutor_review_repo)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
) -> AdminReplyDTO:
    """A8: approve or reject a pending reply."""
    try:
        outcome = repo.moderate_reply(reply_id, uuid.UUID(auth.user_id), body.decision)
    except ReviewError as exc:
        raise review_http_error(exc) from exc
    _notify(outcome, body.decision, service, transport)
    return AdminReplyDTO.model_validate(
        {
            "replyId": str(outcome.item_id),
            "body": outcome.text,
            "textState": outcome.text_state,
            "createdAt": iso_instant(outcome.created_at),
        }
    )


__all__ = ["MODERATION_ENDPOINT", "require_platform_admin", "router"]
