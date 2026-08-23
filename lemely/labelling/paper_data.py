"""Pass-1 / pass-2 data loading for the blind labeller (spec §6).

Pass 1 (transcription) must load ONLY scan-region image data for the paper
— never the mark scheme. Pass 2 (marking) loads the mark scheme plus the
labeller's OWN pass-1 transcription, read back from the just-written
``transcription.jsonl`` — never a pipeline output object such as
``CorrectedQuestion`` (never imported here).
"""

from __future__ import annotations

from pathlib import Path

from lemely.core.loose_schemas import MarkScheme
from lemely.labelling.paths import (
    DEFAULT_EVAL_ROOT,
    mark_scheme_path,
    scan_dir,
    transcription_path,
)
from lemely.labelling.records import read_records


def load_pass1_context(paper_id: str, eval_root: Path = DEFAULT_EVAL_ROOT) -> dict[str, object]:
    """Scan-region image data ONLY. No mark scheme is ever loaded here."""
    directory = scan_dir(paper_id, eval_root)
    scan_images = sorted(str(p) for p in directory.glob("*")) if directory.is_dir() else []
    return {"paper_id": paper_id, "scan_images": scan_images}


def load_pass2_context(
    paper_id: str, labeller_id: str, eval_root: Path = DEFAULT_EVAL_ROOT
) -> dict[str, object]:
    """Mark scheme + the labeller's OWN pass-1 transcription. Never pipeline output."""
    ms_path = mark_scheme_path(paper_id, eval_root)
    mark_scheme: dict[str, object] | None = None
    if ms_path.is_file():
        parsed = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
        mark_scheme = parsed.model_dump(mode="json")

    own_transcription = read_records(transcription_path(paper_id, labeller_id, eval_root))

    return {
        "paper_id": paper_id,
        "labeller_id": labeller_id,
        "mark_scheme": mark_scheme,
        "own_transcription": own_transcription,
    }
