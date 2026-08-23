"""Hash-chain verifier for the labeller's JSONL records (spec §6)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lemely.labelling.records import read_records, record_hash


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
        assert record_prev_hash is None or isinstance(record_prev_hash, str)
        if record_prev_hash != prev_hash:
            return ChainVerification(
                ok=False, broken_index=index, reason="prev_hash does not match prior record"
            )
        payload = record.get("payload", {})
        assert isinstance(payload, dict)
        expected_hash = record_hash(record_prev_hash, payload)
        stored_hash = record.get("hash")
        if stored_hash != expected_hash:
            return ChainVerification(
                ok=False, broken_index=index, reason="stored hash does not match payload"
            )
        assert isinstance(stored_hash, str)
        prev_hash = stored_hash
    return ChainVerification(ok=True)
