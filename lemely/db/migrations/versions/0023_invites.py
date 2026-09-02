"""invites: redeemable school/class invite codes (D7.3)

Revision ID: 0023_invites
Revises: 0022_auth_tokens
Create Date: 2026-08-25 00:00:00.000000

One additive table, ``invites``, backed by a new ``inviterole`` enum
(``student`` / ``teacher``). Codes coexist with the existing direct-create
endpoints rather than replacing them (D7.3): direct-create suits bulk
provisioning from a roster an admin already holds, codes are what UI spec
G-08 describes and what makes a seat feel like joining a school rather than
receiving a password over WhatsApp. Neither subsumes the other.

``inviterole`` is deliberately narrower than the five-member ``role`` enum:
an invite may only ever produce a ``student`` or a ``teacher``, and reusing
``role`` here would put ``platform_admin`` in the type system of a code an
anonymous caller redeems. A narrower type cannot express that mistake.

``school_id``/``class_id`` are both nullable — an invite targets a school
**or** a class, never necessarily both — and ``ck_invites_target`` makes an
invite pointing at neither a rejected insert rather than a case the
redemption path has to defend against (the same "idempotency is enforced by
the database, not by care" rule ``ck_friendships_no_self`` and friends
already follow, migration ``0015``). ``seat_id`` is a nullable back-reference
to the specific seat a school invite reserves at mint time; ``ON DELETE SET
NULL`` because a seat being freed later must not delete the invite's audit
trail. ``redeemed_by``/``redeemed_at`` mark consumption rather than deleting
the row, for the same reason ``auth_tokens.used_at`` does (migration
``0022``): a school admin asking "did that code ever get used, and by whom"
is a question the schema should be able to answer. ``ix_invites_code`` is a
unique index — it is both the redemption lookup and what makes ``code`` a
real uniqueness guarantee, not just a convention.

Reversible: ``downgrade`` drops the table, then drops the ``inviterole``
Postgres type explicitly. A table drop does not drop the type backing an enum
column — the same trap ``0006_at_risk_acknowledgements`` documents for
``atriskreason`` and ``0022_auth_tokens`` follows for ``authtokenpurpose``.
This migration lets ``op.create_table``'s enum column create the type
implicitly and drops it explicitly in ``downgrade`` rather than issuing a
separate, redundant ``CREATE TYPE``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0023_invites"
down_revision: str | Sequence[str] | None = "0022_auth_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "invites",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("student", "teacher", name="inviterole"),
            nullable=False,
        ),
        sa.Column("school_id", sa.UUID(), nullable=True),
        sa.Column("class_id", sa.UUID(), nullable=True),
        sa.Column("seat_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_by", sa.UUID(), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "school_id IS NOT NULL OR class_id IS NOT NULL", name=op.f("ck_invites_target")
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_invites_class_id_classes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_invites_created_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by"],
            ["users.id"],
            name=op.f("fk_invites_redeemed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_invites_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["seat_id"],
            ["seats.id"],
            name=op.f("fk_invites_seat_id_seats"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
    )
    op.create_index("ix_invites_code", "invites", ["code"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("invites")
    sa.Enum(name="inviterole").drop(op.get_bind(), checkfirst=False)
