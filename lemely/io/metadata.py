from __future__ import annotations

import re
from pathlib import Path

from lemely.core.schemas import ExamMetadata

_CAIE_MARK_SCHEME_RE = re.compile(
    r"^(?P<subject_code>\d{4})_(?P<session>[msw])(?P<year>\d{2})_ms_(?P<paper>\d)(?P<variant>\d)\.pdf$",
    re.IGNORECASE,
)

_SESSION_MONTHS = {
    "m": "Feb/Mar",
    "s": "May/June",
    "w": "Oct/Nov",
}


def parse_caie_filename_metadata(filename: str | Path) -> ExamMetadata:
    name = Path(filename).name
    match = _CAIE_MARK_SCHEME_RE.match(name)
    if not match:
        raise ValueError(f"Unsupported CAIE mark-scheme filename: {name}")

    session = match.group("session").lower()
    year = 2000 + int(match.group("year"))
    return ExamMetadata(
        subject_code=match.group("subject_code"),
        paper_number=int(match.group("paper")),
        paper_variant=int(match.group("variant")),
        session_month=_SESSION_MONTHS[session],
        session_year=year,
        source_document=name,
    )
