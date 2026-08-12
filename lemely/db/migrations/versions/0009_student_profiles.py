"""student profiles: onboarding, subject enrolments, papers, confidence (P4.3)

Revision ID: 0009_student_profiles
Revises: 0008_notification_preferences
Create Date: 2026-08-08 00:00:00.000000

D4.5 / P4.3 chunk A. Four additive tables, no existing column touched
(D1.2/D1.3):

* ``student_profiles`` — one row per student user (``user_id`` PK/FK). The
  whole-person facts S-02 collects: qualification level, grade level, school
  name, external-lessons flag, weekly study hours, and
  ``onboarding_completed_at``. Everything the spec calls skippable is
  nullable — a skipped field is ``NULL``, never a sentinel/zero default that
  would look like an answer the student gave.
* ``student_subject_enrolments`` — one row per (student, subject). Carries
  the target grade and the exam session being targeted (S-01). Unique on
  ``(user_id, subject_code)``.
* ``student_enrolment_papers`` — the specific papers (e.g. P2, P4) a student
  will sit for one enrolment. A separate table rather than an array column
  so a paper is a row a later phase can join practice/plan material against.
* ``student_confidence_ratings`` — one row per (enrolment, topic)
  self-assessment slider, keyed on the P4.2 syllabus topic-label vocabulary,
  so the questionnaire, the bank, and the weakness engine speak one
  language.

**Enum type creation.** ``qualificationlevel`` is a brand-new type, created
explicitly with ``checkfirst=True`` before ``student_profiles`` references
it, and every column reference uses ``postgresql.ENUM(..., create_type=False)``
so SQLAlchemy never re-issues ``CREATE TYPE`` — the same fix
``0007_quiz_model`` applies for the same reason. ``sessionmonth`` already
exists (``0002_core_schema``); it is reused read-only here
(``create_type=False``, no creation call) by ``student_subject_enrolments``.

**CHECK constraints.** ``ck_student_profiles_weekly_study_hours_range``
(0..80, or NULL — "unknown" is not a range violation) and
``ck_student_confidence_ratings_rating_range`` (1..5, NOT NULL) are written
with ``op.create_check_constraint``/inline in ``op.create_table`` using
``op.f(...)`` naming so they match the ORM's ``Base.metadata`` naming
convention (``lemely/db/base.py``) exactly — this is the first migration in
this codebase to add a CHECK constraint; ``0007_quiz_model`` is the
precedent followed for the enum-type and multi-table-migration shape.

Downgrade drops tables in reverse dependency order (papers/ratings before
enrolments, enrolments before the profiles table/enum), then drops the
``qualificationlevel`` enum type. Purely additive — no existing table or
column is touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009_student_profiles"
down_revision: str | Sequence[str] | None = "0008_notification_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    qualification_level = postgresql.ENUM(
        "igcse", "o_level", "as_level", "a_level", name="qualificationlevel"
    )
    qualification_level.create(bind, checkfirst=True)

    # sessionmonth already exists (0002_core_schema); reused here read-only.
    session_month = postgresql.ENUM(
        "may_june",
        "oct_nov",
        "feb_mar",
        "specimen",
        name="sessionmonth",
        create_type=False,
    )

    # --- student_profiles ------------------------------------------------
    op.create_table(
        "student_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "qualification_level",
            postgresql.ENUM(
                "igcse",
                "o_level",
                "as_level",
                "a_level",
                name="qualificationlevel",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("grade_level", sa.String(), nullable=True),
        sa.Column("school_name", sa.String(), nullable=True),
        sa.Column("has_external_lessons", sa.Boolean(), nullable=True),
        sa.Column("weekly_study_hours", sa.Integer(), nullable=True),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "weekly_study_hours IS NULL OR (weekly_study_hours >= 0 AND weekly_study_hours <= 80)",
            name=op.f("ck_student_profiles_weekly_study_hours_range"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_student_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_student_profiles")),
    )

    # --- student_subject_enrolments ---------------------------------------
    op.create_table(
        "student_subject_enrolments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column("target_grade", sa.String(), nullable=True),
        sa.Column("session_month", session_month, nullable=True),
        sa.Column("session_year", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["subject_code"],
            ["subjects.code"],
            name=op.f("fk_student_subject_enrolments_subject_code_subjects"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_student_subject_enrolments_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_subject_enrolments")),
        sa.UniqueConstraint(
            "user_id",
            "subject_code",
            name=op.f("uq_student_subject_enrolments_user_id_subject_code"),
        ),
    )
    op.create_index(
        "ix_student_subject_enrolments_user_id",
        "student_subject_enrolments",
        ["user_id"],
        unique=False,
    )

    # --- student_enrolment_papers ------------------------------------------
    op.create_table(
        "student_enrolment_papers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("enrolment_id", sa.UUID(), nullable=False),
        sa.Column("paper_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["enrolment_id"],
            ["student_subject_enrolments.id"],
            name=op.f("fk_student_enrolment_papers_enrolment_id_student_subject_enrolments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_enrolment_papers")),
        sa.UniqueConstraint(
            "enrolment_id",
            "paper_number",
            name=op.f("uq_student_enrolment_papers_enrolment_id_paper_number"),
        ),
    )

    # --- student_confidence_ratings -----------------------------------------
    op.create_table(
        "student_confidence_ratings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("enrolment_id", sa.UUID(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name=op.f("ck_student_confidence_ratings_rating_range"),
        ),
        sa.ForeignKeyConstraint(
            ["enrolment_id"],
            ["student_subject_enrolments.id"],
            name=op.f("fk_student_confidence_ratings_enrolment_id_student_subject_enrolments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_confidence_ratings")),
        sa.UniqueConstraint(
            "enrolment_id",
            "topic",
            name=op.f("uq_student_confidence_ratings_enrolment_id_topic"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("student_confidence_ratings")
    op.drop_table("student_enrolment_papers")

    op.drop_index(
        "ix_student_subject_enrolments_user_id", table_name="student_subject_enrolments"
    )
    op.drop_table("student_subject_enrolments")

    op.drop_table("student_profiles")

    bind = op.get_bind()
    postgresql.ENUM(name="qualificationlevel").drop(bind, checkfirst=True)
