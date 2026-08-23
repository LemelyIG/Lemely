"""Hash-chain integrity for the labeller's append-only JSONL records (#46).

Spec §6: labelling protocol records must be tamper-evident. Each record
carries a hash of the previous record; a verifier walks the chain and
reports the first break.
"""

from __future__ import annotations

import json
from pathlib import Path

from lemely.labelling.paths import marking_path, transcription_path
from lemely.labelling.records import append_record
from lemely.labelling.verify import verify_chain


def test_writing_records_builds_a_valid_chain(tmp_path: Path) -> None:
    path = transcription_path("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)

    for index in range(3):
        append_record(path, {"question_id": f"q{index}", "text": f"answer {index}"})

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    records = [json.loads(line) for line in lines]
    assert records[0]["prev_hash"] is None
    assert records[1]["prev_hash"] == records[0]["hash"]
    assert records[2]["prev_hash"] == records[1]["hash"]

    result = verify_chain(path)
    assert result.ok
    assert result.broken_index is None


def test_verify_detects_a_tampered_middle_record(tmp_path: Path) -> None:
    path = transcription_path("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)
    for index in range(4):
        append_record(path, {"question_id": f"q{index}", "text": f"answer {index}"})

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]
    # Tamper with the payload of the middle (index 1) record post-hoc, leaving
    # its stored hash/prev_hash fields untouched — this is what a naive edit
    # of the file on disk would look like.
    records[1]["payload"]["text"] = "TAMPERED"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    result = verify_chain(path)
    assert not result.ok
    assert result.broken_index == 1


def test_untampered_chain_verifies_clean(tmp_path: Path) -> None:
    path = marking_path("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)
    for index in range(5):
        append_record(path, {"question_id": f"q{index}", "awarded_marks": index})

    result = verify_chain(path)
    assert result.ok
    assert result.broken_index is None


def test_two_labellers_on_the_same_paper_do_not_overwrite_each_other(
    tmp_path: Path,
) -> None:
    path_a = transcription_path("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)
    path_b = transcription_path("0580_s23_qp_22", "labeller-B", eval_root=tmp_path)

    append_record(path_a, {"question_id": "q0", "text": "A's answer"})
    append_record(path_b, {"question_id": "q0", "text": "B's answer"})
    append_record(path_a, {"question_id": "q1", "text": "A's second answer"})

    assert path_a != path_b

    records_a = [json.loads(line) for line in path_a.read_text(encoding="utf-8").splitlines()]
    records_b = [json.loads(line) for line in path_b.read_text(encoding="utf-8").splitlines()]

    assert len(records_a) == 2
    assert len(records_b) == 1
    assert records_a[0]["payload"]["text"] == "A's answer"
    assert records_b[0]["payload"]["text"] == "B's answer"

    assert verify_chain(path_a).ok
    assert verify_chain(path_b).ok
