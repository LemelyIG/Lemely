"""Outcome figures from the database (PLAN T19; SPEC §e.3, ADR-T04, SC-13, SC-14).

The pure rules are ``core.tutor_outcomes``'s and are tested there. This module
proves the SQL side of them on a real Postgres database: who the cohort is,
which attempts feed a figure, the 90-day hold, and the query budget.

**One test per exclusion (SPEC §e.3), each with its red case inside it.** Every
exclusion test starts from the same sufficient world (five closed, eligible
members), adds the one thing that must be left out, checks that the figures
did not move, and then turns that thing into its eligible twin and checks that
the figures *do* move. The second half is what makes the first half able to
fail: a fixture the figures could not see would pass the first half for the
wrong reason.

Times are relative to the real clock, because the repository reads the
database ``now()`` (one transaction, one instant). Members' first sessions sit
150 days back, so each window (120 days) has closed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.tutor_outcomes import OPT_CHANGE_HOLD, OUTCOME_K_MIN
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import (
    AttemptOrigin,
    BookingParty,
    BookingState,
    BoundarySource,
    GrantRevokeReason,
    Role,
    TutoringMode,
)
from lemely.db.models.tutoring import (
    StudentTutoringPreferences,
    TutorBooking,
    TutorDataGrant,
    TutoringBlock,
)
from lemely.db.models.users import User
from lemely.db.tutor_outcomes_repo import SubjectFigures, TutorOutcomes, TutorOutcomesRepository
from lemely.db.tutoring_preferences_repo import TutoringPreferencesRepository
from tests.tutoring_db import (
    SeededTutor,
    add_subject,
    add_tutor,
    count_statements,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from sqlalchemy.orm import Session, sessionmaker

SUBJECT = "0625"
OTHER_SUBJECT = "0620"
LINK = "https://meet.google.com/abc-defg-hij"
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
#: ``(before, during)`` grades of the five base members, in order of first session.
#: Distribution A 2, B 2, C 1 (largest bucket 2 <= 5 - 2); change higher 2, same 2,
#: lower 1 (largest 2 <= 3). Both figures are sufficient with exactly k members.
BASE_GRADES: tuple[tuple[str, str], ...] = (
    ("B", "A"),
    ("A", "A"),
    ("C", "B"),
    ("B", "B"),
    ("B", "C"),
)
BASE_BUCKETS = {"A*": 0, "A": 2, "B": 2, "C": 1, "D": 0, "E": 0, "U": 0}
BASE_CHANGE = (2, 2, 1)
#: The base buckets when member X (A* before and during, first to close) displaces
#: the last base member (during C).
WITH_X_BUCKETS = {"A*": 1, "A": 2, "B": 2, "C": 0, "D": 0, "E": 0, "U": 0}
WITH_X_CHANGE = (2, 3, 0)
_VERIFIED_DAY_BEFORE = object()


# ---------------------------------------------------------------------------
# Fixtures and seeding (imported by tests/test_web_tutoring_outcomes.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def repo(sm: sessionmaker[Session]) -> TutorOutcomesRepository:
    return TutorOutcomesRepository(sm)


def utc_now() -> datetime:
    return datetime.now(UTC)


def closed_base() -> datetime:
    """A first-session start whose 120-day window closed 30 days ago."""
    return utc_now() - timedelta(days=150)


def add_student_at(
    sm: sessionmaker[Session], *, created_at: datetime, verified_at: datetime | None
) -> uuid.UUID:
    student = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=student,
                email=f"{student}@example.com",
                role=Role.student,
                email_verified_at=verified_at,
                created_at=created_at,
            )
        )
    return student


def add_booking_row(
    sm: sessionmaker[Session],
    tutor: SeededTutor,
    student: uuid.UUID,
    *,
    starts_at: datetime,
    state: str = "completed",
    subject: str = SUBJECT,
    accepted: bool = True,
) -> uuid.UUID:
    """One virtual booking in ``state``, coherent with every ``ck_tutor_bookings_*`` CHECK."""
    booking_state = BookingState(state)
    fields: dict[str, object] = {}
    if accepted:
        fields["accepted_at"] = starts_at - 7 * DAY
        fields["meeting_link"] = LINK
    if booking_state is BookingState.completed:
        fields["completed_at"] = starts_at + HOUR
        fields["completed_by_party"] = BookingParty.tutor
    if booking_state is BookingState.no_show:
        fields["no_show_marked_at"] = starts_at + HOUR
    if booking_state is BookingState.cancelled:
        fields["cancelled_at"] = starts_at - 2 * DAY
        fields["cancelled_by_party"] = BookingParty.student
    if booking_state is BookingState.declined:
        fields["declined_at"] = starts_at - 2 * DAY
    if booking_state is BookingState.expired:
        fields["expired_at"] = starts_at
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
                ends_at=starts_at + HOUR,
                state=booking_state,
                **fields,
            )
        )
    return booking_id


def add_attempt(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    *,
    grade: str | None,
    recorded_at: datetime,
    subject: str | None = SUBJECT,
    origin: str = "past_paper",
    boundary: str | None = "exact",
    deleted: bool = False,
) -> uuid.UUID:
    attempt_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Attempt(
                id=attempt_id,
                user_id=student,
                subject_code=subject,
                awarded_marks=50,
                maximum_marks=80,
                percentage=62.5,
                grade=grade,
                boundary_source=BoundarySource(boundary) if boundary is not None else None,
                recorded_at=recorded_at,
                origin=AttemptOrigin(origin),
                deleted_at=recorded_at + HOUR if deleted else None,
            )
        )
    return attempt_id


@dataclass(frozen=True)
class Member:
    student: uuid.UUID
    start: datetime
    booking: uuid.UUID


def add_member(
    sm: sessionmaker[Session],
    tutor: SeededTutor,
    *,
    start: datetime,
    before: str | None,
    during: str | None,
    state: str = "completed",
    subject: str = SUBJECT,
    created_at: datetime | None = None,
    verified_at: datetime | None | object = _VERIFIED_DAY_BEFORE,
) -> Member:
    """A student with one counted session starting at ``start`` (S) and two exact grades.

    The account is 400 days old at S and verified a day before it, unless told
    otherwise. The before grade is recorded 30 days before S, the during grade 30
    days after.
    """
    verified = start - DAY if verified_at is _VERIFIED_DAY_BEFORE else verified_at
    assert verified is None or isinstance(verified, datetime)
    student = add_student_at(
        sm,
        created_at=created_at if created_at is not None else start - timedelta(days=400),
        verified_at=verified,
    )
    booking = add_booking_row(sm, tutor, student, starts_at=start, state=state, subject=subject)
    if before is not None:
        add_attempt(sm, student, grade=before, recorded_at=start - 30 * DAY, subject=subject)
    if during is not None:
        add_attempt(sm, student, grade=during, recorded_at=start + 30 * DAY, subject=subject)
    return Member(student=student, start=start, booking=booking)


def five_members(
    sm: sessionmaker[Session],
    tutor: SeededTutor,
    *,
    base: datetime | None = None,
    subject: str = SUBJECT,
    states: Sequence[str] = ("completed",) * 5,
) -> list[Member]:
    """The base cohort: five closed, eligible members with :data:`BASE_GRADES`."""
    first = base if base is not None else closed_base()
    return [
        add_member(
            sm,
            tutor,
            start=first + index * HOUR,
            before=before,
            during=during,
            subject=subject,
            state=state,
        )
        for index, ((before, during), state) in enumerate(zip(BASE_GRADES, states, strict=True))
    ]


def outcome_world(sm: sessionmaker[Session], **tutor_kwargs: object) -> SeededTutor:
    """A listed tutor of 0625 (Physics) and 0620 (Chemistry); no cohort yet."""
    add_subject(sm, code=SUBJECT, name="Physics")
    add_subject(sm, code=OTHER_SUBJECT, name="Chemistry")
    return add_tutor(sm, subjects=(SUBJECT, OTHER_SUBJECT), **tutor_kwargs)  # type: ignore[arg-type]


def read(repo: TutorOutcomesRepository, tutor: SeededTutor) -> TutorOutcomes:
    """SP4 for a student with no block: the tutor is listed, so this is never ``None``."""
    outcomes = repo.outcomes_for_viewer(tutor.profile_id, uuid.uuid4(), Role.student)
    assert outcomes is not None
    return outcomes


def figures(outcomes: TutorOutcomes, subject: str = SUBJECT) -> SubjectFigures:
    [found] = [item for item in outcomes.subjects if item.subject.code == subject]
    return found


def buckets(item: SubjectFigures) -> Mapping[str, int]:
    return {bucket.grade: bucket.count for bucket in item.outcome.distribution.buckets}


def change(item: SubjectFigures) -> tuple[int | None, int | None, int | None]:
    c = item.outcome.change
    return (c.higher, c.same, c.lower)


def assert_base(item: SubjectFigures) -> None:
    assert item.outcome.distribution.state == "sufficient", item
    assert dict(buckets(item)) == BASE_BUCKETS
    assert item.outcome.distribution.n_graded == OUTCOME_K_MIN
    assert item.outcome.distribution.n_without_grade == 0
    assert item.outcome.change.state == "sufficient", item
    assert change(item) == BASE_CHANGE


def assert_with_x(item: SubjectFigures) -> None:
    assert item.outcome.distribution.state == "sufficient", item
    assert dict(buckets(item)) == WITH_X_BUCKETS
    assert item.outcome.change.state == "sufficient", item
    assert change(item) == WITH_X_CHANGE


def assert_hidden(item: SubjectFigures) -> None:
    """Both figures insufficient, every count withheld (the 90-day hold)."""
    dist, chg = item.outcome.distribution, item.outcome.change
    assert (dist.state, dist.n_graded, dist.n_without_grade, dist.buckets) == (
        "insufficient",
        None,
        None,
        (),
    )
    assert (chg.state, chg.n_paired, chg.higher, chg.same, chg.lower) == (
        "insufficient",
        None,
        None,
        None,
        None,
    )


def execute(sm: sessionmaker[Session], sql: str, **params: object) -> None:
    with sm.begin() as session:
        session.execute(sa.text(sql), params)


def x_member(sm: sessionmaker[Session], tutor: SeededTutor, **kwargs: object) -> Member:
    """Member X: first to close (a day before the base), A* before and during."""
    return add_member(
        sm,
        tutor,
        start=closed_base() - DAY,
        before="A*",
        during="A*",
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# The base world
# ---------------------------------------------------------------------------


def test_base_world_is_sufficient_and_counts_each_member_once(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    outcomes = read(repo, tutor)
    assert outcomes.tutor_id == tutor.profile_id
    assert outcomes.ladder == ("A*", "A", "B", "C", "D", "E", "U")
    # Subjects are the tutor's, by name: Chemistry has no cohort and reads insufficient.
    assert [item.subject.code for item in outcomes.subjects] == [OTHER_SUBJECT, SUBJECT]
    assert_base(figures(outcomes))
    assert figures(outcomes, OTHER_SUBJECT).outcome.distribution.state == "insufficient"


def test_awaiting_outcome_and_no_show_sessions_count_like_completed_ones(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    """Membership is ``accepted_at IS NOT NULL``, never the tutor's outcome mark (F1)."""
    tutor = outcome_world(sm)
    five_members(sm, tutor, states=("completed", "accepted", "no_show", "accepted", "completed"))
    assert_base(figures(read(repo, tutor)))


def test_cancelled_declined_expired_and_unended_sessions_never_count(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    tutor = outcome_world(sm)
    members = five_members(sm, tutor)
    assert_base(figures(read(repo, tutor)))
    # X would close first and displace the last base member (C) if any of these counted.
    start = closed_base() - DAY
    for state, accepted in (
        ("cancelled", True),  # accepted, then cancelled before the start
        ("declined", False),
        ("expired", False),
        ("requested", False),  # a request whose start passed: effective expired
    ):
        x = add_student_at(sm, created_at=start - timedelta(days=400), verified_at=start - DAY)
        add_booking_row(sm, tutor, x, starts_at=start, state=state, accepted=accepted)
        add_attempt(sm, x, grade="A*", recorded_at=start - 30 * DAY)
        add_attempt(sm, x, grade="A*", recorded_at=start + 30 * DAY)
        start -= HOUR
    # An accepted session that has not ended yet.
    future = utc_now() + 3 * DAY
    y = add_student_at(sm, created_at=future - timedelta(days=400), verified_at=future - 9 * DAY)
    add_booking_row(sm, tutor, y, starts_at=future, state="accepted")
    assert_base(figures(read(repo, tutor)))
    # Red case: the same kind of student with one accepted, ended session does count.
    x_member(sm, tutor, state="accepted")
    assert_with_x(figures(read(repo, tutor)))
    assert members  # the base members are untouched


# ---------------------------------------------------------------------------
# One test per exclusion (SPEC §e.3)
# ---------------------------------------------------------------------------


def _attempt_exclusion(
    sm: sessionmaker[Session],
    repo: TutorOutcomesRepository,
    *,
    make_eligible: str,
    eligible_params: Mapping[str, object] | None = None,
    **attempt: object,
) -> None:
    """Add an A* to the last member's window that must be left out, then make it count."""
    tutor = outcome_world(sm)
    members = five_members(sm, tutor)
    assert_base(figures(read(repo, tutor)))
    last = members[-1]
    attempt_id = add_attempt(
        sm,
        last.student,
        grade=attempt.pop("grade", "A*"),  # type: ignore[arg-type]
        recorded_at=last.start + 60 * DAY,  # later than its during C: it would be the latest
        **attempt,  # type: ignore[arg-type]
    )
    assert_base(figures(read(repo, tutor)))
    # Red case: the eligible twin of the same row moves both figures.
    execute(sm, make_eligible, a=attempt_id, **(eligible_params or {}))
    moved = figures(read(repo, tutor))
    assert buckets(moved)["A*"] == 1
    assert buckets(moved)["C"] == 0
    assert change(moved) == (3, 2, 0)


def test_excludes_deleted_attempt(sm: sessionmaker[Session], repo: TutorOutcomesRepository) -> None:
    _attempt_exclusion(
        sm, repo, deleted=True, make_eligible="UPDATE attempts SET deleted_at = NULL WHERE id = :a"
    )


def test_excludes_custom_paper_attempt(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    _attempt_exclusion(
        sm,
        repo,
        origin="custom_paper",
        make_eligible="UPDATE attempts SET origin = 'past_paper' WHERE id = :a",
    )


def test_excludes_quiz_attempt(sm: sessionmaker[Session], repo: TutorOutcomesRepository) -> None:
    # A real quiz row has no grade; this one carries one so only ``origin`` can keep it out.
    _attempt_exclusion(
        sm,
        repo,
        origin="quiz",
        make_eligible="UPDATE attempts SET origin = 'past_paper' WHERE id = :a",
    )


def test_excludes_other_subject_attempt(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    _attempt_exclusion(
        sm,
        repo,
        subject=OTHER_SUBJECT,
        make_eligible="UPDATE attempts SET subject_code = :s WHERE id = :a",
        eligible_params={"s": SUBJECT},
    )


@pytest.mark.parametrize("boundary", ["subject_default", "global_default"])
def test_excludes_estimated_boundary_attempt(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository, boundary: str
) -> None:
    _attempt_exclusion(
        sm,
        repo,
        boundary=boundary,
        make_eligible="UPDATE attempts SET boundary_source = 'exact' WHERE id = :a",
    )


def test_excludes_off_ladder_grade(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    _attempt_exclusion(
        sm, repo, grade="9", make_eligible="UPDATE attempts SET grade = 'A*' WHERE id = :a"
    )


def test_excludes_opted_out_student(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    x = x_member(sm, tutor)
    long_ago = utc_now() - timedelta(days=200)  # outside the 90-day hold
    with sm.begin() as session:
        session.add(
            StudentTutoringPreferences(
                user_id=x.student, outcome_stats_opt_out=True, outcome_pref_changed_at=long_ago
            )
        )
    assert_base(figures(read(repo, tutor)))
    # Red case: counted again (the change is just as old, so no hold).
    execute(
        sm,
        "UPDATE student_tutoring_preferences SET outcome_stats_opt_out = false WHERE user_id = :u",
        u=x.student,
    )
    assert_with_x(figures(read(repo, tutor)))


def test_excludes_student_who_ever_blocked_tutor(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    """Any block from the student to the tutor's user, removed ones included (row 13)."""
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    x = x_member(sm, tutor)
    long_ago = utc_now() - timedelta(days=200)
    with sm.begin() as session:
        session.add(
            TutoringBlock(
                blocker_user_id=x.student,
                blocked_user_id=tutor.user_id,
                created_at=long_ago,
                removed_at=long_ago + DAY,
            )
        )
    assert_base(figures(read(repo, tutor)))  # a removed block still excludes
    execute(
        sm, "UPDATE tutoring_blocks SET removed_at = NULL WHERE blocker_user_id = :u", u=x.student
    )
    assert_base(figures(read(repo, tutor)))  # and so does an active one
    # Red case: a block the *tutor* made (direction tutor -> student) excludes nothing.
    execute(sm, "DELETE FROM tutoring_blocks WHERE blocker_user_id = :u", u=x.student)
    with sm.begin() as session:
        session.add(
            TutoringBlock(
                blocker_user_id=tutor.user_id,
                blocked_user_id=x.student,
                created_at=long_ago,
                removed_at=long_ago + DAY,
            )
        )
    assert_with_x(figures(read(repo, tutor)))


def test_excludes_unverified_student(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    """Verified by S (the first verification): never verified, or first verified after S, is out."""
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    x = x_member(sm, tutor, verified_at=None)
    assert_base(figures(read(repo, tutor)))
    execute(
        sm,
        "UPDATE users SET email_verified_at = :t WHERE id = :u",
        t=x.start + timedelta(microseconds=1),
        u=x.student,
    )
    assert_base(figures(read(repo, tutor)))
    # Red case: verified exactly at S counts (``email_verified_at <= S``).
    execute(sm, "UPDATE users SET email_verified_at = :t WHERE id = :u", t=x.start, u=x.student)
    assert_with_x(figures(read(repo, tutor)))


def test_excludes_account_too_new(sm: sessionmaker[Session], repo: TutorOutcomesRepository) -> None:
    """At least 30 days old at S, in elapsed time."""
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    start = closed_base() - DAY
    x = x_member(sm, tutor, created_at=start - timedelta(days=30) + timedelta(seconds=1))
    assert_base(figures(read(repo, tutor)))
    # Red case: exactly 30 days old at S counts.
    execute(
        sm,
        "UPDATE users SET created_at = :t WHERE id = :u",
        t=x.start - timedelta(days=30),
        u=x.student,
    )
    assert_with_x(figures(read(repo, tutor)))


# ---------------------------------------------------------------------------
# The 90-day hold (SC-13d)
# ---------------------------------------------------------------------------

HOLD_SECONDS = OPT_CHANGE_HOLD.total_seconds()


def shift_pref_change(sm: sessionmaker[Session], student: uuid.UUID, ago_seconds: float) -> None:
    execute(
        sm,
        "UPDATE student_tutoring_preferences "
        "SET outcome_pref_changed_at = now() - make_interval(secs => :s) WHERE user_id = :u",
        s=ago_seconds,
        u=student,
    )


def test_opt_out_hides_both_figures_for_90_days_then_leaves_the_student_out(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    x = x_member(sm, tutor)
    assert_with_x(figures(read(repo, tutor)))
    prefs = TutoringPreferencesRepository(sm)
    # A student with no session with this tutor changing their choice hides nothing.
    stranger = add_student_at(sm, created_at=utc_now() - 400 * DAY, verified_at=utc_now() - DAY)
    prefs.set_opt_out(stranger, True)
    assert_with_x(figures(read(repo, tutor)))

    prefs.set_opt_out(x.student, True)
    assert_hidden(figures(read(repo, tutor)))  # the very next read: nothing is cached
    shift_pref_change(sm, x.student, HOLD_SECONDS - 60)
    assert_hidden(figures(read(repo, tutor)))
    shift_pref_change(sm, x.student, HOLD_SECONDS + 60)
    assert_base(figures(read(repo, tutor)))  # shown again, without X


def test_opt_in_hides_both_figures_for_90_days_then_counts_the_student(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    x = x_member(sm, tutor)
    prefs = TutoringPreferencesRepository(sm)
    prefs.set_opt_out(x.student, True)
    shift_pref_change(sm, x.student, 200 * 86400)
    assert_base(figures(read(repo, tutor)))

    prefs.set_opt_out(x.student, False)
    assert_hidden(figures(read(repo, tutor)))
    shift_pref_change(sm, x.student, HOLD_SECONDS - 60)
    assert_hidden(figures(read(repo, tutor)))
    shift_pref_change(sm, x.student, HOLD_SECONDS + 60)
    assert_with_x(figures(read(repo, tutor)))


def test_student_block_hides_both_figures_for_90_days_then_leaves_the_student_out(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    x = x_member(sm, tutor)
    assert_with_x(figures(read(repo, tutor)))
    with sm.begin() as session:
        session.add(TutoringBlock(blocker_user_id=x.student, blocked_user_id=tutor.user_id))
    assert_hidden(figures(read(repo, tutor)))
    shift = (
        "UPDATE tutoring_blocks SET created_at = now() - make_interval(secs => :s) "
        "WHERE blocker_user_id = :u"
    )
    execute(sm, shift, s=HOLD_SECONDS - 60, u=x.student)
    assert_hidden(figures(read(repo, tutor)))
    execute(sm, shift, s=HOLD_SECONDS + 60, u=x.student)
    assert_base(figures(read(repo, tutor)))


def test_a_recent_change_hides_only_the_subjects_the_student_is_in(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    five_members(sm, tutor, subject=OTHER_SUBJECT, base=closed_base() + DAY)
    x = x_member(sm, tutor)  # a member in Physics only
    TutoringPreferencesRepository(sm).set_opt_out(x.student, True)
    outcomes = read(repo, tutor)
    assert_hidden(figures(outcomes, SUBJECT))
    assert_base(figures(outcomes, OTHER_SUBJECT))


# ---------------------------------------------------------------------------
# Grants, visibility and the query budget
# ---------------------------------------------------------------------------


def test_never_granted_count_between_1_and_k_minus_1_hides_the_figures(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    """``ever_granted`` reads ``tutor_data_grants``, live or revoked (SC-14 i)."""
    tutor = outcome_world(sm)
    members = five_members(sm, tutor)
    assert_base(figures(read(repo, tutor)))  # 5 never granted: shown

    def grant(student: uuid.UUID, *, revoked: bool) -> None:
        created = utc_now() - 10 * DAY
        with sm.begin() as session:
            session.add(
                TutorDataGrant(
                    student_id=student,
                    tutor_profile_id=tutor.profile_id,
                    created_at=created,
                    revoked_at=created + DAY if revoked else None,
                    revoke_reason=GrantRevokeReason.student if revoked else None,
                )
            )

    for member in members[:4]:
        grant(member.student, revoked=False)
    item = figures(read(repo, tutor))  # 1 never granted: hidden
    assert item.outcome.distribution.state == "insufficient"
    assert item.outcome.change.state == "insufficient"
    grant(members[4].student, revoked=True)  # a revoked grant still counts as granted
    assert_base(figures(read(repo, tutor)))  # 0 never granted: shown


def test_outcomes_for_viewer_hides_unlisted_paused_and_blocked_tutors(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    tutor = outcome_world(sm)
    student = add_student_at(sm, created_at=utc_now() - 400 * DAY, verified_at=utc_now())
    assert repo.outcomes_for_viewer(tutor.profile_id, student, Role.student) is not None
    assert repo.outcomes_for_viewer(uuid.uuid4(), student, Role.student) is None
    with sm.begin() as session:
        session.add(TutoringBlock(blocker_user_id=tutor.user_id, blocked_user_id=student))
    assert repo.outcomes_for_viewer(tutor.profile_id, student, Role.student) is None
    # Parents hold no blocks (SPEC §b.2 SP1): the student's block does not hide it from one.
    assert repo.outcomes_for_viewer(tutor.profile_id, uuid.uuid4(), Role.parent) is not None
    execute(sm, "UPDATE tutor_profiles SET paused_at = now() WHERE id = :t", t=tutor.profile_id)
    assert repo.outcomes_for_viewer(tutor.profile_id, uuid.uuid4(), Role.parent) is None


def test_query_budget_outcomes_three_statements(
    sm: sessionmaker[Session], repo: TutorOutcomesRepository
) -> None:
    """SPEC §e.3: profile check + subject names, cohort, observations; whatever the row count."""
    small = outcome_world(sm)
    five_members(sm, small)
    large = add_tutor(sm, subjects=(SUBJECT, OTHER_SUBJECT))
    five_members(sm, large)
    five_members(sm, large, subject=OTHER_SUBJECT, base=closed_base() + DAY)
    five_members(sm, large, base=closed_base() + 2 * DAY)

    counts = []
    for tutor in (small, large):
        with count_statements(sm) as seen:
            item = figures(read(repo, tutor))
        assert item.outcome.distribution.state == "sufficient"  # every statement ran
        counts.append(len(seen))
    assert counts == [3, 3]

    # T8's preview: the profile view (two statements) then the same three.
    with count_statements(sm) as seen:
        preview = repo.preview(large.profile_id)
    assert preview is not None
    assert preview.outcomes is not None
    assert len(seen) == 5

    # A hidden tutor stops after the profile check; a draft's preview after its profile.
    execute(sm, "UPDATE tutor_profiles SET paused_at = now() WHERE id = :t", t=small.profile_id)
    with count_statements(sm) as seen:
        assert repo.outcomes_for_viewer(small.profile_id, uuid.uuid4(), Role.parent) is None
    assert len(seen) == 1
    draft = add_tutor(sm, state="draft", subjects=(SUBJECT,))
    with count_statements(sm) as seen:
        preview = repo.preview(draft.profile_id)
    assert preview is not None
    assert preview.outcomes is None
    assert len(seen) == 3
