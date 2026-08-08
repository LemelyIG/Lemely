"""placement quizzes: student-owned rows, XOR-checked ownership (P4.4)

Revision ID: 0010_placement_quiz_ownership
Revises: 0009_student_profiles
Create Date: 2026-08-08 00:00:00.000000

D4.6 / P4.4 chunk B. Makes the P3.5 quiz engine reusable by a
platform-assembled, student-owned quiz instead of forking it (MISSION §4:
"the placement test and practice sets are quiz-shaped: reuse that engine, do
not fork it"). Two columns blocked that literally — ``quizzes.teacher_id``
and ``quiz_assignments.class_id``, both NOT NULL — because a placement test
has neither a teacher nor a class.

**This migration relaxes two NOT NULL constraints, which the D1.2
additive-only promise did not cover.** The rule is amended in D4.6 §2, not
quietly broken: a relaxation is exactly as reversible as an addition and
strictly safer than the alternative. ``DROP NOT NULL`` rewrites no rows,
takes a catalog-only lock, and breaks no existing reader — every current row
still satisfies the old constraint. What it costs is that the downgrade is
only valid while no NULL-owner row exists, which is precisely why this ships
*before* any placement route does.

Ownership shape, enforced in the database rather than by convention:

* ``quizzes`` gains ``student_id`` (typed FK, ``ON DELETE CASCADE``) and
  ``kind``; ``ck_quizzes_owner_xor`` makes "exactly one owner, always" an
  invariant, and ``ck_quizzes_kind_owner`` ties ``kind = 'teacher'`` to
  ``teacher_id IS NOT NULL`` so the label can never disagree with the owner.
* ``quiz_assignments`` gains ``student_id`` with the matching
  ``ck_quiz_assignments_target_xor``, plus a **partial** unique index so
  one self-assignment per (quiz, student) is enforced without disturbing the
  existing class-assignment uniqueness.

Two typed FKs rather than a polymorphic ``owner_id``/``owner_type`` pair: a
polymorphic id cannot carry a foreign key and therefore cannot carry
``ON DELETE CASCADE``, so deleting a student would leave orphaned quizzes
still holding their answers (D4.6 §1).

**Enum type creation** follows 0009's pattern exactly: ``quizkind`` is created
explicitly with ``checkfirst=True`` before any column references it, and the
column uses ``create_type=False`` so SQLAlchemy never re-issues ``CREATE
TYPE``. The ``server_default`` is cast (``'teacher'::quizkind``) in both the
model and this migration so ``alembic check`` sees no drift (D1.3).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_placement_quiz_ownership"
down_revision = "0009_student_profiles"
branch_labels = None
depends_on = None

QUIZ_KIND = postgresql.ENUM(
    "teacher",
    "placement",
    "practice",
    "study_plan",
    name="quizkind",
    create_type=False,
)


def upgrade() -> None:
    """Relax the two owner NOT NULLs and add the student-owned counterparts."""
    bind = op.get_bind()
    postgresql.ENUM(
        "teacher", "placement", "practice", "study_plan", name="quizkind"
    ).create(bind, checkfirst=True)

    # --- quizzes -----------------------------------------------------------
    op.alter_column("quizzes", "teacher_id", existing_type=postgresql.UUID(), nullable=True)
    op.add_column(
        "quizzes",
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "quizzes",
        sa.Column(
            "kind",
            QUIZ_KIND,
            nullable=False,
            server_default=sa.text("'teacher'::quizkind"),
        ),
    )
    op.create_check_constraint(
        "ck_quizzes_owner_xor",
        "quizzes",
        "(teacher_id IS NULL) <> (student_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_quizzes_kind_owner",
        "quizzes",
        "(kind = 'teacher') = (teacher_id IS NOT NULL)",
    )
    op.create_index(
        "ix_quizzes_student_kind",
        "quizzes",
        ["student_id", "kind", sa.text("created_at DESC")],
    )

    # --- quiz_assignments --------------------------------------------------
    op.alter_column(
        "quiz_assignments", "class_id", existing_type=postgresql.UUID(), nullable=True
    )
    op.add_column(
        "quiz_assignments",
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_quiz_assignments_target_xor",
        "quiz_assignments",
        "(class_id IS NULL) <> (student_id IS NULL)",
    )
    op.create_index(
        "uq_quiz_assignments_student",
        "quiz_assignments",
        ["quiz_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("student_id IS NOT NULL"),
    )
    op.create_index(
        "ix_quiz_assignments_student",
        "quiz_assignments",
        ["student_id", sa.text("assigned_at DESC")],
    )


def downgrade() -> None:
    """Reverse 0010.

    Valid only while no student-owned row exists — restoring the two NOT NULLs
    fails loudly on a NULL owner rather than discarding it, which is the
    correct behaviour: a placement quiz has no teacher to fall back to, and
    inventing one would be exactly the sentinel D4.5 refused.
    """
    op.drop_index("ix_quiz_assignments_student", table_name="quiz_assignments")
    op.drop_index("uq_quiz_assignments_student", table_name="quiz_assignments")
    op.drop_constraint("ck_quiz_assignments_target_xor", "quiz_assignments", type_="check")
    op.drop_column("quiz_assignments", "student_id")
    op.alter_column(
        "quiz_assignments", "class_id", existing_type=postgresql.UUID(), nullable=False
    )

    op.drop_index("ix_quizzes_student_kind", table_name="quizzes")
    op.drop_constraint("ck_quizzes_kind_owner", "quizzes", type_="check")
    op.drop_constraint("ck_quizzes_owner_xor", "quizzes", type_="check")
    op.drop_column("quizzes", "kind")
    op.drop_column("quizzes", "student_id")
    op.alter_column("quizzes", "teacher_id", existing_type=postgresql.UUID(), nullable=False)

    postgresql.ENUM(name="quizkind").drop(op.get_bind(), checkfirst=True)
