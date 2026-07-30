"""Column model: detect which columns carry Q-numbers, answers, guidance, marks."""

from __future__ import annotations

from dataclasses import dataclass

from lemely.io.det.marks import is_marks_column


@dataclass(frozen=True)
class ColumnLayout:
    """Indices describing the column layout of a merged mark-scheme table."""

    q_col: int
    """Column index for the question-number cell (always 0)."""

    answer_col_end: int
    """Exclusive end index of the answer-text span (cols q_col+1 .. answer_col_end-1)."""

    guidance_col: int | None
    """Column index for the guidance/notes column, or None if absent."""

    marks_col: int
    """Column index for the marks column."""


def detect_columns(
    merged_rows: list[list[str | None]],
    max_mark: int = 40,
) -> ColumnLayout:
    """Infer the :class:`ColumnLayout` from the merged table rows.

    Detection strategy (mirrors the original ``_find_marks_col_theory`` but
    uses :func:`~lemely.io.det.marks.is_marks_column` so that CAIE mark-type
    codes like "B1" / "C1" are recognised):

    1. Scan columns right-to-left for the rightmost marks column.
    2. If a 4-column table is found with marks at col 3, treat col 2 as guidance.
    3. Everything between col 0 and the answer_col_end is the answer span.
    """
    if not merged_rows:
        return ColumnLayout(q_col=0, answer_col_end=1, guidance_col=None, marks_col=1)

    ncols = max(len(r) for r in merged_rows)
    marks_col = _find_marks_col(merged_rows, ncols, max_mark)

    guidance_col: int | None = None
    # Only assign a guidance column for the classic dense 4-column format.
    # In the sparse 9-column CAIE layout (data at cols 0, 3, 6) the column
    # just before marks_col is another spacer, not guidance text.
    if ncols == 4 and marks_col == 3:
        guidance_col = 2

    answer_col_end = guidance_col if guidance_col is not None else marks_col
    return ColumnLayout(
        q_col=0,
        answer_col_end=answer_col_end,
        guidance_col=guidance_col,
        marks_col=marks_col,
    )


def _find_marks_col(merged: list[list[str | None]], ncols: int, max_mark: int) -> int:
    """Return the rightmost column index whose non-empty values are all valid marks."""
    for c in range(ncols - 1, -1, -1):
        col_values = [((row[c] if c < len(row) else None) or "") for row in merged]
        if is_marks_column(col_values, max_mark):
            return c
    return ncols - 1  # fallback: last column
