"""tutor reviews: reviews and the tutor's moderated reply

Revision ID: 0048_tutor_reviews
Revises: 0047_tutor_bookings
Create Date: 2026-10-25 00:00:00.000000

Two new tables (SPEC ``docs/tutoring/SPEC.md`` §a.2, §f). Entirely additive.

* ``tutor_reviews``: one per booking (``uq_tutor_reviews_booking_id``). Two
  composite foreign keys tie ``tutor_profile_id`` and ``student_id`` to the
  booking's own values (F34), against ``uq_tutor_bookings_id_tutor`` and
  ``uq_tutor_bookings_id_student``.
* ``tutor_review_replies``: one per review, composite FK to
  ``uq_tutor_reviews_id_tutor``; moderated before it is public (row 15b).

``downgrade`` drops both tables, then resets every profile's rating aggregate
to the zero-review values: ``rating_count = 0``, ``rating_sum = 0`` and
``rank_score = 4.000000`` (the prior mean, written as a literal because a
migration must not import the rules code that computes it, F35).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0048_tutor_reviews"
down_revision: str | Sequence[str] | None = "0047_tutor_bookings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tutor_reviews",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("booking_id", sa.UUID(), nullable=False),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("stars", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "text_state",
            postgresql.ENUM(name="moderationstate", create_type=False),
            nullable=False,
        ),
        sa.Column("text_moderated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text_moderated_by", sa.UUID(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("stars BETWEEN 1 AND 5", name=op.f("ck_tutor_reviews_stars_range")),
        sa.CheckConstraint("char_length(body) <= 1000", name=op.f("ck_tutor_reviews_body_len")),
        sa.CheckConstraint(
            "(body IS NULL) = (text_state = 'none')",
            name=op.f("ck_tutor_reviews_text_state_matches_body"),
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["tutor_bookings.id"],
            name=op.f("fk_tutor_reviews_booking_id_tutor_bookings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["booking_id", "tutor_profile_id"],
            ["tutor_bookings.id", "tutor_bookings.tutor_profile_id"],
            name=op.f("fk_tutor_reviews_booking_tutor_tutor_bookings"),
        ),
        sa.ForeignKeyConstraint(
            ["booking_id", "student_id"],
            ["tutor_bookings.id", "tutor_bookings.student_id"],
            name=op.f("fk_tutor_reviews_booking_student_tutor_bookings"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_tutor_reviews_student_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["text_moderated_by"],
            ["users.id"],
            name=op.f("fk_tutor_reviews_text_moderated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_reviews")),
        sa.UniqueConstraint("id", "tutor_profile_id", name=op.f("uq_tutor_reviews_id_tutor")),
        sa.UniqueConstraint("booking_id", name=op.f("uq_tutor_reviews_booking_id")),
    )
    op.create_index("ix_tutor_reviews_student_id", "tutor_reviews", ["student_id"])
    op.create_index(
        "ix_tutor_reviews_text_moderated_by",
        "tutor_reviews",
        ["text_moderated_by"],
        postgresql_where=sa.text("text_moderated_by IS NOT NULL"),
    )
    op.create_index(
        "ix_tutor_reviews_listing",
        "tutor_reviews",
        ["tutor_profile_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "ix_tutor_reviews_pending",
        "tutor_reviews",
        ["created_at", "id"],
        postgresql_where=sa.text("text_state = 'pending' AND removed_at IS NULL"),
    )
    op.create_index(
        "ix_tutor_reviews_student_latest",
        "tutor_reviews",
        ["tutor_profile_id", "student_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "tutor_review_replies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "text_state",
            postgresql.ENUM(name="moderationstate", create_type=False),
            server_default=sa.text("'pending'::moderationstate"),
            nullable=False,
        ),
        sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moderated_by", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "char_length(btrim(body)) BETWEEN 1 AND 1000",
            name=op.f("ck_tutor_review_replies_body_len"),
        ),
        sa.CheckConstraint(
            "text_state IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_tutor_review_replies_text_state_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["tutor_reviews.id"],
            name=op.f("fk_tutor_review_replies_review_id_tutor_reviews"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "tutor_profile_id"],
            ["tutor_reviews.id", "tutor_reviews.tutor_profile_id"],
            name=op.f("fk_tutor_review_replies_review_tutor_tutor_reviews"),
        ),
        sa.ForeignKeyConstraint(
            ["moderated_by"],
            ["users.id"],
            name=op.f("fk_tutor_review_replies_moderated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_review_replies")),
        sa.UniqueConstraint("review_id", name=op.f("uq_tutor_review_replies_review_id")),
    )
    op.create_index(
        "ix_tutor_review_replies_tutor_profile_id", "tutor_review_replies", ["tutor_profile_id"]
    )
    op.create_index(
        "ix_tutor_review_replies_moderated_by",
        "tutor_review_replies",
        ["moderated_by"],
        postgresql_where=sa.text("moderated_by IS NOT NULL"),
    )
    op.create_index(
        "ix_tutor_review_replies_pending",
        "tutor_review_replies",
        ["created_at", "id"],
        postgresql_where=sa.text("text_state = 'pending'"),
    )


def downgrade() -> None:
    """Drop both tables, then reset every rating aggregate to the zero-review literals."""
    op.drop_table("tutor_review_replies")
    op.drop_table("tutor_reviews")
    op.execute("UPDATE tutor_profiles SET rating_count = 0, rating_sum = 0, rank_score = 4.000000")
