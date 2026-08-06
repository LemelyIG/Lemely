"""notification preferences: per-user toggle + quiet-hours settings (G-12)

Revision ID: 0008_notification_preferences
Revises: 0007_quiz_model
Create Date: 2026-08-06 00:00:00.000000

P3.6 chunk B / ``docs/LEMELY_UI_SPEC.md`` §G-12: one new, additive table, one
row per user. One explicit ``NOT NULL BOOLEAN DEFAULT true`` column per
``lemely.db.models.enums.NotificationType`` member (``grade_ready``,
``announcement``, ``streak_warning``, ``study_plan_reminder``,
``at_risk_alert``) rather than a JSONB blob or a row-per-type table — this
keeps every toggle typed, and a sixth notification type later forces an
additive migration that makes an explicit, reviewed decision about its
default. Pinned against the enum by
``tests/test_db_schema.py::test_notification_type_enum_matches_preference_columns``
(the same three-way-pin pattern P3.5 chunk A used for
``questiondifficulty``) so the two can never silently drift apart.

``quiet_hours_start``/``quiet_hours_end`` are both nullable ``TIME`` (no
date/timezone component); both null means "no quiet hours configured" — see
``lemely.db.notification_prefs_repo.NotificationPreferencesService``, which
enforces "both or neither" at the application layer (not representable as a
CHECK constraint change here without touching D1.2's additive-only guarantee
more than this chunk needs to).

This table stores a preference only — it does not deliver, queue, or filter
any actual notification; that is P5's responsibility.

Additive only (D1.2/D1.3): a new table, no existing column touched.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0008_notification_preferences"
down_revision: Union[str, Sequence[str], None] = "0007_quiz_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("grade_ready", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("announcement", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("streak_warning", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "study_plan_reminder",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("at_risk_alert", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_preferences")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("notification_preferences")
