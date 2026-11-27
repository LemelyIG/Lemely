"""In-process sliding-window rate limiter for anonymous, unauthenticated routes.

:class:`~lemely.auth.cooldown.CooldownStore` (D7.12) is the existing per-key
throttle in this codebase, but it enforces a **single minimum interval between
stamps** — one timestamp per key, "no more than once every N seconds". That
shape does not fit a route that wants "no more than N *events* inside a
rolling window" (e.g. 10 client-error reports per client per minute):
squeezing that requirement onto ``CooldownStore`` would mean either a burst of
exactly one every ``window / limit`` seconds — a much stricter throttle than
"N per window" actually asks for — or a second store built next to it that
copies its shape. This module is that second, small primitive, kept generic
rather than folded into ``lemely.web.routers.client_errors`` because "how many
events land inside a rolling window" is a shape the next anonymous, abusable
route will also want.

**Limitation, stated as plainly as ``CooldownStore``'s own docstring states
its own.** This is a single process-local structure keyed by an arbitrary
string. It is in-process and per-worker — two Cloud Run instances (or two
workers behind a load balancer) each enforce their own window independently,
and every outstanding window is forgotten on restart or redeploy. That is an
accepted simplification: this is a cheap deterrent against casual same-process
abuse and a bound on this process's own memory and log volume, not a security
boundary, and it reproduces the exact trade-off ``CooldownStore`` already
documents for D7.12's routes.

**Bounded memory.** A per-key ``deque`` of timestamps is pruned to the current
window on every access to that key, and a key whose deque empties out this way
is dropped from the map entirely — an attacker revisiting one address does not
grow the map. The map is additionally capped at ``_MAX_TRACKED_KEYS`` distinct
keys; once full, the least-recently-touched key is evicted to make room for a
new one (an :class:`~collections.OrderedDict` tracks recency), so a flood of
distinct, never-repeated keys cannot grow the map without bound either.
"""

from __future__ import annotations

import math
from collections import OrderedDict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class SlidingWindowLimiter:
    """Allow at most ``limit`` events per key inside a rolling ``window_seconds``.

    Unlike :class:`~lemely.auth.cooldown.CooldownStore`, a key here is never
    fully blocked once it exists — it may always make another call once its
    oldest event has aged out of the window, which is what "N per window"
    (rather than "one per interval") means.
    """

    #: Hard cap on distinct tracked keys — see the module docstring's "Bounded
    #: memory" section. Not configurable per instance: every caller of this
    #: primitive wants the same protection against an unbounded key space, and
    #: a size a future route needs to tune would be a sign it wants a
    #: different primitive, not a parameter here.
    _MAX_TRACKED_KEYS = 10_000

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        """Initialise the limiter with an injected clock.

        Args:
            limit: Maximum number of :meth:`allow`-ed events per key inside
                any ``window_seconds``-wide rolling window.
            window_seconds: Width of the rolling window, in seconds.
            clock: Zero-arg callable returning the current time as a float
                (e.g. ``time.monotonic``) — injected, mirroring
                ``CooldownStore``'s clock seam, so a test can drive the window
                deterministically without sleeping.
        """
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._events: OrderedDict[str, deque[float]] = OrderedDict()

    def _pruned(self, key: str, now: float) -> deque[float] | None:
        """Drop ``key``'s expired timestamps; forget the key if none remain.

        Also refreshes ``key``'s position in the recency order the capacity
        eviction below relies on (a key just proven still active is exactly
        the key that eviction must not pick), and returns ``None`` for a key
        with no live events left rather than an empty deque, so every caller
        below checks one thing instead of two.
        """
        events = self._events.get(key)
        if events is None:
            return None
        cutoff = now - self._window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            del self._events[key]
            return None
        self._events.move_to_end(key)
        return events

    def allow(self, key: str) -> bool:
        """Record an event for ``key`` and report whether it is within the limit.

        Check-and-record is one call, not two — mirroring
        :meth:`~lemely.auth.cooldown.CooldownStore.check_and_stamp` — so there
        is no way to ask "would this be allowed" without it counting as the
        attempt. A denied call does not itself record an event.
        """
        now = self._clock()
        events = self._pruned(key, now)
        if events is not None:
            if len(events) >= self._limit:
                return False
            events.append(now)
            self._events.move_to_end(key)
            return True
        if len(self._events) >= self._MAX_TRACKED_KEYS:
            # `_pruned` moves every still-active key to the end on its last
            # touch, so the front of the map is the least-recently-active
            # one — evict it to make room for this new key.
            self._events.popitem(last=False)
        self._events[key] = deque((now,))
        return True

    def retry_after(self, key: str) -> int:
        """Return whole seconds until ``key``'s next :meth:`allow` would pass.

        0 when ``key`` is not currently over the limit — there is nothing to
        wait for. Rounded up so a caller that waits exactly this long is
        guaranteed the window has actually rolled, rather than waking one
        tick early and being denied again.
        """
        now = self._clock()
        events = self._pruned(key, now)
        if events is None or len(events) < self._limit:
            return 0
        remaining = self._window_seconds - (now - events[0])
        return max(1, math.ceil(remaining))


__all__ = ["SlidingWindowLimiter"]
