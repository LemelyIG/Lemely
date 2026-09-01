"""Mirror of GoTrue users into the application-owned ``public.users`` table.

Every GoTrue user is mirrored 1:1 into ``public.users`` with ``id`` equal to the
auth user id (decision D1.1), so the rest of the app can FK to a table it owns.
:class:`UserMirror` is the Protocol the service depends on; the real
:class:`DbUserMirror` writes through :func:`~lemely.db.session.session_scope`,
and hermetic tests substitute an in-memory fake — this avoids needing Postgres to
unit-test :class:`~lemely.auth.service.AuthService` (the ORM models are Postgres
only).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select

from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.session import session_scope

if TYPE_CHECKING:
    from datetime import datetime

    from lemely.runtime.config import Settings


class UserMirror(Protocol):
    """Upsert and lookup of mirrored ``public.users`` rows."""

    def upsert(
        self,
        user_id: uuid.UUID,
        email: str,
        role: Role,
        phone: str | None = None,
        display_name: str | None = None,
        terms_accepted_at: datetime | None = None,
    ) -> None:
        """Insert or update the mirrored row for ``user_id``.

        ``terms_accepted_at`` (D7.11) is written only when the caller supplies
        one; ``None`` leaves an existing row's value untouched rather than
        clearing it, the same rule ``phone``/``display_name`` already follow.
        That is what lets :meth:`~lemely.auth.service.AuthService.login`
        re-mirror an already-consented user (it never passes this argument at
        all) without ever erasing the consent timestamp
        :meth:`~lemely.auth.service.AuthService.signup` recorded.
        """
        ...

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the mirrored user for ``user_id``, or ``None``."""
        ...

    def get_by_phone(self, phone: str) -> User | None:
        """Return the mirrored user with ``phone``, or ``None``."""
        ...

    def get_by_email(self, email: str) -> User | None:
        """Return the mirrored user with ``email``, or ``None``.

        Backs :meth:`~lemely.auth.service.AuthService.request_password_reset`
        (D7.7), which must look a caller-supplied address up **without**
        signalling whether it matched anything — the anti-enumeration rule is
        upheld by that caller never branching on this method's result in an
        observable way, not by anything this method does itself; it answers
        the lookup honestly either way.
        """
        ...

    def mark_email_verified(self, user_id: uuid.UUID, *, verified_at: datetime) -> None:
        """Stamp ``users.email_verified_at`` for ``user_id`` (D7.4).

        Called exactly once per verification, by
        :meth:`~lemely.auth.service.AuthService.verify_email`, immediately
        after it has redeemed a single-use verification token for this exact
        ``user_id`` — this method does no further checking of its own and
        simply writes the timestamp it is given. A ``user_id`` with no
        mirrored row is a silent no-op rather than a raised error: it should
        be unreachable in practice (verification always names a user
        :meth:`~lemely.auth.service.AuthService.signup` itself just mirrored),
        and this is not the place to invent a new failure mode for the token
        store and the mirror having disagreed about who exists.
        """
        ...


class DbUserMirror:
    """Real :class:`UserMirror` writing through the application database."""

    def __init__(self, settings: Settings) -> None:
        """Initialise against ``settings`` (used to build the DB session)."""
        self._settings = settings

    def upsert(
        self,
        user_id: uuid.UUID,
        email: str,
        role: Role,
        phone: str | None = None,
        display_name: str | None = None,
        terms_accepted_at: datetime | None = None,
    ) -> None:
        """Insert or update the mirrored ``public.users`` row for ``user_id``."""
        with session_scope(self._settings) as session:
            user = session.get(User, user_id)
            if user is None:
                session.add(
                    User(
                        id=user_id,
                        email=email,
                        role=role,
                        phone=phone,
                        display_name=display_name,
                        terms_accepted_at=terms_accepted_at,
                    )
                )
            else:
                user.email = email
                user.role = role
                if phone is not None:
                    user.phone = phone
                if display_name is not None:
                    user.display_name = display_name
                if terms_accepted_at is not None:
                    user.terms_accepted_at = terms_accepted_at

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the mirrored user for ``user_id``, detached from the session."""
        with session_scope(self._settings) as session:
            user = session.get(User, user_id)
            if user is not None:
                session.expunge(user)
            return user

    def get_by_phone(self, phone: str) -> User | None:
        """Return the most-recently-created user with ``phone``, or ``None``."""
        with session_scope(self._settings) as session:
            stmt = select(User).where(User.phone == phone).order_by(User.created_at.desc()).limit(1)
            user = session.scalars(stmt).first()
            if user is not None:
                session.expunge(user)
            return user

    def get_by_email(self, email: str) -> User | None:
        """Return the user with ``email``, detached from the session, or ``None``.

        ``users.email`` is unique (migration ``0002``), so — unlike
        :meth:`get_by_phone`, which orders by recency because phone is not
        unique — this is a single unambiguous lookup.
        """
        with session_scope(self._settings) as session:
            user = session.scalars(select(User).where(User.email == email)).first()
            if user is not None:
                session.expunge(user)
            return user

    def mark_email_verified(self, user_id: uuid.UUID, *, verified_at: datetime) -> None:
        """Stamp ``users.email_verified_at`` for ``user_id``, if the row exists."""
        with session_scope(self._settings) as session:
            user = session.get(User, user_id)
            if user is not None:
                user.email_verified_at = verified_at


__all__ = ["DbUserMirror", "UserMirror"]
