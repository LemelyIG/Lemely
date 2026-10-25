"""The shared tutoring SQL predicates, evaluated in Postgres (PLAN §1.4 #9, SPEC §a.3, O11).

Runs against a ``create_all`` database: ``test_db_tutoring_schema.py`` already
proves that schema identical to the migrated one. Each test works inside one
rolled-back transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

from lemely.db.base import Base
from lemely.db.models.enums import TutorListingState
from lemely.db.tutoring_predicates import (
    ACTIVE_STATES_SQL,
    EFFECTIVE_STATE_SQL,
    LIVE_PENDING_SQL,
    OUTCOME_MEMBERSHIP_SQL,
    active_block_between_sql,
    listed_and_not_paused_sql,
    student_ever_blocked_tutor_sql,
)
from tests.test_db_tutoring_schema import (
    LINK,
    World,
    _booking_row,
    _fresh_database,
    _insert,
    _profile_row,
    _rolled_back,
    _user,
    _world,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="module")
def engine() -> Iterator[sa.Engine]:
    with _fresh_database() as url:
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()


def _block(
    conn: sa.Connection, blocker: uuid.UUID, blocked: uuid.UUID, *, removed: bool = False
) -> None:
    _insert(
        conn,
        "tutoring_blocks",
        {
            "blocker_user_id": blocker,
            "blocked_user_id": blocked,
            "removed_at": datetime.now(UTC) if removed else None,
        },
    )


def _scalar(conn: sa.Connection, predicate: str, **params: object) -> bool:
    return bool(conn.execute(sa.text(f"SELECT {predicate}"), params).scalar_one())


# ---------------------------------------------------------------------------
# Listing visibility
# ---------------------------------------------------------------------------


def test_listed_and_not_paused_excludes_every_other_state(engine: sa.Engine) -> None:
    now = datetime.now(UTC)
    with _rolled_back(engine) as conn:
        expected: set[uuid.UUID] = set()
        created = 0
        for state in TutorListingState:
            for paused in (False, True):
                row = _profile_row(_user(conn, "teacher")) | {
                    "listing_state": state.value,
                    "paused_at": now if paused else None,
                    "closed_at": now if state is TutorListingState.closed else None,
                }
                _insert(conn, "tutor_profiles", row)
                created += 1
                if state is TutorListingState.listed and not paused:
                    expected.add(row["id"])
        visible = set(
            conn.execute(
                sa.text(f"SELECT id FROM tutor_profiles p WHERE {listed_and_not_paused_sql('p')}")  # noqa: S608 - predicate module output
            ).scalars()
        )
    assert created == 2 * len(TutorListingState)
    assert len(expected) == 1
    assert visible == expected


# ---------------------------------------------------------------------------
# Blocks (O11): keyed on users.id, either direction, removed rows ignored
# ---------------------------------------------------------------------------


def _blocked_profiles(conn: sa.Connection, student: uuid.UUID, tutor_col: str) -> set[uuid.UUID]:
    predicate = active_block_between_sql(":student", tutor_col)
    return set(
        conn.execute(
            sa.text(f"SELECT tp.id FROM tutor_profiles tp WHERE {predicate}"),  # noqa: S608 - predicate module output
            {"student": student},
        ).scalars()
    )


def test_active_block_between_hides_both_directions(engine: sa.Engine) -> None:
    with _rolled_back(engine) as conn:
        w = _world(conn)
        _block(conn, w.student, w.tutor_user)  # student blocks tutor
        _block(conn, w.tutor_user2, w.student2)  # tutor blocks student
        assert _blocked_profiles(conn, w.student, "tp.user_id") == {w.profile}
        assert _blocked_profiles(conn, w.student2, "tp.user_id") == {w.profile2}
        assert _blocked_profiles(conn, w.parent, "tp.user_id") == set()


def test_active_block_between_ignores_removed_rows(engine: sa.Engine) -> None:
    with _rolled_back(engine) as conn:
        w = _world(conn)
        _block(conn, w.student, w.tutor_user, removed=True)
        _block(conn, w.tutor_user2, w.student, removed=True)
        assert _blocked_profiles(conn, w.student, "tp.user_id") == set()
        # A re-block clears removed_at and the block is active again.
        conn.execute(
            sa.text(
                "UPDATE tutoring_blocks SET removed_at = NULL "
                "WHERE blocker_user_id = :s AND blocked_user_id = :t"
            ),
            {"s": w.student, "t": w.tutor_user},
        )
        assert _blocked_profiles(conn, w.student, "tp.user_id") == {w.profile}


def test_active_block_keyed_on_user_ids_not_profile_ids(engine: sa.Engine) -> None:
    """Blocks name ``users.id``; a tutor is matched through ``tutor_profiles.user_id``."""
    with _rolled_back(engine) as conn:
        w = _world(conn)  # every profile id differs from its user id (asserted inside)
        _block(conn, w.student, w.tutor_user)
        _block(conn, w.tutor_user2, w.student)
        assert _blocked_profiles(conn, w.student, "tp.user_id") == {w.profile, w.profile2}
        # Control: the same predicate fed profile ids finds nothing, so the
        # fixture really distinguishes the two keys.
        assert _blocked_profiles(conn, w.student, "tp.id") == set()
        assert _scalar(
            conn,
            active_block_between_sql(":student", ":tutor"),
            student=w.student,
            tutor=w.tutor_user,
        )


def test_student_ever_blocked_tutor_is_directional_and_counts_removed_rows(
    engine: sa.Engine,
) -> None:
    with _rolled_back(engine) as conn:
        w = _world(conn)
        _block(conn, w.student, w.tutor_user, removed=True)  # student -> tutor, since removed
        _block(conn, w.tutor_user2, w.student2)  # tutor -> student: not the student's block
        predicate = student_ever_blocked_tutor_sql(":student", ":tutor")
        assert _scalar(conn, predicate, student=w.student, tutor=w.tutor_user)
        assert not _scalar(conn, predicate, student=w.student2, tutor=w.tutor_user2)
        assert not _scalar(conn, predicate, student=w.student, tutor=w.tutor_user2)
        # The active-block predicate disagrees on the removed row, as it must.
        assert not _scalar(
            conn,
            active_block_between_sql(":student", ":tutor"),
            student=w.student,
            tutor=w.tutor_user,
        )


# ---------------------------------------------------------------------------
# Booking-state constants
# ---------------------------------------------------------------------------


def _booking_ids_matching(conn: sa.Connection, predicate: str, ids: list[object]) -> set[object]:
    return set(
        conn.execute(
            sa.text(f"SELECT id FROM tutor_bookings WHERE id = ANY(:ids) AND {predicate}"),  # noqa: S608 - predicate module output
            {"ids": ids},
        ).scalars()
    )


def test_live_pending_active_and_outcome_membership_predicates(engine: sa.Engine) -> None:
    now = datetime.now(UTC)
    accepted = {"accepted_at": now - timedelta(days=5), "meeting_link": LINK}
    with _rolled_back(engine) as conn:
        w: World = _world(conn)
        students = [_user(conn, "student") for _ in range(7)]
        rows = {
            "pending_future": _booking_row(w, student=students[0], start=now + timedelta(days=1)),
            "pending_stale": _booking_row(w, student=students[1], start=now - timedelta(hours=3)),
            "accepted_future": _booking_row(
                w, student=students[2], start=now + timedelta(days=2), state="accepted", **accepted
            ),
            "accepted_ended": _booking_row(
                w, student=students[3], start=now - timedelta(days=1), state="accepted", **accepted
            ),
            "completed_ended": _booking_row(
                w,
                student=students[4],
                start=now - timedelta(days=2),
                state="completed",
                completed_at=now,
                completed_by_party="tutor",
                **accepted,
            ),
            "no_show_ended": _booking_row(
                w,
                student=students[5],
                start=now - timedelta(days=3),
                state="no_show",
                no_show_marked_at=now,
                **accepted,
            ),
            "cancelled": _booking_row(
                w,
                student=students[6],
                start=now + timedelta(days=4),
                state="cancelled",
                cancelled_at=now,
                cancelled_by_party="student",
            ),
        }
        for row in rows.values():
            _insert(conn, "tutor_bookings", row)
        ids = [row["id"] for row in rows.values()]
        by_id = {row["id"]: name for name, row in rows.items()}

        def names(predicate: str) -> set[str]:
            return {by_id[i] for i in _booking_ids_matching(conn, predicate, ids)}

        assert names(LIVE_PENDING_SQL) == {"pending_future"}
        assert EFFECTIVE_STATE_SQL["requested"] == LIVE_PENDING_SQL
        assert names(ACTIVE_STATES_SQL) == {
            "pending_future",
            "pending_stale",
            "accepted_future",
            "accepted_ended",
        }
        assert names(OUTCOME_MEMBERSHIP_SQL) == {
            "accepted_ended",
            "completed_ended",
            "no_show_ended",
        }


# ---------------------------------------------------------------------------
# Builders refuse anything but a column or a bind parameter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["", "1=1", "tp.user_id; DROP TABLE users", "tp.user_id OR true", "'x'", "a.b.c", ": x"],
)
def test_predicate_builders_reject_non_identifier_arguments(bad: str) -> None:
    with pytest.raises(ValueError):
        active_block_between_sql(bad, "tp.user_id")
    with pytest.raises(ValueError):
        active_block_between_sql(":student", bad)
    with pytest.raises(ValueError):
        student_ever_blocked_tutor_sql(bad, ":tutor")
    with pytest.raises(ValueError):
        listed_and_not_paused_sql(bad)


def test_predicate_builders_refuse_the_internal_block_alias() -> None:
    with pytest.raises(ValueError):
        active_block_between_sql(":student", "tutoring_block_pred.blocked_user_id")
    with pytest.raises(ValueError):
        listed_and_not_paused_sql("tutoring_block_pred")
