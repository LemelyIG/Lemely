"""SP3: a tutor's public reviews, for students and parents (SPEC §b.2, §a.3, SC-12, O11).

``GET /api/tutors/{tutor_id}/reviews`` is behind a verified email (SC-15) and
answers one identical 404 when the tutor is unlisted, paused or blocked from the
caller (O11). A review shows its stars from the moment it is written, its text
only once approved, and the tutor's reply only once approved. The period is the
quarter in the tutor's zone (such as "Jul-Sep 2026", printed with an en dash): no
name, no date, no booking (SC-12). For the same reason the page cursor names the
last review served and nothing else; a cursor whose review is not one of this
tutor's is 422 ``invalid_cursor``.

This module also holds what the other review routers share, so the error shape and
the DTO builders are written once: the repository provider
(:func:`get_tutor_review_repo`), :func:`review_http_error`, :func:`review_dto` and
:func:`decode_review_cursor`. Built with
:class:`~lemely.web.tutoring_http.TutoringRoute` (``private, no-store``).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.core.keyset import CursorError
from lemely.core.tutor_ratings import quarter_label
from lemely.db.session import get_sessionmaker
from lemely.db.tutor_review_repo import (
    MAX_PAGE_SIZE,
    ReviewError,
    ReviewKey,
    ReviewNotFoundError,
    ReviewValidationError,
    TutorReviewRepository,
    parse_review_cursor,
    review_cursor,
)
from lemely.web.deps import AuthContext, get_settings, require_verified_email
from lemely.web.deps_tutoring import require_student_or_parent
from lemely.web.schemas_tutoring import ReplyDTO, ReviewDTO, ReviewsPageDTO
from lemely.web.tutoring_http import TutoringRoute, iso_instant, tutor_not_found, tutoring_error

if TYPE_CHECKING:
    from lemely.db.tutor_profile_repo import TutorProfileError
    from lemely.db.tutor_review_repo import ReplyView, ReviewsPage, ReviewView

#: The SP3 cursor tag; T21 has its own, so neither list accepts the other's cursor (O21).
REVIEWS_ENDPOINT: Final = "tutor_reviews"
DEFAULT_PAGE_SIZE: Final = 20

router = APIRouter(prefix="/api", tags=["tutoring"], route_class=TutoringRoute)


@lru_cache(maxsize=1)
def get_tutor_review_repo() -> TutorReviewRepository:
    """The process-wide :class:`TutorReviewRepository`."""
    return TutorReviewRepository(get_sessionmaker(get_settings()))


# ---------------------------------------------------------------------------
# Shared by the four review routers
# ---------------------------------------------------------------------------


def review_http_error(exc: ReviewError | TutorProfileError) -> HTTPException:
    """Map a repository refusal to its SPEC §b.2 status and ``{"code", "message"}`` body."""
    if isinstance(exc, ReviewNotFoundError):
        status = 404
    elif isinstance(exc, ReviewValidationError):
        status = 422  # including invalid_cursor for a review-list anchor that is not the tutor's
    else:
        # Not found aside, every other refusal is a state or policy conflict (SPEC §0 "Errors"):
        # not_completed, review_not_open_yet, account_too_new, review_exists,
        # edit_window_closed, reply_exists, not_pending, text_changed, tutor_suspended,
        # tutor_closed.
        status = 409
    return tutoring_error(status, exc.code, exc.message)


def decode_review_cursor(cursor: str | None, endpoint: str) -> ReviewKey | None:
    """The page start from a client cursor; 422 ``invalid_cursor`` for anything not minted here."""
    if cursor is None:
        return None
    try:
        return parse_review_cursor(cursor, endpoint)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


def reply_dto(reply: ReplyView) -> ReplyDTO:
    """A reply as the tutor or (when approved) the public sees it."""
    return ReplyDTO.model_validate(
        {
            "replyId": str(reply.reply_id),
            "body": reply.body,
            "textState": reply.text_state,
            "createdAt": iso_instant(reply.created_at),
        }
    )


def review_fields(view: ReviewView, zone: str) -> dict[str, object]:
    """The :class:`ReviewDTO` fields of ``view``: stars, filtered text, quarter, reply (SC-12)."""
    return {
        "reviewId": str(view.review_id),
        "stars": view.stars,
        "text": view.text,
        "period": quarter_label(view.created_at, zone),
        "reply": reply_dto(view.reply) if view.reply is not None else None,
    }


def review_dto(view: ReviewView, zone: str) -> ReviewDTO:
    """SP3's review."""
    return ReviewDTO.model_validate(review_fields(view, zone))


def next_review_cursor(page: ReviewsPage, endpoint: str) -> str | None:
    """The cursor for the page after ``page``, or ``None`` on the last page."""
    return review_cursor(endpoint, page.next_key) if page.next_key is not None else None


# ---------------------------------------------------------------------------
# SP3
# ---------------------------------------------------------------------------


@router.get("/tutors/{tutor_id}/reviews", response_model=ReviewsPageDTO)
def list_tutor_reviews(
    tutor_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student_or_parent)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    repo: Annotated[TutorReviewRepository, Depends(get_tutor_review_repo)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ReviewsPageDTO:
    """SP3: reviews of a listed, unpaused, unblocked tutor, newest first."""
    after = decode_review_cursor(cursor, REVIEWS_ENDPOINT)
    try:
        page = repo.reviews_for_viewer(
            tutor_id, uuid.UUID(auth.user_id), auth.role, after=after, limit=limit
        )
    except ReviewError as exc:
        raise review_http_error(exc) from exc
    if page is None:
        raise tutor_not_found()
    return ReviewsPageDTO(
        items=[review_dto(item, page.zone) for item in page.items],
        nextCursor=next_review_cursor(page, REVIEWS_ENDPOINT),
    )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "REVIEWS_ENDPOINT",
    "decode_review_cursor",
    "get_tutor_review_repo",
    "next_review_cursor",
    "reply_dto",
    "review_dto",
    "review_fields",
    "review_http_error",
    "router",
]
