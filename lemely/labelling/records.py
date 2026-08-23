"""Append-only, hash-chained JSONL records for the labeller (spec §6).

Each record stores the SHA-256 hash of ``(prev_hash, payload)`` for the
previous record, forming a tamper-evident chain: mutating any record's
payload post-hoc changes its hash, which no longer matches what the next
record's ``prev_hash`` claims. :mod:`lemely.labelling.verify` walks the
chain and reports the first break.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from lemely.labelling.paths import DEFAULT_EVAL_ROOT, marking_path, transcription_path

if TYPE_CHECKING:
    from pathlib import Path


def record_hash(prev_hash: str | None, payload: dict[str, object]) -> str:
    canonical = json.dumps({"prev_hash": prev_hash, "payload": payload}, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _last_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    last_line: str | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                last_line = stripped
    if last_line is None:
        return None
    parsed: dict[str, object] = json.loads(last_line)
    stored_hash = parsed["hash"]
    if not isinstance(stored_hash, str):
        raise TypeError(f"corrupt record chain in {path}: 'hash' is not a string")
    return stored_hash


def append_record(path: Path, payload: dict[str, object]) -> dict[str, object]:
    """Append one hash-chained record to ``path``, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_hash = _last_hash(path)
    record: dict[str, object] = {
        "prev_hash": prev_hash,
        "hash": record_hash(prev_hash, payload),
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return record


def read_records(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def append_transcription_record(
    paper_id: str,
    labeller_id: str,
    payload: dict[str, object],
    eval_root: Path = DEFAULT_EVAL_ROOT,
) -> dict[str, object]:
    return append_record(transcription_path(paper_id, labeller_id, eval_root), payload)


def append_marking_record(
    paper_id: str,
    labeller_id: str,
    payload: dict[str, object],
    eval_root: Path = DEFAULT_EVAL_ROOT,
) -> dict[str, object]:
    return append_record(marking_path(paper_id, labeller_id, eval_root), payload)
