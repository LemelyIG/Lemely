from __future__ import annotations

import re
from pathlib import Path

from lemely.core.schemas import ExamMetadata

_CAIE_MARK_SCHEME_RE = re.compile(
    r"^(?P<subject_code>\d{4})_(?P<session>[msw])(?P<year>\d{2})_ms_(?P<paper>\d)(?P<variant>\d)\.pdf$",
    re.IGNORECASE,
)

_CAIE_QUESTION_PAPER_RE = re.compile(
    r"^(?P<subject_code>\d{4})_(?P<session>[msw])(?P<year>\d{2})_qp_(?P<paper>\d)(?P<variant>\d)\.pdf$",
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


def parse_caie_qp_filename_metadata(filename: str | Path) -> ExamMetadata:
    """Same convention as :func:`parse_caie_filename_metadata`, for ``_qp_`` files.

    CAIE past-paper filenames follow ``<subject>_<session><yy>_qp_<paper><variant>.pdf``
    (question paper) alongside the ``_ms_`` (mark scheme) convention the sibling
    function already handles — same four fields, different infix.
    """
    name = Path(filename).name
    match = _CAIE_QUESTION_PAPER_RE.match(name)
    if not match:
        raise ValueError(f"Unsupported CAIE question-paper filename: {name}")

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


def question_paper_to_mark_scheme_stem(qp_stem: str) -> str:
    """Map a question-paper file stem to its paired mark-scheme stem.

    ``0625_s23_qp_41`` -> ``0625_s23_ms_41`` — the two share every field
    except the ``qp``/``ms`` infix, by CAIE convention. Returns the input
    unchanged if it does not contain ``_qp_`` (caller's problem to detect).
    """
    return qp_stem.replace("_qp_", "_ms_")
