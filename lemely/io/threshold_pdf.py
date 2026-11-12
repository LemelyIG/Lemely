r"""Parser for official CAIE grade-threshold PDFs.

One document carries two tables and they mean different things:

* **Components** -- minimum raw mark per grade for one paper. The document
  states "Grade A\* does not exist at the level of an individual component",
  which is why a single marked paper can never be graded A\*.
* **Options** -- thresholds for a weighted combination of components (e.g.
  ``BX = 21, 41, 51``), and the only place A\* appears.

Two layout eras exist for each table and both are still in circulation, so both
are handled. The component header is either ``mark A B C ...`` or ``Component A
B C ...``; the option header is either ``Option A* A B ...`` (pre-2020, no
maximum-mark column) or ``Option mark after A* A B ...`` (current). A parser
that knows only the current layout returns nothing for older sessions and does
so without complaint, which is worse than failing.

Option rows are parsed by token position rather than by a single greedy regex:
whether a maximum-mark column is present is decided once, from which header
matched, and carried as state while scanning rows. A regex that instead tries
to infer "is this token a max mark or a component number" from punctuation
alone is ambiguous for a single-component option in the no-max-mark era (e.g.
``AX 40 130 106 84 ...`` -- no comma anywhere), and silently misreads the
component number as a max mark and shifts every grade value by one column.

Individual grade cells are read defensively. CAIE has used at least three
spellings of "not applicable at this tier" across the document's lifetime --
an en dash, a hyphen, and (2011-era documents) the literal string "N/A" -- and
a fourth is only a matter of time. A cell that is not a recognised
not-applicable marker and not an integer is logged and treated as
not-applicable rather than raising: one unexpected glyph in one cell must not
abort ingestion of every subject that would otherwise parse cleanly.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

import pdfplumber

logger = logging.getLogger("lemely.io.threshold_pdf")

#: CAIE marks "not applicable at this tier" with an en dash, em dash, or hyphen.
_NOT_APPLICABLE = ("–", "-", "—")  # noqa: RUF001 - matches CAIE's literal dash glyphs

_COMPONENT_HEADER = re.compile(r"^(?:mark|Component)\s+((?:[A-Z]\*?\s+)*[A-Z]\*?)$")
#: A third, older layout wraps the header cell onto its own lines: a bare
#: "mark" line, then the grade letters alone on the next line (e.g. 0580
#: s11: "mark" / "A C E F" / "available"). The grade-letters line is matched
#: only when it directly follows a line that is exactly "mark", so a stray
#: single letter elsewhere in the text (this exact fixture has watermark
#: bleed-through of isolated characters) cannot be mistaken for a header.
_COMPONENT_HEADER_WRAPPED_GRADES = re.compile(r"^((?:[A-Z]\*?\s+)+[A-Z]\*?)$")
_COMPONENT_ROW = re.compile(r"^Component\s+(\d+)\s+(\d+)\s+(.+)$")
#: `mark after` is optional -- that is the whole difference between the eras. It
#: is captured (not just matched) so callers know, from the header alone,
#: whether rows in this table carry a leading maximum-mark token.
_OPTION_HEADER = re.compile(r"^Option\s+(?:(mark\s+after)\s+)?((?:[A-Z]\*?\s+)*[A-Z]\*?)$")
#: Only the option code is pulled out here. The remainder is tokenized and
#: sliced by position -- see `_parse_option_row` -- because a single regex
#: cannot unambiguously tell a max-mark token from a lone component number.
_OPTION_ROW_PREFIX = re.compile(r"^([A-Z]{1,3})\s+(.+)$")


def _grade_value(value: str, line: str) -> int | None:
    """Return the integer for one grade cell, or ``None`` if it is not applicable.

    "Not applicable at this tier" covers a dash, "N/A" (any case), or a
    convention this parser has never seen before. A cell this function
    cannot make sense of never raises: it is logged and treated as
    not-applicable, exactly like a recognised marker, so a single unexpected
    glyph cannot abort parsing of the whole document.
    """
    stripped = value.strip()
    if stripped in _NOT_APPLICABLE or stripped.upper() == "N/A":
        return None
    try:
        return int(stripped)
    except ValueError:
        logger.warning(
            "threshold PDF: unrecognised grade cell %r, treating as not applicable: %r",
            value,
            line,
        )
        return None


def _grade_thresholds(
    grades: list[str], values: list[str], line: str
) -> tuple[dict[str, int], bool]:
    """Zip a header's grades against a row's values.

    Not-applicable cells (a recognised dash/"N/A" marker) are dropped rather
    than raised or stored as a sentinel — that is a real, intentional absence
    ("not applicable at this tier").

    Returns ``(thresholds, had_unrecognised_cell)``. The second element is
    True when at least one cell was neither a parseable integer nor a
    recognised not-applicable marker — i.e. ``_grade_value`` fell through to
    its "unrecognised glyph" branch and logged a warning. That case must stay
    distinguishable from a genuine dash: a garbled cell is a parse failure the
    ingest cannot silently trust, while a dash is Cambridge's own statement
    that the grade does not apply.
    """
    thresholds: dict[str, int] = {}
    had_unrecognised_cell = False
    for grade, value in zip(grades, values, strict=True):
        parsed = _grade_value(value, line)
        if parsed is not None:
            thresholds[grade] = parsed
            continue
        stripped = value.strip()
        if stripped not in _NOT_APPLICABLE and stripped.upper() != "N/A":
            had_unrecognised_cell = True
    return thresholds, had_unrecognised_cell


@dataclass(frozen=True, slots=True)
class ParsedComponent:
    """One component's thresholds, as the document prints them."""

    paper_number: int
    paper_variant: int
    max_mark: int
    thresholds: dict[str, int]
    #: True when at least one grade cell in this row was neither a parseable
    #: integer nor a recognised not-applicable marker (dash/"N/A"). The
    #: ingest must not treat such a row as verified: a dropped, garbled cell
    #: is invisible in ``thresholds`` alone and would otherwise be
    #: indistinguishable from a grade Cambridge genuinely does not publish.
    has_unrecognised_cell: bool = False


@dataclass(frozen=True, slots=True)
class ParsedOption:
    r"""One weighted option's thresholds, including A\*."""

    option_code: str
    component_numbers: list[int]
    max_mark_after_weighting: int | None
    thresholds: dict[str, int]
    #: True when a grade cell was present but unreadable, so `thresholds` is
    #: narrower than the document. Distinct from a recognised "not applicable"
    #: marker, which is a real absence and does not set this.
    parse_incomplete: bool = False


def _text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _parse_option_row(
    line: str, option_grades: list[str], has_max_mark_column: bool
) -> ParsedOption | None:
    """Parse one option row, or return ``None`` (after logging) on a shape mismatch.

    The row is split into whitespace tokens after the option code, and the
    last N of them (N = the header's grade count) are always the grade
    values. Whether a maximum-mark column precedes the component list is
    known in advance from the header, not guessed per row, so the split is
    unambiguous for all four shapes: old/new era crossed with single/multi
    component. The component list itself is re-normalised on comma and/or
    whitespace, since CAIE is inconsistent about the space after a comma.
    """
    match = _OPTION_ROW_PREFIX.match(line)
    if not match:
        return None

    code, remainder = match.group(1), match.group(2)
    tokens = remainder.split()
    grade_count = len(option_grades)

    if len(tokens) < grade_count + (1 if has_max_mark_column else 0):
        logger.warning(
            "threshold PDF: option row too short for %d-grade header, skipping: %r",
            grade_count,
            line,
        )
        return None

    value_tokens = tokens[-grade_count:]
    prefix_tokens = tokens[:-grade_count]

    if has_max_mark_column:
        max_mark_token, component_prefix = prefix_tokens[0], prefix_tokens[1:]
    else:
        max_mark_token, component_prefix = None, prefix_tokens

    # Commas separating component numbers are not reliably followed by a
    # space ("21, 41, 51" and "21,41,51" both occur), so the component list
    # is normalised by re-splitting the joined prefix on any run of commas
    # and/or whitespace rather than trusting whitespace token boundaries.
    component_tokens = [t for t in re.split(r"[,\s]+", " ".join(component_prefix)) if t]

    if not component_tokens or not all(t.isdigit() for t in component_tokens):
        logger.warning("threshold PDF: option row has no valid component list, skipping: %r", line)
        return None
    if max_mark_token is not None and not max_mark_token.isdigit():
        logger.warning("threshold PDF: option row has a non-numeric max mark, skipping: %r", line)
        return None

    option_thresholds, had_unrecognised_cell = _grade_thresholds(option_grades, value_tokens, line)
    return ParsedOption(
        option_code=code,
        component_numbers=[int(t) for t in component_tokens],
        max_mark_after_weighting=int(max_mark_token) if max_mark_token is not None else None,
        thresholds=option_thresholds,
        parse_incomplete=had_unrecognised_cell,
    )


def parse_threshold_pdf(pdf_bytes: bytes) -> tuple[list[ParsedComponent], list[ParsedOption]]:
    """Return ``(components, options)``.

    Empty lists are a supported outcome, not an error: pre-2014 documents carry
    a watermark that bleeds into the text layer and defeats line-based parsing.
    The ingest stores those sessions unverified rather than aborting the run,
    so one unreadable document cannot cost us fifty readable ones.

    A row that matches its table's leading pattern but not its header's grade
    count is dropped, with a warning naming the offending line, rather than
    disappearing silently -- a partial parse should be visible, since Task 12
    trusts this parser to decide which third-party numbers are legitimate.
    """
    try:
        text = _text(pdf_bytes)
    except Exception:
        return [], []

    components: list[ParsedComponent] = []
    options: list[ParsedOption] = []
    component_grades: list[str] | None = None
    option_grades: list[str] | None = None
    option_has_max_mark_column = False
    lines = [raw.strip() for raw in text.splitlines()]

    for i, line in enumerate(lines):
        header = _COMPONENT_HEADER.match(line)
        if header:
            component_grades = header.group(1).split()
            continue
        # 0580 s11-era layout: the header cell wraps onto its own lines, so
        # the grade letters appear alone, directly after a bare "mark" line.
        wrapped_header = _COMPONENT_HEADER_WRAPPED_GRADES.match(line)
        if wrapped_header and i > 0 and lines[i - 1] == "mark":
            component_grades = wrapped_header.group(1).split()
            continue
        option_header = _OPTION_HEADER.match(line)
        if option_header:
            option_has_max_mark_column = option_header.group(1) is not None
            option_grades = option_header.group(2).split()
            continue

        row = _COMPONENT_ROW.match(line)
        if row and component_grades:
            number_variant, max_mark, rest = row.group(1), int(row.group(2)), row.group(3).split()
            if len(rest) != len(component_grades):
                logger.warning(
                    "threshold PDF: component row has %d values for a %d-grade header,"
                    " skipping: %r",
                    len(rest),
                    len(component_grades),
                    line,
                )
                continue
            component_thresholds, had_unrecognised_cell = _grade_thresholds(
                component_grades, rest, line
            )
            components.append(
                ParsedComponent(
                    paper_number=int(number_variant[0]),
                    paper_variant=int(number_variant[1]) if len(number_variant) > 1 else 0,
                    max_mark=max_mark,
                    thresholds=component_thresholds,
                    has_unrecognised_cell=had_unrecognised_cell,
                )
            )
            continue

        if option_grades:
            option = _parse_option_row(line, option_grades, option_has_max_mark_column)
            if option:
                options.append(option)

    return components, options
