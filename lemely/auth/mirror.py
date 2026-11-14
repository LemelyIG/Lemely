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

import structlog
from sqlalchemy import select, update

from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.session import session_scope
from lemely.db.usage_catalogue_repo import grant_signup_allowance

if TYPE_CHECKING:
    from datetime import datetime

    from lemely.runtime.config import Settings

log = structlog.get_logger(__name__)


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
        """Stamp ``users.email_verified_at`` for ``user_id`` (D7.4), keeping the first instant.

        Called by both halves of §4.4's link-and-code pair —
        :meth:`~lemely.auth.service.AuthService.verify_email` (having redeemed
        a single-use verification token) and
        :meth:`~lemely.auth.service.AuthService.verify_email_code` (having
        verified the email-channel OTP) — each immediately after establishing
        the fact for this exact ``user_id``. The two credentials are
        independent, and a resend mints new ones, so an account may
        legitimately reach here more than once. **Only the first call writes:**
        the stamp is set while it is ``NULL`` and never moved afterwards,
        because tutoring outcome statistics count a student only if their email
        was verified at or before their first session (ADR-T04), and a later
        re-verification must not change that. Idempotent either way. A
        ``user_id`` with no
        mirrored row is a silent no-op rather than a raised error: it should
        be unreachable in practice (verification always names a user
        :meth:`~lemely.auth.service.AuthService.signup` itself just mirrored),
        and this is not the place to invent a new failure mode for the token
        store and the mirror having disagreed about who exists.

        The first call also issues the role's billing signup grant (spec §2.1);
        a grant failure is logged and never fails the verification.
        """
        ...

    def set_avatar_path(self, user_id: uuid.UUID, path: str | None) -> None:
        """Set or clear ``users.avatar_path`` for ``user_id``.

        ``path`` is ``None`` to clear the avatar (``DELETE /api/me/avatar``) or
        an object-storage path to set one (``POST /api/me/avatar``) — never a
        URL (see :attr:`~lemely.db.models.users.User.avatar_path`). A
        ``user_id`` with no mirrored row is a silent no-op, matching
        :meth:`mark_email_verified`: both routes authenticate through a token
        whose ``sub`` was itself mirrored at signup, so a missing row here
        should be unreachable rather than a new failure mode to invent.
        """
        ...

    def set_timezone(self, user_id: uuid.UUID, zone: str | None, *, explicit: bool) -> None:
        """Set, follow, or clear ``users.timezone`` (push-delivery spec §3).

        ``explicit=True`` stores ``zone`` and marks it chosen. ``explicit=False``
        with a ``zone`` is the client's device auto-detect and is written only
        while nothing was chosen — a plane must never undo a deliberate choice.
        ``explicit=False`` with ``zone=None`` clears the choice so auto-detect
        resumes. Validation (a resolvable IANA name, at most 64 characters) is
        the route's job; this writes what it is given. A ``user_id`` with no
        mirrored row is a silent no-op, matching :meth:`set_avatar_path`.
        """
        ...

    def set_phone(self, user_id: uuid.UUID, phone: str) -> None:
        """Replace ``users.phone`` with ``phone`` (UD-11).

        ``phone`` is already validated and in E.164 form: the route runs
        :func:`lemely.core.phone.validate_phone` and this writes what it is given. Unlike
        :meth:`upsert`, an existing value is overwritten, because this is the user changing it.
        A ``user_id`` with no mirrored row is a silent no-op, matching :meth:`set_timezone`.
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

    def get_by_email(self, email: str) -> User | None:
        """Return the user with ``email``, detached from the session, or ``None``.

        ``users.email`` is unique (migration ``0002``), so — unlike
        a phone, which is not unique and is
        deliberately never a lookup key — this is a single unambiguous lookup.
        """
        with session_scope(self._settings) as session:
            user = session.scalars(select(User).where(User.email == email)).first()
            if user is not None:
                session.expunge(user)
            return user

    def mark_email_verified(self, user_id: uuid.UUID, *, verified_at: datetime) -> None:
        """Stamp ``users.email_verified_at`` for ``user_id`` unless it is already set.

        One conditional ``UPDATE … WHERE email_verified_at IS NULL``: two
        verifications racing cannot both write, and the first instant is kept.

        Billing spec §2.1 (free start): the call that wins the stamp also issues the
        role's signup grant, in the same transaction. The grant is idempotent per
        account, and it runs in a savepoint so a ledger failure is logged and the
        verification still commits.
        """
        with session_scope(self._settings) as session:
            role = session.execute(
                update(User)
                .where(User.id == user_id, User.email_verified_at.is_(None))
                .values(email_verified_at=verified_at)
                .returning(User.role)
            ).scalar_one_or_none()
            if role is None:
                return
            # Lock order: the UPDATE above holds the ``users`` row lock, then the
            # ledger takes its advisory lock inside ``issue_grant``. Keep that order
            # everywhere: users row first, ledger advisory lock second.
            # The teacher's 30-day expiry counts from this verification instant
            # (``verified_at``), not from signup.
            try:
                with session.begin_nested():
                    grant_signup_allowance(session, user_id=user_id, role=role, now=verified_at)
            except Exception:
                log.exception("signup_grant_failed", user_id=str(user_id))

    def set_avatar_path(self, user_id: uuid.UUID, path: str | None) -> None:
        """Set or clear ``users.avatar_path`` for ``user_id``, if the row exists."""
        with session_scope(self._settings) as session:
            user = session.get(User, user_id)
            if user is not None:
                user.avatar_path = path

    def set_timezone(self, user_id: uuid.UUID, zone: str | None, *, explicit: bool) -> None:
        """Set, follow, or clear ``users.timezone``, if the row exists."""
        with session_scope(self._settings) as session:
            user = session.get(User, user_id)
            if user is None:
                return
            if explicit:
                user.timezone = zone
                user.timezone_is_explicit = True
            elif zone is None:
                user.timezone = None
                user.timezone_is_explicit = False
            elif not user.timezone_is_explicit:
                user.timezone = zone

    def set_phone(self, user_id: uuid.UUID, phone: str) -> None:
        """Replace ``users.phone``, if the row exists."""
        with session_scope(self._settings) as session:
            user = session.get(User, user_id)
            if user is not None:
                user.phone = phone


__all__ = ["DbUserMirror", "UserMirror"]
