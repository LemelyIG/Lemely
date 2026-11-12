"""In-memory phone/email-OTP challenge store.

OTP challenges are ephemeral (single-process dev/test server; see decision D1.4),
so they live in a plain dict keyed by ``(channel, address)`` rather than a DB
table. The store is made fully deterministic in tests by injecting the
``clock`` (a zero-arg callable returning an aware :class:`datetime`) and
``rng`` (a :class:`random.Random`); production wiring passes
``datetime.now(UTC)`` and a default :class:`random.Random`.

**Channel is part of a challenge's identity, not just a label on the
address.** A phone challenge for ``"a@example.com"`` and an email challenge
for the same string are two independent entries with independent codes and
independent TTLs — the dict key is the ``(channel, address)`` pair, never the
address alone. ``channel`` defaults to :attr:`OtpChannel.phone` on both
:meth:`OtpStore.issue` and :meth:`OtpStore.verify`, so every pre-existing
positional call site (``AuthService.request_otp``/``verify_otp``, ``lemely.db.seed``,
and every test that predates the email channel) is unchanged.

Lifecycle:

* :meth:`OtpStore.issue` generates a zero-padded numeric code, stores a fresh
  :class:`OtpChallenge`, and returns the code so the caller can hand it to an
  :class:`~lemely.auth.sms.SmsProvider` or
  :class:`~lemely.auth.email.EmailProvider`.
* :meth:`OtpStore.verify` consumes the challenge on success, rejects an expired
  or unknown challenge, and counts failed attempts up to ``max_attempts`` before
  locking the challenge out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import random
    from collections.abc import Callable


class OtpChannel(Enum):
    """Where a challenge's code is delivered; part of the challenge's identity."""

    phone = "phone"
    email = "email"


class OtpResult(Enum):
    """Outcome of an :meth:`OtpStore.verify` call."""

    ok = "ok"
    no_challenge = "no_challenge"
    expired = "expired"
    wrong_code = "wrong_code"
    locked_out = "locked_out"


class OtpRateLimitError(Exception):
    """Raised when an address re-requests an OTP before the resend cooldown elapses."""


class OtpChallengeStore(Protocol):
    """Issue and verify single-use codes, keyed by ``(channel, address)``.

    :class:`OtpStore` (this module, in-memory) and ``DbOtpStore``
    (``lemely.db.otp_repo``, Postgres-backed) both satisfy this Protocol —
    :class:`~lemely.auth.service.AuthService` depends on the Protocol, not on
    either concrete store, so swapping the wiring in
    ``lemely.web.deps.get_auth_service`` is the only change a caller ever needs.
    """

    def issue(self, address: str, *, channel: OtpChannel = OtpChannel.phone) -> str: ...

    def verify(
        self, address: str, code: str, *, channel: OtpChannel = OtpChannel.phone
    ) -> OtpResult: ...


@dataclass(slots=True)
class OtpChallenge:
    """A pending OTP challenge for a single ``(channel, address)`` pair."""

    code: str
    expires_at: datetime
    issued_at: datetime
    attempts: int = 0


class OtpStore:
    """Process-local store of pending OTP challenges keyed by ``(channel, address)``."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        rng: random.Random,
        ttl_seconds: int = 300,
        email_ttl_seconds: int = 600,
        max_attempts: int = 5,
        code_length: int = 6,
        min_resend_seconds: int = 30,
    ) -> None:
        """Initialise the store with an injected clock and RNG.

        Args:
            clock: Zero-arg callable returning the current aware datetime.
            rng: Source of randomness for code generation (injected for tests).
            ttl_seconds: Lifetime of a phone challenge before it expires.
            email_ttl_seconds: Lifetime of an email challenge before it
                expires. Independent of ``ttl_seconds`` — the two channels are
                tuned separately (spec §4.4).
            max_attempts: Failed-verify attempts allowed before lockout.
            code_length: Number of digits in a generated code.
            min_resend_seconds: Minimum interval between successive issues for the
                same ``(channel, address)`` pair (a re-request cooldown). ``0``
                disables the cooldown.
        """
        self._clock = clock
        self._rng = rng
        self._ttl = timedelta(seconds=ttl_seconds)
        self._email_ttl = timedelta(seconds=email_ttl_seconds)
        self._max_attempts = max_attempts
        self._code_length = code_length
        self._min_resend = timedelta(seconds=min_resend_seconds)
        self._challenges: dict[tuple[OtpChannel, str], OtpChallenge] = {}

    def _generate_code(self) -> str:
        """Return a fresh zero-padded numeric code of the configured length."""
        upper = 10**self._code_length
        return str(self._rng.randrange(upper)).zfill(self._code_length)

    def _ttl_for(self, channel: OtpChannel) -> timedelta:
        """Return the configured TTL for ``channel`` — phone and email differ."""
        return self._ttl if channel is OtpChannel.phone else self._email_ttl

    def issue(self, address: str, *, channel: OtpChannel = OtpChannel.phone) -> str:
        """Generate, store, and return a new OTP code for ``(channel, address)``.

        A fresh challenge replaces any prior one for the same channel (new
        code, reset attempts + TTL), but only after the resend cooldown has
        elapsed since the last live issue. A challenge on the other channel
        for the same ``address`` (or the same address as a *different*
        channel's key) is untouched.

        Raises:
            OtpRateLimitError: A live (non-expired) challenge was issued more
                recently than ``min_resend_seconds`` ago. Without this throttle a
                caller could reset the attempt counter by re-requesting before
                lockout, defeating the ``max_attempts`` brute-force cap.
        """
        now = self._clock()
        key = (channel, address)
        existing = self._challenges.get(key)
        if (
            existing is not None
            and now < existing.expires_at
            and now - existing.issued_at < self._min_resend
        ):
            raise OtpRateLimitError(
                f"OTP already sent; retry in "
                f"{int((self._min_resend - (now - existing.issued_at)).total_seconds())}s."
            )
        code = self._generate_code()
        self._challenges[key] = OtpChallenge(
            code=code,
            expires_at=now + self._ttl_for(channel),
            issued_at=now,
        )
        return code

    def verify(
        self, address: str, code: str, *, channel: OtpChannel = OtpChannel.phone
    ) -> OtpResult:
        """Verify ``code`` against the pending challenge for ``(channel, address)``.

        Consumes the challenge on success. Returns a discriminated
        :class:`OtpResult` describing the outcome; the challenge is also removed
        on lockout (attempts exhausted) so a fresh ``issue`` is required. A
        challenge issued on the other channel is invisible here even for the
        same ``address`` string — the two are unrelated entries.
        """
        key = (channel, address)
        challenge = self._challenges.get(key)
        if challenge is None:
            return OtpResult.no_challenge
        if self._clock() >= challenge.expires_at:
            del self._challenges[key]
            return OtpResult.expired
        if code == challenge.code:
            del self._challenges[key]
            return OtpResult.ok
        challenge.attempts += 1
        if challenge.attempts >= self._max_attempts:
            del self._challenges[key]
            return OtpResult.locked_out
        return OtpResult.wrong_code


__all__ = [
    "OtpChallenge",
    "OtpChallengeStore",
    "OtpChannel",
    "OtpRateLimitError",
    "OtpResult",
    "OtpStore",
]
