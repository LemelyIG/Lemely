"""``review_queue``: let a grading-console paper be a review item's source.

Until now every ``review_queue`` row hung off an ``attempts.id``, and
``AttemptRepository.persist_correction`` — the **student** submission path —
was the only writer. A paper uploaded through the teacher grading console
never creates an ``Attempt`` (``teacher_papers.student_id`` is always NULL,
D1.12), so a console paper the marker flagged showed "Review" on its card
while the review queue stayed empty: the queue was structurally incapable of
holding it.

This makes the source explicit instead of implied. ``attempt_id`` becomes
nullable, ``teacher_paper_id`` joins it, and a CHECK enforces that a row has
exactly one of the two — never both, never neither. There is no "source"
enum column: the two FKs *are* the discriminator, so a row cannot claim one
source while pointing at the other.

``question_id`` is the console side's answer to ``question_result_id``. A
console paper's per-question marks live inside ``teacher_papers.report_json``,
not as ``question_results`` rows, so there is no id to point a FK at; the
scheme's own question id ("5b") is what identifies the flagged question there.
Attempt-backed rows keep using ``question_result_id`` and leave this NULL.

No backfill, and deliberately none. Every existing row is attempt-backed and
stays exactly as it is; console papers graded before this migration have no
review rows and get none retroactively, because the marks a teacher already
looked at in the console should not reappear as unreviewed work weeks later.
Papers graded or re-graded from here on queue normally.

Revision ID: 0034_review_queue_paper_src
Revises: 0033_announcement_notified_at
Create Date: 2026-09-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0034_review_queue_paper_src"
down_revision: str | Sequence[str] | None = "0033_announcement_notified_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("review_queue", "attempt_id", existing_type=sa.UUID(), nullable=True)
    op.add_column(
        "review_queue",
        sa.Column(
            "teacher_paper_id",
            sa.UUID(),
            sa.ForeignKey("teacher_papers.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("review_queue", sa.Column("question_id", sa.Text(), nullable=True))
    # Exactly one source. `<>` on two booleans is XOR in Postgres, so this
    # rejects both-set and neither-set in one expression.
    # Bare name on purpose: `NAMING_CONVENTION["ck"]` is
    # "ck_%(table_name)s_%(constraint_name)s", so passing the already-prefixed
    # name here would render `ck_review_queue_ck_review_queue_one_source`.
    op.create_check_constraint(
        "one_source",
        "review_queue",
        "(attempt_id IS NOT NULL) <> (teacher_paper_id IS NOT NULL)",
    )
    # The console side's listing filter is `teacher_paper_id IN (visible papers)
    # AND status = 'open'`; attempt-backed rows are the overwhelming majority
    # and never match, so the partial index stays small.
    op.create_index(
        "ix_review_queue_teacher_paper",
        "review_queue",
        ["teacher_paper_id"],
        postgresql_where=sa.text("teacher_paper_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Console-sourced rows cannot be represented without `teacher_paper_id`,
    # and `attempt_id` is about to go back to NOT NULL — drop them rather than
    # fail the migration on a constraint violation.
    op.execute(sa.text("DELETE FROM review_queue WHERE teacher_paper_id IS NOT NULL"))
    op.drop_index("ix_review_queue_teacher_paper", table_name="review_queue")
    op.drop_constraint("ck_review_queue_one_source", "review_queue", type_="check")
    op.drop_column("review_queue", "question_id")
    op.drop_column("review_queue", "teacher_paper_id")
    op.alter_column("review_queue", "attempt_id", existing_type=sa.UUID(), nullable=False)
