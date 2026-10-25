"""Migration 0049_tutor_grants_audit: grants and the tutor-read audit log (SPEC §a.2, §f)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.test_migration_tutoring_enums import (
    assert_named_objects_present,
    assert_round_trip,
    spec_names_for,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

DOWN_REVISION = "0048_tutor_reviews"
TABLES = ("tutor_data_grants", "tutor_access_audit")
EARLIER_TABLES = ("tutor_profiles", "tutor_bookings", "tutor_reviews", "tutor_review_replies")


def test_spec_names_objects_for_these_tables() -> None:
    """Non-vacuity: SPEC §a.2 names 10 objects on these tables."""
    assert len(spec_names_for(TABLES)) >= 10


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert_named_objects_present(session, TABLES)


def test_upgrade_downgrade_upgrade_round_trip(migrated_sessionmaker_with_downgrade) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    assert_round_trip(
        sm, downgrade_to, tables=TABLES, down_revision=DOWN_REVISION, survivors=EARLIER_TABLES
    )
