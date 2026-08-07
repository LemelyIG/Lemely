"""review overrides: teacher-override columns on question_results

Revision ID: 0005_review_overrides
Revises: 0004_class_model
Create Date: 2026-08-06 00:00:00.000000

P3.4: five nullable, additive columns on ``question_results`` (D1.2/D1.3 —
new nullable columns only, nothing altered or dropped) recording a teacher's
override of the AI's mark without touching ``awarded_marks`` itself:

* ``teacher_awarded_marks`` — the teacher's corrected mark. NULL means "no
  override recorded"; ``QuestionResult.effective_marks`` (the one accessor
  every student-facing read path must use) falls back to ``awarded_marks``
  when this is NULL.
* ``teacher_note`` — the note to the student that must accompany an override
  (UI-spec T-08).
* ``teacher_breakdown`` — the method/accuracy breakdown a teacher records,
  stored verbatim as the teacher supplied it (JSONB). Deliberately not a
  computed field: the mark scheme's M/A/B point types are not persisted
  per-``matched_point_ids`` entry on this table, so there is nothing honest to
  derive a breakdown from (UI-spec §1.4 — never invent precision).
* ``overridden_by`` / ``overridden_at`` — who made the correction and when,
  the durable attributability MISSION §4 requires ("overrides feed back as
  recorded corrections").

No table is created for the review queue itself — ``review_queue`` (added in
0002) already carries reason/status/assignment/resolution; P3.4 only needed
somewhere to record *what the teacher changed the mark to*, which lives on the
question result it corrects, one row per question, not per review-queue item
(a question can accumulate more than one queue row, e.g. a low_confidence row
and a plagiarism_flag row for the same question — see
``AttemptRepository.persist_correction``).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_review_overrides"
down_revision: Union[str, Sequence[str], None] = "0004_class_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "question_results", sa.Column("teacher_awarded_marks", sa.Integer(), nullable=True)
    )
    op.add_column("question_results", sa.Column("teacher_note", sa.Text(), nullable=True))
    op.add_column(
        "question_results",
        sa.Column("teacher_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("question_results", sa.Column("overridden_by", sa.UUID(), nullable=True))
    op.add_column(
        "question_results",
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_question_results_overridden_by_users"),
        "question_results",
        "users",
        ["overridden_by"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_question_results_overridden_by_users"),
        "question_results",
        type_="foreignkey",
    )
    op.drop_column("question_results", "overridden_at")
    op.drop_column("question_results", "overridden_by")
    op.drop_column("question_results", "teacher_breakdown")
    op.drop_column("question_results", "teacher_note")
    op.drop_column("question_results", "teacher_awarded_marks")
