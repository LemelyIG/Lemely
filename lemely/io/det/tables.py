"""Table selection: filter out embedded grids from mark-scheme PDFs.

pdfplumber sometimes detects *multiple* tables on a single page when a
data/display grid (e.g. a logic-gate truth table) is embedded inside the
mark-scheme table.  We want only the primary mark-scheme table per page.

Strategy: for each page take at most the **first** table that qualifies as a
mark-scheme table.  A table qualifies when:
  - It has at least 2 rows with 2+ non-empty cells, AND
  - Either a marks column is detectable (via ``is_marks_column``) OR a
    header row contains standard mark-scheme keywords.

Any subsequent table on the same page is treated as embedded content.
"""

from __future__ import annotations

from typing import Any

from lemely.io.det.marks import is_marks_column

# Keywords that strongly indicate a row is a mark-scheme column header.
_MS_HEADER_TOKENS: frozenset[str] = frozenset({"question", "answer", "marks", "guidance", "notes"})


def _has_header_row(table: list[list[str | None]]) -> bool:
    """Return True if any row looks like a standard mark-scheme header."""
    for row in table[:3]:  # only inspect the first few rows
        cells_lower = {(c or "").strip().lower() for c in row}
        if cells_lower & _MS_HEADER_TOKENS:
            return True
    return False


def _has_marks_column(table: list[list[str | None]], max_value: int) -> bool:
    """Return True if the table has a detectable marks column."""
    if not table:
        return False
    ncols = max(len(r) for r in table)
    for c in range(ncols - 1, -1, -1):
        col_values = [(r[c] if c < len(r) else None) or "" for r in table]
        non_empty = [v.strip() for v in col_values if v.strip()]
        if non_empty and is_marks_column(col_values, max_value):
            return True
    return False


def _has_enough_data_rows(table: list[list[str | None]], min_rows: int = 2) -> bool:
    """Return True if the table has at least *min_rows* rows with 2+ non-empty cells."""
    count = 0
    for row in table:
        if row and sum(1 for c in row if (c or "").strip()) >= 2:
            count += 1
            if count >= min_rows:
                return True
    return False


def qualifies_as_mark_scheme_table(table: list[list[str | None]], max_mark: int = 40) -> bool:
    """Return True if *table* looks like a primary mark-scheme table."""
    if not _has_enough_data_rows(table):
        return False
    return _has_header_row(table) or _has_marks_column(table, max_mark)


def select_tables(
    pdf: Any,
    page_start: int,
    max_mark: int = 40,
) -> list[list[list[str | None]]]:
    """Collect mark-scheme tables from PDF pages starting at *page_start*.

    For each page, at most **one** table is kept — the first qualifying
    mark-scheme table.  Subsequent tables on the same page are dropped to
    avoid embedded truth tables / data grids being parsed as questions.

    Falls back to page ``page_start - 1`` when no tables are found at
    ``page_start`` (handles short documents or unusual GMP layouts).

    Returns a flat list of tables (each table is a list of rows).
    """
    pages = pdf.pages

    for start in (page_start, max(0, page_start - 1)):
        all_tables: list[list[list[str | None]]] = []
        for page in pages[start:]:
            page_tables = page.extract_tables()
            for tbl in page_tables:
                if qualifies_as_mark_scheme_table(tbl, max_mark):
                    all_tables.append(tbl)
                    break  # skip any further tables on this page
        if all_tables:
            return all_tables

    return []
