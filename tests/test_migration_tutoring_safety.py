"""Migration 0050_tutoring_safety: reports and blocks (SPEC §a.2, §f)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.test_migration_tutoring_enums import (
    assert_named_objects_present,
    assert_round_trip,
    head_revision,
    spec_names_for,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

REVISION = "0050_tutoring_safety"
DOWN_REVISION = "0049_tutor_grants_audit"
TABLES = ("tutoring_reports", "tutoring_blocks")
EARLIER_TABLES = ("tutor_profiles", "tutor_bookings", "tutor_data_grants", "tutor_access_audit")


def test_this_revision_is_the_single_head() -> None:
    assert head_revision() == REVISION


def test_spec_names_objects_for_these_tables() -> None:
    """Non-vacuity: SPEC §a.2 names 5 objects on these tables."""
    assert len(spec_names_for(TABLES)) >= 5


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert_named_objects_present(session, TABLES)


def test_upgrade_downgrade_upgrade_round_trip(migrated_sessionmaker_with_downgrade) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    assert_round_trip(
        sm, downgrade_to, tables=TABLES, down_revision=DOWN_REVISION, survivors=EARLIER_TABLES
    )
