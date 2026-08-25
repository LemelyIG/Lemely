"""Tests for the reusable in-process cooldown store (deterministic clock)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lemely.auth.cooldown import CooldownError, CooldownStore


class _FrozenClock:
    """A mutable clock: ``advance`` moves it forward for window tests."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def test_first_call_passes() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = CooldownStore(clock=clock, min_seconds=30)
    store.check_and_stamp("a@example.com")  # no raise


def test_immediate_second_call_raises_with_positive_retry_after() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = CooldownStore(clock=clock, min_seconds=30)
    store.check_and_stamp("a@example.com")
    with pytest.raises(CooldownError) as exc_info:
        store.check_and_stamp("a@example.com")
    assert exc_info.value.retry_after > 0


def test_retry_after_reflects_the_remaining_window() -> None:
    """Pins the exact contract, not just its sign."""
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = CooldownStore(clock=clock, min_seconds=30)
    store.check_and_stamp("a@example.com")
    clock.advance(5)
    with pytest.raises(CooldownError) as exc_info:
        store.check_and_stamp("a@example.com")
    assert exc_info.value.retry_after == pytest.approx(25.0)


def test_call_after_window_passes() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = CooldownStore(clock=clock, min_seconds=30)
    store.check_and_stamp("a@example.com")
    clock.advance(30)
    store.check_and_stamp("a@example.com")  # cooldown elapsed -> no raise


def test_distinct_keys_do_not_interfere() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = CooldownStore(clock=clock, min_seconds=30)
    store.check_and_stamp("a@example.com")
    store.check_and_stamp("b@example.com")  # different key -> no raise


def test_a_rejected_call_does_not_reset_the_window() -> None:
    """A rejected attempt must not itself extend the cooldown it was rejected by."""
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = CooldownStore(clock=clock, min_seconds=30)
    store.check_and_stamp("a@example.com")

    clock.advance(10)
    with pytest.raises(CooldownError):
        store.check_and_stamp("a@example.com")  # rejected; must not re-stamp

    clock.advance(20)  # 30s since the *original* stamp, not the rejected one
    store.check_and_stamp("a@example.com")  # now allowed
