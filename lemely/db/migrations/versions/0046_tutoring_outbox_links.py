"""tutoring outbox and link events: email_outbox, parent_link_events

Revision ID: 0046_tutoring_outbox_links
Revises: 0045_tutor_profiles
Create Date: 2026-10-25 00:00:00.000000

Two new tables (SPEC ``docs/tutoring/SPEC.md`` §a.2, §f). Entirely additive.

* ``email_outbox``: one row per transactional email. The recipient's address
  is resolved at send time, never stored (F18, EM-5); ``uq_email_outbox_dedupe_key``
  backs the ``ON CONFLICT (dedupe_key) DO NOTHING`` insert (F17).
* ``parent_link_events``: the append-only history of every parent-child link
  (SC-1). ``CASCADE`` on both user FKs, because this records every parent link
  in the product and ``RESTRICT`` would change deletion for non-tutoring users.

``downgrade`` drops both tables in reverse.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0046_tutoring_outbox_links"
down_revision: str | Sequence[str] | None = "0045_tutor_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("recipient_user_id", sa.UUID(), nullable=False),
        sa.Column("template", sa.String(60), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="emailoutboxstatus", create_type=False),
            server_default=sa.text("'pending'::emailoutboxstatus"),
            nullable=False,
        ),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name=op.f("fk_email_outbox_recipient_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_outbox")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_email_outbox_dedupe_key")),
    )
    op.create_index(
        "ix_email_outbox_recipient_user_id", "email_outbox", ["recipient_user_id"]
    )
    op.create_index(
        "ix_email_outbox_pending",
        "email_outbox",
        ["created_at", "id"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_email_outbox_sent_at",
        "email_outbox",
        ["sent_at"],
        postgresql_where=sa.text("status = 'sent'"),
    )

    op.create_table(
        "parent_link_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("child_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=False),
        sa.Column(
            "event", postgresql.ENUM(name="parentlinkevent", create_type=False), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["users.id"],
            name=op.f("fk_parent_link_events_child_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["users.id"],
            name=op.f("fk_parent_link_events_parent_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parent_link_events")),
    )
    op.create_index(
        "ix_parent_link_events_child",
        "parent_link_events",
        ["child_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_parent_link_events_parent_id", "parent_link_events", ["parent_id"])


def downgrade() -> None:
    """Downgrade schema: drop both tables in reverse (indexes go with them)."""
    op.drop_table("parent_link_events")
    op.drop_table("email_outbox")
