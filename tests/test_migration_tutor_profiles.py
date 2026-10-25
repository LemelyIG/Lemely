"""Migration 0045_tutor_profiles: the six profile-side tables (SPEC §a.2, §f)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.test_migration_tutoring_enums import (
    assert_named_objects_present,
    assert_round_trip,
    spec_names_for,
    type_exists,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

DOWN_REVISION = "0044_tutoring_enums_ext"
TABLES = (
    "tutor_profiles",
    "tutor_subjects",
    "tutor_availability_rules",
    "tutor_evidence_files",
    "tutor_approval_events",
    "tutoring_admin_access",
)


def test_spec_names_objects_for_these_tables() -> None:
    """Non-vacuity: SPEC §a.2 names 19 objects on these six tables (14 on tutor_profiles)."""
    assert len(spec_names_for(TABLES)) >= 19


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert_named_objects_present(session, TABLES)


def test_upgrade_downgrade_upgrade_round_trip(migrated_sessionmaker_with_downgrade) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    assert_round_trip(sm, downgrade_to, tables=TABLES, down_revision=DOWN_REVISION)
    with sm() as session:
        # The enum types belong to 0044 and were never dropped by this step.
        assert type_exists(session, "tutorlistingstate")
