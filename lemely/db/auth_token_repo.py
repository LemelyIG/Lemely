"""``AuthTokenService`` — mint, redeem and revoke single-use auth tokens (D7.7).

Backs :class:`~lemely.db.models.auth_tokens.AuthToken`, the table shared by
email verification and password reset. Read that model's docstring first — it
states the design contract this service implements against: the row never
holds a redeemable credential, single-use is recorded rather than enforced by
deletion, and expiry is an absolute timestamp comparison. What follows here is
the *how*, and four of those choices exist specifically because a token link
sits in an inbox, unlike the 60-second phone OTP ``OtpStore`` guards:

1. **``mint`` returns the plaintext once and never stores it.** The token is
   generated with :func:`secrets.token_urlsafe` (32 bytes of entropy — same
   source already used for temporary passwords elsewhere in this codebase);
   only ``hashlib.sha256(token.encode()).hexdigest()`` is written to
   ``token_hash``. A ``SELECT *`` on ``auth_tokens`` — a backup, a log, a
   support query, a leak — therefore yields nothing a holder could redeem.

2. **``redeem`` matches on ``(token_hash, purpose)`` inside the ``WHERE``
   clause of the lookup, never by fetching on hash alone and comparing
   ``purpose`` afterwards in Python.** ``token_hash`` is already
   database-unique, so this is not about narrowing a multi-row result — it is
   about which fact a *miss* can mean. Because the predicate is the query
   itself, a token minted for ``email_verification`` and presented to the
   ``password_reset`` redemption path produces exactly the same outcome as a
   token that was never minted at all: :class:`TokenNotFound`. A caller
   holding a wrong-purpose token cannot use the response to learn that the
   token exists, only for another purpose — the distinction a Python-level
   ``if row.purpose != purpose`` check would have leaked through a different
   error.

3. **The read that decides redemption and the write that consumes it happen
   in one locked transaction.** :meth:`AuthTokenService.redeem` takes the row
   with ``SELECT ... FOR UPDATE`` and stamps ``used_at`` before releasing the
   lock, so two concurrent redemptions of the same link — someone's mail
   client prefetching the reset URL while they also click it, or a browser
   and a curious proxy racing the same request — serialise: the loser sees
   the first's write and raises :class:`TokenAlreadyUsed`, and it is never
   possible for both to observe ``used_at IS NULL`` and proceed.

4. **The checks inside that lock run in a fixed order: found, then not used,
   then not expired.** An expired-but-unused token and an already-used token
   are different facts about what happened to a link, and the copy a caller
   shows for "this link is old, request another" differs from "this link was
   already used, was that you?" — so the distinction has to survive as far as
   the exception type.

:meth:`AuthTokenService.revoke_all` (rule 5 of the five above) is the
password-change primitive: every currently-unused row for a ``(user,
purpose)`` pair is stamped ``used_at`` in the same way a normal redemption
would be, never deleted — a revoked-but-never-presented token remains
evidence that a reset was in flight when the password changed, exactly as
:class:`~lemely.db.models.auth_tokens.AuthToken`'s docstring asks for.

The constructor takes an injectable ``clock`` — a zero-arg callable returning
the current aware :class:`~datetime.datetime` — so expiry is testable without
sleeping, matching :class:`~lemely.auth.otp.OtpStore` and
:class:`~lemely.auth.cooldown.CooldownStore`. Unlike those two, it defaults to
:func:`datetime.now` (``UTC``) rather than requiring the caller to supply one,
because unlike an OTP challenge or a cooldown window, most callers of this
service have no reason to control time at all; only expiry tests do.

Constructed with a ``sessionmaker`` (mirroring
:class:`~lemely.db.seat_repo.SeatService` and
:class:`~lemely.db.device_repo.DeviceRegistry`) so this is Postgres-testable
without the live GoTrue/email stack.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.db.models import AuthToken

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.models.enums import AuthTokenPurpose

_TOKEN_ENTROPY_BYTES = 32
"""Entropy fed to :func:`secrets.token_urlsafe`. 32 bytes (256 bits) matches the
temporary-password generation already used in ``lemely/web/routers/school.py``
and ``admin.py`` - ample margin against guessing for a credential that is,
unlike a 6-digit OTP, valid until it is used or its (much longer) TTL lapses."""


class AuthTokenError(Exception):
    """Base class for :class:`AuthTokenService` failures."""


class TokenNotFound(AuthTokenError):
    """No live row matches the ``(token_hash, purpose)`` redemption lookup.

    Raised identically whether ``token`` was never minted at all, or was
    minted for a *different* :class:`~lemely.db.models.enums.AuthTokenPurpose`
    than the one presented. That is not a coincidence of error handling: the
    query itself filters on both columns together (rule 2 of the module
    docstring), so from the database's point of view a wrong-purpose token and
    an unknown one are the same "no row matched" outcome, and there is no
    Python-level branch that could tell them apart even if a caller wanted it
    to. A caller must never be able to learn "that token exists, just not for
    this" from the shape of the failure.
    """


class TokenExpired(AuthTokenError):
    """The token was found and is unused, but ``expires_at`` has passed.

    Distinct from :class:`TokenAlreadyUsed` on purpose (rule 4): a caller
    whose link merely went stale should be told to request a new one, not
    asked whether they already used this one.
    """


class TokenAlreadyUsed(AuthTokenError):
    """The token was found but its ``used_at`` was already set.

    Set either by an earlier :meth:`AuthTokenService.redeem` of this exact
    token, or by :meth:`AuthTokenService.revoke_all` invalidating it ahead of
    time (e.g. a password change superseding an outstanding reset link). The
    row is never deleted to produce this outcome - it is what a stamped
    ``used_at`` means both times.
    """


class AuthTokenService:
    """Mint, redeem and revoke single-use email-verification / password-reset tokens.

    See the module docstring for the five rules this class is built around
    (hashed storage, purpose-in-the-lookup, locked read-then-write, ordered
    checks, stamp-don't-delete revocation) - each binding and each tied to a
    specific abuse this table exists to prevent.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        """Wire the service to a session factory.

        Args:
            sessionmaker: Session factory every call opens its own session
                and transaction from - no session is held across calls.
            clock: Zero-arg callable returning the current aware datetime.
                Injected (matching :class:`~lemely.auth.otp.OtpStore` and
                :class:`~lemely.auth.cooldown.CooldownStore`) so expiry is
                testable without sleeping. Defaults to ``datetime.now(UTC)``.
            ttl_seconds: Lifetime, in seconds, of a token minted by
                :meth:`mint` before :meth:`redeem` treats it as expired.
        """
        self._sessionmaker = sessionmaker
        self._clock: Callable[[], datetime] = clock if clock is not None else _utcnow
        self._ttl = timedelta(seconds=ttl_seconds)

    def mint(
        self,
        user_id: uuid.UUID | str,
        purpose: AuthTokenPurpose,
        *,
        ttl_seconds: int | None = None,
    ) -> str:
        """Mint a fresh single-use token for ``user_id``/``purpose`` and return it.

        The return value is the **only** place the plaintext token ever
        exists inside this process; only its SHA-256 hash is written to
        ``auth_tokens.token_hash`` (module docstring rule 1). The caller is
        responsible for getting the plaintext into an email link and nowhere
        else - this method makes no attempt to guess what happens to its
        return value.

        A user may hold more than one live token for the same purpose at once
        (e.g. two reset requests in a row); minting does not invalidate an
        older outstanding token. Callers that want "only the newest link
        works" call :meth:`revoke_all` first.

        Args:
            user_id: Owner of the minted token.
            purpose: Which lifecycle this token belongs to - part of every
                future redemption lookup (module docstring rule 2), never
                inferred from the token itself.
            ttl_seconds: Per-call override of the constructor's ``ttl_seconds``
                default. Verification and reset tokens must not share a
                lifetime - a reset token is a credential that can take an
                account over outright, a verification token is far lower
                risk - so :class:`~lemely.auth.service.AuthService` mints both
                purposes from **one** shared :class:`AuthTokenService`
                instance, passing ``settings.auth.email_verification_ttl_seconds``
                or ``settings.auth.password_reset_ttl_seconds`` here per call,
                rather than requiring the caller to stand up two differently
                configured instances just to get two different lifetimes.
                Defaults to ``None``, which keeps the constructor's
                ``ttl_seconds`` unchanged - every caller that predates this
                parameter (and every call that omits it) is unaffected.

        Returns:
            The plaintext token to embed in the emitted link.
        """
        uid = _as_uuid(user_id)
        token = secrets.token_urlsafe(_TOKEN_ENTROPY_BYTES)
        now = self._clock()
        ttl = self._ttl if ttl_seconds is None else timedelta(seconds=ttl_seconds)
        with self._sessionmaker() as session, session.begin():
            session.add(
                AuthToken(
                    user_id=uid,
                    purpose=purpose,
                    token_hash=_hash_token(token),
                    expires_at=now + ttl,
                )
            )
        return token

    def redeem(self, token: str, purpose: AuthTokenPurpose) -> uuid.UUID:
        """Redeem ``token`` for ``purpose`` and return the id of the user it belongs to.

        The row is located and consumed in one locked transaction (module
        docstring rules 2-4): the lookup filters on ``(token_hash, purpose)``
        together under ``SELECT ... FOR UPDATE``, and ``used_at`` is stamped
        before the lock is released, so two concurrent redemptions of one
        link cannot both succeed. Checks run found, then not-used, then
        not-expired, in that fixed order.

        Raises:
            TokenNotFound: No live row matches ``(token_hash, purpose)`` -
                whether ``token`` was never minted, or was minted for the
                *other* purpose. The two are indistinguishable by design.
            TokenAlreadyUsed: The token was found but already redeemed (or
                revoked via :meth:`revoke_all`).
            TokenExpired: The token was found, is unused, but its
                ``expires_at`` has passed.
        """
        token_hash = _hash_token(token)
        now = self._clock()
        with self._sessionmaker() as session, session.begin():
            stmt = (
                select(AuthToken)
                .where(AuthToken.token_hash == token_hash, AuthToken.purpose == purpose)
                .with_for_update()
            )
            row = session.scalars(stmt).first()
            if row is None:
                raise TokenNotFound("No live token matches this token and purpose.")
            if row.used_at is not None:
                raise TokenAlreadyUsed("Token has already been redeemed.")
            if now >= row.expires_at:
                raise TokenExpired("Token has expired.")
            row.used_at = now
            return row.user_id

    def revoke_all(self, user_id: uuid.UUID | str, purpose: AuthTokenPurpose) -> None:
        """Mark every currently-unused ``purpose`` token for ``user_id`` as used.

        Called on password change, for both purposes, so a compromise that
        prompted the change cannot be extended by an outstanding reset or
        verification link the account holder forgot about (module docstring
        rule 5). Rows are stamped ``used_at``, exactly as a normal
        :meth:`redeem` would, never deleted - a revoked row remains evidence
        that a token was outstanding when the password changed. Already-used
        and already-expired rows are left untouched (there is nothing further
        to revoke), and an account with no live tokens for ``purpose`` makes
        this a no-op rather than an error.
        """
        uid = _as_uuid(user_id)
        now = self._clock()
        with self._sessionmaker() as session, session.begin():
            stmt = select(AuthToken).where(
                AuthToken.user_id == uid,
                AuthToken.purpose == purpose,
                AuthToken.used_at.is_(None),
            )
            for row in session.scalars(stmt):
                row.used_at = now


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest stored in place of ``token`` (rule 1)."""
    return hashlib.sha256(token.encode()).hexdigest()


def _utcnow() -> datetime:
    """Default clock: the current aware UTC datetime."""
    return datetime.now(UTC)


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "AuthTokenError",
    "AuthTokenService",
    "TokenAlreadyUsed",
    "TokenExpired",
    "TokenNotFound",
]
