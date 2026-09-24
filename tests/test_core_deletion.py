"""The deletion window arithmetic (design 2026-09-22, §7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lemely.core.deletion import (
    PURGE_GRACE,
    RETENTION_DAYS,
    integrity_hold_until,
    is_within_restore_window,
    purge_cutoff,
    restore_deadline,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def test_retention_is_thirty_days_and_shared() -> None:
    assert RETENTION_DAYS == 30


def test_restore_deadline_is_retention_after_deletion() -> None:
    assert restore_deadline(NOW) == NOW + timedelta(days=30)


def test_integrity_hold_uses_the_same_number() -> None:
    assert integrity_hold_until(NOW) - NOW == restore_deadline(NOW) - NOW


def test_purge_cutoff_is_retention_plus_grace_ago() -> None:
    assert purge_cutoff(NOW) == NOW - timedelta(days=30) - PURGE_GRACE


def test_restore_and_purge_windows_cannot_both_claim_one_row() -> None:
    """The gap is the whole safety argument — no row is restorable and purgeable."""
    just_restorable = NOW - timedelta(days=30) + timedelta(seconds=1)
    assert is_within_restore_window(just_restorable, NOW) is True
    assert just_restorable > purge_cutoff(NOW)

    purgeable = purge_cutoff(NOW) - timedelta(seconds=1)
    assert is_within_restore_window(purgeable, NOW) is False


def test_restore_window_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        is_within_restore_window(datetime(2026, 9, 1), NOW)
