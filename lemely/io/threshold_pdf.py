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
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber

#: CAIE marks "not applicable at this tier" with an en dash, em dash, or hyphen.
_NOT_APPLICABLE = ("–", "-", "—")  # noqa: RUF001 - matches CAIE's literal dash glyphs

_COMPONENT_HEADER = re.compile(r"^(?:mark|Component)\s+((?:[A-Z]\*?\s+)*[A-Z]\*?)$")
_COMPONENT_ROW = re.compile(r"^Component\s+(\d+)\s+(\d+)\s+(.+)$")
#: `mark after` is optional -- that is the whole difference between the eras.
_OPTION_HEADER = re.compile(r"^Option\s+(?:mark\s+after\s+)?((?:[A-Z]\*?\s+)*[A-Z]\*?)$")
_OPTION_ROW = re.compile(
    r"^([A-Z]{1,3})\s+(?:(\d+)\s+)?((?:\d+\s*,\s*)*\d+)\s+((?:[-–\d]+\s+)*[-–\d]+)$"  # noqa: RUF001
)


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


def parse_threshold_pdf(pdf_bytes: bytes) -> tuple[list[ParsedComponent], list[ParsedOption]]:
    """Return ``(components, options)``.

    Empty lists are a supported outcome, not an error: pre-2014 documents carry
    a watermark that bleeds into the text layer and defeats line-based parsing.
    The ingest stores those sessions unverified rather than aborting the run,
    so one unreadable document cannot cost us fifty readable ones.
    """
    try:
        text = _text(pdf_bytes)
    except Exception:
        return [], []

    components: list[ParsedComponent] = []
    options: list[ParsedOption] = []
    component_grades: list[str] | None = None
    option_grades: list[str] | None = None

    for line in (raw.strip() for raw in text.splitlines()):
        header = _COMPONENT_HEADER.match(line)
        if header:
            component_grades = header.group(1).split()
            continue
        option_header = _OPTION_HEADER.match(line)
        if option_header:
            option_grades = option_header.group(1).split()
            continue

        row = _COMPONENT_ROW.match(line)
        if row and component_grades:
            number_variant, max_mark, rest = row.group(1), int(row.group(2)), row.group(3).split()
            if len(rest) != len(component_grades):
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

        option = _OPTION_ROW.match(line)
        if option and option_grades:
            values = option.group(4).split()
            if len(values) != len(option_grades):
                continue
            options.append(
                ParsedOption(
                    option_code=option.group(1),
                    component_numbers=[int(c.strip()) for c in option.group(3).split(",")],
                    max_mark_after_weighting=int(option.group(2)) if option.group(2) else None,
                    thresholds={
                        grade: int(value)
                        for grade, value in zip(option_grades, values, strict=True)
                        if value not in _NOT_APPLICABLE
                    },
                )
            )

    return components, options
