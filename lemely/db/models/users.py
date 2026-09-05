"""ORM models for user identity, parent-child links, and device sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import FriendshipStatus, Role, TimestampMixin


class User(TimestampMixin, Base):
    """Platform user whose ``id`` mirrors ``auth.users.id`` in Supabase.

    The ``id`` is supplied by the application at signup (not server-generated)
    so it can be kept in sync with the Supabase auth system without a
    cross-schema foreign key.
    """

    __tablename__ = "users"
    __table_args__ = (
        sa.Index("ix_users_email", "email"),
        sa.Index("ix_users_role", "role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        # No server_default: caller supplies the auth.users id.
    )
    email: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    role: Mapped[Role] = mapped_column(
        sa.Enum(Role, name="role"),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    phone: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    email_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Migration ``0021`` (D7.4). Set when the account redeems an
    ``email_verification`` token. Verification state lives **here**, not in
    GoTrue: ``admin_create_user`` keeps ``email_confirm: True`` so sign-in
    always succeeds, because UI spec §G-07 requires "a way to continue
    into a limited preview of the app rather than a hard wall" and GoTrue-native
    confirmation *is* that wall. NULL gates exactly one route —
    ``POST /api/student/correct``, the Gemini spend (D7.5) — and nothing else.

    (That sentence says "sign-in" rather than naming the OAuth grant type on
    purpose. ``tests/unit/dataHandling.test.ts`` reads this module and asserts
    it never once mentions the secret the /data page promises is not kept on
    an account row — a claim only as true as this file. The check is crude on
    its face and right in effect: that noun has no business here, and avoiding
    it costs one clearer sentence.)

    Note this is unrelated to ``is_active``, which is dead: it is written
    nowhere and read nowhere, and activation in this product is a
    *subscription* concept (``/api/admin/activations/*``), not a user one."""

    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Migration ``0021`` (D7.11). Set at signup when the G-03 consent box is
    ticked. The consent is to ``/data`` — the data-handling page that actually
    exists — not to a terms-of-service document, because this repository has
    none and PRODUCT.md forbids fabricating one. Nullable because every account
    created before this migration (and every parent, who signs up through no
    form at all) has no such timestamp and inventing one would be a lie about a
    consent nobody gave."""

    avatar_path: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """Migration ``0028``. Object-storage path of the caller's profile picture
    (``avatars/{user_id}/{uuid}.{ext}``), or ``None`` for no avatar set. Never a
    URL — a signed URL is derived from this path per-request
    (:func:`~lemely.web.routers.me._avatar_url_for`), so the bucket, backend, and
    signed-URL TTL can all change without touching stored rows."""

    locale: Mapped[str] = mapped_column(sa.String, nullable=False, server_default=sa.literal("en"))
    friend_code: Mapped[str | None] = mapped_column(sa.String(8), nullable=True, unique=True)
    """Migration ``0015`` (P5.4 chunk A). ``users`` has no ``username`` column,
    so UI spec S-30's "add a friend by username or invite link" is
    unbuildable as written; a friend code serves both (type it, or share a
    link containing it). Nullable because it is minted lazily on first read
    (:meth:`~lemely.db.friend_repo.FriendService.friend_code_for`) rather than
    backfilled — a backfill would have to invent a code for every teacher,
    parent and admin who will never use one. Unique so a lookup by code is
    unambiguous."""

    # Relationships (back-references populated by child models)
    devices: Mapped[list[Device]] = relationship(
        "Device", back_populates="user", cascade="all, delete-orphan"
    )
    parent_links: Mapped[list[ParentChildLink]] = relationship(
        "ParentChildLink",
        foreign_keys="ParentChildLink.parent_id",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    child_links: Mapped[list[ParentChildLink]] = relationship(
        "ParentChildLink",
        foreign_keys="ParentChildLink.child_id",
        back_populates="child",
        cascade="all, delete-orphan",
    )


class ParentChildLink(TimestampMixin, Base):
    """Associates a parent user with a child (student) user."""

    __tablename__ = "parent_child_links"
    __table_args__ = (
        sa.UniqueConstraint(
            "parent_id",
            "child_id",
            name="uq_parent_child_links_parent_id_child_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    parent: Mapped[User] = relationship(
        "User", foreign_keys=[parent_id], back_populates="parent_links"
    )
    child: Mapped[User] = relationship(
        "User", foreign_keys=[child_id], back_populates="child_links"
    )


class Friendship(TimestampMixin, Base):
    """One friendship request/relationship between two students (P5.4, D5.1).

    ``requester_id``/``addressee_id`` record who asked whom — one row, one
    direction of record. ``pair_low``/``pair_high`` are a *second*, derived
    representation of the same two parties, always the smaller/larger of the
    two ids: the canonical, order-independent pair.

    **Why both representations exist.** "A and B are friends" must be unique
    regardless of who asked — a plain unique constraint on
    ``(requester_id, addressee_id)`` would happily admit both an A→B and a
    B→A row for the same pair. The natural fix, a unique index on
    ``(LEAST(requester_id, addressee_id), GREATEST(requester_id,
    addressee_id))``, is not available: Postgres cannot index the output of
    ``LEAST()``/``GREATEST()`` because they are not ``IMMUTABLE`` over
    arbitrary types in an index expression. Storing the canonical pair in two
    real columns sidesteps that, and ``uq_friendships_pair`` (migration
    ``0015``) makes the reciprocal row a rejected insert rather than a
    leaderboard-style anomaly. Three ``CHECK`` constraints
    (``ck_friendships_no_self``, ``ck_friendships_pair_ordered``,
    ``ck_friendships_pair_matches_parties``) make it impossible for
    ``pair_low``/``pair_high`` to disagree with ``requester_id``/
    ``addressee_id`` — this is D5.1 §8's "idempotency is enforced by the
    database, not by care" applied to a second table.

    ``status``/``responded_at``: ``pending`` until the addressee accepts;
    ``responded_at`` is set only on acceptance. There is no ``declined``
    status — see :class:`~lemely.db.models.enums.FriendshipStatus`.
    """

    __tablename__ = "friendships"
    __table_args__ = (
        sa.CheckConstraint("requester_id <> addressee_id", name="ck_friendships_no_self"),
        sa.CheckConstraint("pair_low < pair_high", name="ck_friendships_pair_ordered"),
        sa.CheckConstraint(
            "(pair_low = requester_id AND pair_high = addressee_id) OR "
            "(pair_low = addressee_id AND pair_high = requester_id)",
            name="ck_friendships_pair_matches_parties",
        ),
        sa.Index("uq_friendships_pair", "pair_low", "pair_high", unique=True),
        sa.Index("ix_friendships_addressee_id_status", "addressee_id", "status"),
        sa.Index("ix_friendships_requester_id_status", "requester_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    addressee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[FriendshipStatus] = mapped_column(
        sa.Enum(FriendshipStatus, name="friendshipstatus"),
        nullable=False,
        server_default=FriendshipStatus.pending.value,
    )
    pair_low: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    """``min(requester_id, addressee_id)`` — see class docstring."""
    pair_high: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    """``max(requester_id, addressee_id)`` — see class docstring."""
    responded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """Set only when ``status`` transitions to ``accepted``; ``NULL`` while pending."""


class Device(TimestampMixin, Base):
    """Session/device registry entry for a user.

    The application enforces a max-3-concurrent-device policy by revoking the
    oldest entry; this table only stores the records.
    """

    __tablename__ = "devices"
    __table_args__ = (
        sa.Index("ix_devices_user_id_revoked_at", "user_id", "revoked_at"),
        sa.Index("ix_devices_user_id_client_device_id", "user_id", "client_device_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stable opaque identifier the client (SPA) mints once and stores locally, so a
    # re-login on the same device reuses its row instead of consuming a new slot
    # (D1.11). Nullable: a client that supplies none gets a fresh device per login.
    client_device_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    device_label: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    refresh_token_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="devices")


__all__ = ["Device", "Friendship", "ParentChildLink", "User"]
