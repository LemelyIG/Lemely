"""Pass-1 / pass-2 data loading for the blind labeller (spec §6).

Pass 1 (transcription) must load ONLY scan-region image data for the paper
— never the mark scheme. Pass 2 (marking) loads the mark scheme plus the
labeller's OWN pass-1 transcription, read back from the just-written
``transcription.jsonl`` — never a pipeline output object such as
``CorrectedQuestion`` (never imported here).

:class:`~lemely.core.loose_schemas.MarkScheme` is imported *inside*
:func:`load_pass2_context` (and :func:`question_mark_point_ids`), not at
module scope. The pass-1-serving code path (this module's import, plus
:func:`load_pass1_context`) must never load the mark-scheme model at all —
a module-scope import would defeat that, since
:mod:`lemely.labelling.server` imports this module at import time
regardless of which pass is actually being served.

Spec §6 storage keeps one ``transcription.jsonl`` per paper, shared across
labellers (see :mod:`lemely.labelling.paths`), so "the labeller's OWN
transcription" is no longer a distinct file — it is every record in that
shared file whose ``labeller_id`` matches the requesting labeller. Filtering
happens here, in :func:`load_pass2_context`, rather than relying on file
segregation.
"""

from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING

from lemely.labelling.paths import (
    DEFAULT_EVAL_ROOT,
    mark_scheme_path,
    scan_dir,
    scan_image_path,
    transcription_path,
)
from lemely.labelling.records import read_records

if TYPE_CHECKING:
    from pathlib import Path


def load_pass1_context(paper_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> dict[str, object]:
    """Scan-region image data ONLY. No mark scheme is ever loaded here.

    Raises ``FileNotFoundError`` if no scan directory exists for
    ``paper_id`` — silently returning an empty list here would let a smoke
    test "pass" over a paper that was never actually set up.
    """
    directory = scan_dir(paper_id, eval_root)
    if not directory.is_dir():
        raise FileNotFoundError(f"no scan directory for paper_id={paper_id!r}: {directory}")
    scan_images = sorted(p.name for p in directory.glob("*") if p.is_file())
    return {"paper_id": paper_id, "scan_images": scan_images}


def _load_mark_scheme_dict(paper_id: str, eval_root: Path) -> dict[str, object]:
    """Load and dump ``paper_id``'s mark scheme as plain JSON (pass 2 only).

    Raises ``FileNotFoundError`` if no mark scheme exists for ``paper_id`` —
    silently serving ``None``/``[]`` here would let a smoke test "pass" over
    a paper that was never actually set up.
    """
    from lemely.core.loose_schemas import MarkScheme

    ms_path = mark_scheme_path(paper_id, eval_root)
    if not ms_path.is_file():
        raise FileNotFoundError(f"no mark scheme for paper_id={paper_id!r}: {ms_path}")
    parsed = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
    return parsed.model_dump(mode="json")


def _find_question(mark_scheme: dict[str, object], question_id: str) -> dict[str, object] | None:
    questions = mark_scheme.get("questions", [])
    if not isinstance(questions, list):
        raise TypeError(f"mark_scheme['questions'] must be a list, got {type(questions)!r}")
    for question in questions:
        if isinstance(question, dict) and question.get("id") == question_id:
            return question
    return None


def question_mark_point_ids(
    paper_id: str, question_id: str, eval_root: Path = DEFAULT_EVAL_ROOT
) -> list[str]:
    """The authoritative set of mark-point ids for one question (pass 2 only).

    Used server-side to turn a POSTed set of *checked* mark-point ids into a
    complete verdict (every known point explicitly True/False) — never
    trusted from the client, which could otherwise omit a point entirely
    rather than explicitly marking it not-awarded.

    Raises ``FileNotFoundError`` if ``question_id`` is not in the mark
    scheme — a client posting a mark for a question that does not exist
    must not silently produce an empty verdict set.
    """
    mark_scheme = _load_mark_scheme_dict(paper_id, eval_root)
    question = _find_question(mark_scheme, question_id)
    if question is None:
        raise FileNotFoundError(
            f"no question {question_id!r} in mark scheme for paper_id={paper_id!r}"
        )
    answer_points = question.get("answer_points", [])
    if not isinstance(answer_points, list):
        raise TypeError(f"question['answer_points'] must be a list, got {type(answer_points)!r}")
    return [
        str(point["id"]) for point in answer_points if isinstance(point, dict) and "id" in point
    ]


def load_pass2_context(
    paper_id: str,
    labeller_id: str,
    eval_root: Path = DEFAULT_EVAL_ROOT,
    question_id: str | None = None,
) -> dict[str, object]:
    """Mark scheme + the labeller's OWN pass-1 transcription. Never pipeline output.

    ``question_id`` scopes the page to one question's marking form (spec
    §6: checkboxes per mark point). When omitted, the first question in the
    mark scheme is used as the default so the page always has something to
    mark; the full question list is still returned so the labeller can jump
    to any other question via its link. Raises ``FileNotFoundError`` if an
    explicit ``question_id`` does not match any question in the scheme.

    "Own" transcription is filtered out of the paper-wide, multi-labeller
    ``transcription.jsonl`` by ``labeller_id`` (spec §6 storage keeps one
    file per paper, not per labeller) — this is where blindness between
    labellers is enforced now that the file itself is shared.
    """
    mark_scheme = _load_mark_scheme_dict(paper_id, eval_root)

    questions = mark_scheme.get("questions", [])
    if not isinstance(questions, list):
        raise TypeError(f"mark_scheme['questions'] must be a list, got {type(questions)!r}")

    if question_id is not None:
        selected_question = _find_question(mark_scheme, question_id)
        if selected_question is None:
            raise FileNotFoundError(
                f"no question {question_id!r} in mark scheme for paper_id={paper_id!r}"
            )
    elif questions and isinstance(questions[0], dict):
        selected_question = questions[0]
    else:
        selected_question = None

    all_records = read_records(transcription_path(paper_id, eval_root))
    own_transcription: list[dict[str, object]] = []
    for record in all_records:
        payload = record.get("payload")
        if isinstance(payload, dict) and payload.get("labeller_id") == labeller_id:
            own_transcription.append(record)

    return {
        "paper_id": paper_id,
        "labeller_id": labeller_id,
        "mark_scheme": mark_scheme,
        "own_transcription": own_transcription,
        "selected_question": selected_question,
    }


def read_scan_image(
    paper_id: str, name: str, eval_root: Path = DEFAULT_EVAL_ROOT
) -> tuple[str, bytes]:
    """Read one scan-region image's bytes plus a best-guess Content-Type.

    Pass 1 only — this is the image-byte counterpart of ``scan_images`` in
    :func:`load_pass1_context`; it never touches the mark scheme.
    """
    path = scan_image_path(paper_id, name, eval_root)
    if not path.is_file():
        raise FileNotFoundError(f"no scan image {name!r} for paper_id={paper_id!r}: {path}")
    content_type, _ = mimetypes.guess_type(path.name)
    return content_type or "application/octet-stream", path.read_bytes()
