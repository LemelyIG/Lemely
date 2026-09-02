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
_COMPONENT_ROW = re.compile(r"^Component\s+(\d+)\s+(\d+)\s+(.+)$")
#: `mark after` is optional -- that is the whole difference between the eras. It
#: is captured (not just matched) so callers know, from the header alone,
#: whether rows in this table carry a leading maximum-mark token.
_OPTION_HEADER = re.compile(r"^Option\s+(?:(mark\s+after)\s+)?((?:[A-Z]\*?\s+)*[A-Z]\*?)$")
#: Only the option code is pulled out here. The remainder is tokenized and
#: sliced by position -- see `_parse_option_row` -- because a single regex
#: cannot unambiguously tell a max-mark token from a lone component number.
_OPTION_ROW_PREFIX = re.compile(r"^([A-Z]{1,3})\s+(.+)$")


@dataclass(frozen=True, slots=True)
class ParsedComponent:
    """One component's thresholds, as the document prints them."""

    paper_number: int
    paper_variant: int
    max_mark: int
    thresholds: dict[str, int]


@dataclass(frozen=True, slots=True)
class ParsedOption:
    r"""One weighted option's thresholds, including A\*."""

    option_code: str
    component_numbers: list[int]
    max_mark_after_weighting: int | None
    thresholds: dict[str, int]


def _text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _parse_option_row(
    line: str, option_grades: list[str], has_max_mark_column: bool
) -> ParsedOption | None:
    """Parse one option row, or return ``None`` (after logging) on a shape mismatch.

    The row is split into whitespace tokens after the option code. Whether a
    maximum-mark column exists is known in advance from the header, not
    guessed per row, so the split is unambiguous for all four shapes: old/new
    era crossed with single/multi component.
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
        max_mark_token, component_tokens = prefix_tokens[0], prefix_tokens[1:]
    else:
        max_mark_token, component_tokens = None, prefix_tokens

    if not component_tokens or not all(t.rstrip(",").isdigit() for t in component_tokens):
        logger.warning("threshold PDF: option row has no valid component list, skipping: %r", line)
        return None
    if max_mark_token is not None and not max_mark_token.isdigit():
        logger.warning("threshold PDF: option row has a non-numeric max mark, skipping: %r", line)
        return None

    return ParsedOption(
        option_code=code,
        component_numbers=[int(t.rstrip(",")) for t in component_tokens],
        max_mark_after_weighting=int(max_mark_token) if max_mark_token is not None else None,
        thresholds={
            grade: int(value)
            for grade, value in zip(option_grades, value_tokens, strict=True)
            if value not in _NOT_APPLICABLE
        },
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

    for line in (raw.strip() for raw in text.splitlines()):
        header = _COMPONENT_HEADER.match(line)
        if header:
            component_grades = header.group(1).split()
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
            components.append(
                ParsedComponent(
                    paper_number=int(number_variant[0]),
                    paper_variant=int(number_variant[1]) if len(number_variant) > 1 else 0,
                    max_mark=max_mark,
                    thresholds={
                        grade: int(value)
                        for grade, value in zip(component_grades, rest, strict=True)
                        if value not in _NOT_APPLICABLE
                    },
                )
            )
            continue

        if option_grades:
            option = _parse_option_row(line, option_grades, option_has_max_mark_column)
            if option:
                options.append(option)

    return components, options
