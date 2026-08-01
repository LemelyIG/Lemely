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
    ) -> None:
        """Insert or update the mirrored row for ``user_id``."""
        ...

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the mirrored user for ``user_id``, or ``None``."""
        ...

    def get_by_phone(self, phone: str) -> User | None:
        """Return the mirrored user with ``phone``, or ``None``."""
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
                    )
                )
            else:
                user.email = email
                user.role = role
                if phone is not None:
                    user.phone = phone
                if display_name is not None:
                    user.display_name = display_name

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


__all__ = ["DbUserMirror", "UserMirror"]
