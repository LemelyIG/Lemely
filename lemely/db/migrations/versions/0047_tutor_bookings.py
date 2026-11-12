"""tutor bookings: student preferences, bookings with exclusion constraints, notes

Revision ID: 0047_tutor_bookings
Revises: 0046_tutoring_outbox_links
Create Date: 2026-10-25 00:00:00.000000

Three new tables (SPEC ``docs/tutoring/SPEC.md`` §a.2, §a.4, §f). Entirely
additive.

* ``student_tutoring_preferences``: outcome opt-out, its change time (the
  90-day hold) and the safety-notice acknowledgement.
* ``tutor_bookings``: ``slot`` is a STORED generated ``tstzrange(starts_at,
  ends_at, '[)')``. Two GiST exclusion constraints refuse an overlapping
  active booking for the same tutor or the same student, and
  ``uq_tutor_bookings_one_pending`` allows one live request per pair. "Active"
  is exactly ``state IN ('requested', 'accepted')`` in both (pinned to
  ``core.booking.ACTIVE_STATES`` by a test). The late-cancel CHECK carries the
  literal ``24 hours`` (pinned to ``core.booking.CANCEL_CUTOFF``) and needs its
  ``IS NOT NULL`` conjunct: without it a NULL reason makes the CHECK pass.
* ``tutor_booking_notes``: the booking's immutable notes thread.

``downgrade`` drops the three tables in reverse.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0047_tutor_bookings"
down_revision: str | Sequence[str] | None = "0046_tutoring_outbox_links"
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


def _party(name: str, *, nullable: bool) -> sa.Column:
    return sa.Column(
        name, postgresql.ENUM(name="bookingparty", create_type=False), nullable=nullable
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "student_tutoring_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "outcome_stats_opt_out", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("outcome_pref_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safety_notice_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_student_tutoring_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_student_tutoring_preferences")),
    )
    op.create_index(
        "ix_student_tutoring_preferences_opt_out",
        "student_tutoring_preferences",
        ["user_id"],
        postgresql_where=sa.text("outcome_stats_opt_out"),
    )

    op.create_table(
        "tutor_bookings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        _party("requested_by_party", nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column("mode", postgresql.ENUM(name="tutoringmode", create_type=False), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "slot",
            postgresql.TSTZRANGE(),
            sa.Computed("tstzrange(starts_at, ends_at, '[)')", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="bookingstate", create_type=False),
            server_default=sa.text("'requested'::bookingstate"),
            nullable=False,
        ),
        sa.Column("meeting_link", sa.String(500), nullable=True),
        sa.Column("location_detail", sa.String(300), nullable=True),
        sa.Column("other_mode_note", sa.String(300), nullable=True),
        sa.Column("decline_reason", sa.String(300), nullable=True),
        sa.Column("cancel_reason", sa.String(300), nullable=True),
        _party("cancelled_by_party", nullable=True),
        sa.Column("cancelled_by_user_id", sa.UUID(), nullable=True),
        _party("completed_by_party", nullable=True),
        sa.Column("notes_frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("no_show_marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "requested_by_party IN ('student', 'parent')",
            name=op.f("ck_tutor_bookings_requested_by_party_allowed"),
        ),
        sa.CheckConstraint(
            "ends_at > starts_at AND ends_at - starts_at "
            "BETWEEN interval '30 minutes' AND interval '4 hours'",
            name=op.f("ck_tutor_bookings_duration"),
        ),
        sa.CheckConstraint(
            "meeting_link IS NULL OR mode = 'virtual'",
            name=op.f("ck_tutor_bookings_meeting_link_mode"),
        ),
        sa.CheckConstraint(
            "location_detail IS NULL OR mode = 'in_person'",
            name=op.f("ck_tutor_bookings_location_detail_mode"),
        ),
        sa.CheckConstraint(
            "other_mode_note IS NULL OR mode = 'other'",
            name=op.f("ck_tutor_bookings_other_mode_note_mode"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('accepted', 'completed', 'no_show') OR accepted_at IS NOT NULL",
            name=op.f("ck_tutor_bookings_accepted_ts"),
        ),
        sa.CheckConstraint(
            "state <> 'declined' OR declined_at IS NOT NULL",
            name=op.f("ck_tutor_bookings_declined_ts"),
        ),
        sa.CheckConstraint(
            "state <> 'cancelled' OR (cancelled_at IS NOT NULL AND cancelled_by_party IS NOT NULL)",
            name=op.f("ck_tutor_bookings_cancelled_ts"),
        ),
        sa.CheckConstraint(
            "state <> 'completed' OR (completed_at IS NOT NULL AND completed_by_party IS NOT NULL)",
            name=op.f("ck_tutor_bookings_completed_ts"),
        ),
        sa.CheckConstraint(
            "state <> 'no_show' OR no_show_marked_at IS NOT NULL",
            name=op.f("ck_tutor_bookings_no_show_ts"),
        ),
        sa.CheckConstraint(
            "state <> 'expired' OR expired_at IS NOT NULL",
            name=op.f("ck_tutor_bookings_expired_ts"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('accepted', 'completed', 'no_show') OR mode <> 'virtual' "
            "OR meeting_link IS NOT NULL",
            name=op.f("ck_tutor_bookings_virtual_link"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('accepted', 'completed', 'no_show') OR mode <> 'in_person' "
            "OR location_detail IS NOT NULL",
            name=op.f("ck_tutor_bookings_in_person_location"),
        ),
        sa.CheckConstraint(
            "state <> 'cancelled' OR cancelled_by_party <> 'tutor' "
            "OR cancelled_at <= starts_at - interval '24 hours' "
            "OR (cancel_reason IS NOT NULL AND char_length(btrim(cancel_reason)) >= 1)",
            name=op.f("ck_tutor_bookings_late_cancel_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["tutor_profile_id"],
            ["tutor_profiles.id"],
            name=op.f("fk_tutor_bookings_tutor_profile_id_tutor_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_tutor_bookings_student_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_tutor_bookings_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["subject_code"],
            ["subjects.code"],
            name=op.f("fk_tutor_bookings_subject_code_subjects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_user_id"],
            ["users.id"],
            name=op.f("fk_tutor_bookings_cancelled_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_bookings")),
        sa.UniqueConstraint("id", "tutor_profile_id", name=op.f("uq_tutor_bookings_id_tutor")),
        sa.UniqueConstraint("id", "student_id", name=op.f("uq_tutor_bookings_id_student")),
    )
    op.create_exclude_constraint(
        "excl_tutor_bookings_tutor_slot",
        "tutor_bookings",
        ("tutor_profile_id", "="),
        ("slot", "&&"),
        using="gist",
        where=sa.text("state IN ('requested', 'accepted')"),
    )
    op.create_exclude_constraint(
        "excl_tutor_bookings_student_slot",
        "tutor_bookings",
        ("student_id", "="),
        ("slot", "&&"),
        using="gist",
        where=sa.text("state IN ('requested', 'accepted')"),
    )
    op.create_index(
        "uq_tutor_bookings_one_pending",
        "tutor_bookings",
        ["student_id", "tutor_profile_id"],
        unique=True,
        postgresql_where=sa.text("state = 'requested'"),
    )
    op.create_index(
        "ix_tutor_bookings_tutor_starts", "tutor_bookings", ["tutor_profile_id", "starts_at", "id"]
    )
    op.create_index(
        "ix_tutor_bookings_student_starts", "tutor_bookings", ["student_id", "starts_at", "id"]
    )
    op.create_index(
        "ix_tutor_bookings_tutor_requests",
        "tutor_bookings",
        ["tutor_profile_id", "starts_at"],
        postgresql_where=sa.text("state = 'requested'"),
    )
    op.create_index(
        "ix_tutor_bookings_outcome_cohort",
        "tutor_bookings",
        ["tutor_profile_id", "subject_code", "student_id", "starts_at"],
        postgresql_where=sa.text(
            "accepted_at IS NOT NULL AND state IN ('accepted', 'completed', 'no_show')"
        ),
    )
    op.create_index(
        "ix_tutor_bookings_requested_by",
        "tutor_bookings",
        ["requested_by_user_id", "created_at"],
        postgresql_where=sa.text("requested_by_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_tutor_bookings_cancelled_by",
        "tutor_bookings",
        ["cancelled_by_user_id", "cancelled_at"],
        postgresql_where=sa.text("cancelled_by_user_id IS NOT NULL"),
    )

    op.create_table(
        "tutor_booking_notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("booking_id", sa.UUID(), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        _party("author_party", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_by_user_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "author_party IN ('student', 'tutor')",
            name=op.f("ck_tutor_booking_notes_author_party_allowed"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(body)) BETWEEN 1 AND 2000",
            name=op.f("ck_tutor_booking_notes_body_len"),
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["tutor_bookings.id"],
            name=op.f("fk_tutor_booking_notes_booking_id_tutor_bookings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_tutor_booking_notes_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["hidden_by_user_id"],
            ["users.id"],
            name=op.f("fk_tutor_booking_notes_hidden_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_booking_notes")),
    )
    op.create_index(
        "ix_tutor_booking_notes_thread",
        "tutor_booking_notes",
        ["booking_id", "created_at", "id"],
    )
    op.create_index(
        "ix_tutor_booking_notes_author_user_id",
        "tutor_booking_notes",
        ["author_user_id"],
        postgresql_where=sa.text("author_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_tutor_booking_notes_hidden_by_user_id",
        "tutor_booking_notes",
        ["hidden_by_user_id"],
        postgresql_where=sa.text("hidden_by_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema: drop the three tables in reverse (indexes and constraints go too)."""
    op.drop_table("tutor_booking_notes")
    op.drop_table("tutor_bookings")
    op.drop_table("student_tutoring_preferences")
