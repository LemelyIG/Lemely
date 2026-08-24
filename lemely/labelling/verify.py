"""Hash-chain verifier for the labeller's JSONL records (spec §6).

``verify_chain`` on its own has no production caller — only tests invoked
it (NIT, accuracy-review #46 repair pass 3) — so a human auditing the label
corpus had no way to actually run the tamper check the spec calls for.
``verify_paper_labels`` plus ``lemely label-verify`` (see
:mod:`lemely.app.cli`) close that gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lemely.labelling.paths import DEFAULT_EVAL_ROOT, marking_path, transcription_path
from lemely.labelling.records import read_records, record_hash

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    broken_index: int | None = None
    reason: str | None = None


def verify_chain(path: Path) -> ChainVerification:
    """Walk ``path``'s hash chain and report the first break, if any."""
    records = read_records(path)
    prev_hash: str | None = None
    for index, record in enumerate(records):
        record_prev_hash = record.get("prev_hash")
        if not (record_prev_hash is None or isinstance(record_prev_hash, str)):
            raise TypeError(
                f"record {index}: 'prev_hash' must be a string or null, "
                f"got {type(record_prev_hash)!r}"
            )
        if record_prev_hash != prev_hash:
            return ChainVerification(
                ok=False, broken_index=index, reason="prev_hash does not match prior record"
            )
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            raise TypeError(f"record {index}: 'payload' must be an object, got {type(payload)!r}")
        expected_hash = record_hash(record_prev_hash, payload)
        stored_hash = record.get("hash")
        if not isinstance(stored_hash, str):
            raise TypeError(f"record {index}: 'hash' must be a string, got {type(stored_hash)!r}")
        if stored_hash != expected_hash:
            return ChainVerification(
                ok=False, broken_index=index, reason="stored hash does not match payload"
            )
        prev_hash = stored_hash
    return ChainVerification(ok=True)


@dataclass(frozen=True)
class PaperVerification:
    """Chain-verification results for one paper's ``transcription.jsonl`` / ``marking.jsonl``."""

    paper_id: str
    ok: bool
    files: dict[str, ChainVerification | None]  # None means the file does not exist yet


def verify_paper_labels(paper_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> PaperVerification:
    """Verify both of ``paper_id``'s hash chains (spec §6 storage: one pair per paper).

    A file that does not exist yet (e.g. only pass 1 has been done so far)
    is reported as missing, not as broken — nothing to verify is not
    tampering.
    """
    targets = {
        "transcription": transcription_path(paper_id, eval_root),
        "marking": marking_path(paper_id, eval_root),
    }
    files: dict[str, ChainVerification | None] = {}
    ok = True
    for name, path in targets.items():
        if not path.is_file():
            files[name] = None
            continue
        result = verify_chain(path)
        files[name] = result
        if not result.ok:
            ok = False
    return PaperVerification(paper_id=paper_id, ok=ok, files=files)
