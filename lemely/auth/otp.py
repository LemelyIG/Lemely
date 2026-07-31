"""In-memory phone-OTP challenge store.

OTP challenges are ephemeral (single-process dev/test server; see decision D1.4),
so they live in a plain dict keyed by phone number rather than a DB table. The
store is made fully deterministic in tests by injecting the ``clock`` (a
zero-arg callable returning an aware :class:`datetime`) and ``rng`` (a
:class:`random.Random`); production wiring passes ``datetime.now(UTC)`` and a
default :class:`random.Random`.

Lifecycle:

* :meth:`OtpStore.issue` generates a zero-padded numeric code, stores a fresh
  :class:`OtpChallenge`, and returns the code so the caller can hand it to an
  :class:`~lemely.auth.sms.SmsProvider`.
* :meth:`OtpStore.verify` consumes the challenge on success, rejects an expired
  or unknown challenge, and counts failed attempts up to ``max_attempts`` before
  locking the challenge out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import random
    from collections.abc import Callable


class OtpResult(Enum):
    """Outcome of an :meth:`OtpStore.verify` call."""

    ok = "ok"
    no_challenge = "no_challenge"
    expired = "expired"
    wrong_code = "wrong_code"
    locked_out = "locked_out"


class OtpRateLimitError(Exception):
    """Raised when a phone re-requests an OTP before the resend cooldown elapses."""


@dataclass(slots=True)
class OtpChallenge:
    """A pending OTP challenge for a single phone number."""

    code: str
    expires_at: datetime
    issued_at: datetime
    attempts: int = 0


class OtpStore:
    """Process-local store of pending OTP challenges keyed by phone number."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        rng: random.Random,
        ttl_seconds: int = 300,
        max_attempts: int = 5,
        code_length: int = 6,
        min_resend_seconds: int = 30,
    ) -> None:
        """Initialise the store with an injected clock and RNG.

        Args:
            clock: Zero-arg callable returning the current aware datetime.
            rng: Source of randomness for code generation (injected for tests).
            ttl_seconds: Lifetime of a challenge before it expires.
            max_attempts: Failed-verify attempts allowed before lockout.
            code_length: Number of digits in a generated code.
            min_resend_seconds: Minimum interval between successive issues for the
                same phone (a re-request cooldown). ``0`` disables the cooldown.
        """
        self._clock = clock
        self._rng = rng
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_attempts = max_attempts
        self._code_length = code_length
        self._min_resend = timedelta(seconds=min_resend_seconds)
        self._challenges: dict[str, OtpChallenge] = {}

    def _generate_code(self) -> str:
        """Return a fresh zero-padded numeric code of the configured length."""
        upper = 10**self._code_length
        return str(self._rng.randrange(upper)).zfill(self._code_length)

    def issue(self, phone: str) -> str:
        """Generate, store, and return a new OTP code for ``phone``.

        A fresh challenge replaces any prior one (new code, reset attempts + TTL),
        but only after the resend cooldown has elapsed since the last live issue.

        Raises:
            OtpRateLimitError: A live (non-expired) challenge was issued more
                recently than ``min_resend_seconds`` ago. Without this throttle a
                caller could reset the attempt counter by re-requesting before
                lockout, defeating the ``max_attempts`` brute-force cap.
        """
        now = self._clock()
        existing = self._challenges.get(phone)
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
        self._challenges[phone] = OtpChallenge(
            code=code,
            expires_at=now + self._ttl,
            issued_at=now,
        )
        return code

    def verify(self, phone: str, code: str) -> OtpResult:
        """Verify ``code`` against the pending challenge for ``phone``.

        Consumes the challenge on success. Returns a discriminated
        :class:`OtpResult` describing the outcome; the challenge is also removed
        on lockout (attempts exhausted) so a fresh ``issue`` is required.
        """
        challenge = self._challenges.get(phone)
        if challenge is None:
            return OtpResult.no_challenge
        if self._clock() >= challenge.expires_at:
            del self._challenges[phone]
            return OtpResult.expired
        if code == challenge.code:
            del self._challenges[phone]
            return OtpResult.ok
        challenge.attempts += 1
        if challenge.attempts >= self._max_attempts:
            del self._challenges[phone]
            return OtpResult.locked_out
        return OtpResult.wrong_code


__all__ = ["OtpChallenge", "OtpRateLimitError", "OtpResult", "OtpStore"]
