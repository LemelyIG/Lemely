"""T18 and T21: a tutor's reviews and their one reply (SPEC §b.2 "Tutor", O4, O27, SC-12).

Both routes resolve the caller's own profile from ``auth.user_id`` through
``deps_tutoring`` (O1) and take no tutor id. T21 lists the caller's reviews, newest
first: review text only once approved, the caller's own reply in any moderation
state. T21's cursor carries the last review's id and no instant (SC-12: paging one
review at a time must not date each review). T18 writes the one reply (it starts
``pending`` and is public once an admin approves it) and is refused with 409
``tutor_suspended`` / ``tutor_closed`` for a suspended or closed profile (CB-7);
T21 is a read and still works for them. A review of another tutor, a removed one
and an unknown one are the same 404 (O4).
Built with :class:`~lemely.web.tutoring_http.TutoringRoute`.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI reads the path parameter type at runtime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from lemely.db.tutor_profile_repo import TutorProfileError, TutorProfileRow
from lemely.db.tutor_review_repo import (
    MAX_PAGE_SIZE,
    ReviewError,
    TutorReviewRepository,
)
from lemely.web.deps_tutoring import require_tutor_profile, require_writable_tutor_profile
from lemely.web.routers.tutoring_reviews import (
    DEFAULT_PAGE_SIZE,
    decode_review_cursor,
    get_tutor_review_repo,
    next_review_cursor,
    reply_dto,
    review_fields,
    review_http_error,
)
from lemely.web.schemas_tutoring import (
    ReplyCreateDTO,
    ReplyDTO,
    TutorReviewItemDTO,
    TutorReviewsPageDTO,
)
from lemely.web.tutoring_http import TutoringRoute

#: The T21 cursor tag (O21): SP3's cursor is refused here and vice versa.
OWN_REVIEWS_ENDPOINT: Final = "tutor_own_reviews"

router = APIRouter(prefix="/api/tutor", tags=["tutoring"], route_class=TutoringRoute)


@router.get("/reviews", response_model=TutorReviewsPageDTO)
def list_own_reviews(
    profile: Annotated[TutorProfileRow, Depends(require_tutor_profile)],
    repo: Annotated[TutorReviewRepository, Depends(get_tutor_review_repo)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> TutorReviewsPageDTO:
    """T21: the caller's reviews, newest first; the cursor names a review, never its instant."""
    after = decode_review_cursor(cursor, OWN_REVIEWS_ENDPOINT)
    try:
        page = repo.own_reviews(profile.id, after=after, limit=limit)
    except ReviewError as exc:
        raise review_http_error(exc) from exc
    return TutorReviewsPageDTO(
        items=[
            TutorReviewItemDTO.model_validate(
                {**review_fields(item, page.zone), "textState": item.text_state}
            )
            for item in page.items
        ],
        nextCursor=next_review_cursor(page, OWN_REVIEWS_ENDPOINT),
    )


@router.post("/reviews/{review_id}/reply", status_code=201, response_model=ReplyDTO)
def create_reply(
    review_id: uuid.UUID,
    body: ReplyCreateDTO,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    repo: Annotated[TutorReviewRepository, Depends(get_tutor_review_repo)],
) -> ReplyDTO:
    """T18: reply once to a review of the caller's; the reply is checked before it is public."""
    try:
        reply = repo.create_reply(profile.id, review_id, body.body)
    except (ReviewError, TutorProfileError) as exc:
        raise review_http_error(exc) from exc
    return reply_dto(reply)


__all__ = ["OWN_REVIEWS_ENDPOINT", "router"]
