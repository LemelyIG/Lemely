"""friendships table + users.friend_code (P5.4 chunk A, D5.1 §8/§9/§10)

Revision ID: 0015_friendships
Revises: 0014_leaderboard_opt_out
Create Date: 2026-08-09 00:00:00.000000

Two additive things, no existing column touched (D1.2/D1.3):

**(a) ``friendships``.** One row per friendship request/relationship, stored
in exactly one direction of record: ``requester_id`` asked, ``addressee_id``
was asked. But "A and B are friends" must be unique regardless of who asked,
and a plain unique index on ``(requester_id, addressee_id)`` would happily
admit both an A→B row and a B→A row for the same pair — two rows, one real
friendship, and now every membership check has to know to look both ways.

The natural fix would be a unique index on
``(LEAST(requester_id, addressee_id), GREATEST(requester_id, addressee_id))``.
Postgres will not allow it: ``LEAST()``/``GREATEST()`` are not ``IMMUTABLE``
over arbitrary input types as far as the index machinery is concerned, so
they cannot appear in an index expression. The workaround this migration
takes instead is to store the canonical ordered pair in two real columns,
``pair_low``/``pair_high`` (always ``min``/``max`` of the two party ids), and
put the actual uniqueness on those: ``uq_friendships_pair``. That alone would
only be as trustworthy as whatever code populates the two extra columns, so
three ``CHECK`` constraints pin them to the parties they must always agree
with:

* ``ck_friendships_no_self`` — a user cannot friend themselves.
* ``ck_friendships_pair_ordered`` — ``pair_low`` is always the smaller id,
  so the pair has one canonical representation, not two.
* ``ck_friendships_pair_matches_parties`` — ``pair_low``/``pair_high`` are
  always exactly ``{requester_id, addressee_id}`` in sorted order, never an
  independent pair of ids that happens to look plausible.

Together these three CHECKs make it structurally impossible for the pair
columns to drift from the parties, which is what makes
``uq_friendships_pair`` a trustworthy uniqueness guarantee rather than a
guarantee about columns nothing keeps honest. This is D5.1 §8's "idempotency
is enforced by the database, not by care" applied to a second table (the
first being ``xp_events.dedupe_key`` in migration ``0013``).

``status`` is the new ``friendshipstatus`` enum: ``pending``/``accepted``
only — see ``lemely.db.models.enums.FriendshipStatus`` for why there is no
third state. ``responded_at`` is set only on acceptance.

**(b) ``users.friend_code``**, ``String(8)``, nullable, unique. ``users`` has
no ``username`` column, so UI spec S-30's "add a friend by username or
invite link" is unbuildable as written; a friend code serves both purposes
(type it in, or share a link that embeds it). It is nullable because it is
minted lazily on first read
(``lemely.db.friend_repo.FriendService.friend_code_for``), not backfilled —
a backfill would have to invent a code for every teacher, parent and admin
who will never use one, for a feature that is student-only. It is unique so
a lookup by code is unambiguous.

Reversible: ``downgrade`` drops the column, the table, and the
``friendshipstatus`` enum type in that order (a table drop does not drop the
Postgres type backing an enum column — the same trap migration
``0006_at_risk_acknowledgements`` documents for ``atriskreason``; this
migration follows that one's pattern exactly, letting ``op.create_table``'s
enum column create the type and dropping it explicitly in ``downgrade``
rather than issuing a separate, redundant ``CREATE TYPE``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015_friendships"
down_revision: str | Sequence[str] | None = "0014_leaderboard_opt_out"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "friendships",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("requester_id", sa.UUID(), nullable=False),
        sa.Column("addressee_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", name="friendshipstatus"),
            server_default=sa.text("'pending'::friendshipstatus"),
            nullable=False,
        ),
        sa.Column("pair_low", sa.UUID(), nullable=False),
        sa.Column("pair_high", sa.UUID(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "requester_id <> addressee_id", name=op.f("ck_friendships_no_self")
        ),
        sa.CheckConstraint("pair_low < pair_high", name=op.f("ck_friendships_pair_ordered")),
        sa.CheckConstraint(
            "(pair_low = requester_id AND pair_high = addressee_id) OR "
            "(pair_low = addressee_id AND pair_high = requester_id)",
            name=op.f("ck_friendships_pair_matches_parties"),
        ),
        sa.ForeignKeyConstraint(
            ["addressee_id"],
            ["users.id"],
            name=op.f("fk_friendships_addressee_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name=op.f("fk_friendships_requester_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_friendships")),
    )
    op.create_index(
        "uq_friendships_pair", "friendships", ["pair_low", "pair_high"], unique=True
    )
    op.create_index(
        "ix_friendships_addressee_id_status", "friendships", ["addressee_id", "status"]
    )
    op.create_index(
        "ix_friendships_requester_id_status", "friendships", ["requester_id", "status"]
    )

    op.add_column("users", sa.Column("friend_code", sa.String(length=8), nullable=True))
    op.create_unique_constraint(op.f("uq_users_friend_code"), "users", ["friend_code"])


def downgrade() -> None:
    """Reverse 0015: drop the column, the table, then the enum type."""
    op.drop_constraint(op.f("uq_users_friend_code"), "users", type_="unique")
    op.drop_column("users", "friend_code")

    op.drop_index("ix_friendships_requester_id_status", table_name="friendships")
    op.drop_index("ix_friendships_addressee_id_status", table_name="friendships")
    op.drop_index("uq_friendships_pair", table_name="friendships")
    op.drop_table("friendships")
    op.execute("DROP TYPE IF EXISTS friendshipstatus")
