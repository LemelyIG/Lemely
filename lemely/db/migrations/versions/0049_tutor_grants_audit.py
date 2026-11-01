"""tutor grants and audit: tutor_data_grants, tutor_access_audit

Revision ID: 0049_tutor_grants_audit
Revises: 0048_tutor_reviews
Create Date: 2026-10-25 00:00:00.000000

Two new tables (SPEC ``docs/tutoring/SPEC.md`` §a.2, §f; ADR-T02). Entirely
additive.

* ``tutor_data_grants``: a student's consent for one tutor to read their
  derived data. ``uq_tutor_data_grants_live`` allows one unrevoked grant per
  pair. Validity is never stored: it is computed at read time.
* ``tutor_access_audit``: one append-only row per tutor read of granted data,
  shown to the student and their linked parents.

``downgrade`` drops both tables in reverse. **It destroys the audit log**:
incident response snapshots ``tutor_access_audit`` before any downgrade past
this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0049_tutor_grants_audit"
down_revision: str | Sequence[str] | None = "0048_tutor_reviews"
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
        "tutor_data_grants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column(
            "scope",
            postgresql.ENUM(name="tutorgrantscope", create_type=False),
            server_default=sa.text("'all_subjects_derived'::tutorgrantscope"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoke_reason",
            postgresql.ENUM(name="grantrevokereason", create_type=False),
            nullable=True,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name=op.f("ck_tutor_data_grants_expires_after_created"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_tutor_data_grants_revoked_after_created"),
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoke_reason IS NULL)",
            name=op.f("ck_tutor_data_grants_revoke_reason_matches"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_tutor_data_grants_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tutor_profile_id"],
            ["tutor_profiles.id"],
            name=op.f("fk_tutor_data_grants_tutor_profile_id_tutor_profiles"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_data_grants")),
    )
    op.create_index("ix_tutor_data_grants_tutor", "tutor_data_grants", ["tutor_profile_id"])
    op.create_index(
        "uq_tutor_data_grants_live",
        "tutor_data_grants",
        ["student_id", "tutor_profile_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_tutor_data_grants_tutor_live",
        "tutor_data_grants",
        ["tutor_profile_id", sa.text("created_at DESC"), "id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_tutor_data_grants_student",
        "tutor_data_grants",
        ["student_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "tutor_access_audit",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=True),
        sa.Column("tutor_public_name", sa.String(60), nullable=False),
        sa.Column(
            "action",
            postgresql.ENUM(name="tutoraccessaction", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "accessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Append-only: created_at, no updated_at (SPEC §a.2).
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["tutor_data_grants.id"],
            name=op.f("fk_tutor_access_audit_grant_id_tutor_data_grants"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_tutor_access_audit_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tutor_profile_id"],
            ["tutor_profiles.id"],
            name=op.f("fk_tutor_access_audit_tutor_profile_id_tutor_profiles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_access_audit")),
    )
    op.create_index(
        "ix_tutor_access_audit_student",
        "tutor_access_audit",
        ["student_id", sa.text("accessed_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_tutor_access_audit_tutor",
        "tutor_access_audit",
        ["tutor_profile_id", "accessed_at"],
        postgresql_where=sa.text("tutor_profile_id IS NOT NULL"),
    )
    op.create_index(
        "ix_tutor_access_audit_grant_id",
        "tutor_access_audit",
        ["grant_id"],
        postgresql_where=sa.text("grant_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop both tables in reverse. This destroys the audit log (see the module docstring)."""
    op.drop_table("tutor_access_audit")
    op.drop_table("tutor_data_grants")
