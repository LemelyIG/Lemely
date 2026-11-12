"""tutoring enums: btree_gist, 16 enum types, 8 notification types and toggles

Revision ID: 0044_tutoring_enums_ext
Revises: 0043_merge_heads
Create Date: 2026-10-25 00:00:00.000000

First revision of the tutoring marketplace (SPEC ``docs/tutoring/SPEC.md`` §a.1,
§a.4, §f). Entirely additive:

* ``CREATE EXTENSION IF NOT EXISTS btree_gist``, the first statement of the
  chain: the GiST exclusion constraints of ``0045`` and ``0047`` compare
  ``uuid``/``smallint`` columns with ``=``, which needs it.
* The sixteen new enum types, values exactly as SPEC §a.1 lists them.
* Eight ``ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS`` (precedent
  ``0039_paper_soft_delete``). Safe inside the migration transaction on
  PostgreSQL 12+ because no statement of this chain uses a new value.
* Eight ``notification_preferences`` booleans, ``NOT NULL DEFAULT true``, one per
  new type, so ``test_notification_type_enum_matches_preference_columns`` keeps
  holding.

``downgrade`` deletes the ``notifications`` rows of the eight new types first
(pre-0044 code cannot load them, precedent 0039), drops the eight columns and
the sixteen types. It **never drops** ``btree_gist`` (it may predate 0044, F35),
and the eight ``notificationtype`` values stay: Postgres has no ``DROP VALUE``
and rebuilding the type would rewrite every dependent column (precedent 0039).
Rolling a Cloud Run revision back across this release needs the same
``DELETE`` first (SPEC §f "Reversibility").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0044_tutoring_enums_ext"
down_revision: str | Sequence[str] | None = "0043_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: SPEC §a.1, in table order.
_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "tutorlistingstate",
        ("draft", "pending_review", "listed", "rejected", "suspended", "closed"),
    ),
    ("tutoringmode", ("virtual", "in_person", "other")),
    (
        "bookingstate",
        ("requested", "accepted", "declined", "cancelled", "completed", "no_show", "expired"),
    ),
    ("bookingparty", ("student", "parent", "tutor", "platform_admin", "system")),
    ("moderationstate", ("none", "pending", "approved", "rejected")),
    ("tutorgrantscope", ("all_subjects_derived",)),
    ("grantrevokereason", ("student", "block", "tutor_suspended", "tutor_closed")),
    ("tutoraccessaction", ("list", "detail")),
    ("tutorapprovaldecision", ("approved", "rejected", "suspended", "reinstated", "closed")),
    (
        "reporttargettype",
        ("tutor_profile", "review", "review_reply", "booking", "booking_note"),
    ),
    (
        "reportreason",
        (
            "safety_concern",
            "inappropriate_content",
            "harassment",
            "spam",
            "fake_profile",
            "disputed_outcome",
            "other",
        ),
    ),
    ("reportstate", ("open", "dismissed", "actioned")),
    (
        "reportresolution",
        (
            "dismissed",
            "content_hidden",
            "tutor_suspended",
            "booking_cancelled",
            "booking_completed",
        ),
    ),
    ("emailoutboxstatus", ("pending", "sent", "failed", "skipped")),
    ("parentlinkevent", ("linked", "unlinked")),
    ("tutoringadminaction", ("report_thread_view", "evidence_open")),
)

#: The eight new ``notificationtype`` values, each also a preference column.
_NOTIFICATION_TYPES: tuple[str, ...] = (
    "booking_request",
    "booking_update",
    "booking_note",
    "tutor_access",
    "tutor_review",
    "tutor_listing",
    "parent_link",
    "tutoring_report",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)

    for value in _NOTIFICATION_TYPES:
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")

    for column in _NOTIFICATION_TYPES:
        op.add_column(
            "notification_preferences",
            sa.Column(column, sa.Boolean(), server_default=sa.true(), nullable=False),
        )


def downgrade() -> None:
    """Downgrade schema. ``btree_gist`` and the notificationtype values stay."""
    quoted = ", ".join(f"'{value}'" for value in _NOTIFICATION_TYPES)
    op.execute(f"DELETE FROM notifications WHERE type IN ({quoted})")

    for column in reversed(_NOTIFICATION_TYPES):
        op.drop_column("notification_preferences", column)

    bind = op.get_bind()
    for name, _values in reversed(_ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
