"""tutor evidence uploads: the T6 upload-attempt log

Revision ID: 0051_tutor_evidence_uploads
Revises: 0050_tutoring_safety
Create Date: 2026-10-27 00:00:00.000000

One new table (T30 F30-5). Entirely additive: no existing table, column, type or
row changes.

* ``tutor_evidence_uploads``: one append-only row per T6 upload attempt, committed
  before the file is checked, so the quota (``lemely/db/tutor_evidence_repo.py``)
  counts an attempt the check refused, and a T7 delete (which deletes the
  ``tutor_evidence_files`` row only) gives none back. It keeps the profile and the
  instant only: no filename, no personal data. ``CASCADE`` with the profile, like
  ``tutor_evidence_files``. ``ix_tutor_evidence_uploads_profile_day`` serves the
  quota's 24-hour COUNT.

``downgrade`` drops the table (its index goes with it) and nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0051_tutor_evidence_uploads"
down_revision: str | Sequence[str] | None = "0050_tutoring_safety"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tutor_evidence_uploads",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tutor_profile_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tutor_profile_id"],
            ["tutor_profiles.id"],
            name=op.f("fk_tutor_evidence_uploads_tutor_profile_id_tutor_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_evidence_uploads")),
    )
    op.create_index(
        "ix_tutor_evidence_uploads_profile_day",
        "tutor_evidence_uploads",
        ["tutor_profile_id", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema: drop the attempt log (its index goes with it)."""
    op.drop_table("tutor_evidence_uploads")
