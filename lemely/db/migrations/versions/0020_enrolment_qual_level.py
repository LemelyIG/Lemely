"""per-subject qualification level on student_subject_enrolments (P5.x)

Revision ID: 0020_enrolment_qual_level
Revises: 0019_activation_review
Create Date: 2026-08-17 00:00:00.000000

Additive: one nullable column on ``student_subject_enrolments``, reusing the
``qualificationlevel`` enum type ``0009_student_profiles`` already created
(``create_type=False`` — this migration does not own that type and must not
re-issue ``CREATE TYPE``). Backfills every existing enrolment row from that
student's ``student_profiles.qualification_level`` (NULL where the student
never set one) — see the design spec's "Backfill" decision.

Revision id abbreviated to ``0020_enrolment_qual_level`` (25 chars): the
brief's original ``0020_enrolment_qualification_level`` is 34 characters,
which overflows ``alembic_version.version_num`` (``varchar(32)``) — the same
constraint ``0019_activation_review``'s docstring calls out for its own id.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0020_enrolment_qual_level"
down_revision: str | Sequence[str] | None = "0019_activation_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "student_subject_enrolments",
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
    )
    op.execute(
        """
        UPDATE student_subject_enrolments AS e
        SET qualification_level = p.qualification_level
        FROM student_profiles AS p
        WHERE p.user_id = e.user_id
          AND p.qualification_level IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("student_subject_enrolments", "qualification_level")
