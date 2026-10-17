"""teacher_papers: the grading console's paper, as a row (spec 2026-09-03 §4.2)

Revision ID: 0024_teacher_papers
Revises: 0023_invites
Create Date: 2026-09-03 00:00:00.000000

One additive table. It replaces ``_PaperStore`` in ``routers/teacher.py`` — a
process-local dict that lost every teacher paper on restart and was invisible
to a second instance, the single largest reason the Cloud Run service was
pinned to one instance (DS2, DS13).

``status`` reuses the existing ``uploadstatus`` type (``create_type=False``):
a teacher paper's lifecycle is the same four states a student upload has, and
a second enum with the same members would be a type the schema could not
explain. ``graded``/``review`` are not states — they are read off
``report_json``. ``run_started_at`` plus ``TimestampMixin.updated_at`` are the
liveness signal for the claim query (a ``processing`` row whose
``updated_at`` is stale is a dead run). ``student_id`` is nullable and, today,
always NULL (D1.12) — kept so the column exists when class ownership lands.

Reversible: ``downgrade`` drops the table only. The enum type predates this
migration and is not ours to drop.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0029_teacher_papers"
down_revision: str | Sequence[str] | None = "0028_user_avatar_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "teacher_papers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("scheme_storage_path", sa.String(), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=True),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "processing",
                "complete",
                "failed",
                name="uploadstatus",
                create_type=False,
            ),
            server_default=sa.text("'pending'::uploadstatus"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("progress_index", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mark_scheme_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_teacher_papers_uploaded_by_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_teacher_papers_student_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teacher_papers")),
    )
    op.create_index("ix_teacher_papers_uploaded_by_created_at", "teacher_papers", ["uploaded_by", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_teacher_papers_uploaded_by_created_at", table_name="teacher_papers")
    op.drop_table("teacher_papers")
