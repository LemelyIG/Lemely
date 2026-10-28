"""Migration 0048_tutor_reviews: reviews and replies (SPEC §a.2, §f)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa

from tests.test_migration_tutoring_enums import (
    assert_named_objects_present,
    assert_round_trip,
    public_tables,
    spec_names_for,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

DOWN_REVISION = "0047_tutor_bookings"
TABLES = ("tutor_reviews", "tutor_review_replies")
EARLIER_TABLES = ("tutor_profiles", "tutor_bookings", "tutor_booking_notes")


def test_spec_names_objects_for_these_tables() -> None:
    """Non-vacuity: SPEC §a.2 names 19 objects on these tables (3 composite FKs among them)."""
    assert len(spec_names_for(TABLES)) >= 19


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert_named_objects_present(session, TABLES)


def test_reviews_downgrade_resets_rating_literals(migrated_sessionmaker_with_downgrade) -> None:
    """SPEC §f: the downgrade resets every aggregate to the zero-review literals (F35)."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    user_id = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:id, :email, 'teacher')"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        session.execute(
            sa.text(
                "INSERT INTO tutor_profiles (user_id, public_first_name, headline, "
                "offers_virtual, area_code, rating_count, rating_sum, rank_score) "
                "VALUES (:u, 'Sara', 'Maths', true, 'cairo', 2, 9, 4.2)"
            ),
            {"u": user_id},
        )

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert not set(TABLES) & public_tables(session)
        row = session.execute(
            sa.text(
                "SELECT rating_count, rating_sum, rank_score, rating_avg FROM tutor_profiles "
                "WHERE user_id = :u"
            ),
            {"u": user_id},
        ).one()
    assert row.rating_count == 0
    assert row.rating_sum == 0
    assert row.rank_score == Decimal("4.000000")
    assert row.rating_avg is None


def test_upgrade_downgrade_upgrade_round_trip(migrated_sessionmaker_with_downgrade) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    assert_round_trip(
        sm, downgrade_to, tables=TABLES, down_revision=DOWN_REVISION, survivors=EARLIER_TABLES
    )
