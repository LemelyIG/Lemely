"""S6 and S7: a student's review of a completed session and its edits (SPEC §b.2, §a.2, O10).

Both routes are ``STUDENT`` + verified email (SC-15), so a parent is refused by the
guard. The repository checks, inside the write transaction, that the booking is the
caller's own and ``completed``, that its notes window has closed (7 days after the
session), that the account is at least 14 days old, and that no review exists; a
block does not remove the right to review. An edit works for 14 days and sends new
text back to moderation. Every free-text field passes ``core.contact_patterns``
(SC-7). Built with :class:`~lemely.web.tutoring_http.TutoringRoute`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends

from lemely.core.tutor_ratings import review_edit_deadline
from lemely.db.models.enums import Role
from lemely.db.tutor_review_repo import (
    ReviewError,
    TutorReviewRepository,
)
from lemely.web.deps import AuthContext, require_role, require_verified_email
from lemely.web.routers.tutoring_reviews import get_tutor_review_repo, review_http_error
from lemely.web.schemas_tutoring import MyReviewDTO, ReviewCreateDTO, ReviewUpdateDTO
from lemely.web.tutoring_http import TutoringRoute, iso_instant

if TYPE_CHECKING:
    from lemely.db.tutor_review_repo import MyReview

require_student: Final = require_role(Role.student)

router = APIRouter(prefix="/api/student", tags=["tutoring"], route_class=TutoringRoute)


def my_review_dto(review: MyReview) -> MyReviewDTO:
    """The student's own review, with the instant its edit window closes."""
    return MyReviewDTO.model_validate(
        {
            "reviewId": str(review.review_id),
            "bookingId": str(review.booking_id),
            "stars": review.stars,
            "text": review.text,
            "textState": review.text_state,
            "editableUntil": iso_instant(review_edit_deadline(review.created_at)),
        }
    )


@router.post("/bookings/{booking_id}/review", status_code=201, response_model=MyReviewDTO)
def create_review(
    booking_id: uuid.UUID,
    body: ReviewCreateDTO,
    auth: Annotated[AuthContext, Depends(require_student)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    repo: Annotated[TutorReviewRepository, Depends(get_tutor_review_repo)],
) -> MyReviewDTO:
    """S6: review a completed session."""
    try:
        review = repo.create_review(
            uuid.UUID(auth.user_id), booking_id, stars=body.stars, text=body.text
        )
    except ReviewError as exc:
        raise review_http_error(exc) from exc
    return my_review_dto(review)


@router.patch("/reviews/{review_id}", response_model=MyReviewDTO)
def update_review(
    review_id: uuid.UUID,
    body: ReviewUpdateDTO,
    auth: Annotated[AuthContext, Depends(require_student)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    repo: Annotated[TutorReviewRepository, Depends(get_tutor_review_repo)],
) -> MyReviewDTO:
    """S7: change the stars or text of the caller's review inside its 14-day window."""
    try:
        review = repo.update_review(
            uuid.UUID(auth.user_id),
            review_id,
            stars=body.stars,
            text=body.text,
            clear_text=body.clearText,
        )
    except ReviewError as exc:
        raise review_http_error(exc) from exc
    return my_review_dto(review)


__all__ = ["my_review_dto", "require_student", "router"]
