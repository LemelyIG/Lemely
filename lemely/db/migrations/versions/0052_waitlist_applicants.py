"""waitlist applicants: the landing-page waitlist table.

Revision ID: 0052_waitlist_applicants
Revises: 0051_tutor_evidence_uploads
Create Date: 2026-11-08 00:00:00.000000

Two new tables and two new enum types. Entirely additive.

* ``waitlist_applicants``: one row per applicant. ``email`` is unique and stored lowercased
  by the application. A row exists as soon as step 1 of the two-step form is submitted
  (``completed_at`` NULL = partial). ``completion_token_hash`` is the SHA-256 digest of the
  one-time token (never the token), cleared when step 2 completes the row; its partial unique
  index serves the token lookup. ``consent_version``, ``consent_text`` and ``consent_at``
  record the wording version, its canonical text and when the applicant accepted it.
  ``email_confirmed`` is false until a confirmation flow exists.

* ``waitlist_digest_log``: one row per UTC day the team digest was claimed (primary key =
  the day), so a second scheduler firing the same day sends nothing. ``window_end`` is where
  the digest's window stopped, set once the mail was sent (NULL = claimed, not yet sent): the
  next digest starts there, so no applicant is in two digests or in none.

``downgrade`` drops both tables and the two enum types, nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0052_waitlist_applicants"
down_revision: str | Sequence[str] | None = "0051_tutor_evidence_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "waitlist_applicants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column(
            "role",
            sa.Enum("student", "teacher", "parent", "centre_admin", name="waitlistrole"),
            nullable=False,
        ),
        sa.Column("centre_name", sa.String(length=120), nullable=True),
        sa.Column(
            "levels",
            postgresql.ARRAY(sa.String(length=20)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "subjects",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "other_subjects",
            postgresql.ARRAY(sa.String(length=60)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "exam_boards",
            postgresql.ARRAY(sa.String(length=20)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("exam_session", sa.String(length=10), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("phone_has_whatsapp", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("email_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("consent_version", sa.String(length=40), nullable=False),
        sa.Column("consent_text", sa.String(length=500), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("new", "contacted", "invited", "declined", name="waitliststatus"),
            server_default=sa.text("'new'::waitliststatus"),
            nullable=False,
        ),
        sa.Column("admin_note", sa.String(length=2000), nullable=True),
        sa.Column("utm_source", sa.String(length=100), nullable=True),
        sa.Column("utm_medium", sa.String(length=100), nullable=True),
        sa.Column("utm_campaign", sa.String(length=100), nullable=True),
        sa.Column("utm_content", sa.String(length=100), nullable=True),
        sa.Column("utm_term", sa.String(length=100), nullable=True),
        sa.Column("completion_token_hash", sa.String(length=64), nullable=True),
        sa.Column("completion_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waitlist_applicants")),
        sa.UniqueConstraint("email", name="uq_waitlist_applicants_email"),
    )
    op.create_index(
        "uq_waitlist_applicants_token_hash",
        "waitlist_applicants",
        ["completion_token_hash"],
        unique=True,
        postgresql_where=sa.text("completion_token_hash IS NOT NULL"),
    )
    op.create_index("ix_waitlist_applicants_created_at", "waitlist_applicants", ["created_at"])
    op.create_index("ix_waitlist_applicants_status", "waitlist_applicants", ["status"])
    op.create_table(
        "waitlist_digest_log",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("new_applicants", sa.Integer(), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_waitlist_digest_log")),
    )


def downgrade() -> None:
    """Downgrade schema: drop the table (its indexes go with it) and its two enum types."""
    op.drop_table("waitlist_digest_log")
    op.drop_table("waitlist_applicants")
    op.execute("DROP TYPE waitliststatus")
    op.execute("DROP TYPE waitlistrole")
