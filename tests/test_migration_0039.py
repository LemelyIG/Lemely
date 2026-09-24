"""Migration 0039 puts the soft-delete columns and enum values in place."""

from __future__ import annotations

import sqlalchemy as sa


def test_attempts_and_uploads_have_deleted_at(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        rows = session.execute(
            sa.text(
                "SELECT table_name, is_nullable, data_type FROM information_schema.columns "
                "WHERE column_name = 'deleted_at' AND table_name IN ('attempts', 'uploads')"
            )
        ).all()
    assert {r.table_name for r in rows} == {"attempts", "uploads"}
    assert all(r.is_nullable == "YES" for r in rows)
    assert all(r.data_type == "timestamp with time zone" for r in rows)


def test_partial_index_exists_on_attempts(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        ddl = session.execute(
            sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_attempts_deleted_at'")
        ).scalar_one()
    assert "deleted_at IS NOT NULL" in ddl


def test_review_status_gained_withdrawn(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        values = set(
            session.scalars(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'reviewstatus'"
                )
            ).all()
        )
    assert values == {"open", "resolved", "dismissed", "withdrawn"}


def test_notification_type_gained_review_withdrawn(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        values = set(
            session.scalars(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'notificationtype'"
                )
            ).all()
        )
    assert "review_withdrawn" in values


def test_class_paper_exclusions_is_keyed_on_the_pair(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        cols = set(
            session.scalars(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'class_paper_exclusions'"
                )
            ).all()
        )
    assert cols == {"class_id", "attempt_id", "excluded_by", "created_at", "updated_at"}


def test_review_queue_gained_withdrawn_at(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        nullable = session.execute(
            sa.text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'review_queue' AND column_name = 'withdrawn_at'"
            )
        ).scalar_one()
    assert nullable == "YES"


def test_teacher_papers_has_deleted_at(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text(
                "SELECT is_nullable, data_type FROM information_schema.columns "
                "WHERE table_name = 'teacher_papers' AND column_name = 'deleted_at'"
            )
        ).one()
    assert row.is_nullable == "YES"
    assert row.data_type == "timestamp with time zone"


def test_notification_preferences_gained_review_withdrawn(migrated_sessionmaker) -> None:
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'notification_preferences' "
                "AND column_name = 'review_withdrawn'"
            )
        ).one()
    assert row.is_nullable == "NO"
    assert row.column_default is not None
