"""Persistent cumulative-USD ledger for the Gemini spend cap.

Unlike the per-process token counters in :mod:`lemely.io.gemini`, this ledger
survives process restarts by persisting to a JSON file, giving Lemely a real
cross-run USD ceiling for unattended multi-day builds.

Single-writer assumption: concurrent CLI + web writes to the same ledger file
resolve as last-writer-wins (a lost increment under-counts spend, never
over-counts). Each :meth:`CostLedger.add` performs a read-modify-write; there is
no OS-level lock. Future: add ``fcntl.flock`` around the read-modify-write for
POSIX multi-writer scenarios.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA_VERSION = 1


class CostLedger:
    """Persistent cumulative-USD ledger backed by a single JSON file.

    On-disk layout (JSON object)::

        {
          "schema_version": 1,
          "cumulative_usd": 12.34,
          "warnings_sent": [4.0, 6.0],
          "updated_at": "2026-07-30T12:00:00+00:00"
        }

    Writes are atomic (write-to-temp then :func:`os.replace`) for crash-atomicity.
    """

    def __init__(self, path: Path) -> None:
        """Initialise the ledger.

        Args:
            path: Location of the JSON ledger file. The parent directory is
                created on first write, not here, so constructing a ledger is
                side-effect free.
        """
        self._path = path
        self._log = structlog.get_logger().bind(component="cost_ledger")

    def _read(self) -> tuple[float, list[float]]:
        """Read ``(cumulative_usd, warnings_sent)`` from disk.

        Returns ``(0.0, [])`` when the file is absent. A corrupt or unreadable
        file is treated as ``(0.0, [])`` but logs a warning first — a corrupt
        ledger is never silently zeroed.
        """
        if not self._path.exists():
            return 0.0, []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            cumulative = float(data["cumulative_usd"])
            warnings_sent = [float(w) for w in data.get("warnings_sent", [])]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._log.warning(
                "cost_ledger_corrupt",
                path=str(self._path),
                error=str(exc),
                action="treating cumulative spend as 0.0",
            )
            return 0.0, []
        return cumulative, warnings_sent

    def _write(self, cumulative_usd: float, warnings_sent: list[float]) -> None:
        """Atomically persist the ledger state (write-to-temp then replace)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "cumulative_usd": cumulative_usd,
            "warnings_sent": sorted(warnings_sent),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, prefix=".gemini_spend_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def total(self) -> float:
        """Return the current cumulative USD spend.

        Returns ``0.0`` if the file is absent or corrupt (a warning is logged
        for corruption via :meth:`_read`).
        """
        cumulative, _ = self._read()
        return cumulative

    def add(self, usd: float, *, thresholds: list[float]) -> tuple[float, list[float]]:
        """Add ``usd`` to the cumulative total and persist atomically.

        Performs a read-modify-write: loads current state, adds ``usd``, records
        any newly crossed warning thresholds, and persists the result.

        A threshold is "newly crossed" when ``new_total >= threshold`` and that
        threshold is not already present in ``warnings_sent``. Newly crossed
        thresholds are appended to ``warnings_sent`` (so they fire exactly once)
        and returned sorted ascending.

        Args:
            usd: Incremental spend to add (may be ``0.0``).
            thresholds: Warning thresholds to evaluate against the new total.

        Returns:
            A tuple ``(new_total, newly_crossed_thresholds)``.
        """
        cumulative, warnings_sent = self._read()
        new_total = cumulative + usd

        already = set(warnings_sent)
        newly_crossed = sorted(t for t in thresholds if new_total >= t and t not in already)
        if newly_crossed:
            warnings_sent = sorted(already | set(newly_crossed))

        self._write(new_total, warnings_sent)
        return new_total, newly_crossed
