"""teacher team: teacher_members, assistant invites, usage_grants seat FK

Revision ID: 0054_teacher_team
Revises: 0053_billing_payments
Create Date: 2026-11-05 00:00:00.000000

Paymob billing Phase 03 (spec §4.4).

* ``teacher_members``: one row per seat or assistant attached to a teacher, with
  four new enums (``teachermemberkind``, ``teachermemberstatus``, ``assistantrole``,
  ``capperiod``) and CHECKs that tie the columns to ``kind`` and ``status``.
* ``invites``: ``inviterole`` gains ``assistant``; new ``team_teacher_id`` (FK users,
  CASCADE) and ``assistant_role`` columns; ``ck_invites_target`` is widened to accept
  ``team_teacher_id``; ``ck_invites_assistant_shape`` ties both columns to
  ``role = 'assistant'`` (an assistant invite has both, no other invite has either).
  It compares ``role::text`` because the enum value added in this transaction cannot
  be used as an enum literal before commit, so the ``ADD VALUE`` needs no
  ``autocommit_block`` (which would commit every earlier revision of the same run).
  Any later revision that runs in the same transaction as this one, as in a
  base-to-head upgrade, must likewise compare ``role::text`` and never name
  ``'assistant'`` as an ``inviterole`` literal.
* ``usage_grants.teacher_member_id`` gets its FK to ``teacher_members`` (``ON DELETE
  RESTRICT``, stated).
* ``ix_teacher_members_leaves_at``: partial index (``WHERE status = 'leaving'``) for the
  month-end sweep.
* ``ix_school_memberships_user_id`` and ``ix_classes_teacher_id``: neither table had an
  index leading with the lead's id, and the assistant guard's school-data refusal looks
  both up on every request. Both tables already exist, so ``downgrade`` drops just the
  two indexes.

``downgrade`` drops every seat and assistant (the whole ``teacher_members`` table) and
every assistant invite. It refuses to run while any ``usage_grants`` row has a
``teacher_member_id``: such a grant cannot be deleted (``usage_entries`` RESTRICT) or
detached (``ck_usage_grants_seat_link``), so dropping the table would orphan it and the
next upgrade would fail on the foreign key. Postgres cannot drop an enum label, so
``inviterole`` is renamed and recreated with its three original labels, as 0053 does for
``subscriptionstatus``, and the four new enums are dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054_teacher_team"
down_revision: str | Sequence[str] | None = "0053_billing_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("teachermemberkind", ("student_seat", "assistant")),
    ("teachermemberstatus", ("active", "leaving", "removed")),
    ("assistantrole", ("co_teacher", "marker", "viewer")),
    ("capperiod", ("month", "total")),
)

_TARGET_CHECK = "school_id IS NOT NULL OR class_id IS NOT NULL OR child_id IS NOT NULL"


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _restore_invite_role_labels() -> None:
    """Rebuild ``inviterole`` without ``assistant``.

    Postgres cannot drop an enum label, so the type is renamed, recreated with the
    three pre-0054 labels, and ``invites.role`` is re-pointed at it. The caller has
    already deleted every ``assistant`` invite. ``invites.role`` has no default and no
    index or CHECK depends on it once ``ck_invites_assistant_shape`` is dropped.
    """
    op.execute("ALTER TYPE inviterole RENAME TO inviterole_old")
    op.execute("CREATE TYPE inviterole AS ENUM ('student', 'teacher', 'parent')")
    op.execute("ALTER TABLE invites ALTER COLUMN role TYPE inviterole USING role::text::inviterole")
    op.execute("DROP TYPE inviterole_old")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE inviterole ADD VALUE IF NOT EXISTS 'assistant'")
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "teacher_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("teacher_user_id", sa.UUID(), nullable=False),
        sa.Column("member_user_id", sa.UUID(), nullable=False),
        sa.Column("kind", _enum("teachermemberkind"), nullable=False),
        sa.Column("scope_subjects", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("scope_actions", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("role_preset", _enum("assistantrole"), nullable=True),
        sa.Column("permissions", postgresql.JSONB(), nullable=True),
        sa.Column("cap_units", sa.BigInteger(), nullable=True),
        sa.Column(
            "cap_period",
            _enum("capperiod"),
            server_default=sa.text("'month'::capperiod"),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum("teachermemberstatus"),
            server_default=sa.text("'active'::teachermemberstatus"),
            nullable=False,
        ),
        sa.Column("leaves_at", sa.DateTime(timezone=True), nullable=True),
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
            ["teacher_user_id"],
            ["users.id"],
            name=op.f("fk_teacher_members_teacher_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_user_id"],
            ["users.id"],
            name=op.f("fk_teacher_members_member_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teacher_members")),
        sa.UniqueConstraint(
            "teacher_user_id", "member_user_id", name="uq_teacher_members_teacher_member"
        ),
        sa.CheckConstraint(
            "teacher_user_id <> member_user_id", name=op.f("ck_teacher_members_not_self")
        ),
        sa.CheckConstraint(
            "kind <> 'student_seat' OR (scope_subjects IS NOT NULL AND scope_actions IS NOT NULL"
            " AND role_preset IS NULL AND permissions IS NULL)",
            name=op.f("ck_teacher_members_seat_fields"),
        ),
        sa.CheckConstraint(
            "kind <> 'assistant' OR (role_preset IS NOT NULL AND permissions IS NOT NULL"
            " AND scope_subjects IS NULL AND scope_actions IS NULL)",
            name=op.f("ck_teacher_members_assistant_fields"),
        ),
        sa.CheckConstraint(
            "cap_units IS NULL OR cap_units >= 0", name=op.f("ck_teacher_members_cap_nonnegative")
        ),
        sa.CheckConstraint(
            "status <> 'leaving' OR leaves_at IS NOT NULL",
            name=op.f("ck_teacher_members_leaving_has_date"),
        ),
        sa.CheckConstraint(
            "status <> 'active' OR leaves_at IS NULL",
            name=op.f("ck_teacher_members_active_has_no_date"),
        ),
    )
    op.create_index("ix_teacher_members_member_user_id", "teacher_members", ["member_user_id"])
    op.create_index(
        "ix_teacher_members_teacher_kind_status",
        "teacher_members",
        ["teacher_user_id", "kind", "status"],
    )
    op.create_index(
        "ix_teacher_members_leaves_at",
        "teacher_members",
        ["leaves_at"],
        postgresql_where=sa.text("status = 'leaving'"),
    )

    op.add_column(
        "invites",
        sa.Column(
            "team_teacher_id",
            sa.UUID(),
            sa.ForeignKey(
                "users.id", name=op.f("fk_invites_team_teacher_id_users"), ondelete="CASCADE"
            ),
            nullable=True,
        ),
    )
    op.add_column("invites", sa.Column("assistant_role", _enum("assistantrole"), nullable=True))
    op.create_index("ix_invites_team_teacher_id", "invites", ["team_teacher_id"])
    # The assistant guard refuses a lead who holds school data on every request: one
    # lookup per table by the lead's id, which no earlier migration indexes (the unique
    # constraint on school_memberships leads with school_id).
    op.create_index("ix_school_memberships_user_id", "school_memberships", ["user_id"])
    op.create_index("ix_classes_teacher_id", "classes", ["teacher_id"])
    op.drop_constraint(op.f("ck_invites_target"), "invites", type_="check")
    op.create_check_constraint(
        op.f("ck_invites_target"),
        "invites",
        f"{_TARGET_CHECK} OR team_teacher_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_invites_assistant_shape"),
        "invites",
        "(role::text = 'assistant') = (team_teacher_id IS NOT NULL)"
        " AND (role::text = 'assistant') = (assistant_role IS NOT NULL)",
    )

    op.create_foreign_key(
        op.f("fk_usage_grants_teacher_member_id_teacher_members"),
        "usage_grants",
        "teacher_members",
        ["teacher_member_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema: remove everything above and restore the three original labels.

    Refuses while a seat grant exists (see the module docstring), and drops every seat
    and assistant otherwise.
    """
    seat_grant = op.get_bind().execute(
        sa.text("SELECT 1 FROM usage_grants WHERE teacher_member_id IS NOT NULL LIMIT 1")
    )
    if seat_grant.first() is not None:
        raise RuntimeError(
            "Cannot downgrade 0054_teacher_team: usage_grants still has seat grants "
            "(teacher_member_id IS NOT NULL). A seat grant can be neither deleted nor "
            "detached, so dropping teacher_members would orphan it and the next upgrade "
            "would fail. Downgrading past 0054 is not possible once seat grants exist."
        )
    op.drop_constraint(
        op.f("fk_usage_grants_teacher_member_id_teacher_members"),
        "usage_grants",
        type_="foreignkey",
    )
    op.execute("DELETE FROM invites WHERE team_teacher_id IS NOT NULL OR role::text = 'assistant'")
    op.drop_constraint(op.f("ck_invites_assistant_shape"), "invites", type_="check")
    op.drop_constraint(op.f("ck_invites_target"), "invites", type_="check")
    op.create_check_constraint(op.f("ck_invites_target"), "invites", _TARGET_CHECK)
    op.drop_index("ix_invites_team_teacher_id", table_name="invites")
    op.drop_index("ix_classes_teacher_id", table_name="classes")
    op.drop_index("ix_school_memberships_user_id", table_name="school_memberships")
    op.drop_column("invites", "assistant_role")
    op.drop_column("invites", "team_teacher_id")
    op.drop_table("teacher_members")
    _restore_invite_role_labels()
    bind = op.get_bind()
    for name, _values in reversed(_ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
