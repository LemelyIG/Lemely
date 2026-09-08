"""Tests for the in-memory OTP challenge store (deterministic clock + RNG)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from lemely.auth.otp import OtpChannel, OtpRateLimitError, OtpResult, OtpStore


class _FrozenClock:
    """A mutable clock: ``advance`` moves it forward for TTL tests."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _store(
    clock: _FrozenClock,
    *,
    ttl: int = 300,
    max_attempts: int = 5,
    length: int = 6,
    min_resend: int = 0,
) -> OtpStore:
    # min_resend defaults to 0 (cooldown disabled) so tests that exercise the
    # verify/reissue lifecycle are not incidentally throttled; the resend cooldown
    # has its own dedicated tests below.
    return OtpStore(
        clock=clock,
        rng=random.Random(1234),
        ttl_seconds=ttl,
        max_attempts=max_attempts,
        code_length=length,
        min_resend_seconds=min_resend,
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


def test_resend_within_cooldown_is_rate_limited() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock, min_resend=30)
    store.issue("+600")
    # A second issue inside the cooldown window is rejected — otherwise a caller
    # could reset the attempt counter by re-requesting before lockout.
    clock.advance(29)
    with pytest.raises(OtpRateLimitError):
        store.issue("+600")


def test_resend_allowed_after_cooldown_elapses() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock, min_resend=30)
    store.issue("+700")
    clock.advance(30)
    second = store.issue("+700")  # cooldown elapsed → no raise, fresh challenge
    # The reissued challenge is live and verifiable with the new code.
    assert store.verify("+700", second) is OtpResult.ok


def test_resend_allowed_once_prior_challenge_expired() -> None:
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = _store(clock, ttl=60, min_resend=30)
    store.issue("+800")
    # Past TTL the old challenge is dead, so a resend is allowed even though the
    # cooldown check only guards *live* challenges.
    clock.advance(61)
    code = store.issue("+800")
    assert store.verify("+800", code) is OtpResult.ok


def test_channels_are_independent_and_email_has_its_own_ttl() -> None:
    clock = _FrozenClock(datetime(2026, 9, 3, tzinfo=UTC))
    store = OtpStore(
        clock=clock,
        rng=random.Random(1),
        ttl_seconds=300,
        email_ttl_seconds=600,
        min_resend_seconds=0,
    )
    phone_code = store.issue("+201000000000")
    email_code = store.issue("a@example.com", channel=OtpChannel.email)
    wrong_channel = store.verify("a@example.com", phone_code, channel=OtpChannel.email)
    assert wrong_channel is OtpResult.wrong_code
    clock.advance(400)
    assert store.verify("+201000000000", phone_code) is OtpResult.expired
    assert store.verify("a@example.com", email_code, channel=OtpChannel.email) is OtpResult.ok


def test_same_address_is_independent_across_channels() -> None:
    """The ``(channel, address)`` key holds even when the address string is
    identical on both channels — the property the composite key exists for.
    A phone challenge and an email challenge for the same address are two
    unrelated entries: each verifies only against its own channel and its own
    code, and the other channel's code is simply wrong, never a match.
    """
    clock = _FrozenClock(datetime(2026, 9, 3, tzinfo=UTC))
    store = OtpStore(clock=clock, rng=random.Random(2), min_resend_seconds=0)
    address = "same@example.com"
    phone_code = store.issue(address)
    email_code = store.issue(address, channel=OtpChannel.email)
    assert phone_code != email_code  # distinct draws; the cross-checks below rely on this

    # Each channel's code is wrong on the other channel — neither challenge is
    # consumed by a wrong-code attempt, so both are still live afterward.
    assert store.verify(address, email_code, channel=OtpChannel.phone) is OtpResult.wrong_code
    assert store.verify(address, phone_code, channel=OtpChannel.email) is OtpResult.wrong_code

    # Each channel's own code still verifies correctly against its own entry.
    assert store.verify(address, phone_code, channel=OtpChannel.phone) is OtpResult.ok
    assert store.verify(address, email_code, channel=OtpChannel.email) is OtpResult.ok
