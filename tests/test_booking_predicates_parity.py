"""The booking SQL predicates agree with ``core.booking`` over generated inputs (SPEC §a.3, F6).

Four predicates, each evaluated by Postgres and by the pure core over the same generated rows,
inside one transaction so ``now()`` is one instant on both sides:

* every compare-and-set guard (``booking_repo.transition_guard_sql``) against
  ``core.booking.check_transition`` for its action and party;
* every effective-state fragment (``tutoring_predicates.EFFECTIVE_STATE_SQL``) as the booking
  lists filter by it (T9 ``state``) against ``core.booking.effective_state``;
* the upcoming/past split of S1, T9 and PA1 (``booking_repo.BOOKING_WHEN_SQL``) against SPEC
  §b.2 S1 read with ``effective_state``;
* the live pending count behind ``MAX_PENDING_PER_STUDENT`` against counting live requests in
  Python.

The generated rows sit on every boundary the rules have: exactly 24 hours before the start, the
start itself, the end itself and exactly 48 hours after the end.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.booking import (
    CANCEL_CUTOFF,
    OUTCOME_CLAIM_AFTER,
    BookingFacts,
    check_transition,
    effective_state,
)
from lemely.db.booking_repo import (
    BOOKING_WHEN_SQL,
    GUARD_BINDS,
    live_pending_count_in_session,
    transition_guard_sql,
)
from lemely.db.tutoring_predicates import EFFECTIVE_STATE_SQL
from tests.test_booking_repo import add_booking, add_student, another_tutor, make_world
from tests.tutoring_db import emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sqlalchemy.orm import Session, sessionmaker

STATES = ("requested", "accepted", "declined", "cancelled", "completed", "no_show", "expired")
ACTOR_PARENT = uuid.UUID("20000000-0000-4000-8000-000000000001")
OTHER_PARENT = uuid.UUID("20000000-0000-4000-8000-000000000002")
STUDENT = uuid.UUID("20000000-0000-4000-8000-000000000003")
SESSION_LENGTH = timedelta(hours=1)
SECOND = timedelta(seconds=1)

#: Start offsets from now (the session lasts an hour), chosen to sit on and beside every boundary.
STARTS_IN = (
    timedelta(days=3),
    CANCEL_CUTOFF + SECOND,
    CANCEL_CUTOFF,
    CANCEL_CUTOFF - SECOND,
    timedelta(hours=10),
    SECOND,
    timedelta(0),  # starts now
    -timedelta(minutes=10),  # in progress
    -SESSION_LENGTH,  # ends now
    -SESSION_LENGTH - timedelta(hours=1),
    -SESSION_LENGTH - OUTCOME_CLAIM_AFTER + SECOND,
    -SESSION_LENGTH - OUTCOME_CLAIM_AFTER,  # ended exactly 48 hours ago
    -SESSION_LENGTH - OUTCOME_CLAIM_AFTER - SECOND,
    -timedelta(days=9),
)
REQUESTERS = (("student", STUDENT), ("parent", ACTOR_PARENT), ("parent", OTHER_PARENT))
GUARDED = (
    ("accept", "tutor"),
    ("decline", "tutor"),
    ("cancel", "student"),
    ("cancel", "parent"),
    ("cancel", "tutor"),
    ("cancel", "platform_admin"),
    ("cancel", "system"),
    ("complete", "tutor"),
    ("no_show", "tutor"),
    ("complete", "platform_admin"),
    ("claim_complete", "student"),
    ("claim_complete", "parent"),
    ("expire", "system"),
)
REASONS = (None, "", "   ", "Unwell")


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


Row = tuple[int, str, datetime, datetime, str, uuid.UUID]


def generated_rows(now: datetime) -> list[Row]:
    rows: list[Row] = []
    for index, (state, offset, (party, requester)) in enumerate(
        itertools.product(STATES, STARTS_IN, REQUESTERS)
    ):
        starts_at = now + offset
        rows.append((index, state, starts_at, starts_at + SESSION_LENGTH, party, requester))
    return rows


def evaluate(
    session: Session, fragment: str, rows: Sequence[Row], params: dict[str, object]
) -> dict[int, bool]:
    """``fragment`` over the rows, as a relation aliased ``b`` with the booking column names."""
    result = session.execute(
        sa.text(
            f"SELECT b.id, COALESCE(({fragment}), false) AS holds FROM unnest("  # noqa: S608 - test fragments
            "CAST(:ids AS int[]), CAST(:states AS text[]), CAST(:starts AS timestamptz[]), "
            "CAST(:ends AS timestamptz[]), CAST(:parties AS text[]), CAST(:requesters AS uuid[])"
            ") AS b(id, state, starts_at, ends_at, requested_by_party, requested_by_user_id)"
        ),
        {
            "ids": [row[0] for row in rows],
            "states": [row[1] for row in rows],
            "starts": [row[2] for row in rows],
            "ends": [row[3] for row in rows],
            "parties": [row[4] for row in rows],
            "requesters": [row[5] for row in rows],
            **params,
        },
    ).all()
    return {int(row_id): bool(holds) for row_id, holds in result}


def db_now(session: Session) -> datetime:
    value = session.execute(sa.select(sa.func.now())).scalar_one()
    assert isinstance(value, datetime)
    return value


def test_transition_guards_match_check_transition(sm: sessionmaker[Session]) -> None:
    compared = 0
    with sm.begin() as session:
        now = db_now(session)
        rows = generated_rows(now)
        for (action, party), reason in itertools.product(GUARDED, REASONS):
            sql = evaluate(
                session,
                transition_guard_sql(action, party),  # type: ignore[arg-type]
                rows,
                {**GUARD_BINDS, "actor_id": ACTOR_PARENT, "reason": reason},
            )
            outcomes = set()
            for row_id, state, starts_at, ends_at, requested_party, requester in rows:
                facts = BookingFacts(
                    state=state,  # type: ignore[arg-type]
                    starts_at=starts_at,
                    ends_at=ends_at,
                    viewer=party,  # type: ignore[arg-type]
                    viewer_is_requester=(requested_party == "parent" and requester == ACTOR_PARENT),
                    tutor_outcome_recorded=state in {"completed", "no_show"},
                )
                has_reason = reason is not None and bool(reason.strip())
                core = check_transition(action, facts, now=now, has_reason=has_reason) is None  # type: ignore[arg-type]
                assert sql[row_id] is core, (action, party, reason, state, starts_at - now)
                outcomes.add(core)
                compared += 1
            assert outcomes == {True, False}, (action, party, reason)  # each guard can go both ways
    assert compared == len(GUARDED) * len(REASONS) * len(STATES) * len(STARTS_IN) * len(REQUESTERS)


def test_every_guard_rejects_actions_the_core_never_allows() -> None:
    for action, party in (
        ("accept", "student"),
        ("decline", "parent"),
        ("no_show", "platform_admin"),
    ):
        with pytest.raises(ValueError, match="no compare-and-set guard"):
            transition_guard_sql(action, party)  # type: ignore[arg-type]


def test_effective_state_filters_match_core(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        now = db_now(session)
        rows = generated_rows(now)
        seen: dict[str, int] = {}
        for name, fragment in EFFECTIVE_STATE_SQL.items():
            sql = evaluate(session, fragment, rows, {})
            for row_id, state, starts_at, ends_at, _, _ in rows:
                core = effective_state(state, starts_at=starts_at, ends_at=ends_at, now=now)  # type: ignore[arg-type]
                assert sql[row_id] is (core == name), (name, state, starts_at - now)
            seen[name] = sum(sql.values())
    assert set(seen) == {*STATES, "awaiting_outcome"}  # non-vacuity: all eight effective states
    assert all(count > 0 for count in seen.values()), seen


def test_upcoming_and_past_split_matches_spec_s1(sm: sessionmaker[Session]) -> None:
    """S1: upcoming = effective requested/accepted/awaiting_outcome with ``ends_at > split``."""
    with sm.begin() as session:
        now = db_now(session)
        rows = generated_rows(now)
        for split in (now, now - timedelta(hours=2), now + timedelta(days=1)):
            upcoming = evaluate(session, BOOKING_WHEN_SQL["upcoming"], rows, {"split": split})
            past = evaluate(session, BOOKING_WHEN_SQL["past"], rows, {"split": split})
            for row_id, state, starts_at, ends_at, _, _ in rows:
                live = effective_state(state, starts_at=starts_at, ends_at=ends_at, now=now) in {  # type: ignore[arg-type]
                    "requested",
                    "accepted",
                    "awaiting_outcome",
                }
                expected = live and ends_at > split
                assert upcoming[row_id] is expected, (state, starts_at - now, split - now)
                assert past[row_id] is not expected
            assert 0 < sum(upcoming.values()) < len(rows)
    assert set(BOOKING_WHEN_SQL) == {"upcoming", "past"}


def test_live_pending_count_matches_core(sm: sessionmaker[Session]) -> None:
    w = make_world(sm)
    expected = 0
    offsets = (
        timedelta(days=2),
        timedelta(hours=3),
        timedelta(minutes=1),
        -timedelta(minutes=1),
        -timedelta(days=2),
    )
    # One tutor per booking (the one-pending index is per pair) and four hours between any two
    # of the student's bookings (the student-slot exclusion), on either side of now.
    for index, (state, offset) in enumerate(itertools.product(STATES, offsets)):
        spread = timedelta(hours=4 * index)
        add_booking(
            sm,
            w,
            tutor=another_tutor(sm, w.subject),
            state=state,
            starts_in=offset + spread if offset > timedelta(0) else offset - spread,
        )
    with sm.begin() as session:
        now = db_now(session)
        stored = session.execute(
            sa.text(
                "SELECT state::text, starts_at, ends_at FROM tutor_bookings WHERE student_id = :s"
            ),
            {"s": w.student},
        ).all()
        for state, starts_at, ends_at in stored:
            if effective_state(state, starts_at=starts_at, ends_at=ends_at, now=now) == "requested":
                expected += 1
        assert live_pending_count_in_session(session, w.student) == expected
    assert len(stored) == len(STATES) * len(offsets)
    assert 0 < expected < len(stored)  # non-vacuity: some counted, some not
    other = add_student(sm)
    with sm.begin() as session:
        assert live_pending_count_in_session(session, other) == 0
