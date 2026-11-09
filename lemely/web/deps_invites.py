"""Rate limiters for the invite routes: the public preview and the authenticated redeem.

Process-wide, lazily built singletons, the ``lru_cache`` pattern of
``lemely.web.deps_billing``; tests override them through ``app.dependency_overrides``.

**Every limit here is per Cloud Run instance** (``SlidingWindowLimiter`` is
in-process), and the service runs with ``max-instances=3``. The effective ceilings are
therefore up to three times the constants below, and a flood spread over instances
fills each budget separately. They are deterrents, not a security boundary.

**Check-then-record can overshoot.** Each route checks a miss budget (``retry_after``),
looks the code up, then records the miss (``allow``) only on a 404. Those are separate
calls, so concurrent requests that all pass the check before any records can overshoot a
budget by up to the threadpool size per instance. Bounded and accepted: the budgets are
deterrents, and making the pair atomic would hold a lock across a database lookup.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from lemely.web.ratelimit import SlidingWindowLimiter

if TYPE_CHECKING:
    from collections.abc import Callable

# -- Public preview: GET /api/invites/{code} ---------------------------------------

#: Per client IP, every preview call counts: 240 per minute. High on purpose: a whole
#: classroom behind one school NAT previews the same code within a minute and must not
#: lock itself out. The preview no longer returns anything private (no email), so this
#: bounds enumeration of which codes exist, not a secret.
#:
#: Keyed by the same ``_client_ip`` the contact form and the public catalogue use, with
#: the same caveat (``ClientErrorLimiters`` in ``deps.py``): ``per_client`` binds only a
#: caller that arrives through the Cloudflare Worker. A direct caller of the Cloud Run
#: URL can rotate ``X-Forwarded-For`` and get a fresh bucket each time; for that caller
#: the global miss budget below is the only bound.
_INVITE_PREVIEW_PER_CLIENT_LIMIT = 240
_INVITE_PREVIEW_PER_CLIENT_WINDOW_SECONDS = 60.0

#: Per client IP, *misses* only: 20 unknown codes per minute. Without it two IPs at 8
#: requests a second (inside the 240 above) would drain the global miss budget below and
#: block every preview. A client that spends it is refused, valid codes included, until its
#: window rolls; one address cannot take the shared budget past 20 a minute. A real user
#: mistypes a code a few times at most.
_INVITE_PREVIEW_PER_CLIENT_MISS_LIMIT = 20
_INVITE_PREVIEW_PER_CLIENT_MISS_WINDOW_SECONDS = 60.0

#: Global budget of *misses* only: 300 unknown codes per minute across every caller. A
#: request that resolves a real code never consumes it, so a flood of valid previews
#: cannot lock students out; only guessing (unknown codes) spends it. Once spent, the
#: route refuses new requests, hits included, until the window rolls, so a flood of
#: guesses can still hold the route shut for its duration. That is the price of making
#: a sweep of the code space impossible, and a real join rush produces almost no misses.
_INVITE_PREVIEW_GLOBAL_MISS_LIMIT = 300
_INVITE_PREVIEW_GLOBAL_MISS_WINDOW_SECONDS = 60.0

#: Codes an IP has already resolved (a 200) stay "known" to that IP for this long, so a
#: client that has spent its per-IP miss budget (a few typos) can still re-open the code it
#: already used. Only that IP's own miss refusal is bypassed; the 240 per-call limit and the
#: global miss budget still apply. The memory is bounded: at most 8 codes per IP (oldest
#: dropped first) and at most 10 000 IPs (least recently used dropped first).
_INVITE_PREVIEW_RESOLVED_TTL_SECONDS = 60.0
_INVITE_PREVIEW_RESOLVED_CODES_PER_IP = 8
_INVITE_PREVIEW_RESOLVED_MAX_IPS = 10_000

#: The key the global miss limiter tracks its one shared bucket under. Not a real client
#: identity: ``SlidingWindowLimiter`` is keyed by arbitrary strings.
INVITE_PREVIEW_GLOBAL_KEY = "__global__"


class ResolvedCodeMemory:
    """A bounded, per-IP memory of codes that recently previewed successfully (in-process).

    Per Cloud Run instance, like the limiters. Entries expire ``ttl_seconds`` after they
    were last resolved; each IP keeps at most ``codes_per_ip`` codes and the map at most
    ``max_ips`` IPs, evicting the oldest, so a flood of distinct IPs or codes cannot grow
    it without bound. The clock is injected so tests drive expiry.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        codes_per_ip: int,
        max_ips: int,
        clock: Callable[[], float],
    ) -> None:
        self._ttl = ttl_seconds
        self._codes_per_ip = codes_per_ip
        self._max_ips = max_ips
        self._clock = clock
        self._lock = threading.Lock()
        self._by_ip: OrderedDict[str, OrderedDict[str, float]] = OrderedDict()

    def knows(self, ip: str, code: str) -> bool:
        """Whether ``ip`` resolved ``code`` within the TTL."""
        with self._lock:
            codes = self._by_ip.get(ip)
            if codes is None:
                return False
            resolved_at = codes.get(code)
            if resolved_at is None:
                return False
            if self._clock() - resolved_at >= self._ttl:
                del codes[code]
                if not codes:
                    del self._by_ip[ip]
                return False
            return True

    def remember(self, ip: str, code: str) -> None:
        """Record that ``ip`` just resolved ``code``."""
        with self._lock:
            codes = self._by_ip.get(ip)
            if codes is None:
                if len(self._by_ip) >= self._max_ips:
                    self._by_ip.popitem(last=False)
                codes = OrderedDict()
                self._by_ip[ip] = codes
            codes[code] = self._clock()
            codes.move_to_end(code)
            while len(codes) > self._codes_per_ip:
                codes.popitem(last=False)
            self._by_ip.move_to_end(ip)


@dataclass(frozen=True, slots=True)
class InvitePreviewLimiters:
    """The limiters (and one memory) guarding the public preview.

    ``per_client`` throttles one caller (keyed by IP) on every call. ``per_client_misses``
    (keyed by IP) and ``global_misses`` cap unknown-code lookups per caller and across all
    callers: the route checks each before the lookup (``retry_after`` > 0 means spent) and
    records a miss with ``allow`` only on a 404. ``resolved`` remembers the codes an IP
    already resolved: those skip that IP's own miss refusal and nothing else.
    """

    per_client: SlidingWindowLimiter
    per_client_misses: SlidingWindowLimiter
    global_misses: SlidingWindowLimiter
    resolved: ResolvedCodeMemory


@lru_cache(maxsize=1)
def get_invite_preview_limiters() -> InvitePreviewLimiters:
    """The process-wide limiters for ``GET /api/invites/{code}``.

    Wired with ``time.monotonic``; tests override this dependency with limiters built
    on a fake clock, so no test sleeps out a window.
    """
    return InvitePreviewLimiters(
        per_client=SlidingWindowLimiter(
            limit=_INVITE_PREVIEW_PER_CLIENT_LIMIT,
            window_seconds=_INVITE_PREVIEW_PER_CLIENT_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
        per_client_misses=SlidingWindowLimiter(
            limit=_INVITE_PREVIEW_PER_CLIENT_MISS_LIMIT,
            window_seconds=_INVITE_PREVIEW_PER_CLIENT_MISS_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
        global_misses=SlidingWindowLimiter(
            limit=_INVITE_PREVIEW_GLOBAL_MISS_LIMIT,
            window_seconds=_INVITE_PREVIEW_GLOBAL_MISS_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
        resolved=ResolvedCodeMemory(
            ttl_seconds=_INVITE_PREVIEW_RESOLVED_TTL_SECONDS,
            codes_per_ip=_INVITE_PREVIEW_RESOLVED_CODES_PER_IP,
            max_ips=_INVITE_PREVIEW_RESOLVED_MAX_IPS,
            clock=time.monotonic,
        ),
    )


# -- Authenticated redeem: POST /api/invites/{code}/redeem -------------------------

#: Per user, every redeem attempt counts: 30 per 10 minutes. A real user redeems one
#: code; a retry after a typo or a refusal needs a few more.
_INVITE_REDEEM_PER_USER_LIMIT = 30
_INVITE_REDEEM_PER_USER_WINDOW_SECONDS = 600.0

#: Per user, unknown codes only: 10 per hour. The redeem route answers 404 / 403 / 409
#: differently, so an account probing codes learns which exist from the status alone;
#: only the 404s (guesses) are counted, and once spent the user is refused with 429
#: before any lookup. A real user mistypes a code a few times at most.
_INVITE_REDEEM_MISS_LIMIT = 10
_INVITE_REDEEM_MISS_WINDOW_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class InviteRedeemLimiters:
    """The two per-user :class:`SlidingWindowLimiter` instances guarding redeem.

    ``per_user`` counts every attempt (``allow``). ``misses`` is checked before the
    lookup (``retry_after`` > 0 means spent) and records with ``allow`` only on a 404.
    Both are keyed by the authenticated user id.
    """

    per_user: SlidingWindowLimiter
    misses: SlidingWindowLimiter


@lru_cache(maxsize=1)
def get_invite_redeem_limiters() -> InviteRedeemLimiters:
    """The process-wide limiters for ``POST /api/invites/{code}/redeem``."""
    return InviteRedeemLimiters(
        per_user=SlidingWindowLimiter(
            limit=_INVITE_REDEEM_PER_USER_LIMIT,
            window_seconds=_INVITE_REDEEM_PER_USER_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
        misses=SlidingWindowLimiter(
            limit=_INVITE_REDEEM_MISS_LIMIT,
            window_seconds=_INVITE_REDEEM_MISS_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
    )


def reset_invite_singletons() -> None:
    """Clear this module's cached providers; ``deps.reset_singletons`` calls this."""
    get_invite_preview_limiters.cache_clear()
    get_invite_redeem_limiters.cache_clear()


__all__ = [
    "INVITE_PREVIEW_GLOBAL_KEY",
    "InvitePreviewLimiters",
    "InviteRedeemLimiters",
    "ResolvedCodeMemory",
    "get_invite_preview_limiters",
    "get_invite_redeem_limiters",
    "reset_invite_singletons",
]
