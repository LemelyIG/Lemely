"""Reusable in-process cooldown store for public auth endpoints.

D7.12 reuses D1.7 item 2's abuse defence — a per-key resend cooldown — for
routes :class:`~lemely.auth.otp.OtpStore` was never built to guard: signup,
``verify-email/resend`` and ``password-reset/request``. ``OtpStore`` already
implements exactly this mechanism, coupled to phone-OTP challenges (its
``min_resend_seconds`` handling inside
:meth:`~lemely.auth.otp.OtpStore.issue`). :class:`CooldownStore` is that
mechanism pulled out to where three unrelated flows can reuse it without
either writing a third dict-and-clock cooldown from scratch or coupling
themselves to the OTP challenge lifecycle just to borrow its throttle.
``OtpStore`` keeps its own inline copy rather than being rewritten to compose
this store — the two are independent call sites that happen to share a shape,
and there is no correctness reason to entangle an OTP challenge (issue,
verify, attempt-lockout) with a generic dependency.

**Limitation, stated plainly.** Like ``OtpStore``, this is a single
process-local ``dict`` keyed by an arbitrary string (an email address, for
every caller D7.12 names). It is **in-process and per-worker**: two workers
behind a load balancer each enforce their own cooldown independently, so a
retry that happens to land on a different worker sees no cooldown at all, and
every outstanding cooldown is forgotten on restart or redeploy. That is an
accepted simplification, not an oversight — D7.12 explicitly puts real
per-IP/infrastructure-backed throttling out of scope, reasoning that
in-process IP limiting behind a proxy is unreliable and not worth faking here.
This store is a cheap deterrent against casual same-process abuse, not a
security boundary, and no caller should treat it as one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable


class CooldownError(Exception):
    """Raised by :meth:`CooldownStore.check_and_stamp` inside the cooldown window.

    :attr:`retry_after` is the number of seconds (a positive float) remaining
    until ``key`` may be stamped again, computed against the same injected
    clock the store uses — exact under a frozen test clock, an honest estimate
    under a real one. Callers that map this to HTTP (D7.12: **429**, mirroring
    the existing OTP-resend route) may surface it directly, e.g. in a
    ``Retry-After`` header or an error body.
    """

    def __init__(self, key: str, retry_after: float) -> None:
        """Record the throttled ``key`` and the ``retry_after`` seconds."""
        self.key = key
        self.retry_after = retry_after
        super().__init__(f"Cooldown active for {key!r}; retry in {retry_after:.0f}s.")


class CooldownStoreProtocol(Protocol):
    """Check-and-stamp a per-key resend cooldown.

    :class:`CooldownStore` (this module, in-memory) and
    :class:`~lemely.db.cooldown_repo.DbCooldownStore` (Postgres-backed) both
    satisfy this Protocol — ``lemely.web.routers.auth`` depends on the
    Protocol, not on either concrete store, so swapping the wiring in
    ``lemely.web.deps.get_signup_and_reset_cooldown_store`` /
    ``get_resend_verification_cooldown_store`` is the only change a caller
    ever needs, matching :class:`~lemely.auth.otp.OtpChallengeStore`'s
    established shape for the sibling OTP store.
    """

    def check_and_stamp(self, key: str) -> None: ...


class CooldownStore:
    """Process-local last-stamped-at store enforcing a minimum interval per key.

    Extracted from :class:`~lemely.auth.otp.OtpStore`'s resend-cooldown logic
    (D1.7 item 2) so the public auth routes D7.12 requires a cooldown on —
    signup, ``verify-email/resend``, ``password-reset/request`` — can each get
    their own instance without a third copy of the same mechanism. See the
    module docstring for the in-process/per-worker limitation this inherits
    from ``OtpStore`` unchanged.
    """

    def __init__(self, *, clock: Callable[[], datetime], min_seconds: int = 30) -> None:
        """Initialise the store with an injected clock.

        Args:
            clock: Zero-arg callable returning the current aware datetime —
                injected (matching :class:`~lemely.auth.otp.OtpStore`) so the
                cooldown window is testable without sleeping.
            min_seconds: Minimum interval between successive successful
                stamps of the same key.
        """
        self._clock = clock
        self._min_interval = timedelta(seconds=min_seconds)
        self._stamped_at: dict[str, datetime] = {}

    def check_and_stamp(self, key: str) -> None:
        """Raise if ``key`` was stamped within the cooldown window, else stamp it now.

        Check and stamp are one call, not two, so there is no way for a caller
        to ask "would I be throttled" without it counting as the attempt —
        mirroring how :meth:`~lemely.auth.otp.OtpStore.issue` folds its own
        cooldown check into the act it can gate rather than exposing a
        separate query.

        Raises:
            CooldownError: ``key`` was last stamped less than ``min_seconds``
                ago. ``retry_after`` on the exception carries the seconds
                remaining. The key is left untouched by a raise — a rejected
                call does not itself extend the window.
        """
        now = self._clock()
        last = self._stamped_at.get(key)
        if last is not None:
            elapsed = now - last
            if elapsed < self._min_interval:
                retry_after = (self._min_interval - elapsed).total_seconds()
                raise CooldownError(key, retry_after)
        self._stamped_at[key] = now


__all__ = ["CooldownError", "CooldownStore", "CooldownStoreProtocol"]
