"""JSON-per-student persistence for cross-paper performance history.

Backs the local CLI and Gradio debug tool only. The web/product surface persists
history in Postgres via ``lemely.db.history_repo.DbHistoryStore`` (decisions
D1.8/D1.9); ``now_iso`` and the shared ``HistoryStoreProtocol`` now live in
``lemely.core.history``. Full retirement of this JSON store is deferred until the
CLI/Gradio tools are migrated or retired.

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
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from lemely.core.history import HISTORY_SCHEMA_VERSION, PaperRecord, StudentHistory
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger(__name__)


def _safe_key(student_id: str) -> str:
    """Return ``student_id`` if it is a safe single-segment filename key, else raise.

    The student id becomes a filename (``{root}/{student_id}.json``). Some callers
    pass a value that originates from an untrusted request (e.g. a teacher-supplied
    ``student_id`` on paper upload), so a key containing a path separator, a
    ``.``/``..`` segment, or a NUL byte could escape ``root`` and read/overwrite an
    arbitrary ``.json`` file. Reject those instead of trusting them.
    """
    if (
        not student_id
        or student_id in {".", ".."}
        or "/" in student_id
        or "\\" in student_id
        or "\x00" in student_id
    ):
        raise ValueError(f"Unsafe history store key: {student_id!r}")
    return student_id


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
        return self._root / f"{_safe_key(student_id)}.json"

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
        """Load a student's history.

        A *missing* file is a legitimate empty history and returns an empty
        ``StudentHistory``. A file that exists but is unreadable, not valid JSON,
        carries an unsupported ``schema_version``, or fails schema validation is
        surfaced as a ``ParseError`` — never silently treated as "no history"
        (that would mask corruption and hide data loss).

        Raises:
            ParseError: the file exists but cannot be read/parsed/validated.
        """
        path = self._path(student_id)
        if not path.exists():
            return StudentHistory(student_id=student_id)

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.error("history_read_failed", student_id=student_id, path=str(path), error=str(exc))
            raise ParseError(f"Cannot read history file {path}: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.error("history_corrupt_json", student_id=student_id, path=str(path), error=str(exc))
            raise ParseError(f"Corrupt history file {path} (invalid JSON): {exc}") from exc

        version = data.get("schema_version", 1) if isinstance(data, dict) else 1
        if version > HISTORY_SCHEMA_VERSION:
            log.error(
                "history_schema_too_new",
                student_id=student_id,
                path=str(path),
                found=version,
                supported=HISTORY_SCHEMA_VERSION,
            )
            raise ParseError(
                f"History file {path} has unsupported schema_version {version} "
                f"(max supported {HISTORY_SCHEMA_VERSION}); refusing to misread it."
            )

        try:
            # Feed the *resolved* version back in rather than letting
            # ``model_validate`` fall through to the model default, which is
            # always the current version: a pre-versioning file would otherwise
            # load claiming to be whatever HISTORY_SCHEMA_VERSION happens to be
            # today, destroying the very "detect an older file" signal this
            # field exists to carry. ``version`` is already absent-means-1 above.
            if isinstance(data, dict):
                data = {**data, "schema_version": version}
            return StudentHistory.model_validate(data)
        except ValidationError as exc:
            log.error("history_schema_mismatch", student_id=student_id, path=str(path))
            raise ParseError(f"Corrupt history file {path} (schema mismatch): {exc}") from exc

    def list_students(self) -> list[str]:
        """Return all student IDs with recorded history."""
        return [p.stem for p in sorted(self._root.glob("*.json"))]
