"""Retention arithmetic for paper deletion (design 2026-09-22 §7, decisions D3/D8).

One module so the 30 days is **one number**: D8's integrity hold and the purge
window are the same retention, and a second literal is how they drift apart.

Deliberately not a settings knob. A configurable retention would make the
public "How Lemely handles your data" page conditional on deployment config,
and that page states the window as fact.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: The restore window, and D8's integrity hold. One number, both uses.
RETENTION_DAYS = 30

#: Gap between the last restorable instant and the first purgeable one.
#: Absorbs clock skew between replicas so restore and purge can never both
#: succeed on one row — the whole reason purge may delete the GCS object first.
PURGE_GRACE = timedelta(hours=1)

_RETENTION = timedelta(days=RETENTION_DAYS)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")


def restore_deadline(deleted_at: datetime) -> datetime:
    """The instant after which this deletion can no longer be undone."""
    _require_aware(deleted_at, "deleted_at")
    return deleted_at + _RETENTION


def integrity_hold_until(recorded_at: datetime) -> datetime:
    """The instant an integrity-flagged paper becomes deletable (D8).

    Keyed on ``recorded_at`` because the flags are written at marking time and
    there is no ``flagged_at`` column — inventing one would be a second clock.
    """
    _require_aware(recorded_at, "recorded_at")
    return recorded_at + _RETENTION


def purge_cutoff(now: datetime) -> datetime:
    """Rows whose ``deleted_at`` is at or before this are purgeable."""
    _require_aware(now, "now")
    return now - _RETENTION - PURGE_GRACE


def is_within_restore_window(deleted_at: datetime, now: datetime) -> bool:
    """Whether a row stamped at ``deleted_at`` may still be restored."""
    _require_aware(deleted_at, "deleted_at")
    _require_aware(now, "now")
    return deleted_at > now - _RETENTION


__all__ = [
    "PURGE_GRACE",
    "RETENTION_DAYS",
    "integrity_hold_until",
    "is_within_restore_window",
    "purge_cutoff",
    "restore_deadline",
]
