"""CAIE mark-type notation parser.

Handles both bare integers ("2") and mark-type codes used in mark-scheme
PDFs ("B1", "C1", "A1", "M1", "B2", "(C1)", "(A1)", etc.).

CAIE mark types relevant to sciences:
  B — independent knowledge mark
  C — consequential / method mark (Physics / Sciences; NOT in the mathematics
      tradition's A/M split, but ubiquitous in CAIE science mark schemes)
  A — accuracy mark
  M — method mark (mathematics papers)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lemely.core.loose_schemas import MathMarkType

# Matches the canonical CAIE mark-type notation:
#   optional leading paren  →  optional letter  →  digits  →  optional closing paren
#
# Examples matched: "1", "B1", "C1", "A1", "M2", "(C1)", "(A1)", "(B2)", "b1"
# Examples NOT matched: "B", "", "abc", "100+" (value > max handled separately)
_MARK_CELL_RE = re.compile(r"^\(?\s*([BbCcAaMm])?\s*(\d+)\s*\)?$")

# Mapping from the (uppercase) letter in a mark-type cell to MathMarkType.
# Letters not in this map produce math_mark_type=None.
_LETTER_MAP: dict[str, MathMarkType] = {
    "B": MathMarkType.B,
    "C": MathMarkType.C,
    "A": MathMarkType.A,
    "M": MathMarkType.M,
}


@dataclass(frozen=True)
class ParsedMark:
    """Result of parsing a single mark-type cell."""

    value: int
    """The integer mark value (e.g. 1, 2)."""

    math_mark_type: MathMarkType | None
    """The CAIE mark type letter, or None for bare integers."""


def parse_marks_cell(cell: str, max_value: int = 40) -> ParsedMark | None:
    """Parse a mark-type notation cell to a :class:`ParsedMark`.

    Returns ``None`` for empty cells or cells that do not match the expected
    notation (so the caller can distinguish "not a marks cell" from "marks=0").

    Args:
        cell: Raw string from the marks column of a pdfplumber table row.
        max_value: Upper bound for plausible mark values; prevents year
            numbers (e.g. "2019") from being accepted. Defaults to 40.

    Examples::

        parse_marks_cell("B1")     → ParsedMark(1, MathMarkType.B)
        parse_marks_cell("C1")     → ParsedMark(1, MathMarkType.C)
        parse_marks_cell("(A1)")   → ParsedMark(1, MathMarkType.A)
        parse_marks_cell("2")      → ParsedMark(2, None)
        parse_marks_cell("B2")     → ParsedMark(2, MathMarkType.B)
        parse_marks_cell("")       → None
        parse_marks_cell("abc")    → None
        parse_marks_cell("2019")   → None  (exceeds max_value)
    """
    stripped = cell.strip()
    if not stripped:
        return None
    m = _MARK_CELL_RE.match(stripped)
    if not m:
        return None
    value = int(m.group(2))
    if value > max_value:
        return None
    letter = (m.group(1) or "").upper()
    return ParsedMark(value=value, math_mark_type=_LETTER_MAP.get(letter))


def is_marks_column(column_values: list[str], max_value: int = 40) -> bool:
    """Return True if all non-empty values in *column_values* are valid mark cells.

    A column qualifies as the marks column when every non-empty cell either:
    - Is a bare integer in ``[0, max_value]``, or
    - Matches CAIE mark-type notation like "B1", "(C1)", "A2".

    An entirely-empty column returns False (spacer columns in sparse tables).
    """
    non_empty = [v.strip() for v in column_values if v.strip()]
    if not non_empty:
        return False
    return all(parse_marks_cell(v, max_value) is not None for v in non_empty)
