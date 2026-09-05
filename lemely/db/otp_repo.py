"""``DbOtpStore`` — Postgres-backed :class:`~lemely.auth.otp.OtpChallengeStore` (spec §4.4, D7.7).

Read ``lemely/db/models/otp_challenges.py`` first — it states the storage
contract this class implements against (composite ``(channel, address_hash)``
key, both hashes ``String(64)``, no plaintext column). This module is the
*how*: the concrete store a Cloud Run deployment with more than one instance
wires in place of :class:`~lemely.auth.otp.OtpStore`'s process-local dict, so
a code one instance issues can be verified by another.

Two rules carry over from :class:`~lemely.auth.otp.OtpStore` unchanged — same
resend cooldown, same attempt counting and lockout, same single-use
consumption, same per-channel TTL — and one is new because more than one
process can now reach the same row at once:

1. **Never a raw contact or a redeemable code in a column, a log, or an
   exception message (D7.7).** :func:`_hash` — plain
   ``hashlib.sha256(value.encode()).hexdigest()`` — is applied to both the
   address and the code before either reaches a query; :attr:`OtpRateLimitError`'s
   message (mirroring :class:`~lemely.auth.otp.OtpStore`'s own wording) names
   neither. A database read — a backup, a support query, a leak — yields
   nothing that identifies who a challenge was sent to or that would verify
   it.

2. **``issue`` and ``verify`` each take the row with ``SELECT ... FOR UPDATE``
   inside one transaction, so the resend cooldown, the attempt counter, and
   single-use consumption hold across instances exactly as they hold across
   threads today.** Two instances calling :meth:`verify` on the same
   ``(channel, address)`` at nearly the same moment serialise on that row
   lock: whichever transaction commits first deletes the row (success,
   expiry, or lockout all delete it), and the second transaction's ``SELECT
   ... FOR UPDATE`` — which blocks until the first commits — then finds no
   row and returns :data:`~lemely.auth.otp.OtpResult.no_challenge`. There is
   no window in which both observe a live, unconsumed challenge; the database
   arbitrates the race, not a read-then-write in this process (the same
   pattern :meth:`~lemely.db.teacher_paper_repo.TeacherPaperRepository.claim_run`
   and :meth:`~lemely.db.auth_token_repo.AuthTokenService.redeem` use for
   exactly this reason).

``issue`` also opportunistically sweeps every expired row on each call
(``DELETE ... WHERE expires_at < now``), table-wide rather than scoped to the
caller's own key — there is no scheduler in this deployment
(``docs/deployment.md`` §5.2), so this is the only place stale rows are ever
removed. A row a caller never revisits (an abandoned challenge nobody
verifies or reissues) is cleaned up the next time *any* address issues a
challenge, not left to accumulate forever.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import select

from lemely.auth.otp import OtpChannel, OtpRateLimitError, OtpResult
from lemely.db.models.otp_challenges import OtpChallenge

if TYPE_CHECKING:
    import random
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker


def _hash(value: str) -> str:
    """SHA-256 hex digest of ``value`` (D7.7) — the only form an address or code takes here."""
    return hashlib.sha256(value.encode()).hexdigest()


class DbOtpStore:
    """Postgres-backed :class:`~lemely.auth.otp.OtpChallengeStore` (spec §4.4, D7.7).

    See the module docstring for the concurrency and hashing guarantees. This
    class is otherwise a drop-in replacement for
    :class:`~lemely.auth.otp.OtpStore`: same constructor keyword shape, same
    ``(channel, address)`` identity, same discriminated
    :class:`~lemely.auth.otp.OtpResult` outcomes — ``tests/test_otp_store_parity.py``
    proves the two agree on every case that matters across processes.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime],
        rng: random.Random,
        ttl_seconds: int = 300,
        email_ttl_seconds: int = 600,
        max_attempts: int = 5,
        code_length: int = 6,
        min_resend_seconds: int = 30,
    ) -> None:
        """Wire the store to a session factory.

        Args:
            session_factory: Session factory every call opens its own session
                and transaction from — no session is held across calls.
            clock: Zero-arg callable returning the current aware datetime.
                Injected (matching :class:`~lemely.auth.otp.OtpStore`) so
                expiry and the resend cooldown are testable without sleeping.
            rng: Source of randomness for code generation (injected for
                deterministic tests, matching :class:`~lemely.auth.otp.OtpStore`).
            ttl_seconds: Lifetime of a phone challenge before it expires.
            email_ttl_seconds: Lifetime of an email challenge before it
                expires. Independent of ``ttl_seconds`` (spec §4.4).
            max_attempts: Failed-verify attempts allowed before lockout.
            code_length: Number of digits in a generated code.
            min_resend_seconds: Minimum interval between successive issues for
                the same ``(channel, address)`` pair. ``0`` disables the
                cooldown.
        """
        self._sm = session_factory
        self._clock = clock
        self._rng = rng
        self._ttl = timedelta(seconds=ttl_seconds)
        self._email_ttl = timedelta(seconds=email_ttl_seconds)
        self._max_attempts = max_attempts
        self._code_length = code_length
        self._min_resend = timedelta(seconds=min_resend_seconds)

    def _generate_code(self) -> str:
        """Return a fresh zero-padded numeric code of the configured length."""
        upper = 10**self._code_length
        return str(self._rng.randrange(upper)).zfill(self._code_length)

    def _ttl_for(self, channel: OtpChannel) -> timedelta:
        """Return the configured TTL for ``channel`` — phone and email differ."""
        return self._ttl if channel is OtpChannel.phone else self._email_ttl

    def issue(self, address: str, *, channel: OtpChannel = OtpChannel.phone) -> str:
        """Generate, store, and return a new OTP code for ``(channel, address)``.

        A fresh challenge replaces any prior one for the same ``(channel,
        address_hash)`` row (new code, reset attempts and TTL), but only
        after the resend cooldown has elapsed since the last live issue.
        Locks the row (if any) with ``SELECT ... FOR UPDATE`` for the
        duration of the check-and-write, so two concurrent re-issues for the
        same address cannot both observe the cooldown as elapsed and both
        reset the attempt counter.

        Raises:
            OtpRateLimitError: A live (non-expired) challenge was issued more
                recently than ``min_resend_seconds`` ago. The message names
                neither the address nor the code (D7.7).
        """
        now = self._clock()
        key = _hash(address)
        with self._sm.begin() as session:
            session.execute(sa.delete(OtpChallenge).where(OtpChallenge.expires_at < now))
            row = session.execute(
                select(OtpChallenge)
                .where(OtpChallenge.channel == channel, OtpChallenge.address_hash == key)
                .with_for_update()
            ).scalar_one_or_none()
            if row is not None and now < row.expires_at and now - row.issued_at < self._min_resend:
                remaining = int((self._min_resend - (now - row.issued_at)).total_seconds())
                raise OtpRateLimitError(f"OTP already sent; retry in {remaining}s.")
            code = self._generate_code()
            if row is None:
                session.add(
                    OtpChallenge(
                        channel=channel,
                        address_hash=key,
                        code_hash=_hash(code),
                        expires_at=now + self._ttl_for(channel),
                        issued_at=now,
                        attempts=0,
                    )
                )
            else:
                row.code_hash = _hash(code)
                row.expires_at = now + self._ttl_for(channel)
                row.issued_at = now
                row.attempts = 0
        return code

    def verify(
        self, address: str, code: str, *, channel: OtpChannel = OtpChannel.phone
    ) -> OtpResult:
        """Verify ``code`` against the pending challenge for ``(channel, address)``.

        Locks the row with ``SELECT ... FOR UPDATE`` for the duration of the
        check-and-consume, so two concurrent verifies of the same challenge
        cannot both succeed (module docstring, point 2): the loser's lookup
        blocks until the winner's transaction — which deleted the row —
        commits, then finds nothing and reports
        :data:`~lemely.auth.otp.OtpResult.no_challenge`.

        Consumes the challenge (deletes the row) on success, on expiry, and
        on lockout; a wrong code short of the limit leaves the row in place
        with its attempt counter incremented.
        """
        now = self._clock()
        key = _hash(address)
        with self._sm.begin() as session:
            row = session.execute(
                select(OtpChallenge)
                .where(OtpChallenge.channel == channel, OtpChallenge.address_hash == key)
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                return OtpResult.no_challenge
            if now >= row.expires_at:
                session.delete(row)
                return OtpResult.expired
            if hmac.compare_digest(row.code_hash, _hash(code)):
                session.delete(row)
                return OtpResult.ok
            row.attempts += 1
            if row.attempts >= self._max_attempts:
                session.delete(row)
                return OtpResult.locked_out
            return OtpResult.wrong_code


__all__ = ["DbOtpStore"]
