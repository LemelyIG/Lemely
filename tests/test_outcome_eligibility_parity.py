"""The outcome SQL equals ``core.tutor_outcomes`` over generated inputs (F6, F9, F10; ADR-T04).

``lemely/db/tutor_outcomes_repo.py`` decides three things in SQL, and each is
checked here against the pure functions on facts written down in this module,
never read back through the code under test:

* **Which attempts may feed a figure**: the SQL mirror of
  ``is_outcome_eligible`` (origin, grade on the ladder, exact boundary, subject,
  not deleted), over every combination of those inputs and two ladders.
* **Who is in the cohort, and with what facts**: ``S`` as the start of the first
  counted session (``is_counted_session`` over every booking state and time
  position), and the facts behind ``CohortMember.eligible``, ``ever_granted``
  and ``recent_change`` (``is_member_eligible``, ``is_recent_change``) over
  every combination of verification, account age, counting choice, blocks and
  grants.
* **Which observations fall in the windows**: ``[S - 180 d, S + 120 d)`` in
  elapsed time. The session runs in ``Africa/Cairo`` and S is chosen so both
  window edges cross a clock change, where ``interval '120 days'`` (wall clock)
  and ``make_interval(secs => ...)`` (elapsed) disagree by an hour; the test
  first proves they disagree there.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.history import GRADE_ORDER
from lemely.core.tutor_outcomes import (
    BEFORE_LOOKBACK,
    DURING_WINDOW,
    AttemptFacts,
    CohortMember,
    is_counted_session,
    is_member_eligible,
    is_outcome_eligible,
    is_recent_change,
)
from lemely.db.models.enums import GrantRevokeReason
from lemely.db.models.tutoring import StudentTutoringPreferences, TutorDataGrant, TutoringBlock
from lemely.db.tutor_outcomes_repo import (
    CohortEntry,
    cohort_in_session,
    observations_in_session,
    outcome_eligible_attempt_sql,
)
from tests.test_tutor_outcomes_repo import (
    OTHER_SUBJECT,
    SUBJECT,
    add_attempt,
    add_booking_row,
    add_student_at,
    outcome_world,
    utc_now,
)
from tests.tutoring_db import add_tutor, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sqlalchemy.orm import Session, sessionmaker

    from tests.tutoring_db import SeededTutor

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
NINE_TO_ONE = ("9", "8", "7", "6", "5", "4", "3", "2", "1", "U")


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


def cohort(
    sm: sessionmaker[Session], tutor: SeededTutor, subjects: Sequence[str] = (SUBJECT,)
) -> tuple[datetime, list[CohortEntry]]:
    """The cohort statement and the database ``now()`` it was evaluated at (one transaction)."""
    with sm() as session:
        now = session.execute(sa.text("SELECT now()")).scalar_one()
        entries = cohort_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            tutor_user_id=tutor.user_id,
            subject_codes=subjects,
            now=now,
        )
    assert isinstance(now, datetime)
    return now, entries


# ---------------------------------------------------------------------------
# is_outcome_eligible
# ---------------------------------------------------------------------------

ORIGINS = ("past_paper", "quiz", "custom_paper")
GRADES: tuple[str | None, ...] = ("A*", "U", "9", "F", None)
BOUNDARIES: tuple[str | None, ...] = ("exact", "subject_default", "global_default", None)
SUBJECTS: tuple[str | None, ...] = (SUBJECT, OTHER_SUBJECT, None)


@pytest.mark.parametrize("ladder", [GRADE_ORDER, NINE_TO_ONE], ids=["a_star_to_u", "nine_to_one"])
def test_sql_attempt_eligibility_equals_core_over_generated_inputs(
    sm: sessionmaker[Session], ladder: Sequence[str]
) -> None:
    student = add_student_at(sm, created_at=utc_now() - 400 * DAY, verified_at=utc_now())
    expected: dict[uuid.UUID, bool] = {}
    recorded_at = utc_now() - 10 * DAY
    for origin, grade, boundary, subject, deleted in itertools.product(
        ORIGINS, GRADES, BOUNDARIES, SUBJECTS, (False, True)
    ):
        attempt = add_attempt(
            sm,
            student,
            grade=grade,
            recorded_at=recorded_at,
            subject=subject,
            origin=origin,
            boundary=boundary,
            deleted=deleted,
        )
        facts = AttemptFacts(
            origin=origin,
            grade=grade,
            boundary_source=boundary,
            subject_code=subject,
            deleted=deleted,
        )
        expected[attempt] = is_outcome_eligible(facts, subject_code=SUBJECT, ladder=ladder)

    fragment = outcome_eligible_attempt_sql("a", ":subject")
    with sm() as session:
        rows = session.execute(
            sa.text(
                f"SELECT a.id, COALESCE({fragment}, false) AS eligible "  # noqa: S608 - built from constants
                "FROM attempts a WHERE a.user_id = :u"
            ),
            {"u": student, "subject": SUBJECT, "ladder": list(ladder)},
        ).all()
    actual = {row.id: bool(row.eligible) for row in rows}
    assert actual == expected
    # Non-vacuity: every combination is present; exactly the two on-ladder grades of a
    # live, exact past paper in the subject are eligible.
    assert len(expected) == len(ORIGINS) * len(GRADES) * len(BOUNDARIES) * len(SUBJECTS) * 2
    assert len(expected) == 360
    assert sum(expected.values()) == 2


def test_attempt_fragment_refuses_unqualified_or_spliced_operands() -> None:
    for alias, subject in (
        ("a; DROP TABLE attempts", ":subject"),
        ("a", "subject_code"),
        ("a", "c.subject_code OR true"),
        ("a", "'0625'"),
    ):
        with pytest.raises(ValueError, match="must be"):
            outcome_eligible_attempt_sql(alias, subject)


# ---------------------------------------------------------------------------
# The cohort's facts: eligible, ever_granted, recent_change
# ---------------------------------------------------------------------------

VERIFICATION = ("never", "day_before", "at_start", "just_after")
AGE = ("old", "exactly_30_days", "a_second_short")
PREFS = ("none", "in_old", "out_old", "out_recent", "in_recent")
BLOCKS = (
    "none",
    "active_old",
    "removed_old",
    "recent",
    "removed_recent",  # created 10 days ago, removed 5 days ago: removal does not lift the hold
    "tutor_blocked_student",
    "other_tutor_blocked",  # the student's recent block of a *different* tutor: not this pair's
)
GRANTS = ("none", "live", "revoked")


@dataclass(frozen=True)
class Facts:
    start: datetime
    verified_at: datetime | None
    created_at: datetime
    opted_out: bool
    pref_changed_at: datetime | None
    student_block_created_at: datetime | None
    granted: bool


def _seed_student(
    sm: sessionmaker[Session],
    tutor: SeededTutor,
    other_tutor: SeededTutor,
    start: datetime,
    combo: tuple[str, str, str, str, str],
) -> tuple[uuid.UUID, Facts]:
    verification, age, prefs, block, grant = combo
    now = utc_now()
    verified_at = {
        "never": None,
        "day_before": start - DAY,
        "at_start": start,
        "just_after": start + timedelta(microseconds=1),
    }[verification]
    created_at = {
        "old": start - 400 * DAY,
        "exactly_30_days": start - 30 * DAY,
        "a_second_short": start - 30 * DAY + timedelta(seconds=1),
    }[age]
    student = add_student_at(sm, created_at=created_at, verified_at=verified_at)
    add_booking_row(sm, tutor, student, starts_at=start)
    opted_out, pref_changed_at = {
        "none": (False, None),
        "in_old": (False, now - 200 * DAY),
        "out_old": (True, now - 200 * DAY),
        "out_recent": (True, now - 10 * DAY),
        "in_recent": (False, now - 10 * DAY),
    }[prefs]
    student_block_created_at: datetime | None = None
    with sm.begin() as session:
        if prefs != "none":
            session.add(
                StudentTutoringPreferences(
                    user_id=student,
                    outcome_stats_opt_out=opted_out,
                    outcome_pref_changed_at=pref_changed_at,
                )
            )
        if block in ("active_old", "removed_old", "recent", "removed_recent"):
            student_block_created_at = now - (
                10 * DAY if block in ("recent", "removed_recent") else 200 * DAY
            )
            removed_at = {"removed_old": now - 150 * DAY, "removed_recent": now - 5 * DAY}.get(
                block
            )
            session.add(
                TutoringBlock(
                    blocker_user_id=student,
                    blocked_user_id=tutor.user_id,
                    created_at=student_block_created_at,
                    removed_at=removed_at,
                )
            )
        if block == "other_tutor_blocked":  # recent, but of another tutor: no fact for this pair
            session.add(
                TutoringBlock(
                    blocker_user_id=student,
                    blocked_user_id=other_tutor.user_id,
                    created_at=now - 10 * DAY,
                )
            )
        if block == "tutor_blocked_student":  # recent, but the tutor's: neither excludes nor holds
            session.add(
                TutoringBlock(
                    blocker_user_id=tutor.user_id,
                    blocked_user_id=student,
                    created_at=now - 10 * DAY,
                )
            )
        if grant != "none":
            session.add(
                TutorDataGrant(
                    student_id=student,
                    tutor_profile_id=tutor.profile_id,
                    created_at=now - 20 * DAY,
                    revoked_at=now - 19 * DAY if grant == "revoked" else None,
                    revoke_reason=GrantRevokeReason.student if grant == "revoked" else None,
                )
            )
    return student, Facts(
        start=start,
        verified_at=verified_at,
        created_at=created_at,
        opted_out=opted_out,
        pref_changed_at=pref_changed_at,
        student_block_created_at=student_block_created_at,
        granted=grant != "none",
    )


def test_sql_cohort_facts_equal_core_over_generated_inputs(sm: sessionmaker[Session]) -> None:
    tutor = outcome_world(sm)
    other_tutor = add_tutor(sm, subjects=(SUBJECT,))
    base = utc_now() - 150 * DAY
    seeded: dict[uuid.UUID, Facts] = {}
    block_grant_pairs: set[tuple[str, str]] = set()
    combos = itertools.product(VERIFICATION, AGE, PREFS, BLOCKS)
    for index, (verification, age, prefs, block) in enumerate(combos):
        # ``index % 3`` alone would equal ``block % 3`` (every other stride is a multiple of
        # 3), pairing each block with one grant kind; the second term breaks that.
        grant = GRANTS[(index + index // len(BLOCKS)) % len(GRANTS)]
        block_grant_pairs.add((block, grant))
        student, facts = _seed_student(
            sm,
            tutor,
            other_tutor,
            base - index * timedelta(minutes=5),
            (verification, age, prefs, block, grant),
        )
        seeded[student] = facts

    now, entries = cohort(sm, tutor)
    by_student = {entry.student_id: entry for entry in entries}
    assert set(by_student) == set(seeded)
    for student, facts in seeded.items():
        member = by_student[student].member
        assert by_student[student].subject_code == SUBJECT
        expected = CohortMember(
            ref=member.ref,
            first_session_start=facts.start,
            eligible=is_member_eligible(
                first_session_start=facts.start,
                email_verified_at=facts.verified_at,
                account_created_at=facts.created_at,
                opted_out=facts.opted_out,
                ever_blocked_tutor=facts.student_block_created_at is not None,
            ),
            ever_granted=facts.granted,
            recent_change=is_recent_change(
                now=now,
                outcome_pref_changed_at=facts.pref_changed_at,
                block_created_at=facts.student_block_created_at,
            ),
        )
        assert member == expected, (student, facts)

    # Non-vacuity: every combination is present and every flag takes both values.
    assert len(seeded) == len(VERIFICATION) * len(AGE) * len(PREFS) * len(BLOCKS) == 420
    # Every block kind meets every grant kind (the grant is not a function of the block).
    assert len(block_grant_pairs) == len(BLOCKS) * len(GRANTS)
    members = [entry.member for entry in entries]
    assert len({m.ref for m in members}) == len(members)  # refs are unique
    for flag in ("eligible", "ever_granted", "recent_change"):
        assert {getattr(m, flag) for m in members} == {True, False}, flag
    # Eligible by the ADR-T04 definition, counted from the dimensions above: verified by S
    # (day before, at start: 2) x 30 days old at S (old, exactly: 2) x counted (no row,
    # in_old, in_recent: 3) x never blocked the tutor (none, the tutor's own block, a block of
    # another tutor: 3).
    assert sum(m.eligible for m in members) == 2 * 2 * 3 * 3


# ---------------------------------------------------------------------------
# Membership: S is the start of the first counted session
# ---------------------------------------------------------------------------

#: Each case: the bookings of one student, ``(state, start offset from now, accepted, subject,
#: own tutor)``. The active ones (requested, accepted) of the one tutor never overlap, so the
#: exclusion constraints accept them.
CASES: dict[str, tuple[tuple[str, timedelta, bool, str, bool], ...]] = {
    "completed": (("completed", -150 * DAY, True, SUBJECT, True),),
    "no_show": (("no_show", -150 * DAY, True, SUBJECT, True),),
    "awaiting_outcome": (("accepted", -150 * DAY - 2 * HOUR, True, SUBJECT, True),),
    "accepted_not_started": (("accepted", 3 * DAY, True, SUBJECT, True),),
    "accepted_in_progress": (("accepted", -timedelta(minutes=30), True, SUBJECT, True),),
    "accepted_just_ended": (("accepted", -timedelta(minutes=121), True, SUBJECT, True),),
    "cancelled_after_accept": (("cancelled", -150 * DAY, True, SUBJECT, True),),
    "requested_start_passed": (("requested", -150 * DAY - 4 * HOUR, False, SUBJECT, True),),
    "declined": (("declined", -150 * DAY, False, SUBJECT, True),),
    "expired": (("expired", -150 * DAY, False, SUBJECT, True),),
    "cancelled_then_completed": (
        ("cancelled", -200 * DAY, True, SUBJECT, True),
        ("completed", -150 * DAY, True, SUBJECT, True),
    ),
    "completed_then_no_show": (
        ("no_show", -140 * DAY, True, SUBJECT, True),
        ("completed", -150 * DAY, True, SUBJECT, True),
    ),
    "other_subject_only": (("completed", -150 * DAY, True, OTHER_SUBJECT, True),),
    "both_subjects": (
        ("completed", -150 * DAY, True, SUBJECT, True),
        ("completed", -130 * DAY, True, OTHER_SUBJECT, True),
    ),
    "other_tutor_only": (("completed", -150 * DAY, True, SUBJECT, False),),
}


def test_sql_cohort_membership_and_first_session_equal_core(sm: sessionmaker[Session]) -> None:
    tutor = outcome_world(sm)
    other = add_tutor(sm, subjects=(SUBJECT,))
    now_py = utc_now()
    bookings: dict[uuid.UUID, list[tuple[str, datetime, bool, str, bool]]] = {}
    for plan in CASES.values():
        student = add_student_at(sm, created_at=now_py - 400 * DAY, verified_at=now_py - 300 * DAY)
        rows = []
        for state, delta, accepted, subject, own in plan:
            starts_at = now_py + delta
            add_booking_row(
                sm,
                tutor if own else other,
                student,
                starts_at=starts_at,
                state=state,
                subject=subject,
                accepted=accepted,
            )
            rows.append((state, starts_at, accepted, subject, own))
        bookings[student] = rows

    now, entries = cohort(sm, tutor, subjects=(SUBJECT, OTHER_SUBJECT))
    expected: dict[tuple[uuid.UUID, str], datetime] = {}
    for student, rows in bookings.items():
        for state, starts_at, accepted, subject, own in rows:
            counted = own and is_counted_session(
                state=state,
                accepted_at=starts_at - 7 * DAY if accepted else None,
                ends_at=starts_at + timedelta(hours=1),
                now=now,
            )
            if counted:
                key = (student, subject)
                expected[key] = min(expected.get(key, starts_at), starts_at)
    actual = {
        (entry.student_id, entry.subject_code): entry.member.first_session_start
        for entry in entries
    }
    assert actual == expected
    # Non-vacuity: members and non-members both occur, and S picked the earlier of two.
    names = list(CASES)
    students = list(bookings)
    assert 0 < len({student for student, _ in expected}) < len(students)
    first = students[names.index("completed_then_no_show")]
    assert expected[(first, SUBJECT)] == bookings[first][1][1]  # the completed one, 10 days earlier
    assert (students[names.index("both_subjects")], OTHER_SUBJECT) in expected
    assert len(expected) == 9


# ---------------------------------------------------------------------------
# Observation windows: elapsed time, not wall clock
# ---------------------------------------------------------------------------

#: S such that S + 120 days crosses Cairo's 29 October 2026 change and S - 180 days
#: crosses nothing but sits in winter time while S is in summer time.
WINDOW_START = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
MICRO = timedelta(microseconds=1)
HALF_HOUR = timedelta(minutes=30)


def test_observation_windows_are_elapsed_time_in_a_cairo_session(
    sm: sessionmaker[Session],
) -> None:
    s = WINDOW_START
    student = add_student_at(sm, created_at=s - 400 * DAY, verified_at=s - DAY)
    offsets = {
        "lookback_minus_1us": (-BEFORE_LOOKBACK - MICRO, False),
        "lookback_start": (-BEFORE_LOOKBACK, True),
        "lookback_plus_30m": (-BEFORE_LOOKBACK + HALF_HOUR, True),  # wall clock would drop it
        "start_minus_1us": (-MICRO, True),
        "start": (timedelta(0), True),
        "close_minus_1us": (DURING_WINDOW - MICRO, True),
        "close": (DURING_WINDOW, False),
        "close_plus_30m": (DURING_WINDOW + HALF_HOUR, False),  # wall clock would keep it
    }
    for offset, _ in offsets.values():
        add_attempt(sm, student, grade="B", recorded_at=s + offset)
    # In the window but estimated: the eligibility mirror runs inside the same statement.
    add_attempt(sm, student, grade="A", recorded_at=s, boundary="subject_default")

    entry = CohortEntry(
        subject_code=SUBJECT,
        student_id=student,
        member=CohortMember(
            ref=7, first_session_start=s, eligible=True, ever_granted=False, recent_change=False
        ),
    )
    with sm() as session:
        session.execute(sa.text("SET TIME ZONE 'Africa/Cairo'"))
        # Non-vacuity: in this session, at these instants, wall clock and elapsed time differ.
        wall_close, elapsed_close, wall_open, elapsed_open = session.execute(
            sa.text(
                "SELECT CAST(:s AS timestamptz) + interval '120 days', "
                "CAST(:s AS timestamptz) + make_interval(secs => :during), "
                "CAST(:s AS timestamptz) - interval '180 days', "
                "CAST(:s AS timestamptz) - make_interval(secs => :before)"
            ),
            {
                "s": s,
                "during": DURING_WINDOW.total_seconds(),
                "before": BEFORE_LOOKBACK.total_seconds(),
            },
        ).one()
        assert wall_close - elapsed_close == timedelta(hours=1)
        assert wall_open - elapsed_open == timedelta(hours=1)
        observations = observations_in_session(session, [entry])

    assert {o.ref for o in observations} == {7}
    assert {o.grade for o in observations} == {"B"}
    got = sorted(o.recorded_at for o in observations)
    want = sorted(s + offset for offset, inside in offsets.values() if inside)
    assert got == want
    assert len(want) == 5


def test_observations_statement_with_no_members_reads_nothing(
    sm: sessionmaker[Session],
) -> None:
    with sm() as session:
        assert observations_in_session(session, []) == []


def test_ineligible_members_are_listed_in_the_cohort(sm: sessionmaker[Session]) -> None:
    """An opted-out member is still a member: their recent change must be able to hide."""
    tutor = outcome_world(sm)
    start = utc_now() - 150 * DAY
    other_tutor = add_tutor(sm, subjects=(SUBJECT,))
    student, _ = _seed_student(
        sm, tutor, other_tutor, start, ("never", "old", "out_recent", "none", "none")
    )
    _, entries = cohort(sm, tutor)
    [entry] = entries
    assert entry.student_id == student
    assert (entry.member.eligible, entry.member.recent_change) == (False, True)
