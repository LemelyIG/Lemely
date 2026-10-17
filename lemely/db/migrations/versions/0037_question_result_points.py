"""question_result_points + revisions: per-mark-point detail (spec 2026-09-17)

Revision ID: 0037_question_result_pts
Revises: 0036_upload_idempotency_key
Create Date: 2026-09-17 00:00:00.000000

Two additive tables and six additive nullable columns. **No data migration.**
Existing attempts have no usable link to a paper — ``attempts.paper_id`` was
never written by ``AttemptRepository._persist`` — so there is no honest mark
scheme to derive their point rows from, and a best-effort match would attach
today's parsed scheme to a paper marked against a possibly different one (D7).
Point rows accrue from the first correction after this ships.

``mark_type`` is text, not an enum: ``MathMarkType`` has fifteen members and a
narrower type would silently drop most of them.

Three enum types are created here and two of them
(``evidenceverdict``, and ``student_evidence_unjudged`` on ``reviewreason``)
are unused until the student self-review spec, which by design adds no
migration of its own (D5).

Reversible: ``downgrade`` drops both tables, the six columns, and the two enum
types this migration created. The added ``reviewreason`` value is NOT removed —
Postgres cannot drop an enum value, and recreating the type would require
rewriting every dependent column for no benefit.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0037_question_result_pts"
down_revision: str | Sequence[str] | None = "0036_upload_idempotency_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVISION_SOURCE = postgresql.ENUM(
    "ai", "teacher", "student_selfmark", "remark", name="revisionsource"
)
_EVIDENCE_VERDICT = postgresql.ENUM(
    "accepted", "rejected", "not_required", name="evidenceverdict"
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    _REVISION_SOURCE.create(bind, checkfirst=True)
    _EVIDENCE_VERDICT.create(bind, checkfirst=True)
    op.execute("ALTER TYPE reviewreason ADD VALUE IF NOT EXISTS 'student_evidence_unjudged'")

    op.create_table(
        "question_result_points",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("question_result_id", sa.UUID(), nullable=False),
        sa.Column("mark_point_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("mark_type", sa.Text(), nullable=True),
        sa.Column("tariff", sa.Integer(), nullable=False),
        sa.Column(
            "tariff_defaulted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("point_text", sa.Text(), nullable=False),
        sa.Column("awarded", sa.Boolean(), nullable=False),
        sa.Column(
            "is_alternative", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("is_optional", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("student_selfmark", sa.Boolean(), nullable=True),
        sa.Column("student_selfmark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("student_evidence", sa.Text(), nullable=True),
        sa.Column(
            "evidence_verdict",
            postgresql.ENUM(name="evidenceverdict", create_type=False),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["question_result_id"], ["question_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_result_id", "mark_point_id", name="uq_question_result_points_point"),
    )
    op.create_index(
        "ix_question_result_points_question_result_id",
        "question_result_points",
        ["question_result_id"],
    )

    op.create_table(
        "question_result_revisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("question_result_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", postgresql.ENUM(name="revisionsource", create_type=False), nullable=False),
        sa.Column("awarded_marks", sa.Integer(), nullable=False),
        sa.Column(
            "points_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["question_result_id"], ["question_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_result_id", "revision", name="uq_question_result_revisions_revision"),
    )
    op.create_index(
        "ix_question_result_revisions_question_result_id",
        "question_result_revisions",
        ["question_result_id"],
    )

    op.add_column("question_results", sa.Column("extraction_confidence", sa.Float(), nullable=True))
    op.add_column(
        "question_results",
        sa.Column("plagiarism_flagged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "question_results",
        sa.Column("ai_detection_flagged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("question_results", sa.Column("rationale", sa.Text(), nullable=True))
    op.add_column("question_results", sa.Column("student_selfmark_marks", sa.Integer(), nullable=True))
    op.add_column(
        "question_results",
        sa.Column("student_selfmarked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    for column in (
        "student_selfmarked_at",
        "student_selfmark_marks",
        "rationale",
        "ai_detection_flagged",
        "plagiarism_flagged",
        "extraction_confidence",
    ):
        op.drop_column("question_results", column)

    op.drop_index(
        "ix_question_result_revisions_question_result_id",
        table_name="question_result_revisions",
    )
    op.drop_table("question_result_revisions")
    op.drop_index(
        "ix_question_result_points_question_result_id", table_name="question_result_points"
    )
    op.drop_table("question_result_points")

    bind = op.get_bind()
    _EVIDENCE_VERDICT.drop(bind, checkfirst=True)
    _REVISION_SOURCE.drop(bind, checkfirst=True)
