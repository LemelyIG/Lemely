"""Tutor reviews, replies, moderation and the rating aggregate (SPEC §a.2, §a.3, §b.2).

This module is the single writer of ``tutor_reviews`` and ``tutor_review_replies``
and of the three aggregate columns of ``tutor_profiles`` (``rating_sum``,
``rating_count``, ``rank_score``).

**The aggregate (SC-16).** Every change that can move it (a review created, its
stars edited, a review removed) runs :func:`_recompute` in the same transaction,
after taking ``SELECT ... FOR UPDATE`` on the tutor row (SPEC §a.4b, step 1).
The lock serialises every writer of one tutor's aggregate, so two reviews that
commit together cannot overwrite each other's total; the recompute reads the
review rows again instead of adding a delta, so a stored value that ever went
wrong is repaired by the next change or by ``lemely tutoring recompute-ratings``.
Each student counts once, by their latest non-removed review: the SQL is
``DISTINCT ON (student_id) ... ORDER BY created_at DESC, id DESC``, the same rule
as ``core.tutor_ratings.aggregate_latest_per_student`` (SPEC §i.4: a ``created_at``
tie goes to the greater ``id``). ``rank_score`` is ``core.tutor_ratings.bayesian_score``
of the two totals.

**Windows (O10, SPEC §a.2).** A review opens at ``core.booking.review_open_at``
(``ends_at`` + 7 days, when the booking's notes close), needs a ``completed``
booking of the caller's own, an account at least ``REVIEW_MIN_ACCOUNT_AGE`` old,
and can be edited until ``core.tutor_ratings.review_edit_deadline``. A block does
not remove the right to review. Instants are compared as UTC instants against
the database ``now()`` (SPEC §0 "Clock"), never as wall-clock arithmetic in the
session zone, so a clock change inside a window cannot shorten or lengthen it
(SPEC §i.4).

**Visibility (SC-12).** A review's stars are public from the moment it is written;
its text only once an admin approved it, and an edit sends the text back to
``pending``. A reply is public only when approved. A tutor sees their own reply in
any state. Nothing here returns the reviewer's id or the booking id.

**Moderation revisions.** Notices about a moderated text are deduplicated on a
revision number (``tutoring_notify.review_notices``). No column stores a text
version, so the revision is the number of moderation notices already written to
that recipient for that review or reply: 0 for the first, 1 once an edit has been
moderated again, and so on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal

import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError

from lemely.core.booking import review_open_at
from lemely.core.contact_patterns import find_contact_details
from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.core.tutor_ratings import REVIEW_MIN_ACCOUNT_AGE, bayesian_score, review_edit_deadline
from lemely.db.models.enums import ModerationState, Role, TutorListingState
from lemely.db.models.tutoring import TutorProfile, TutorReview, TutorReviewReply
from lemely.db.models.users import User
from lemely.db.tutor_profile_repo import TutorClosedError, TutorSuspendedError
from lemely.db.tutoring_predicates import active_block_between_sql, listed_and_not_paused_sql

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)

MAX_PAGE_SIZE: Final = 50
MAX_REVIEW_TEXT: Final = 1000  # ck_tutor_reviews_body_len
MAX_REPLY_TEXT: Final = 1000  # ck_tutor_review_replies_body_len
_MIN_STARS: Final = 1
_MAX_STARS: Final = 5

Decision = Literal["approved", "rejected"]
ModerationKind = Literal["review", "reply"]


# ---------------------------------------------------------------------------
# Errors (each carries the API code the router sends)
# ---------------------------------------------------------------------------


class ReviewError(Exception):
    """Base class: ``code`` is the stable API code, ``message`` plain English."""

    code: str = "review_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ReviewNotFoundError(ReviewError):
    """Nothing the caller may see: unknown, someone else's, or removed."""

    code = "not_found"


class NotCompletedError(ReviewError):
    """The booking is not ``completed``."""

    code = "not_completed"


class ReviewNotOpenYetError(ReviewError):
    """Reviews open when the booking's notes window closes (``ends_at`` + 7 days)."""

    code = "review_not_open_yet"


class AccountTooNewError(ReviewError):
    """The reviewer's account is younger than ``REVIEW_MIN_ACCOUNT_AGE`` (F7)."""

    code = "account_too_new"


class ReviewExistsError(ReviewError):
    """One review per booking."""

    code = "review_exists"


class EditWindowClosedError(ReviewError):
    """More than 14 days since the review was written."""

    code = "edit_window_closed"


class ReplyExistsError(ReviewError):
    """One reply per review."""

    code = "reply_exists"


class NotPendingError(ReviewError):
    """The text is not awaiting moderation."""

    code = "not_pending"


class ReviewValidationError(ReviewError):
    """A 422: ``code`` names the rule, ``field`` the input."""

    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplyView:
    """A tutor's reply as a viewer may see it."""

    reply_id: uuid.UUID
    body: str
    text_state: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewView:
    """A review as a viewer may see it: ``text`` is already filtered to approved."""

    review_id: uuid.UUID
    stars: int
    text: str | None
    text_state: str
    created_at: datetime
    reply: ReplyView | None


@dataclass(frozen=True, slots=True)
class ReviewKey:
    """Keyset position in a review list: newest first."""

    created_at: datetime
    review_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ReviewsPage:
    """One page of reviews and the tutor's zone (for the quarter label)."""

    items: tuple[ReviewView, ...]
    next_key: ReviewKey | None
    zone: str


@dataclass(frozen=True, slots=True)
class MyReview:
    """The student's own review."""

    review_id: uuid.UUID
    booking_id: uuid.UUID
    stars: int
    text: str | None
    text_state: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ModerationItem:
    """One text awaiting moderation. No reviewer, no booking (SC-12)."""

    kind: ModerationKind
    item_id: uuid.UUID
    text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ModerationKey:
    """Keyset position in the moderation queue: oldest first."""

    created_at: datetime
    kind: str
    item_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ModerationPage:
    """One page of the moderation queue."""

    items: tuple[ModerationItem, ...]
    next_key: ModerationKey | None


@dataclass(frozen=True, slots=True)
class ModerationOutcome:
    """The result of moderating one review text or reply.

    ``recipient_user_id`` is the author to notify (the student for a review, the
    tutor's user for a reply). ``changed`` is false for an idempotent repeat, which
    must not send a second notice. ``revision`` is the notice's dedupe revision.
    """

    kind: ModerationKind
    item_id: uuid.UUID
    stars: int | None
    text: str
    text_state: str
    created_at: datetime
    recipient_user_id: uuid.UUID
    changed: bool
    revision: int


@dataclass(frozen=True, slots=True)
class RatingRecompute:
    """Stored versus recomputed aggregate of one tutor."""

    tutor_profile_id: uuid.UUID
    before_sum: int
    before_count: int
    before_rank: Decimal
    after_sum: int
    after_count: int
    after_rank: Decimal

    @property
    def changed(self) -> bool:
        """True when the stored aggregate was wrong."""
        return (self.before_sum, self.before_count, self.before_rank) != (
            self.after_sum,
            self.after_count,
            self.after_rank,
        )


# ---------------------------------------------------------------------------
# Cursors (SPEC §0 "Paging", O21): the endpoint tag is the router's
# ---------------------------------------------------------------------------


def review_cursor(endpoint: str, key: ReviewKey) -> str:
    """The opaque cursor for the page that follows ``key`` in list ``endpoint``."""
    return encode_cursor(endpoint, [key.created_at, key.review_id])


def parse_review_cursor(token: str, endpoint: str) -> ReviewKey:
    """Decode a review-list cursor; :class:`CursorError` unless minted for ``endpoint``."""
    created_at, review_id = decode_cursor(token, endpoint=endpoint, types=(datetime, uuid.UUID))
    if not isinstance(created_at, datetime) or not isinstance(review_id, uuid.UUID):
        raise CursorError("cursor has the wrong value types")  # pragma: no cover - decoder-typed
    return ReviewKey(created_at=created_at, review_id=review_id)


def moderation_cursor(endpoint: str, key: ModerationKey) -> str:
    """The opaque cursor for the page that follows ``key`` in the moderation queue."""
    return encode_cursor(endpoint, [key.created_at, key.kind, key.item_id])


def parse_moderation_cursor(token: str, endpoint: str) -> ModerationKey:
    """Decode a moderation-queue cursor; :class:`CursorError` for anything not minted for it."""
    created_at, kind, item_id = decode_cursor(
        token, endpoint=endpoint, types=(datetime, str, uuid.UUID)
    )
    if (
        not isinstance(created_at, datetime)
        or not isinstance(kind, str)
        or not isinstance(item_id, uuid.UUID)
    ):
        raise CursorError("cursor has the wrong value types")  # pragma: no cover - decoder-typed
    if kind not in ("review", "reply"):
        raise CursorError("cursor names an unknown kind")
    return ModerationKey(created_at=created_at, kind=kind, item_id=item_id)


# ---------------------------------------------------------------------------
# Validation (SC-7)
# ---------------------------------------------------------------------------


def _stars(value: int) -> int:
    if not _MIN_STARS <= value <= _MAX_STARS:
        raise ReviewValidationError(
            "invalid_stars", "stars", f"Choose {_MIN_STARS} to {_MAX_STARS} stars."
        )
    return value


def _text(value: str, *, limit: int, field: str, what: str) -> str:
    """A non-empty, trimmed, contact-free free-text value."""
    if len(value) > limit:
        raise ReviewValidationError(
            "text_too_long", field, f"{what} can be at most {limit} characters."
        )
    if find_contact_details(value):
        raise ReviewValidationError(
            "contact_details_not_allowed",
            field,
            "Keep phone numbers, emails and links out. Lemely connects students and tutors.",
        )
    return value


def _review_text(value: str | None) -> str | None:
    """Review text: ``None`` for absent or blank, else trimmed and checked."""
    if value is None or not value.strip():
        return None
    return _text(value.strip(), limit=MAX_REVIEW_TEXT, field="text", what="A review")


def _reply_text(value: str) -> str:
    body = value.strip()
    if not body:
        raise ReviewValidationError("reply_empty", "body", "Write a reply first.")
    return _text(body, limit=MAX_REPLY_TEXT, field="body", what="A reply")


def _utc(value: datetime) -> datetime:
    """``value`` as a UTC instant, so datetime arithmetic is elapsed time (SPEC §i.4)."""
    return value.astimezone(UTC)


def _constraint(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return name if isinstance(name, str) else None


# ---------------------------------------------------------------------------
# Session-level steps (the caller owns the transaction)
# ---------------------------------------------------------------------------


def _lock_profile(
    session: Session, tutor_profile_id: uuid.UUID, *, shared: bool = False
) -> TutorListingState:
    """Lock the tutor row first, as SPEC §a.4b orders (``FOR SHARE`` for a tutor's own action)."""
    state = session.execute(
        sa.select(TutorProfile.listing_state)
        .where(TutorProfile.id == tutor_profile_id)
        .with_for_update(read=shared)
    ).scalar_one_or_none()
    if state is None:
        raise ReviewNotFoundError("No such tutor profile.")
    return state


def _recompute(session: Session, tutor_profile_id: uuid.UUID) -> RatingRecompute:
    """Rewrite the tutor aggregate from their review rows, under ``FOR UPDATE`` on the tutor row."""
    stored = session.execute(
        sa.select(TutorProfile.rating_sum, TutorProfile.rating_count, TutorProfile.rank_score)
        .where(TutorProfile.id == tutor_profile_id)
        .with_for_update()
    ).one_or_none()
    if stored is None:
        raise ReviewNotFoundError("No such tutor profile.")
    # Each student's latest non-removed review, once (SC-16). The ORDER BY is the tie-break
    # of SPEC §i.4: equal created_at goes to the greater id.
    counted = session.execute(
        sa.text(
            "SELECT coalesce(sum(latest.stars), 0) AS rating_sum, count(*) AS rating_count "
            "FROM (SELECT DISTINCT ON (r.student_id) r.student_id, r.stars "
            "FROM tutor_reviews r "
            "WHERE r.tutor_profile_id = :tutor_id AND r.removed_at IS NULL "
            "ORDER BY r.student_id, r.created_at DESC, r.id DESC) latest"
        ),
        {"tutor_id": tutor_profile_id},
    ).one()
    total, count = int(counted.rating_sum), int(counted.rating_count)
    rank = bayesian_score(total, count)
    result = RatingRecompute(
        tutor_profile_id=tutor_profile_id,
        before_sum=int(stored.rating_sum),
        before_count=int(stored.rating_count),
        before_rank=Decimal(stored.rank_score),
        after_sum=total,
        after_count=count,
        after_rank=rank,
    )
    if result.changed:
        session.execute(
            sa.update(TutorProfile)
            .where(TutorProfile.id == tutor_profile_id)
            .values(rating_sum=total, rating_count=count, rank_score=rank)
        )
    return result


def _moderation_revision(
    session: Session, kind: ModerationKind, target_id: uuid.UUID, recipient: uuid.UUID
) -> int:
    """How many moderation notices this recipient already has for this review or reply."""
    count = session.execute(
        sa.text(
            "SELECT count(*) FROM notifications "
            "WHERE user_id = :recipient AND dedupe_key LIKE :prefix"
        ),
        {"recipient": recipient, "prefix": f"{kind}:{target_id}:%"},
    ).scalar_one()
    return int(count)


def _my_review(review: TutorReview) -> MyReview:
    return MyReview(
        review_id=review.id,
        booking_id=review.booking_id,
        stars=review.stars,
        text=review.body,
        text_state=review.text_state.value,
        created_at=_utc(review.created_at),
    )


_REPLY_COLUMNS: Final = (
    "p.id AS reply_id, p.body AS reply_body, p.text_state::text AS reply_state, "
    "p.created_at AS reply_created_at"
)


def _review_view(row: sa.Row[tuple[object, ...]]) -> ReviewView:
    """A review row of :meth:`TutorReviewRepository._page`, text hidden unless approved."""
    approved = row.text_state == ModerationState.approved.value
    reply = (
        None
        if row.reply_id is None
        else ReplyView(
            reply_id=row.reply_id,
            body=row.reply_body,
            text_state=row.reply_state,
            created_at=_utc(row.reply_created_at),
        )
    )
    return ReviewView(
        review_id=row.id,
        stars=int(row.stars),
        text=row.body if approved else None,
        text_state=row.text_state,
        created_at=_utc(row.created_at),
        reply=reply,
    )


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class TutorReviewRepository:
    """Review, reply and moderation reads and writes over a ``sessionmaker``.

    Each public method is one transaction. The ``*_in_session`` helpers are
    static: they run inside the caller's transaction (the report-resolution
    path of T25) and take the same tutor-row lock first.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the repository to a session factory."""
        self._sessionmaker = sessionmaker

    # -- S6, S7 -------------------------------------------------------------

    def create_review(
        self, student_id: uuid.UUID, booking_id: uuid.UUID, *, stars: int, text: str | None
    ) -> MyReview:
        """S6: the caller's review of one of their completed bookings.

        Raises :class:`ReviewNotFoundError` (not the caller's booking),
        :class:`NotCompletedError`, :class:`ReviewNotOpenYetError`,
        :class:`AccountTooNewError`, :class:`ReviewExistsError` or
        :class:`ReviewValidationError`. Nothing is written on a refusal.
        """
        rating = _stars(stars)
        body = _review_text(text)
        try:
            with self._sessionmaker.begin() as session:
                booking = session.execute(
                    sa.text(
                        "SELECT tutor_profile_id, state::text AS state, ends_at, now() AS db_now "
                        "FROM tutor_bookings WHERE id = :booking_id AND student_id = :student_id"
                    ),
                    {"booking_id": booking_id, "student_id": student_id},
                ).one_or_none()
                if booking is None:
                    raise ReviewNotFoundError("Booking not found.")
                tutor_id: uuid.UUID = booking.tutor_profile_id
                _lock_profile(session, tutor_id)
                if booking.state != "completed":
                    raise NotCompletedError("You can review a session once it is marked completed.")
                now = _utc(booking.db_now)
                if now < review_open_at(_utc(booking.ends_at)):
                    raise ReviewNotOpenYetError(
                        "Reviews open a week after the session, when its notes close."
                    )
                joined = session.execute(
                    sa.select(User.created_at).where(User.id == student_id)
                ).scalar_one()
                if now - _utc(joined) < REVIEW_MIN_ACCOUNT_AGE:
                    raise AccountTooNewError(
                        "Accounts can leave reviews once they are two weeks old."
                    )
                already = session.execute(
                    sa.select(TutorReview.id).where(TutorReview.booking_id == booking_id)
                ).first()
                if already is not None:
                    raise ReviewExistsError("You already reviewed this session.")
                review = session.execute(
                    sa.insert(TutorReview)
                    .values(
                        booking_id=booking_id,
                        tutor_profile_id=tutor_id,
                        student_id=student_id,
                        stars=rating,
                        body=body,
                        text_state=(
                            ModerationState.none if body is None else ModerationState.pending
                        ),
                    )
                    .returning(TutorReview)
                ).scalar_one()
                _recompute(session, tutor_id)
                return _my_review(review)
        except IntegrityError as exc:
            if _constraint(exc) == "uq_tutor_reviews_booking_id":
                raise ReviewExistsError("You already reviewed this session.") from exc
            raise

    def update_review(
        self,
        student_id: uuid.UUID,
        review_id: uuid.UUID,
        *,
        stars: int | None,
        text: str | None,
        clear_text: bool,
    ) -> MyReview:
        """S7: edit the caller's own review inside its 14-day window.

        New text goes back to ``pending`` (SPEC §a.3); identical text, or a stars-only
        edit, leaves the text state alone; ``clear_text`` removes the text. Raises
        :class:`ReviewNotFoundError` (not the caller's, or removed),
        :class:`EditWindowClosedError` or :class:`ReviewValidationError`.
        """
        if stars is None and text is None and not clear_text:
            raise ReviewValidationError("empty_update", "body", "Change the stars or the text.")
        if clear_text and text is not None:
            raise ReviewValidationError(
                "text_conflict", "text", "Send new text or ask to remove it, not both."
            )
        new_stars = None if stars is None else _stars(stars)
        new_body = None
        if text is not None:
            new_body = _review_text(text)
            if new_body is None:
                raise ReviewValidationError(
                    "text_blank", "text", "Write some text, or choose to remove it."
                )
        with self._sessionmaker.begin() as session:
            tutor_id = session.execute(
                sa.select(TutorReview.tutor_profile_id).where(
                    TutorReview.id == review_id,
                    TutorReview.student_id == student_id,
                    TutorReview.removed_at.is_(None),
                )
            ).scalar_one_or_none()
            if tutor_id is None:
                raise ReviewNotFoundError("Review not found.")
            _lock_profile(session, tutor_id)
            review = session.execute(
                sa.select(TutorReview)
                .where(
                    TutorReview.id == review_id,
                    TutorReview.student_id == student_id,
                    TutorReview.removed_at.is_(None),
                )
                .with_for_update()
            ).scalar_one_or_none()
            if review is None:
                raise ReviewNotFoundError("Review not found.")
            now = _utc(session.execute(sa.select(sa.func.now())).scalar_one())
            if now > review_edit_deadline(_utc(review.created_at)):
                raise EditWindowClosedError(
                    "Reviews can be edited for 14 days after they are written."
                )
            stars_changed = new_stars is not None and new_stars != review.stars
            if new_stars is not None:
                review.stars = new_stars
            if clear_text:
                review.body = None
                review.text_state = ModerationState.none
                review.text_moderated_at = None
                review.text_moderated_by = None
            elif new_body is not None and new_body != review.body:
                review.body = new_body
                review.text_state = ModerationState.pending
                review.text_moderated_at = None
                review.text_moderated_by = None
            session.flush()
            if stars_changed:
                _recompute(session, tutor_id)
            return _my_review(review)

    # -- SP3, T21 -----------------------------------------------------------

    def reviews_for_viewer(
        self,
        tutor_id: uuid.UUID,
        viewer_id: uuid.UUID,
        viewer_role: Role | str,
        *,
        after: ReviewKey | None,
        limit: int,
    ) -> ReviewsPage | None:
        """SP3: a tutor's public reviews, ``None`` unless listed, unpaused and unblocked (O11).

        A student never sees the reviews of a tutor with whom an active block
        exists in either direction; a parent holds no blocks.
        """
        where = f"tp.id = :tutor_id AND {listed_and_not_paused_sql('tp')}"
        params: dict[str, object] = {"tutor_id": tutor_id}
        if Role(viewer_role) is Role.student:
            where += f" AND NOT {active_block_between_sql(':viewer_id', 'tp.user_id')}"
            params["viewer_id"] = viewer_id
        with self._sessionmaker() as session:
            zone = session.execute(
                sa.text(f"SELECT tp.zone FROM tutor_profiles tp WHERE {where}"),  # noqa: S608 - trusted fragments
                params,
            ).scalar_one_or_none()
            if zone is None:
                return None
            return self._page(session, tutor_id, str(zone), own=False, after=after, limit=limit)

    def own_reviews(
        self, tutor_profile_id: uuid.UUID, *, after: ReviewKey | None, limit: int
    ) -> ReviewsPage:
        """T21: the caller's own reviews; text only when approved, their reply in any state."""
        with self._sessionmaker() as session:
            zone = session.execute(
                sa.select(TutorProfile.zone).where(TutorProfile.id == tutor_profile_id)
            ).scalar_one_or_none()
            if zone is None:
                raise ReviewNotFoundError("No such tutor profile.")
            return self._page(session, tutor_profile_id, zone, own=True, after=after, limit=limit)

    # -- T18 ----------------------------------------------------------------

    def create_reply(
        self, tutor_profile_id: uuid.UUID, review_id: uuid.UUID, body: str
    ) -> ReplyView:
        """T18: the tutor's one reply to a review of theirs; it starts ``pending``.

        Raises :class:`ReviewNotFoundError` (not a live review of this tutor),
        :class:`ReplyExistsError`, :class:`~lemely.db.tutor_profile_repo.TutorSuspendedError`,
        :class:`~lemely.db.tutor_profile_repo.TutorClosedError` or :class:`ReviewValidationError`.
        """
        text = _reply_text(body)
        try:
            with self._sessionmaker.begin() as session:
                state = _lock_profile(session, tutor_profile_id, shared=True)
                if state is TutorListingState.suspended:
                    raise TutorSuspendedError("Your tutor profile is suspended.")
                if state is TutorListingState.closed:
                    raise TutorClosedError("Your tutor profile is closed.")
                found = session.execute(
                    sa.select(TutorReview.id).where(
                        TutorReview.id == review_id,
                        TutorReview.tutor_profile_id == tutor_profile_id,
                        TutorReview.removed_at.is_(None),
                    )
                ).first()
                if found is None:
                    raise ReviewNotFoundError("Review not found.")
                if session.execute(
                    sa.select(TutorReviewReply.id).where(TutorReviewReply.review_id == review_id)
                ).first():
                    raise ReplyExistsError("You already replied to this review.")
                reply = session.execute(
                    sa.insert(TutorReviewReply)
                    .values(
                        review_id=review_id,
                        tutor_profile_id=tutor_profile_id,
                        body=text,
                        text_state=ModerationState.pending,
                    )
                    .returning(TutorReviewReply)
                ).scalar_one()
                return ReplyView(
                    reply_id=reply.id,
                    body=reply.body,
                    text_state=reply.text_state.value,
                    created_at=_utc(reply.created_at),
                )
        except IntegrityError as exc:
            if _constraint(exc) == "uq_tutor_review_replies_review_id":
                raise ReplyExistsError("You already replied to this review.") from exc
            raise

    # -- A6-A8 --------------------------------------------------------------

    def moderation_page(
        self,
        kind: Literal["review", "reply", "all"],
        *,
        after: ModerationKey | None,
        limit: int,
    ) -> ModerationPage:
        """A6: texts awaiting moderation, oldest first (review texts and replies)."""
        _check_limit(limit)
        parts: list[str] = []
        if kind in ("review", "all"):
            parts.append(
                "SELECT CAST('review' AS text) AS kind, r.id AS item_id, r.body AS text, "
                "r.created_at AS created_at FROM tutor_reviews r "
                "WHERE r.text_state = 'pending' AND r.removed_at IS NULL"
            )
        if kind in ("reply", "all"):
            # A reply to a removed review is never public, so it needs no moderator.
            parts.append(
                "SELECT CAST('reply' AS text) AS kind, p.id AS item_id, p.body AS text, "
                "p.created_at AS created_at FROM tutor_review_replies p "
                "WHERE p.text_state = 'pending' AND EXISTS (SELECT 1 FROM tutor_reviews rr "
                "WHERE rr.id = p.review_id AND rr.removed_at IS NULL)"
            )
        sql = f"SELECT q.kind, q.item_id, q.text, q.created_at FROM ({' UNION ALL '.join(parts)}) q"  # noqa: S608 - constants
        params: dict[str, object] = {"limit": limit + 1}
        if after is not None:
            sql += " WHERE (q.created_at, q.kind, q.item_id) > (:after_at, :after_kind, :after_id)"
            params |= {
                "after_at": after.created_at,
                "after_kind": after.kind,
                "after_id": after.item_id,
            }
        sql += " ORDER BY q.created_at, q.kind, q.item_id LIMIT :limit"
        with self._sessionmaker() as session:
            rows = session.execute(sa.text(sql), params).all()
        page = rows[:limit]
        items = tuple(
            ModerationItem(
                kind="review" if row.kind == "review" else "reply",
                item_id=row.item_id,
                text=str(row.text),
                created_at=_utc(row.created_at),
            )
            for row in page
        )
        next_key = (
            ModerationKey(
                created_at=items[-1].created_at, kind=items[-1].kind, item_id=items[-1].item_id
            )
            if len(rows) > limit
            else None
        )
        return ModerationPage(items=items, next_key=next_key)

    def moderate_review(
        self, review_id: uuid.UUID, admin_user_id: uuid.UUID, decision: Decision
    ) -> ModerationOutcome:
        """A7: approve or reject a review's pending text.

        Repeating the decision that already holds is a no-op (``changed`` false);
        any other state is :class:`NotPendingError`; an unknown or removed review
        is :class:`ReviewNotFoundError`. The stars are not touched: they count
        from insert (SPEC §a.3).
        """
        target = ModerationState(decision)
        with self._sessionmaker.begin() as session:
            review = session.execute(
                sa.select(TutorReview).where(TutorReview.id == review_id).with_for_update()
            ).scalar_one_or_none()
            if review is None or review.removed_at is not None:
                raise ReviewNotFoundError("Review not found.")
            revision = _moderation_revision(session, "review", review_id, review.student_id)
            changed = review.text_state is ModerationState.pending
            if not changed and review.text_state is not target:
                raise NotPendingError("This review text is not waiting for moderation.")
            if changed:
                session.execute(
                    sa.update(TutorReview)
                    .where(TutorReview.id == review_id)
                    .values(
                        text_state=target,
                        text_moderated_at=sa.func.now(),
                        text_moderated_by=admin_user_id,
                    )
                )
            return ModerationOutcome(
                kind="review",
                item_id=review_id,
                stars=review.stars,
                text=review.body or "",
                text_state=target.value,
                created_at=_utc(review.created_at),
                recipient_user_id=review.student_id,
                changed=changed,
                revision=revision,
            )

    def moderate_reply(
        self, reply_id: uuid.UUID, admin_user_id: uuid.UUID, decision: Decision
    ) -> ModerationOutcome:
        """A8: approve or reject a pending reply (same rules as :meth:`moderate_review`)."""
        target = ModerationState(decision)
        with self._sessionmaker.begin() as session:
            row = session.execute(
                sa.text(
                    "SELECT p.body, p.text_state::text AS text_state, p.created_at, "
                    "tp.user_id AS recipient "
                    "FROM tutor_review_replies p "
                    "JOIN tutor_reviews r ON r.id = p.review_id "
                    "JOIN tutor_profiles tp ON tp.id = p.tutor_profile_id "
                    "WHERE p.id = :reply_id AND r.removed_at IS NULL FOR UPDATE OF p"
                ),
                {"reply_id": reply_id},
            ).one_or_none()
            if row is None:
                raise ReviewNotFoundError("Reply not found.")
            revision = _moderation_revision(session, "reply", reply_id, row.recipient)
            changed = row.text_state == ModerationState.pending.value
            if not changed and row.text_state != target.value:
                raise NotPendingError("This reply is not waiting for moderation.")
            if changed:
                session.execute(
                    sa.update(TutorReviewReply)
                    .where(TutorReviewReply.id == reply_id)
                    .values(
                        text_state=target,
                        moderated_at=sa.func.now(),
                        moderated_by=admin_user_id,
                    )
                )
            return ModerationOutcome(
                kind="reply",
                item_id=reply_id,
                stars=None,
                text=str(row.body),
                text_state=target.value,
                created_at=_utc(row.created_at),
                recipient_user_id=row.recipient,
                changed=changed,
                revision=revision,
            )

    # -- the aggregate ------------------------------------------------------

    def recompute_ratings(self, tutor_profile_id: uuid.UUID) -> None:
        """Rewrite one tutor's aggregate from their reviews, in its own transaction."""
        self.recompute_ratings_report(tutor_profile_id)

    def recompute_ratings_report(self, tutor_profile_id: uuid.UUID) -> RatingRecompute:
        """As :meth:`recompute_ratings`, returning the stored and the recomputed values."""
        with self._sessionmaker.begin() as session:
            return _recompute(session, tutor_profile_id)

    def tutor_profile_ids(self) -> list[uuid.UUID]:
        """Every tutor profile id, in a stable order (the CLI's worklist)."""
        with self._sessionmaker() as session:
            return list(session.scalars(sa.select(TutorProfile.id).order_by(TutorProfile.id)))

    @staticmethod
    def recompute_ratings_in_session(session: Session, tutor_profile_id: uuid.UUID) -> None:
        """Rewrite the aggregate inside the caller's transaction (takes the tutor-row lock)."""
        _recompute(session, tutor_profile_id)

    @staticmethod
    def remove_review_in_session(
        session: Session, review_id: uuid.UUID, admin_user_id: uuid.UUID
    ) -> bool:
        """Remove a review from every aggregate and list (``removed_at``); true if this call did.

        Takes the tutor-row lock first and recomputes in the same transaction, so a
        removal and a concurrent review cannot leave the aggregate stale. False for
        an unknown or already removed review.
        """
        tutor_id = session.execute(
            sa.select(TutorReview.tutor_profile_id).where(TutorReview.id == review_id)
        ).scalar_one_or_none()
        if tutor_id is None:
            return False
        _lock_profile(session, tutor_id)
        removed = session.execute(
            sa.update(TutorReview)
            .where(TutorReview.id == review_id, TutorReview.removed_at.is_(None))
            .values(removed_at=sa.func.now())
            .returning(TutorReview.id)
        ).first()
        if removed is None:
            return False
        _recompute(session, tutor_id)
        log.info("tutor_review_removed", review_id=str(review_id), admin_user_id=str(admin_user_id))
        return True

    @staticmethod
    def hide_reply_in_session(
        session: Session, reply_id: uuid.UUID, admin_user_id: uuid.UUID
    ) -> bool:
        """Take a reply down (state ``rejected``, RF-7); true if this call did."""
        hidden = session.execute(
            sa.update(TutorReviewReply)
            .where(
                TutorReviewReply.id == reply_id,
                TutorReviewReply.text_state != ModerationState.rejected,
            )
            .values(
                text_state=ModerationState.rejected,
                moderated_at=sa.func.now(),
                moderated_by=admin_user_id,
            )
            .returning(TutorReviewReply.id)
        ).first()
        if hidden is not None:
            log.info("tutor_reply_hidden", reply_id=str(reply_id), admin_user_id=str(admin_user_id))
        return hidden is not None

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _page(
        session: Session,
        tutor_id: uuid.UUID,
        zone: str,
        *,
        own: bool,
        after: ReviewKey | None,
        limit: int,
    ) -> ReviewsPage:
        _check_limit(limit)
        reply_filter = "" if own else " AND p.text_state = 'approved'"
        after_filter = ""
        params: dict[str, object] = {"tutor_id": tutor_id, "limit": limit + 1}
        if after is not None:
            after_filter = " AND (r.created_at, r.id) < (:after_at, :after_id)"
            params |= {"after_at": after.created_at, "after_id": after.review_id}
        rows = session.execute(
            sa.text(
                "SELECT r.id, r.stars, r.body, r.text_state::text AS text_state, r.created_at, "  # noqa: S608 - constants
                f"{_REPLY_COLUMNS} FROM tutor_reviews r "
                f"LEFT JOIN tutor_review_replies p ON p.review_id = r.id{reply_filter} "
                f"WHERE r.tutor_profile_id = :tutor_id AND r.removed_at IS NULL{after_filter} "
                "ORDER BY r.created_at DESC, r.id DESC LIMIT :limit"
            ),
            params,
        ).all()
        items = tuple(_review_view(row) for row in rows[:limit])
        next_key = (
            ReviewKey(created_at=items[-1].created_at, review_id=items[-1].review_id)
            if len(rows) > limit
            else None
        )
        return ReviewsPage(items=items, next_key=next_key, zone=zone)


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be 1 to {MAX_PAGE_SIZE}, got {limit}")


__all__ = [
    "MAX_PAGE_SIZE",
    "MAX_REPLY_TEXT",
    "MAX_REVIEW_TEXT",
    "AccountTooNewError",
    "Decision",
    "EditWindowClosedError",
    "ModerationItem",
    "ModerationKey",
    "ModerationKind",
    "ModerationOutcome",
    "ModerationPage",
    "MyReview",
    "NotCompletedError",
    "NotPendingError",
    "RatingRecompute",
    "ReplyExistsError",
    "ReplyView",
    "ReviewError",
    "ReviewExistsError",
    "ReviewKey",
    "ReviewNotFoundError",
    "ReviewNotOpenYetError",
    "ReviewValidationError",
    "ReviewView",
    "ReviewsPage",
    "TutorReviewRepository",
    "moderation_cursor",
    "parse_moderation_cursor",
    "parse_review_cursor",
    "review_cursor",
]
