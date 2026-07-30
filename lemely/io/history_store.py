"""JSON-per-student persistence for cross-paper performance history.

Single-writer assumption: concurrent CLI + Gradio writes to the same student file
result in last-writer-wins. The lost record is detectable (missing from
compare-performance output) and recoverable (re-run correct-paper --record).
Future: add fcntl.flock around read-modify-write for POSIX multi-writer scenarios.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lemely.core.history import PaperRecord, StudentHistory

if TYPE_CHECKING:
    from pathlib import Path


class HistoryStore:
    """Persistent JSON store for student paper records.

    On-disk layout: {root}/{student_id}.json  →  serialized StudentHistory.
    Writes are atomic (write-to-temp then os.replace) for crash-atomicity.
    Interface is backend-neutral; a SQLite backend can replace without changing callers.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, student_id: str) -> Path:
        return self._root / f"{student_id}.json"

    def append(self, student_id: str, record: PaperRecord) -> None:
        """Append a PaperRecord to the student's history.

        Uses write-then-replace for crash-atomicity (torn-write protection).
        """
        history = self.load(student_id)
        history.records.append(record)
        data = history.model_dump(mode="json")
        path = self._path(student_id)
        fd, tmp_path = tempfile.mkstemp(dir=self._root, prefix=f".{student_id}_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def load(self, student_id: str) -> StudentHistory:
        """Load a student's history. Returns empty StudentHistory if file absent."""
        path = self._path(student_id)
        if not path.exists():
            return StudentHistory(student_id=student_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return StudentHistory.model_validate(data)
        except Exception:
            return StudentHistory(student_id=student_id)

    def list_students(self) -> list[str]:
        """Return all student IDs with recorded history."""
        return [p.stem for p in sorted(self._root.glob("*.json"))]


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()
