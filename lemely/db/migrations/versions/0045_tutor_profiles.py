"""tutor profiles: profiles, subjects, availability rules, evidence, approvals, admin reads

Revision ID: 0045_tutor_profiles
Revises: 0044_tutoring_enums_ext
Create Date: 2026-10-25 00:00:00.000000

Six new tables (SPEC ``docs/tutoring/SPEC.md`` §a.2, §f): ``tutor_profiles``,
``tutor_subjects``, ``tutor_availability_rules`` with its GiST exclusion
constraint (§a.4), ``tutor_evidence_files``, ``tutor_approval_events`` and
``tutoring_admin_access``. Entirely additive; nothing is backfilled.

Every name is written out in full with ``op.f`` so this file reads the same as
the catalogue; ``lemely/db/models/tutoring.py`` declares the same objects and
``tests/test_db_tutoring_schema.py`` compares the two databases object by
object.

``downgrade`` drops the six tables in reverse. Evidence objects in storage are
not deleted by a downgrade: only their rows go.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0045_tutor_profiles"
down_revision: str | Sequence[str] | None = "0044_tutoring_enums_ext"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LISTED_NOT_PAUSED = "listing_state = 'listed' AND paused_at IS NULL"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _id() -> sa.Column:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tutor_profiles",
        _id(),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("public_first_name", sa.String(40), nullable=False),
        sa.Column("public_last_initial", sa.String(1), nullable=True),
        sa.Column("headline", sa.String(160), nullable=False),
        sa.Column("bio", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("qualification_note", sa.Text(), nullable=True),
        sa.Column("offers_virtual", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("offers_in_person", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("offers_other", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("other_mode_note", sa.String(200), nullable=True),
        sa.Column("country_code", sa.CHAR(2), server_default=sa.text("'EG'"), nullable=False),
        sa.Column("area_code", sa.String(40), nullable=False),
        sa.Column("zone", sa.String(64), server_default=sa.text("'Africa/Cairo'"), nullable=False),
        sa.Column(
            "listing_state",
            postgresql.ENUM(name="tutorlistingstate", create_type=False),
            server_default=sa.text("'draft'::tutorlistingstate"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("listed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_listed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexable", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("documents_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rating_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rating_sum", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "rating_avg",
            sa.Numeric(3, 2),
            sa.Computed(
                "CASE WHEN rating_count = 0 THEN NULL "
                "ELSE round(rating_sum::numeric / rating_count, 2) END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "rank_score", sa.Numeric(7, 6), server_default=sa.text("4.000000"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "char_length(btrim(public_first_name)) BETWEEN 1 AND 40",
            name=op.f("ck_tutor_profiles_first_name_len"),
        ),
        sa.CheckConstraint(
            sa.literal_column(
                "public_first_name !~ '[0-9./@:]' AND public_first_name !~ '[[:cntrl:]]'"
            ),
            name=op.f("ck_tutor_profiles_first_name_chars"),
        ),
        sa.CheckConstraint(
            "char_length(public_last_initial) = 1",
            name=op.f("ck_tutor_profiles_last_initial_len"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(headline)) >= 1", name=op.f("ck_tutor_profiles_headline_not_blank")
        ),
        sa.CheckConstraint("char_length(bio) <= 2000", name=op.f("ck_tutor_profiles_bio_len")),
        sa.CheckConstraint(
            "char_length(qualification_note) <= 1000",
            name=op.f("ck_tutor_profiles_qualification_note_len"),
        ),
        sa.CheckConstraint(
            "offers_virtual OR offers_in_person OR offers_other",
            name=op.f("ck_tutor_profiles_has_mode"),
        ),
        sa.CheckConstraint(
            "offers_other OR other_mode_note IS NULL", name=op.f("ck_tutor_profiles_other_note")
        ),
        sa.CheckConstraint(
            "(listing_state = 'closed') = (closed_at IS NOT NULL)",
            name=op.f("ck_tutor_profiles_closed"),
        ),
        sa.CheckConstraint("rating_count >= 0", name=op.f("ck_tutor_profiles_rating_count_nonneg")),
        sa.CheckConstraint(
            "rating_sum BETWEEN rating_count AND 5 * rating_count",
            name=op.f("ck_tutor_profiles_rating_sum_range"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tutor_profiles_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_profiles")),
        sa.UniqueConstraint("user_id", name=op.f("uq_tutor_profiles_user_id")),
    )
    op.create_index(
        "ix_tutor_profiles_directory",
        "tutor_profiles",
        [sa.text("rank_score DESC"), "first_listed_at", "id"],
        postgresql_where=sa.text(_LISTED_NOT_PAUSED),
    )
    op.create_index(
        "ix_tutor_profiles_area_rank",
        "tutor_profiles",
        ["area_code", sa.text("rank_score DESC"), "first_listed_at", "id"],
        postgresql_where=sa.text(_LISTED_NOT_PAUSED),
    )
    op.create_index(
        "ix_tutor_profiles_rated",
        "tutor_profiles",
        ["rating_avg"],
        postgresql_where=sa.text(f"{_LISTED_NOT_PAUSED} AND rating_count >= 3"),
    )
    for mode in ("virtual", "in_person", "other"):
        op.create_index(
            f"ix_tutor_profiles_mode_{mode}",
            "tutor_profiles",
            [sa.text("rank_score DESC"), "first_listed_at", "id"],
            postgresql_where=sa.text(f"{_LISTED_NOT_PAUSED} AND offers_{mode}"),
        )
    op.create_index(
        "ix_tutor_profiles_review_queue",
        "tutor_profiles",
        ["listing_state", "submitted_at", "id"],
    )

    op.create_table(
        "tutor_subjects",
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tutor_profile_id"],
            ["tutor_profiles.id"],
            name=op.f("fk_tutor_subjects_tutor_profile_id_tutor_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_code"],
            ["subjects.code"],
            name=op.f("fk_tutor_subjects_subject_code_subjects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tutor_profile_id", "subject_code", name=op.f("pk_tutor_subjects")),
    )
    op.create_index(
        "ix_tutor_subjects_subject_code",
        "tutor_subjects",
        ["subject_code", "tutor_profile_id"],
    )

    op.create_table(
        "tutor_availability_rules",
        _id(),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column("iso_weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_minute", sa.SmallInteger(), nullable=False),
        sa.Column("end_minute", sa.SmallInteger(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "iso_weekday BETWEEN 1 AND 7",
            name=op.f("ck_tutor_availability_rules_iso_weekday_range"),
        ),
        sa.CheckConstraint(
            "start_minute BETWEEN 0 AND 1425 AND start_minute % 15 = 0",
            name=op.f("ck_tutor_availability_rules_start_minute_range"),
        ),
        sa.CheckConstraint(
            "end_minute BETWEEN 15 AND 1440 AND end_minute % 15 = 0 "
            "AND end_minute > start_minute",
            name=op.f("ck_tutor_availability_rules_end_minute_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tutor_profile_id"],
            ["tutor_profiles.id"],
            name=op.f("fk_tutor_availability_rules_tutor_profile_id_tutor_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_availability_rules")),
        # Inline rather than `op.create_exclude_constraint` (the form SPEC §a.4
        # sketches): Alembic builds a stub column per element for that call and
        # cannot name one for the `int4range(...)` expression. Same constraint.
        postgresql.ExcludeConstraint(
            ("tutor_profile_id", "="),
            ("iso_weekday", "="),
            (sa.text("int4range(start_minute, end_minute, '[)')"), "&&"),
            name="excl_tutor_availability_rules_no_overlap",
            using="gist",
        ),
    )
    op.create_index(
        "ix_tutor_availability_rules_window",
        "tutor_availability_rules",
        ["iso_weekday", "start_minute", "end_minute", "tutor_profile_id"],
    )

    op.create_table(
        "tutor_evidence_files",
        _id(),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column("storage_path", sa.String(300), nullable=False),
        sa.Column("original_filename", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png')",
            name=op.f("ck_tutor_evidence_files_content_type_allowed"),
        ),
        sa.CheckConstraint(
            "size_bytes BETWEEN 1 AND 10485760",
            name=op.f("ck_tutor_evidence_files_size_bytes_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tutor_profile_id"],
            ["tutor_profiles.id"],
            name=op.f("fk_tutor_evidence_files_tutor_profile_id_tutor_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_evidence_files")),
    )
    op.create_index(
        "ix_tutor_evidence_files_tutor_profile_id", "tutor_evidence_files", ["tutor_profile_id"]
    )

    op.create_table(
        "tutor_approval_events",
        _id(),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column("admin_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "decision",
            postgresql.ENUM(name="tutorapprovaldecision", create_type=False),
            nullable=False,
        ),
        sa.Column("documents_seen", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("profile_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(note) <= 2000", name=op.f("ck_tutor_approval_events_note_len")
        ),
        sa.ForeignKeyConstraint(
            ["tutor_profile_id"],
            ["tutor_profiles.id"],
            name=op.f("fk_tutor_approval_events_tutor_profile_id_tutor_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            name=op.f("fk_tutor_approval_events_admin_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_approval_events")),
    )
    op.create_index(
        "ix_tutor_approval_events_tutor",
        "tutor_approval_events",
        ["tutor_profile_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_tutor_approval_events_admin_user_id", "tutor_approval_events", ["admin_user_id"]
    )

    op.create_table(
        "tutoring_admin_access",
        _id(),
        sa.Column("admin_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "action",
            postgresql.ENUM(name="tutoringadminaction", create_type=False),
            nullable=False,
        ),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=True),
        sa.Column("report_id", sa.UUID(), nullable=True),
        sa.Column("booking_id", sa.UUID(), nullable=True),
        sa.Column("evidence_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            name=op.f("fk_tutoring_admin_access_admin_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutoring_admin_access")),
    )
    op.create_index(
        "ix_tutoring_admin_access_tutor",
        "tutoring_admin_access",
        ["tutor_profile_id", "created_at"],
    )
    op.create_index(
        "ix_tutoring_admin_access_admin_user_id",
        "tutoring_admin_access",
        ["admin_user_id"],
        postgresql_where=sa.text("admin_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema: drop the six tables in reverse (indexes go with them)."""
    op.drop_table("tutoring_admin_access")
    op.drop_table("tutor_approval_events")
    op.drop_table("tutor_evidence_files")
    op.drop_table("tutor_availability_rules")
    op.drop_table("tutor_subjects")
    op.drop_table("tutor_profiles")
