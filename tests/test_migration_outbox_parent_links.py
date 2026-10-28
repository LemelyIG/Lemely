"""Migration 0046_tutoring_outbox_links: ``email_outbox`` and ``parent_link_events``."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from tests.test_migration_tutoring_enums import (
    assert_named_objects_present,
    assert_round_trip,
    spec_names_for,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

DOWN_REVISION = "0045_tutor_profiles"
TABLES = ("email_outbox", "parent_link_events")
EARLIER_TABLES = ("tutor_profiles", "tutor_subjects", "tutor_availability_rules")


def test_spec_names_objects_for_these_tables() -> None:
    """Non-vacuity: SPEC §a.2 names 6 objects on these tables."""
    assert len(spec_names_for(TABLES)) >= 6


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert_named_objects_present(session, TABLES)


def test_outbox_dedupe_conflict_does_not_abort_the_transaction(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """F17: ``ON CONFLICT (dedupe_key) DO NOTHING`` leaves the caller's transaction usable."""
    user_id = uuid.uuid4()
    insert = sa.text(
        "INSERT INTO email_outbox (recipient_user_id, template, context, dedupe_key) "
        "VALUES (:u, 'booking_update', '{}', 'k1') ON CONFLICT (dedupe_key) DO NOTHING"
    )
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:id, :email, 'student')"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        assert session.execute(insert, {"u": user_id}).rowcount == 1
        assert session.execute(insert, {"u": user_id}).rowcount == 0
        # Still usable: a later statement in the same transaction succeeds.
        assert session.execute(sa.text("SELECT count(*) FROM email_outbox")).scalar_one() == 1

    with (
        pytest.raises(sa.exc.IntegrityError) as excinfo,
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO email_outbox (recipient_user_id, template, context, dedupe_key) "
                "VALUES (:u, 'booking_update', '{}', 'k1')"
            ),
            {"u": user_id},
        )
    assert excinfo.value.orig.diag.constraint_name == "uq_email_outbox_dedupe_key"


def test_upgrade_downgrade_upgrade_round_trip(migrated_sessionmaker_with_downgrade) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    assert_round_trip(
        sm, downgrade_to, tables=TABLES, down_revision=DOWN_REVISION, survivors=EARLIER_TABLES
    )
