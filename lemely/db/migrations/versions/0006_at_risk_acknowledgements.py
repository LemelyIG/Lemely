"""at-risk acknowledgements: teacher-scoped, evidence-fingerprinted flag acks

Revision ID: 0006_at_risk_acknowledgements
Revises: 0005_review_overrides
Create Date: 2026-08-06 00:00:00.000000

P3.4b / D3.5: one new, additive table. At-risk flags are derived, not stored
(``lemely.core.at_risk.assess_at_risk`` recomputes them from history on every
request, D3.3), so there is no flag row an acknowledgement could reference by
id. This table is the only persistent state T-06's "acknowledge with a note"
action needs:

* ``teacher_id`` / ``student_id`` / ``reason`` — who acknowledged which
  signal for which student. Unique on the triple (per-teacher scoping: D3.5
  is explicit that teacher A acknowledging must not blind teacher B, who
  carries their own responsibility for the same student in a different
  class) so an upsert against this key refreshes an existing row rather than
  duplicating it.
* ``evidence_fingerprint`` — ``lemely.core.at_risk.flag_fingerprint()``'s
  output for the flag this ack covers. A flag renders as acknowledged only
  when a stored ack exists *and* its fingerprint matches the flag currently
  firing; new evidence (a further decline, a fresh submission ending an
  inactivity streak) changes the fingerprint and the flag re-surfaces
  unacknowledged. Without this column an ack would be a permanent mute,
  exactly the failure mode D3.5 rejects.
* ``note`` — optional, teacher-facing only, never surfaced on any
  student/parent route (unlike the T-08 override note, which is explicitly a
  note *to* the student).

``reason`` is a native Postgres enum built from
``lemely.core.at_risk.AtRiskReason`` directly (not a hand-copied db-layer
enum) — see ``lemely.db.models.ops.AtRiskAcknowledgement``'s docstring for
why that import direction is already established and is not an
import-linter layering violation.

Additive only (D1.2/D1.3): a new table, no existing column touched.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006_at_risk_acknowledgements"
down_revision: Union[str, Sequence[str], None] = "0005_review_overrides"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "at_risk_acknowledgements",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("teacher_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum("declining_trend", "below_target", "inactive", name="atriskreason"),
            nullable=False,
        ),
        sa.Column("evidence_fingerprint", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_at_risk_acknowledgements_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"],
            ["users.id"],
            name=op.f("fk_at_risk_acknowledgements_teacher_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_at_risk_acknowledgements")),
        sa.UniqueConstraint(
            "teacher_id",
            "student_id",
            "reason",
            name="uq_at_risk_acknowledgements_teacher_id_student_id_reason",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("at_risk_acknowledgements")
    op.execute("DROP TYPE IF EXISTS atriskreason")
