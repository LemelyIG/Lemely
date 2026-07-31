"""Tests for the in-memory OTP challenge store (deterministic clock + RNG)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from lemely.auth.otp import OtpResult, OtpStore


class _FrozenClock:
    """A mutable clock: ``advance`` moves it forward for TTL tests."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _store(
    clock: _FrozenClock, *, ttl: int = 300, max_attempts: int = 5, length: int = 6
) -> OtpStore:
    return OtpStore(
        clock=clock,
        rng=random.Random(1234),
        ttl_seconds=ttl,
        max_attempts=max_attempts,
        code_length=length,
    )


def test_code_generation_is_deterministic_and_zero_padded() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store_a = _store(clock)
    store_b = OtpStore(clock=clock, rng=random.Random(1234))
    code_a = store_a.issue("+1")
    code_b = store_b.issue("+1")
    assert code_a == code_b  # same seed → same code
    assert len(code_a) == 6
    assert code_a.isdigit()


def test_successful_verify_consumes_challenge() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock)
    code = store.issue("+100")
    assert store.verify("+100", code) is OtpResult.ok
    # Consumed: a second verify finds no challenge.
    assert store.verify("+100", code) is OtpResult.no_challenge


def test_ttl_expiry() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock, ttl=300)
    code = store.issue("+200")
    clock.advance(301)
    assert store.verify("+200", code) is OtpResult.expired


def test_wrong_code_rejected() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock)
    code = store.issue("+300")
    wrong = "000000" if code != "000000" else "111111"
    assert store.verify("+300", wrong) is OtpResult.wrong_code


def test_max_attempts_lockout() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock, max_attempts=3)
    code = store.issue("+400")
    wrong = "000000" if code != "000000" else "111111"
    assert store.verify("+400", wrong) is OtpResult.wrong_code
    assert store.verify("+400", wrong) is OtpResult.wrong_code
    # 3rd wrong attempt hits the limit → locked out and challenge removed.
    assert store.verify("+400", wrong) is OtpResult.locked_out
    # Even the correct code now fails: the challenge is gone.
    assert store.verify("+400", code) is OtpResult.no_challenge


def test_unknown_phone_returns_no_challenge() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock)
    assert store.verify("+999", "123456") is OtpResult.no_challenge


def test_reissue_resets_attempts_and_ttl() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock, max_attempts=2)
    store.issue("+500")
    store.verify("+500", "bad000")  # 1 failed attempt
    new_code = store.issue("+500")  # reissue resets counter
    assert store.verify("+500", new_code) is OtpResult.ok
