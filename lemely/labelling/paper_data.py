"""Pass-1 / pass-2 data loading for the blind labeller (spec §6).

Pass 1 (transcription) must load ONLY scan-region image data for the paper
— never the mark scheme. Pass 2 (marking) loads the mark scheme plus the
labeller's OWN pass-1 transcription, read back from the just-written
``transcription.jsonl`` — never a pipeline output object such as
``CorrectedQuestion`` (never imported here).

:class:`~lemely.core.loose_schemas.MarkScheme` is imported *inside*
:func:`load_pass2_context`, not at module scope. The pass-1-serving code
path (this module's import, plus :func:`load_pass1_context`) must never
load the mark-scheme model at all — a module-scope import would defeat
that, since :mod:`lemely.labelling.server` imports this module at import
time regardless of which pass is actually being served.
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


def load_pass2_context(
    paper_id: str, labeller_id: str, eval_root: Path = DEFAULT_EVAL_ROOT
) -> dict[str, object]:
    """Mark scheme + the labeller's OWN pass-1 transcription. Never pipeline output.

    Raises ``FileNotFoundError`` if no mark scheme exists for ``paper_id`` —
    silently serving ``None`` here would let a smoke test "pass" over a
    paper that was never actually set up.
    """
    from lemely.core.loose_schemas import MarkScheme

    ms_path = mark_scheme_path(paper_id, eval_root)
    if not ms_path.is_file():
        raise FileNotFoundError(f"no mark scheme for paper_id={paper_id!r}: {ms_path}")
    parsed = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
    mark_scheme = parsed.model_dump(mode="json")

    own_transcription = read_records(transcription_path(paper_id, labeller_id, eval_root))

    return {
        "paper_id": paper_id,
        "labeller_id": labeller_id,
        "mark_scheme": mark_scheme,
        "own_transcription": own_transcription,
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
