"""Migration 0039 puts the soft-delete columns and enum values in place."""

from __future__ import annotations

import uuid

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


def test_downgrade_clears_the_rows_pre_0039_code_cannot_load(
    migrated_sessionmaker_with_downgrade,
) -> None:
    """I1 / docs/deployment.md §5.7: `downgrade()` prevents the 500, at least.

    Pre-0039 code reads `notifications.type`/`review_queue.status` through
    enums that lack `review_withdrawn`/`withdrawn`, so a row of either kind
    left behind by a downgrade would 500 the first pre-0039 read of it. The
    migration's `downgrade()` deletes/updates both before dropping the
    columns; this proves the rows are actually gone afterwards, not just
    that the columns are. It does not — and cannot — prove that deleted
    papers stay invisible: that regresses regardless, once `deleted_at` is
    dropped, which is exactly why the deploy doc calls this a documentation
    fix, not a safe rollback.
    """
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        user_id = uuid.uuid4()
        session.execute(
            sa.text(
                "INSERT INTO users (id, email, role) "
                "VALUES (:id, 'rollback-probe@example.com', 'student')"
            ),
            {"id": user_id},
        )
        session.execute(
            sa.text(
                "INSERT INTO notifications (user_id, type, title) "
                "VALUES (:user_id, 'review_withdrawn', 'A review was withdrawn')"
            ),
            {"user_id": user_id},
        )
        session.commit()

    downgrade_to("0038_point_group_key")

    with sm() as session:
        remaining_notifications = session.execute(
            sa.text("SELECT count(*) FROM notifications WHERE type = 'review_withdrawn'")
        ).scalar_one()
        assert remaining_notifications == 0
