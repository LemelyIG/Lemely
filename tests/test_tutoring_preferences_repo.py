"""A student's tutoring preferences (SPEC §a.2 ``student_tutoring_preferences``, PLAN P30).

* An absent row reads as the defaults: counted in outcome figures (decision row
  8), no change instant, no safety notice acknowledged.
* ``outcome_pref_changed_at`` moves only when the opt-out value really changes
  (SC-13d: it starts the 90-day hold, so a repeated "save" must not restart it).
* The safety-notice acknowledgement (decision row 16 ii) is set once; a repeat
  keeps the first instant.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.enums import Role
from lemely.db.tutoring_preferences_repo import (
    DEFAULT_PREFERENCES,
    TutoringPreferences,
    TutoringPreferencesRepository,
)
from tests.tutoring_db import add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def repo(sm: sessionmaker[Session]) -> TutoringPreferencesRepository:
    return TutoringPreferencesRepository(sm)


@pytest.fixture
def student(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.student)


def stored(sm: sessionmaker[Session], student: uuid.UUID) -> tuple[object, ...] | None:
    with sm() as session:
        row = session.execute(
            sa.text(
                "SELECT outcome_stats_opt_out, outcome_pref_changed_at, "
                "safety_notice_acknowledged_at FROM student_tutoring_preferences "
                "WHERE user_id = :u"
            ),
            {"u": student},
        ).first()
    return tuple(row) if row is not None else None


def test_get_absent_row_reads_defaults(
    sm: sessionmaker[Session], repo: TutoringPreferencesRepository, student: uuid.UUID
) -> None:
    assert repo.get(student) == DEFAULT_PREFERENCES
    assert (
        TutoringPreferences(
            outcome_stats_opt_out=False,
            outcome_pref_changed_at=None,
            safety_notice_acknowledged_at=None,
        )
        == DEFAULT_PREFERENCES
    )
    assert stored(sm, student) is None  # a read writes nothing


def test_opt_out_round_trip_sets_changed_at_on_change_only(
    sm: sessionmaker[Session], repo: TutoringPreferencesRepository, student: uuid.UUID
) -> None:
    # Saving the default is not a change: the row appears, the hold does not start.
    unchanged = repo.set_opt_out(student, value=False)
    assert unchanged.outcome_stats_opt_out is False
    assert unchanged.outcome_pref_changed_at is None

    opted_out = repo.set_opt_out(student, value=True)
    assert opted_out.outcome_stats_opt_out is True
    assert opted_out.outcome_pref_changed_at is not None

    repeated = repo.set_opt_out(student, value=True)
    assert repeated.outcome_pref_changed_at == opted_out.outcome_pref_changed_at

    opted_in = repo.set_opt_out(student, value=False)
    assert opted_in.outcome_stats_opt_out is False
    assert opted_in.outcome_pref_changed_at is not None
    assert opted_in.outcome_pref_changed_at > opted_out.outcome_pref_changed_at

    assert repo.get(student) == opted_in
    assert stored(sm, student) == (False, opted_in.outcome_pref_changed_at, None)


def test_first_save_of_an_opt_out_sets_changed_at(
    repo: TutoringPreferencesRepository, student: uuid.UUID
) -> None:
    """No row yet means counted, so a first opt-out is a change."""
    first = repo.set_opt_out(student, value=True)
    assert first.outcome_stats_opt_out is True
    assert first.outcome_pref_changed_at is not None


def test_acknowledge_safety_notice_idempotent(
    sm: sessionmaker[Session], repo: TutoringPreferencesRepository, student: uuid.UUID
) -> None:
    first = repo.acknowledge_safety_notice(student)
    assert first.safety_notice_acknowledged_at is not None
    second = repo.acknowledge_safety_notice(student)
    assert second.safety_notice_acknowledged_at == first.safety_notice_acknowledged_at
    # The acknowledgement leaves the outcome preference alone, and the reverse holds too.
    assert second.outcome_stats_opt_out is False
    assert second.outcome_pref_changed_at is None
    after_opt_out = repo.set_opt_out(student, value=True)
    assert after_opt_out.safety_notice_acknowledged_at == first.safety_notice_acknowledged_at
    assert stored(sm, student) == (
        True,
        after_opt_out.outcome_pref_changed_at,
        first.safety_notice_acknowledged_at,
    )


def test_preferences_are_per_student(
    sm: sessionmaker[Session], repo: TutoringPreferencesRepository, student: uuid.UUID
) -> None:
    other = add_user(sm, Role.student)
    repo.set_opt_out(student, value=True)
    repo.acknowledge_safety_notice(student)
    assert repo.get(other) == DEFAULT_PREFERENCES
