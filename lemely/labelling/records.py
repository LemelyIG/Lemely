"""Append-only, hash-chained JSONL records for the labeller (spec §6).

Each record stores the SHA-256 hash of ``(prev_hash, payload)`` for the
previous record, forming a tamper-evident chain: mutating any record's
payload post-hoc changes its hash, which no longer matches what the next
record's ``prev_hash`` claims. :mod:`lemely.labelling.verify` walks the
chain and reports the first break.

Spec §6 storage keeps one file per ``(paper_id, pass)``, not per labeller
(see :mod:`lemely.labelling.paths`), so two labellers on the same paper
interleave records in the same chain. ``append_transcription_record`` /
``append_marking_record`` stamp the server-bound ``labeller_id`` onto every
payload before writing it — never a client-supplied value — so a reader can
still attribute each interleaved record, and
:func:`~lemely.labelling.paper_data.load_pass2_context` can filter a shared
``transcription.jsonl`` down to "this labeller's own transcription" for
blindness purposes.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import TYPE_CHECKING

from lemely.core.loose_schemas import QuestionType  # noqa: TC001 - pydantic needs this at runtime
from lemely.eval.manifest import StrictModel
from lemely.labelling.paths import DEFAULT_EVAL_ROOT, marking_path, transcription_path

if TYPE_CHECKING:
    from pathlib import Path


class MarkingRecordPayload(StrictModel):
    """Spec §6 pass-2 output contract.

    One binary verdict per mark point, plus the labeller's own judgement
    of the question's true type.

    ``question_type_judgement`` is deliberately independent of any
    pipeline-emitted ``question_type`` — it is the labeller's OWN call,
    read back from a plain ``<select>`` populated from
    :class:`~lemely.core.loose_schemas.QuestionType`. It is a REPORTING
    variable for M2.4's stratification table (DA1) and must never be wired
    into split assignment.

    ``mark_point_verdicts`` maps every mark-point id known for the question
    (derived server-side from the mark scheme, never trusted from the
    client) to an explicit ``True``/``False`` — absence of a checkbox is
    coerced to an explicit ``False`` before this model ever sees the
    payload, so "not awarded" and "never considered" cannot be confused.
    """

    question_id: str
    awarded_marks: int
    mark_point_verdicts: dict[str, bool]
    question_type_judgement: QuestionType
    labeller_id: str


# The labeller server is a ThreadingHTTPServer: two concurrent POSTs to the
# same file (e.g. a human double-clicking Submit) could otherwise both read
# the same prev_hash and fork the chain. verify_chain would then report that
# as tampering — precisely the wrong failure for a tamper-evidence mechanism
# to present on an honest double-submit. One global lock serialises the
# read-then-append critical section; the labeller is a single-operator local
# tool, so a single lock across all paths costs nothing observable and needs
# no per-path bookkeeping.
_APPEND_LOCK = threading.Lock()


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
    """Append one hash-chained record to ``path``, creating parents as needed.

    The read-then-append is serialised by ``_APPEND_LOCK`` (see module
    docstring above) so two threads can never both read the same
    ``prev_hash`` and fork the chain.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with _APPEND_LOCK:
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
    """Append one transcription record, stamped with the server-bound ``labeller_id``.

    ``labeller_id`` is never taken from ``payload`` (which comes straight
    off the request) — it is the identity the server was started with, so a
    client cannot forge attribution in the shared per-paper chain.
    """
    stamped = {**payload, "labeller_id": labeller_id}
    return append_record(transcription_path(paper_id, eval_root), stamped)


def append_marking_record(
    paper_id: str,
    labeller_id: str,
    payload: dict[str, object],
    eval_root: Path = DEFAULT_EVAL_ROOT,
) -> dict[str, object]:
    """Append one marking record, validated against the spec §6 output contract.

    ``MarkingRecordPayload`` enforces both required fields from the MUST-FIX
    (accuracy-review, #46 repair pass 3): per-mark-point verdicts and the
    labeller's own question-type judgement. Validation happens here — the
    one place every marking record must pass through, regardless of caller
    — not only in the HTTP layer, so a future non-HTTP caller cannot ship a
    record missing either field.
    """
    stamped = {**payload, "labeller_id": labeller_id}
    validated = MarkingRecordPayload.model_validate(stamped)
    return append_record(marking_path(paper_id, eval_root), validated.model_dump(mode="json"))
