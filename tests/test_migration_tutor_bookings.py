"""Migration 0047_tutor_bookings: preferences, bookings and notes (SPEC §a.2, §a.4, §f)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.db.models.enums import BookingState
from tests.test_migration_tutoring_enums import (
    assert_named_objects_present,
    assert_round_trip,
    spec_names_for,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

DOWN_REVISION = "0046_tutoring_outbox_links"
TABLES = ("student_tutoring_preferences", "tutor_bookings", "tutor_booking_notes")
EARLIER_TABLES = ("tutor_profiles", "email_outbox", "parent_link_events")
EXCLUSIONS = ("excl_tutor_bookings_tutor_slot", "excl_tutor_bookings_student_slot")
ACTIVE = {"requested", "accepted"}


def test_spec_names_objects_for_these_tables() -> None:
    """Non-vacuity: SPEC §a.2 names 31 objects here (25 on tutor_bookings, 14 of them CHECKs)."""
    names = spec_names_for(TABLES)
    assert len(names) >= 31
    assert set(EXCLUSIONS) <= names


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert_named_objects_present(session, TABLES)


def test_bookings_exclusion_defs_contain_gist_overlap_and_active_states(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """F20: ``alembic check`` cannot see exclusion constraints, so their text is asserted here.

    Each must be a GiST exclusion with ``&&`` on ``slot`` whose predicate names
    both active states and no other state.
    """
    with migrated_sessionmaker() as session:
        defs = dict(
            session.execute(
                sa.text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = ANY(:names) AND contype = 'x'"
                ),
                {"names": list(EXCLUSIONS)},
            ).all()
        )
    assert set(defs) == set(EXCLUSIONS)
    inactive = {state.value for state in BookingState} - ACTIVE
    for name, definition in defs.items():
        assert "EXCLUDE USING gist" in definition, name
        assert "slot WITH &&" in definition, name
        for state in ACTIVE:
            assert f"'{state}'" in definition, (name, state)
        for state in inactive:
            assert f"'{state}'" not in definition, (name, state)
    assert "tutor_profile_id WITH =" in defs["excl_tutor_bookings_tutor_slot"]
    assert "student_id WITH =" in defs["excl_tutor_bookings_student_slot"]


def test_upgrade_downgrade_upgrade_round_trip(migrated_sessionmaker_with_downgrade) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    assert_round_trip(
        sm, downgrade_to, tables=TABLES, down_revision=DOWN_REVISION, survivors=EARLIER_TABLES
    )
