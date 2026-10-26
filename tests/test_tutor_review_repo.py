"""Reviews, replies, moderation and the rating aggregate (SPEC §a.2, §a.3, §a.4b, SC-12, SC-16).

The module also holds the seeding helpers the other review test files import
(``add_student``, ``add_booking``, ``add_review_row``, ``add_reply_row``,
``stored_ratings``, ``expected_ratings``): the repository under test is never
used to build the world it is judged against.

``expected_ratings`` is the independent oracle: it reads the raw review rows and
feeds them to ``core.tutor_ratings``, so a SQL rule that drifted from the core
rule (latest per student, ties to the later entry, removed excluded) is caught.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker as sessionmaker_factory

from lemely.core.tutor_ratings import aggregate_latest_per_student, bayesian_score
from lemely.db.models.enums import (
    BookingParty,
    BookingState,
    ModerationState,
    NotificationType,
    Role,
    TutoringMode,
)
from lemely.db.models.ops import Notification
from lemely.db.models.tutoring import TutorBooking, TutorReview, TutorReviewReply
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.tutor_profile_repo import TutorSuspendedError
from lemely.db.tutor_review_repo import (
    AccountTooNewError,
    EditWindowClosedError,
    NotCompletedError,
    NotPendingError,
    ReplyExistsError,
    ReviewExistsError,
    ReviewKey,
    ReviewNotFoundError,
    ReviewNotOpenYetError,
    ReviewValidationError,
    TutorReviewRepository,
)
from lemely.web.push import RecordingPushTransport
from lemely.web.tutoring_notify import review_notices, send_after_commit
from tests.tutoring_db import (
    SeededTutor,
    add_block,
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOTES_WINDOW = timedelta(days=7)  # SPEC §a.2 / O10: reviews open 7 days after the session ends
EDIT_WINDOW = timedelta(days=14)  # SPEC §a.2: edits within 14 days of creation
MIN_ACCOUNT_AGE = timedelta(days=14)  # SPEC F7
PRIOR = Decimal("4.000000")
MEETING_LINK = "https://meet.google.com/abc-defg-hij"


# ---------------------------------------------------------------------------
# Seeding helpers (direct inserts; imported by the other review test files)
# ---------------------------------------------------------------------------


def set_account_age(sm: sessionmaker[Session], user_id: uuid.UUID, age: timedelta) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE users SET created_at = now() - make_interval(secs => :s) WHERE id = :u"
            ),
            {"s": age.total_seconds(), "u": user_id},
        )


def add_student(
    sm: sessionmaker[Session], *, age: timedelta = timedelta(days=60), verified: bool = True
) -> uuid.UUID:
    student = add_user(sm, Role.student, verified=verified)
    set_account_age(sm, student, age)
    return student


def add_booking(
    sm: sessionmaker[Session],
    *,
    student: uuid.UUID,
    tutor: SeededTutor,
    subject: str,
    state: str = "completed",
    ended_ago: timedelta = NOTES_WINDOW + timedelta(days=1),
    duration: timedelta = timedelta(hours=1),
) -> uuid.UUID:
    ends_at = datetime.now(UTC) - ended_ago
    starts_at = ends_at - duration
    booking_state = BookingState(state)
    fields: dict[str, object] = {}
    if booking_state in {BookingState.accepted, BookingState.completed, BookingState.no_show}:
        fields["accepted_at"] = starts_at - timedelta(days=1)
        fields["meeting_link"] = MEETING_LINK
    if booking_state is BookingState.completed:
        fields["completed_at"] = ends_at + timedelta(minutes=5)
        fields["completed_by_party"] = BookingParty.tutor
    if booking_state is BookingState.no_show:
        fields["no_show_marked_at"] = ends_at + timedelta(minutes=5)
    if booking_state is BookingState.cancelled:
        fields["cancelled_at"] = starts_at - timedelta(days=2)
        fields["cancelled_by_party"] = BookingParty.student
    if booking_state is BookingState.declined:
        fields["declined_at"] = starts_at - timedelta(days=2)
    if booking_state is BookingState.expired:
        fields["expired_at"] = ends_at
    booking_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            TutorBooking(
                id=booking_id,
                tutor_profile_id=tutor.profile_id,
                student_id=student,
                requested_by_user_id=student,
                requested_by_party=BookingParty.student,
                subject_code=subject,
                mode=TutoringMode.virtual,
                starts_at=starts_at,
                ends_at=ends_at,
                state=booking_state,
                **fields,
            )
        )
    return booking_id


def add_review_row(
    sm: sessionmaker[Session],
    *,
    booking: uuid.UUID,
    tutor_id: uuid.UUID,
    student: uuid.UUID,
    stars: int = 5,
    text: str | None = None,
    text_state: str | None = None,
    created_at: datetime | None = None,
    removed: bool = False,
    review_id: uuid.UUID | None = None,
) -> uuid.UUID:
    rid = review_id or uuid.uuid4()
    state = text_state or ("none" if text is None else "pending")
    with sm.begin() as session:
        review = TutorReview(
            id=rid,
            booking_id=booking,
            tutor_profile_id=tutor_id,
            student_id=student,
            stars=stars,
            body=text,
            text_state=ModerationState(state),
            removed_at=datetime.now(UTC) if removed else None,
        )
        if created_at is not None:
            review.created_at = created_at
        session.add(review)
    return rid


def add_reply_row(
    sm: sessionmaker[Session],
    *,
    review: uuid.UUID,
    tutor_id: uuid.UUID,
    body: str = "Thank you for the feedback.",
    state: str = "pending",
    created_at: datetime | None = None,
) -> uuid.UUID:
    rid = uuid.uuid4()
    with sm.begin() as session:
        reply = TutorReviewReply(
            id=rid,
            review_id=review,
            tutor_profile_id=tutor_id,
            body=body,
            text_state=ModerationState(state),
        )
        if created_at is not None:
            reply.created_at = created_at
        session.add(reply)
    return rid


def stored_ratings(sm: sessionmaker[Session], tutor_id: uuid.UUID) -> tuple[int, int, Decimal]:
    with sm() as session:
        row = session.execute(
            sa.text(
                "SELECT rating_sum, rating_count, rank_score FROM tutor_profiles WHERE id = :t"
            ),
            {"t": tutor_id},
        ).one()
    return int(row[0]), int(row[1]), Decimal(row[2])


def expected_ratings(sm: sessionmaker[Session], tutor_id: uuid.UUID) -> tuple[int, int, Decimal]:
    """The aggregate the SPEC defines, computed by ``core.tutor_ratings`` from the raw rows."""
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT student_id::text, stars, created_at FROM tutor_reviews "
                "WHERE tutor_profile_id = :t AND removed_at IS NULL ORDER BY created_at, id"
            ),
            {"t": tutor_id},
        ).all()
    total, count = aggregate_latest_per_student([(r[0], int(r[1]), r[2]) for r in rows])
    return total, count, bayesian_score(total, count)


def review_row(sm: sessionmaker[Session], review_id: uuid.UUID) -> sa.Row[tuple[object, ...]]:
    with sm() as session:
        return session.execute(
            sa.text(
                "SELECT stars, body, text_state::text AS text_state, text_moderated_at, "
                "text_moderated_by, removed_at, created_at FROM tutor_reviews WHERE id = :r"
            ),
            {"r": review_id},
        ).one()


def set_review_created(sm: sessionmaker[Session], review_id: uuid.UUID, age: timedelta) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE tutor_reviews SET created_at = now() - make_interval(secs => :s) "
                "WHERE id = :r"
            ),
            {"s": age.total_seconds(), "r": review_id},
        )


def notification_service(sm: sessionmaker[Session]) -> NotificationService:
    return NotificationService(sm, NotificationPreferencesService(sm))


@dataclass(frozen=True)
class World:
    tutor: SeededTutor
    subject: str
    student: uuid.UUID


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def repo(sm: sessionmaker[Session]) -> TutorReviewRepository:
    return TutorReviewRepository(sm)


@pytest.fixture
def w(sm: sessionmaker[Session]) -> World:
    subject = add_subject(sm)
    return World(tutor=add_tutor(sm, subjects=(subject,)), subject=subject, student=add_student(sm))


def completed(sm: sessionmaker[Session], w: World, **kwargs: object) -> uuid.UUID:
    return add_booking(sm, student=w.student, tutor=w.tutor, subject=w.subject, **kwargs)  # type: ignore[arg-type]


def review_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.execute(sa.text("SELECT count(*) FROM tutor_reviews")).scalar_one())


# ---------------------------------------------------------------------------
# Create: the window, completion, ownership, account age, blocks (O10, F7)
# ---------------------------------------------------------------------------


def test_review_create_refused_before_notes_window_closes(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    early = completed(sm, w, ended_ago=NOTES_WINDOW - timedelta(minutes=5))
    with pytest.raises(ReviewNotOpenYetError):
        repo.create_review(w.student, early, stars=5, text=None)
    assert review_count(sm) == 0
    assert stored_ratings(sm, w.tutor.profile_id) == (0, 0, PRIOR)

    on_time = completed(sm, w, ended_ago=NOTES_WINDOW + timedelta(minutes=5))
    review = repo.create_review(w.student, on_time, stars=5, text=None)
    assert (review.stars, review.text, review.text_state) == (5, None, "none")
    assert review_count(sm) == 1


def test_review_requires_completed_booking_and_own_student(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    for offset, state in enumerate(["accepted", "no_show", "cancelled", "declined", "requested"]):
        booking = completed(
            sm, w, state=state, ended_ago=NOTES_WINDOW + timedelta(days=2 * (offset + 1))
        )
        with pytest.raises(NotCompletedError):
            repo.create_review(w.student, booking, stars=4, text=None)
    mine = completed(sm, w)
    stranger = add_student(sm)
    with pytest.raises(ReviewNotFoundError):
        repo.create_review(stranger, mine, stars=1, text=None)
    with pytest.raises(ReviewNotFoundError):
        repo.create_review(w.student, uuid.uuid4(), stars=1, text=None)
    assert review_count(sm) == 0
    assert stored_ratings(sm, w.tutor.profile_id) == (0, 0, PRIOR)


def test_account_too_new_409(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    newcomer = add_student(sm, age=MIN_ACCOUNT_AGE - timedelta(minutes=5))
    booking = add_booking(sm, student=newcomer, tutor=w.tutor, subject=w.subject)
    with pytest.raises(AccountTooNewError):
        repo.create_review(newcomer, booking, stars=5, text=None)
    assert review_count(sm) == 0
    set_account_age(sm, newcomer, MIN_ACCOUNT_AGE + timedelta(minutes=5))
    assert repo.create_review(newcomer, booking, stars=5, text=None).stars == 5


def test_one_review_per_booking(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    booking = completed(sm, w)
    repo.create_review(w.student, booking, stars=5, text=None)
    with pytest.raises(ReviewExistsError):
        repo.create_review(w.student, booking, stars=1, text=None)
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (5, 1)


def test_windows_hold_when_the_database_session_zone_is_cairo(
    sm: sessionmaker[Session], w: World
) -> None:
    """Instants are compared as UTC: a non-UTC session zone changes no boundary (SPEC §i.4)."""
    cairo = sa.create_engine(
        sm.kw["bind"].url, connect_args={"options": "-c TimeZone=Africa/Cairo"}
    )
    try:
        repo = TutorReviewRepository(sessionmaker_factory(bind=cairo, expire_on_commit=False))
        with cairo.connect() as conn:
            assert conn.execute(sa.text("SHOW TimeZone")).scalar_one() == "Africa/Cairo"
        with pytest.raises(ReviewNotOpenYetError):
            repo.create_review(
                w.student,
                completed(sm, w, ended_ago=NOTES_WINDOW - timedelta(minutes=5)),
                stars=5,
                text=None,
            )
        review = repo.create_review(
            w.student,
            completed(sm, w, ended_ago=NOTES_WINDOW + timedelta(minutes=5)),
            stars=5,
            text=None,
        )
        set_review_created(sm, review.review_id, EDIT_WINDOW - timedelta(minutes=5))
        assert (
            repo.update_review(
                w.student, review.review_id, stars=2, text=None, clear_text=False
            ).stars
            == 2
        )
        set_review_created(sm, review.review_id, EDIT_WINDOW + timedelta(minutes=5))
        with pytest.raises(EditWindowClosedError):
            repo.update_review(w.student, review.review_id, stars=3, text=None, clear_text=False)
    finally:
        cairo.dispose()


@pytest.mark.parametrize("direction", ["student_blocks_tutor", "tutor_blocks_student"])
def test_block_keeps_review_right(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World, direction: str
) -> None:
    booking = completed(sm, w)
    if direction == "student_blocks_tutor":
        add_block(sm, w.student, w.tutor.user_id)
    else:
        add_block(sm, w.tutor.user_id, w.student)
    review = repo.create_review(w.student, booking, stars=2, text=None)
    assert review.stars == 2
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (2, 1)


def test_review_of_a_suspended_tutor_is_still_accepted(
    sm: sessionmaker[Session], repo: TutorReviewRepository
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(sm, state="suspended", subjects=(subject,))
    student = add_student(sm)
    booking = add_booking(sm, student=student, tutor=tutor, subject=subject)
    assert repo.create_review(student, booking, stars=3, text=None).stars == 3


def test_stars_and_text_are_validated_before_anything_is_written(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    booking = completed(sm, w)
    for stars in (0, 6, -1):
        with pytest.raises(ReviewValidationError) as bad_stars:
            repo.create_review(w.student, booking, stars=stars, text=None)
        assert bad_stars.value.code == "invalid_stars"
    with pytest.raises(ReviewValidationError) as too_long:
        repo.create_review(w.student, booking, stars=5, text="x" * 1001)
    assert too_long.value.code == "text_too_long"
    with pytest.raises(ReviewValidationError) as contact:
        repo.create_review(w.student, booking, stars=5, text="call me on 01012345678")
    assert contact.value.code == "contact_details_not_allowed"
    assert review_count(sm) == 0


def test_blank_text_is_stored_as_no_text(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    review = repo.create_review(w.student, completed(sm, w), stars=4, text="   \n ")
    assert (review.text, review.text_state) == (None, "none")


def test_text_review_starts_pending_and_is_trimmed(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    review = repo.create_review(w.student, completed(sm, w), stars=4, text="  Clear and patient.  ")
    assert (review.text, review.text_state) == ("Clear and patient.", "pending")


# ---------------------------------------------------------------------------
# Edit: text returns to pending, 14 days (SPEC §a.3, row 7)
# ---------------------------------------------------------------------------


def test_edit_returns_text_to_pending_and_closes_after_14_days(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    created = repo.create_review(w.student, completed(sm, w), stars=4, text="Good lessons.")
    admin = add_user(sm, Role.platform_admin)
    repo.moderate_review(created.review_id, admin, "approved")
    assert review_row(sm, created.review_id).text_state == "approved"

    edited = repo.update_review(
        w.student, created.review_id, stars=None, text="Excellent lessons.", clear_text=False
    )
    assert (edited.text, edited.text_state) == ("Excellent lessons.", "pending")
    row = review_row(sm, created.review_id)
    assert (row.text_moderated_at, row.text_moderated_by) == (None, None)

    set_review_created(sm, created.review_id, EDIT_WINDOW - timedelta(minutes=5))
    assert (
        repo.update_review(w.student, created.review_id, stars=3, text=None, clear_text=False).stars
        == 3
    )

    set_review_created(sm, created.review_id, EDIT_WINDOW + timedelta(minutes=5))
    with pytest.raises(EditWindowClosedError):
        repo.update_review(w.student, created.review_id, stars=1, text=None, clear_text=False)
    assert review_row(sm, created.review_id).stars == 3
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (3, 1)


def test_a_stars_only_edit_leaves_the_text_state_alone(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    created = repo.create_review(w.student, completed(sm, w), stars=4, text="Good lessons.")
    repo.moderate_review(created.review_id, add_user(sm, Role.platform_admin), "approved")
    repo.update_review(w.student, created.review_id, stars=2, text=None, clear_text=False)
    assert review_row(sm, created.review_id).text_state == "approved"
    repo.update_review(
        w.student, created.review_id, stars=None, text="Good lessons.", clear_text=False
    )
    assert (
        review_row(sm, created.review_id).text_state == "approved"
    )  # same words, nothing to re-check


def test_clear_text_removes_the_text_and_its_moderation(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    created = repo.create_review(w.student, completed(sm, w), stars=4, text="Good lessons.")
    cleared = repo.update_review(
        w.student, created.review_id, stars=None, text=None, clear_text=True
    )
    assert (cleared.text, cleared.text_state) == (None, "none")
    row = review_row(sm, created.review_id)
    assert (row.body, row.text_state) == (None, "none")


def test_edit_validation(sm: sessionmaker[Session], repo: TutorReviewRepository, w: World) -> None:
    created = repo.create_review(w.student, completed(sm, w), stars=4, text="Good lessons.")

    def code_of(**kwargs: object) -> str:
        with pytest.raises(ReviewValidationError) as caught:
            repo.update_review(w.student, created.review_id, **kwargs)  # type: ignore[arg-type]
        return caught.value.code

    assert code_of(stars=None, text=None, clear_text=False) == "empty_update"
    assert code_of(stars=9, text=None, clear_text=False) == "invalid_stars"
    assert code_of(stars=None, text="Good", clear_text=True) == "text_conflict"
    assert code_of(stars=None, text="   ", clear_text=False) == "text_blank"
    assert (
        code_of(stars=None, text="mail me a@b.com", clear_text=False)
        == "contact_details_not_allowed"
    )
    assert code_of(stars=None, text="x" * 1001, clear_text=False) == "text_too_long"
    assert review_row(sm, created.review_id).body == "Good lessons."


def test_only_the_author_can_edit_and_a_removed_review_cannot_be_edited(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    created = repo.create_review(w.student, completed(sm, w), stars=4, text=None)
    with pytest.raises(ReviewNotFoundError):
        repo.update_review(add_student(sm), created.review_id, stars=1, text=None, clear_text=False)
    with pytest.raises(ReviewNotFoundError):
        repo.update_review(w.student, uuid.uuid4(), stars=1, text=None, clear_text=False)
    with sm.begin() as session:
        assert repo.remove_review_in_session(session, created.review_id, uuid.uuid4()) is True
    with pytest.raises(ReviewNotFoundError):
        repo.update_review(w.student, created.review_id, stars=1, text=None, clear_text=False)
    assert review_row(sm, created.review_id).stars == 4


# ---------------------------------------------------------------------------
# The aggregate: written with every change, latest per student, removed leaves (SC-16)
# ---------------------------------------------------------------------------


def test_rank_score_written_with_rating_change(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    tutor_id = w.tutor.profile_id
    students = [add_student(sm) for _ in range(3)]
    reviews = []
    # (stars) -> hand-computed (sum, count, (5 * 4.0 + sum) / (5 + count)); not taken from the code.
    steps = [
        (5, (5, 1, Decimal("4.166667"))),
        (3, (8, 2, Decimal("4.000000"))),
        (5, (13, 3, Decimal("4.125000"))),
    ]
    for student, (stars, expected) in zip(students, steps, strict=True):
        booking = add_booking(sm, student=student, tutor=w.tutor, subject=w.subject)
        reviews.append(repo.create_review(student, booking, stars=stars, text=None))
        assert stored_ratings(sm, tutor_id) == expected
        assert expected_ratings(sm, tutor_id) == expected
    with sm() as session:
        average = session.execute(
            sa.text("SELECT rating_avg FROM tutor_profiles WHERE id = :t"), {"t": tutor_id}
        ).scalar_one()
    assert average == Decimal("4.33")

    repo.update_review(students[1], reviews[1].review_id, stars=5, text=None, clear_text=False)
    assert stored_ratings(sm, tutor_id) == (15, 3, Decimal("4.375000"))
    assert expected_ratings(sm, tutor_id) == stored_ratings(sm, tutor_id)


def test_removed_review_leaves_aggregate(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    other = add_student(sm)
    first = repo.create_review(w.student, completed(sm, w), stars=5, text=None)
    second = repo.create_review(
        other,
        add_booking(sm, student=other, tutor=w.tutor, subject=w.subject),
        stars=1,
        text=None,
    )
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (6, 2)
    admin = add_user(sm, Role.platform_admin)

    with sm.begin() as session:
        assert repo.remove_review_in_session(session, second.review_id, admin) is True
    assert stored_ratings(sm, w.tutor.profile_id) == (5, 1, Decimal("4.166667"))
    assert expected_ratings(sm, w.tutor.profile_id) == stored_ratings(sm, w.tutor.profile_id)
    with sm.begin() as session:
        assert repo.remove_review_in_session(session, second.review_id, admin) is False
        assert repo.remove_review_in_session(session, uuid.uuid4(), admin) is False
    page = repo.own_reviews(w.tutor.profile_id, after=None, limit=20)
    assert [item.review_id for item in page.items] == [first.review_id]
    assert review_row(sm, second.review_id).removed_at is not None

    with sm.begin() as session:
        assert repo.remove_review_in_session(session, first.review_id, admin) is True
    assert stored_ratings(sm, w.tutor.profile_id) == (0, 0, PRIOR)


def test_latest_review_per_student_counts_once(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    now = datetime.now(UTC)
    tutor_id = w.tutor.profile_id
    old = add_review_row(
        sm,
        booking=completed(sm, w, ended_ago=timedelta(days=40)),
        tutor_id=tutor_id,
        student=w.student,
        stars=1,
        created_at=now - timedelta(days=30),
    )
    add_review_row(
        sm,
        booking=completed(sm, w, ended_ago=timedelta(days=20)),
        tutor_id=tutor_id,
        student=w.student,
        stars=4,
        created_at=now - timedelta(days=10),
    )
    repo.recompute_ratings(tutor_id)
    assert stored_ratings(sm, tutor_id) == (4, 1, Decimal("4.000000"))
    assert expected_ratings(sm, tutor_id) == stored_ratings(sm, tutor_id)

    # Removing the latest hands the student's slot back to their earlier review.
    with sm.begin() as session:
        latest = session.execute(
            sa.text("SELECT id FROM tutor_reviews WHERE tutor_profile_id = :t AND id <> :o"),
            {"t": tutor_id, "o": old},
        ).scalar_one()
        repo.remove_review_in_session(session, latest, uuid.uuid4())
    assert stored_ratings(sm, tutor_id)[:2] == (1, 1)


def test_exact_created_at_tie_goes_to_the_greater_review_id(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    """SPEC §i.4: `DISTINCT ON (student_id)` breaks a created_at tie by `id` descending."""
    instant = datetime.now(UTC) - timedelta(days=3)
    ids = sorted([uuid.uuid4(), uuid.uuid4()])
    stars_by_id = {ids[0]: 2, ids[1]: 5}
    for review_id in ids:
        add_review_row(
            sm,
            booking=completed(sm, w, ended_ago=timedelta(days=30 + ids.index(review_id) * 3)),
            tutor_id=w.tutor.profile_id,
            student=w.student,
            stars=stars_by_id[review_id],
            created_at=instant,
            review_id=review_id,
        )
    repo.recompute_ratings(w.tutor.profile_id)
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (stars_by_id[ids[1]], 1)
    assert expected_ratings(sm, w.tutor.profile_id)[:2] == (stars_by_id[ids[1]], 1)


def test_recompute_restores_a_corrupted_aggregate(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    other = add_student(sm)
    for student, stars in ((w.student, 4), (other, 2)):
        add_review_row(
            sm,
            booking=add_booking(sm, student=student, tutor=w.tutor, subject=w.subject),
            tutor_id=w.tutor.profile_id,
            student=student,
            stars=stars,
        )
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE tutor_profiles SET rating_sum = 20, rating_count = 5, "
                "rank_score = 4.900000 WHERE id = :t"
            ),
            {"t": w.tutor.profile_id},
        )
    repo.recompute_ratings(w.tutor.profile_id)
    assert stored_ratings(sm, w.tutor.profile_id) == (
        6,
        2,
        Decimal("3.714286"),
    )  # (5 * 4.0 + 6) / (5 + 2)


def test_recompute_in_session_rolls_back_with_the_caller(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    add_review_row(
        sm,
        booking=completed(sm, w),
        tutor_id=w.tutor.profile_id,
        student=w.student,
        stars=5,
    )
    with sm() as session:
        repo.recompute_ratings_in_session(session, w.tutor.profile_id)
        session.rollback()
    assert stored_ratings(sm, w.tutor.profile_id) == (0, 0, PRIOR)


def test_recompute_unknown_tutor_is_refused(repo: TutorReviewRepository) -> None:
    with pytest.raises(ReviewNotFoundError):
        repo.recompute_ratings(uuid.uuid4())


# ---------------------------------------------------------------------------
# Replies (T18)
# ---------------------------------------------------------------------------


def test_reply_is_created_pending_and_only_one_is_allowed(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    review = repo.create_review(w.student, completed(sm, w), stars=5, text=None)
    reply = repo.create_reply(w.tutor.profile_id, review.review_id, "  Thank you!  ")
    assert (reply.body, reply.text_state) == ("Thank you!", "pending")
    with pytest.raises(ReplyExistsError):
        repo.create_reply(w.tutor.profile_id, review.review_id, "Again")


def test_reply_to_a_review_of_another_tutor_or_a_removed_one_is_not_found(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    review = repo.create_review(w.student, completed(sm, w), stars=5, text=None)
    rival = add_tutor(sm, subjects=(w.subject,))
    with pytest.raises(ReviewNotFoundError):
        repo.create_reply(rival.profile_id, review.review_id, "Mine now")
    with pytest.raises(ReviewNotFoundError):
        repo.create_reply(w.tutor.profile_id, uuid.uuid4(), "Nothing here")
    with sm.begin() as session:
        repo.remove_review_in_session(session, review.review_id, uuid.uuid4())
    with pytest.raises(ReviewNotFoundError):
        repo.create_reply(w.tutor.profile_id, review.review_id, "Too late")


def test_reply_validation(sm: sessionmaker[Session], repo: TutorReviewRepository, w: World) -> None:
    review = repo.create_review(w.student, completed(sm, w), stars=5, text=None)

    def code_of(body: str) -> str:
        with pytest.raises(ReviewValidationError) as caught:
            repo.create_reply(w.tutor.profile_id, review.review_id, body)
        return caught.value.code

    assert code_of("   ") == "reply_empty"
    assert code_of("x" * 1001) == "text_too_long"
    assert code_of("write to me at https://example.com") == "contact_details_not_allowed"
    assert len(repo.own_reviews(w.tutor.profile_id, after=None, limit=5).items) == 1
    with sm() as session:
        assert (
            session.execute(sa.text("SELECT count(*) FROM tutor_review_replies")).scalar_one() == 0
        )


def test_reply_refused_for_a_suspended_tutor_inside_the_transaction(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    review = repo.create_review(w.student, completed(sm, w), stars=5, text=None)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE tutor_profiles SET listing_state = 'suspended' WHERE id = :t"),
            {"t": w.tutor.profile_id},
        )
    with pytest.raises(TutorSuspendedError):
        repo.create_reply(w.tutor.profile_id, review.review_id, "Thanks")
    with sm() as session:
        assert (
            session.execute(sa.text("SELECT count(*) FROM tutor_review_replies")).scalar_one() == 0
        )


# ---------------------------------------------------------------------------
# Who sees what (SP3, T21; SC-12, O11, O27)
# ---------------------------------------------------------------------------


def _seed_four_states(sm: sessionmaker[Session], w: World) -> dict[str, uuid.UUID]:
    """One review per text state, newest first in the order none, pending, approved, rejected."""
    now = datetime.now(UTC)
    ids: dict[str, uuid.UUID] = {}
    for index, (state, text) in enumerate(
        [
            ("none", None),
            ("pending", "pending text"),
            ("approved", "approved text"),
            ("rejected", "rejected text"),
        ]
    ):
        student = add_student(sm)
        ids[state] = add_review_row(
            sm,
            booking=add_booking(sm, student=student, tutor=w.tutor, subject=w.subject),
            tutor_id=w.tutor.profile_id,
            student=student,
            stars=index + 1,
            text=text,
            text_state=state,
            created_at=now - timedelta(days=index + 1),
        )
    return ids


def test_public_text_only_after_approval_and_reply_only_when_approved(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    ids = _seed_four_states(sm, w)
    add_reply_row(
        sm, review=ids["none"], tutor_id=w.tutor.profile_id, body="pending reply", state="pending"
    )
    add_reply_row(
        sm,
        review=ids["pending"],
        tutor_id=w.tutor.profile_id,
        body="rejected reply",
        state="rejected",
    )
    add_reply_row(
        sm,
        review=ids["approved"],
        tutor_id=w.tutor.profile_id,
        body="approved reply",
        state="approved",
    )
    viewer = add_user(sm, Role.student)

    page = repo.reviews_for_viewer(w.tutor.profile_id, viewer, Role.student, after=None, limit=20)
    assert page is not None
    assert [item.review_id for item in page.items] == [
        ids[s] for s in ("none", "pending", "approved", "rejected")
    ]
    assert [item.text for item in page.items] == [None, None, "approved text", None]
    assert [item.reply.body if item.reply else None for item in page.items] == [
        None,
        None,
        "approved reply",
        None,
    ]
    assert page.zone == "Africa/Cairo"


def test_the_tutor_sees_their_own_reply_in_any_state_and_text_only_when_approved(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    ids = _seed_four_states(sm, w)
    add_reply_row(
        sm, review=ids["none"], tutor_id=w.tutor.profile_id, body="pending reply", state="pending"
    )
    add_reply_row(
        sm,
        review=ids["pending"],
        tutor_id=w.tutor.profile_id,
        body="rejected reply",
        state="rejected",
    )
    page = repo.own_reviews(w.tutor.profile_id, after=None, limit=20)
    by_id = {item.review_id: item for item in page.items}
    assert [by_id[ids[s]].text for s in ("none", "pending", "approved", "rejected")] == [
        None,
        None,
        "approved text",
        None,
    ]
    assert [by_id[ids[s]].text_state for s in ("none", "pending", "approved", "rejected")] == [
        "none",
        "pending",
        "approved",
        "rejected",
    ]
    assert by_id[ids["none"]].reply is not None
    assert (by_id[ids["none"]].reply.body, by_id[ids["none"]].reply.text_state) == (
        "pending reply",
        "pending",
    )  # type: ignore[union-attr]
    assert by_id[ids["pending"]].reply.text_state == "rejected"  # type: ignore[union-attr]
    assert by_id[ids["approved"]].reply is None


def test_own_reviews_belong_to_the_caller_only(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    other_subject = add_subject(sm)
    rival = add_tutor(sm, subjects=(other_subject,))
    student = add_student(sm)
    add_review_row(
        sm,
        booking=add_booking(sm, student=student, tutor=rival, subject=other_subject),
        tutor_id=rival.profile_id,
        student=student,
        stars=1,
    )
    mine = repo.create_review(w.student, completed(sm, w), stars=5, text=None)
    assert [
        i.review_id for i in repo.own_reviews(w.tutor.profile_id, after=None, limit=20).items
    ] == [mine.review_id]
    assert len(repo.own_reviews(rival.profile_id, after=None, limit=20).items) == 1


@pytest.mark.parametrize(
    "hidden", ["draft", "pending_review", "rejected", "suspended", "closed", "paused"]
)
def test_o11_reviews_of_a_tutor_who_is_not_listed_and_unpaused_are_not_served(
    sm: sessionmaker[Session], repo: TutorReviewRepository, hidden: str
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(
        sm,
        state="listed" if hidden == "paused" else hidden,
        paused=hidden == "paused",
        subjects=(subject,),
    )
    student = add_student(sm)
    add_review_row(
        sm,
        booking=add_booking(sm, student=student, tutor=tutor, subject=subject),
        tutor_id=tutor.profile_id,
        student=student,
    )
    viewer = add_user(sm, Role.student)
    assert (
        repo.reviews_for_viewer(tutor.profile_id, viewer, Role.student, after=None, limit=20)
        is None
    )
    assert repo.reviews_for_viewer(uuid.uuid4(), viewer, Role.student, after=None, limit=20) is None


@pytest.mark.parametrize("direction", ["student_blocks_tutor", "tutor_blocks_student"])
def test_a_blocked_pair_gets_no_reviews_but_a_parent_holds_no_blocks(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World, direction: str
) -> None:
    viewer = add_user(sm, Role.student)
    parent = add_user(sm, Role.parent)
    if direction == "student_blocks_tutor":
        add_block(sm, viewer, w.tutor.user_id)
    else:
        add_block(sm, w.tutor.user_id, viewer)
    assert (
        repo.reviews_for_viewer(w.tutor.profile_id, viewer, Role.student, after=None, limit=20)
        is None
    )
    assert (
        repo.reviews_for_viewer(w.tutor.profile_id, parent, Role.parent, after=None, limit=20)
        is not None
    )


def test_reviews_page_newest_first_with_a_keyset_and_removed_excluded(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    now = datetime.now(UTC)
    ids: list[uuid.UUID] = []
    for days in (1, 2, 3, 4, 5):
        student = add_student(sm)
        ids.append(
            add_review_row(
                sm,
                booking=add_booking(sm, student=student, tutor=w.tutor, subject=w.subject),
                tutor_id=w.tutor.profile_id,
                student=student,
                created_at=now - timedelta(days=days),
                removed=days == 2,
            )
        )
    viewer = add_user(sm, Role.student)
    first = repo.reviews_for_viewer(w.tutor.profile_id, viewer, Role.student, after=None, limit=2)
    assert first is not None
    assert [i.review_id for i in first.items] == [ids[0], ids[2]]
    assert isinstance(first.next_key, ReviewKey)
    second = repo.reviews_for_viewer(
        w.tutor.profile_id, viewer, Role.student, after=first.next_key, limit=2
    )
    assert second is not None
    assert [i.review_id for i in second.items] == [ids[3], ids[4]]
    assert second.next_key is None


# ---------------------------------------------------------------------------
# Moderation (A6-A8, SPEC §a.3)
# ---------------------------------------------------------------------------


def test_moderate_review_approve_reject_and_idempotent_repeat(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    admin = add_user(sm, Role.platform_admin)
    created = repo.create_review(w.student, completed(sm, w), stars=5, text="Lovely.")
    approved = repo.moderate_review(created.review_id, admin, "approved")
    assert (approved.changed, approved.text_state, approved.text, approved.stars) == (
        True,
        "approved",
        "Lovely.",
        5,
    )
    assert approved.recipient_user_id == w.student
    row = review_row(sm, created.review_id)
    assert (row.text_state, row.text_moderated_by) == ("approved", admin)
    assert row.text_moderated_at is not None

    again = repo.moderate_review(created.review_id, admin, "approved")
    assert (again.changed, again.text_state) == (False, "approved")
    with pytest.raises(NotPendingError):
        repo.moderate_review(created.review_id, admin, "rejected")


def test_moderate_review_without_text_or_unknown_or_removed(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    admin = add_user(sm, Role.platform_admin)
    stars_only = repo.create_review(w.student, completed(sm, w), stars=3, text=None)
    with pytest.raises(NotPendingError):
        repo.moderate_review(stars_only.review_id, admin, "approved")
    with pytest.raises(ReviewNotFoundError):
        repo.moderate_review(uuid.uuid4(), admin, "approved")
    other = add_student(sm)
    gone = repo.create_review(
        other,
        add_booking(sm, student=other, tutor=w.tutor, subject=w.subject),
        stars=2,
        text="Hmm.",
    )
    with sm.begin() as session:
        repo.remove_review_in_session(session, gone.review_id, admin)
    with pytest.raises(ReviewNotFoundError):
        repo.moderate_review(gone.review_id, admin, "approved")


def test_moderate_reply_and_hide_reply(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    admin = add_user(sm, Role.platform_admin)
    review = repo.create_review(w.student, completed(sm, w), stars=5, text=None)
    reply = repo.create_reply(w.tutor.profile_id, review.review_id, "Thanks for the kind words.")
    outcome = repo.moderate_reply(reply.reply_id, admin, "approved")
    assert (outcome.changed, outcome.text_state, outcome.text, outcome.stars) == (
        True,
        "approved",
        "Thanks for the kind words.",
        None,
    )
    assert outcome.recipient_user_id == w.tutor.user_id
    assert repo.moderate_reply(reply.reply_id, admin, "approved").changed is False
    with pytest.raises(NotPendingError):
        repo.moderate_reply(reply.reply_id, admin, "rejected")
    with pytest.raises(ReviewNotFoundError):
        repo.moderate_reply(uuid.uuid4(), admin, "approved")

    with sm.begin() as session:
        assert repo.hide_reply_in_session(session, reply.reply_id, admin) is True
    with sm.begin() as session:
        assert repo.hide_reply_in_session(session, reply.reply_id, admin) is False
        assert repo.hide_reply_in_session(session, uuid.uuid4(), admin) is False
    with sm() as session:
        state, by = session.execute(
            sa.text(
                "SELECT text_state::text, moderated_by FROM tutor_review_replies WHERE id = :r"
            ),
            {"r": reply.reply_id},
        ).one()
    assert (state, by) == ("rejected", admin)


def test_moderation_revision_counts_the_text_versions_for_the_notice(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    """The notice dedupe key needs a revision that grows with every moderated text version."""
    admin = add_user(sm, Role.platform_admin)
    service = notification_service(sm)
    created = repo.create_review(w.student, completed(sm, w), stars=5, text="First words.")

    def moderate_and_notify(decision: str) -> int:
        outcome = repo.moderate_review(created.review_id, admin, decision)  # type: ignore[arg-type]
        send_after_commit(
            review_notices(
                kind="review",
                target_id=outcome.item_id,
                recipient_user_id=outcome.recipient_user_id,
                outcome=decision,  # type: ignore[arg-type]
                revision=outcome.revision,
            ),
            service=service,
            transport=RecordingPushTransport(),
        )
        return outcome.revision

    def notice_count() -> int:
        with sm() as session:
            return int(
                session.execute(
                    sa.select(sa.func.count())
                    .select_from(Notification)
                    .where(Notification.type == NotificationType.tutor_review)
                ).scalar_one()
            )

    assert moderate_and_notify("approved") == 0
    assert notice_count() == 1
    repo.update_review(
        w.student, created.review_id, stars=None, text="Second words.", clear_text=False
    )
    assert moderate_and_notify("approved") == 1
    assert notice_count() == 2  # the same outcome on edited text is a new event
    repo.update_review(
        w.student, created.review_id, stars=None, text="Third words.", clear_text=False
    )
    assert moderate_and_notify("rejected") == 2
    assert notice_count() == 3


def test_moderation_queue_is_oldest_first_filtered_and_paged(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    now = datetime.now(UTC)
    review_ids: list[uuid.UUID] = []
    for days, state in ((5, "pending"), (3, "pending"), (4, "approved"), (1, "none")):
        student = add_student(sm)
        review_ids.append(
            add_review_row(
                sm,
                booking=add_booking(sm, student=student, tutor=w.tutor, subject=w.subject),
                tutor_id=w.tutor.profile_id,
                student=student,
                text=None if state == "none" else f"text {days}",
                text_state=state,
                created_at=now - timedelta(days=days),
            )
        )
    gone_student = add_student(sm)
    removed_review = add_review_row(
        sm,
        booking=add_booking(sm, student=gone_student, tutor=w.tutor, subject=w.subject),
        tutor_id=w.tutor.profile_id,
        student=gone_student,
        text="removed text",
        text_state="pending",
        removed=True,
        created_at=now - timedelta(days=9),
    )
    # A reply to a removed review is never public, so it never needs a moderator.
    add_reply_row(
        sm,
        review=removed_review,
        tutor_id=w.tutor.profile_id,
        body="reply to removed",
        created_at=now - timedelta(days=8),
    )
    reply = add_reply_row(
        sm,
        review=review_ids[2],
        tutor_id=w.tutor.profile_id,
        body="reply text",
        created_at=now - timedelta(days=2),
    )

    everything = repo.moderation_page("all", after=None, limit=20)
    assert [(i.kind, i.text) for i in everything.items] == [
        ("review", "text 5"),
        ("review", "text 3"),
        ("reply", "reply text"),
    ]
    assert everything.items[2].item_id == reply
    assert [i.item_id for i in repo.moderation_page("review", after=None, limit=20).items] == [
        review_ids[0],
        review_ids[1],
    ]
    assert [i.kind for i in repo.moderation_page("reply", after=None, limit=20).items] == ["reply"]

    first = repo.moderation_page("all", after=None, limit=2)
    assert len(first.items) == 2
    assert first.next_key is not None
    second = repo.moderation_page("all", after=first.next_key, limit=2)
    assert [i.kind for i in second.items] == ["reply"]
    assert second.next_key is None
