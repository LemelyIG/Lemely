"""Unit tests for :class:`~lemely.web.ratelimit.SlidingWindowLimiter` (fake clock).

``tests/test_client_errors.py`` exercises this class only through the two
limiters ``POST /api/client-errors`` wires up (10/min per client, 300/min
global), which never touches the window-expiry ``popleft``, the
drop-key-when-empty path, the ``_MAX_TRACKED_KEYS`` LRU eviction, or a
``retry_after`` of exactly 0 — all load-bearing lines this module's own
docstring promises ("Bounded memory"). This file drives the class directly,
mirroring ``tests/test_auth_cooldown.py``'s own deterministic-clock
convention for :class:`~lemely.auth.cooldown.CooldownStore`, so nothing here
sleeps out a real window.
"""

from __future__ import annotations

from lemely.web.ratelimit import SlidingWindowLimiter


class FakeClock:
    """A settable clock: ``advance`` moves it forward for window tests.

    Starts at an arbitrary large value (not 0) so ``now - window_seconds``
    never goes negative in a test — a stand-in for "some time after process
    start", mirroring how ``time.monotonic`` behaves in production.
    """

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ── allow(): the (limit+1)th call, and recovery once the window rolls ──────


def test_over_limit_call_is_denied_then_allowed_once_the_oldest_event_expires() -> None:
    """Events land at distinct timestamps, so the window rolls one at a time.

    Also exercises the "prune some, not all" branch inside ``_pruned``: at
    t=10 only the event at t=0 has aged out of the 10s window, leaving the
    t=3 and t=6 events behind it — a partial prune, not the whole key
    dropping out of the map.
    """
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=3, window_seconds=10.0, clock=clock)

    assert limiter.allow("k") is True  # t=0
    clock.advance(3.0)
    assert limiter.allow("k") is True  # t=3
    clock.advance(3.0)
    assert limiter.allow("k") is True  # t=6 — 3 events in window: 0, 3, 6

    assert limiter.allow("k") is False  # still 3 in-window events

    clock.advance(4.0)  # t=10: cutoff=0, so only the t=0 event ages out
    assert limiter.allow("k") is True  # 2 events remain (3, 6) — under limit


def test_denied_call_does_not_itself_record_an_event() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=1, window_seconds=10.0, clock=clock)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False  # denied
    clock.advance(1.0)
    assert limiter.allow("k") is False  # still denied — the rejected call above didn't count


def test_distinct_keys_do_not_interfere() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=1, window_seconds=10.0, clock=clock)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True  # separate bucket — unaffected by "a"


# ── Bounded memory: a fully-expired key is dropped from the map ────────────


def test_key_with_all_events_expired_is_removed_from_the_map() -> None:
    """``retry_after`` reads via ``_pruned`` too, without re-recording an event.

    Using ``allow`` here would immediately re-add a fresh event after
    pruning, masking the thing this test is actually about — that a key with
    no live events left is dropped from ``_events`` entirely, not kept
    around as an empty deque.
    """
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=5, window_seconds=10.0, clock=clock)
    limiter.allow("k")
    assert "k" in limiter._events

    clock.advance(10.0)  # the only event ages out exactly at the boundary
    assert limiter.retry_after("k") == 0
    assert "k" not in limiter._events


def test_key_never_seen_has_no_map_entry_and_retry_after_zero() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=5, window_seconds=10.0, clock=clock)
    assert limiter.retry_after("ghost") == 0
    assert "ghost" not in limiter._events


# ── Bounded memory: _MAX_TRACKED_KEYS LRU eviction ──────────────────────────


def test_capacity_eviction_evicts_the_least_recently_touched_key() -> None:
    """Fill the map to capacity, refresh one key, then add one more.

    The refreshed key must survive (it was moved to the recent end); the key
    that was never touched again after its own insertion — now the
    least-recently-active — must be the one evicted to make room.
    """
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60.0, clock=clock)
    max_keys = SlidingWindowLimiter._MAX_TRACKED_KEYS

    for i in range(max_keys):
        assert limiter.allow(f"key-{i}") is True
    assert len(limiter._events) == max_keys

    # Touch "key-0" again — denied (limit=1), but `_pruned` still refreshes
    # its recency before that denial, moving it to the most-recently-used end.
    assert limiter.allow("key-0") is False

    # "key-1" is now the least-recently-touched key — it must be evicted.
    assert limiter.allow("new-key") is True
    assert len(limiter._events) == max_keys
    assert "key-1" not in limiter._events
    assert "key-0" in limiter._events
    assert "new-key" in limiter._events


# ── retry_after ──────────────────────────────────────────────────────────


def test_retry_after_is_zero_when_under_the_limit() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=3, window_seconds=10.0, clock=clock)
    limiter.allow("k")
    assert limiter.retry_after("k") == 0


def test_retry_after_is_ceiling_of_the_remaining_window_when_over_limit() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10.0, clock=clock)
    limiter.allow("k")  # t=0
    clock.advance(3.0)
    limiter.allow("k")  # t=3 — now at the limit (events at 0, 3)

    clock.advance(1.0)  # t=4: oldest event (t=0) has 10 - 4 = 6s left in-window
    assert limiter.retry_after("k") == 6


def test_retry_after_is_never_below_one() -> None:
    """A near-zero remainder still rounds up to a full second, never to 0."""
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=1, window_seconds=10.0, clock=clock)
    limiter.allow("k")  # t=0
    clock.advance(9.9999)  # remaining = 10 - 9.9999 = 0.0001s
    assert limiter.retry_after("k") == 1


def test_retry_after_does_not_itself_record_an_event() -> None:
    """Calling ``retry_after`` must not change what ``allow`` later decides."""
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=1, window_seconds=10.0, clock=clock)
    limiter.allow("k")
    assert limiter.retry_after("k") > 0
    assert limiter.retry_after("k") > 0  # still over limit — unchanged by the read above
    clock.advance(10.0)
    assert limiter.allow("k") is True  # the earlier retry_after() calls added nothing
