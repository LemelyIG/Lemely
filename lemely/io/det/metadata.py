"""Cover-page and filename metadata extraction."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lemely.core.loose_schemas import (
    MarkSchemeMetadata,
    PaperType,
    SchemeFormat,
    SessionMonth,
    Tier,
)
from lemely.io.det.profiles import get_profile
from lemely.io.metadata import parse_caie_filename_metadata
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_PAPER_CODE_RE = re.compile(r"\b(\d{4})/(\d)(\d)\b")
# Two CAIE cover-page wordings, and the second is 94% of everything the
# parser could not read once the corpus was extended back to 2010.
#
#   2017+   "Maximum Mark: 70"
#   2010-16 "0580/21 Paper 2 (Extended), maximum raw mark 70"
#
# Measured over 1,130 source schemes: 411 of 438 parse failures (93.8%)
# were this pattern, and EVERY affected session is 2010-2016 — CAIE changed
# the cover page at the 2016/17 boundary. The parser raised here, before
# looking at a single question, so the whole decade was unreadable.
#
# `raw` is optional but SPECIFIC: a permissive gap such as \S+ would let
# unrelated cover prose ("the maximum number of candidates per mark is 99")
# supply the number, which is worse than failing.
_MAX_MARK_RE = re.compile(r"[Mm]aximum\s+(?:raw\s+)?[Mm]ark\s*[:\s]+(\d+)")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

_SESSION_PATTERNS: list[tuple[re.Pattern[str], SessionMonth]] = [
    (re.compile(r"May[/–\-]June|May/Jun", re.IGNORECASE), SessionMonth.MAY_JUNE),
    (re.compile(r"Oct(?:ober)?[/–\-]Nov(?:ember)?", re.IGNORECASE), SessionMonth.OCT_NOV),
    (re.compile(r"Feb(?:ruary)?[/–\-]Mar(?:ch)?", re.IGNORECASE), SessionMonth.FEB_MAR),
    (re.compile(r"Specimen", re.IGNORECASE), SessionMonth.SPECIMEN),
]

# Lines on the cover page that are definitely NOT the subject name
_SKIP_LINE_TOKENS = frozenset(
    ["cambridge", "igcse", "mark scheme", "©", "maximum", "published", "confidential"]
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_metadata(
    pdf: Any,
    pdf_path: Path,
    skip_line_tokens: frozenset[str] | None = None,
) -> MarkSchemeMetadata:
    """Build :class:`MarkSchemeMetadata` from the filename (primary) and cover page (fallback)."""
    skip_tokens = skip_line_tokens if skip_line_tokens is not None else _SKIP_LINE_TOKENS
    cover_text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""

    # --- Filename (authoritative for coded fields) ---
    subject_code: str | None = None
    paper_number: int | None = None
    paper_variant: int | None = None
    session_month: SessionMonth | None = None
    session_year: int | None = None

    try:
        fm = parse_caie_filename_metadata(pdf_path)
        subject_code = fm.subject_code
        paper_number = fm.paper_number
        paper_variant = fm.paper_variant
        session_month = _parse_session_month(fm.session_month)
        session_year = fm.session_year
    except ValueError:
        pass

    # --- Cover-page fallbacks ---
    if subject_code is None or paper_number is None:
        m = _PAPER_CODE_RE.search(cover_text)
        if m:
            subject_code = subject_code or m.group(1)
            paper_number = paper_number or int(m.group(2))
            paper_variant = paper_variant or int(m.group(3))

    if subject_code is None:
        raise ParseError(f"Cannot determine subject_code for {pdf_path.name}")
    if paper_number is None or paper_variant is None:
        raise ParseError(f"Cannot determine paper_number/paper_variant for {pdf_path.name}")

    # --- Session month ---
    if session_month is None:
        for pattern, month_val in _SESSION_PATTERNS:
            if pattern.search(cover_text):
                session_month = month_val
                break
        else:
            session_month = SessionMonth.MAY_JUNE

    # --- Session year ---
    if session_year is None and session_month != SessionMonth.SPECIMEN:
        m2 = _YEAR_RE.search(cover_text)
        if m2:
            session_year = int(m2.group(1))

    # --- Maximum mark (required) ---
    m3 = _MAX_MARK_RE.search(cover_text)
    if not m3:
        raise ParseError(f"Cannot extract maximum_mark from cover page of {pdf_path.name}")
    maximum_mark = int(m3.group(1))

    # --- Subject profile (drives name + paper_type) ---
    profile = get_profile(subject_code)
    subject = profile.name or _extract_subject_name_from_cover(
        cover_text, subject_code, skip_tokens
    )
    paper_type = profile.paper_type(paper_number, cover_text)
    scheme_format = SchemeFormat.MCQ if paper_type == PaperType.MCQ else SchemeFormat.POINT_BASED
    tier = _detect_tier(cover_text)
    published = "Published" in cover_text

    return MarkSchemeMetadata(
        subject=subject,
        subject_code=subject_code,
        paper_number=paper_number,
        paper_variant=paper_variant,
        session_month=session_month,
        session_year=session_year if session_month != SessionMonth.SPECIMEN else None,
        paper_type=paper_type,
        tier=tier,
        maximum_mark=maximum_mark,
        scheme_format=scheme_format,
        published=published,
        source_document=pdf_path.name,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_session_month(s: str) -> SessionMonth:
    for pattern, val in _SESSION_PATTERNS:
        if pattern.search(s):
            return val
    return SessionMonth.MAY_JUNE


def _extract_subject_name_from_cover(
    cover_text: str,
    subject_code: str,
    skip_tokens: frozenset[str],
) -> str:
    """Return the subject name line from the cover page, or a code-based fallback.

    Heuristics:
    - Skip blank / very short lines.
    - Skip lines containing known non-subject tokens (publisher, session, etc.).
    - Skip lines containing the subject code itself.
    - Skip lines that start with a digit.
    - Skip lines that look like sentences (contain lowercase letters followed by
      punctuation mid-line), which catches boilerplate like
      "It shows the basis on which Examiners were instructed…".
    """
    _SENTENCE_RE = re.compile(r"[a-z][.,:;?!]")

    for line in cover_text.splitlines():
        line = line.strip()
        if not line or len(line) < 4:
            continue
        lower = line.lower()
        if any(tok in lower for tok in skip_tokens):
            continue
        if subject_code in line:
            continue
        if any(p.search(line) for p, _ in _SESSION_PATTERNS):
            continue
        if line[0].isdigit():
            continue
        # Reject sentences — boilerplate paragraph lines
        if _SENTENCE_RE.search(line):
            continue
        return line
    return f"CAIE Subject {subject_code}"


def _detect_tier(cover_text: str) -> Tier | None:
    lower = cover_text.lower()
    if "core" in lower:
        return Tier.CORE
    if "extended" in lower:
        return Tier.EXTENDED
    return None
