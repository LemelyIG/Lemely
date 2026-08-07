"""Table selection: filter out embedded grids from mark-scheme PDFs.

pdfplumber sometimes detects *multiple* tables on a single page when a
data/display grid (e.g. a logic-gate truth table) is embedded inside the
mark-scheme table, or simply because two consecutive questions' mark-scheme
tables both land on the same physical page (common when a question is short,
e.g. a 1-2 mark question directly followed by the next question's header row
lower on the page).

Strategy: for each page, keep **every** table that individually qualifies as
a mark-scheme table.  A table qualifies when:
  - It has at least 2 rows with 2+ non-empty cells, AND
  - Either a marks column is detectable (via ``is_marks_column``) OR a
    header row contains standard mark-scheme keywords.

Non-qualifying tables (embedded truth tables / data grids, which have
neither a marks column nor mark-scheme header tokens) are dropped. Note this
function previously kept only the *first* qualifying table per page and
dropped any subsequent ones as "embedded content" — that was wrong: a
second, independently-qualifying table on the same page is a second
legitimate question block, not embedded content. The qualification check
above is what actually distinguishes real mark-scheme tables from grids;
capping at one-per-page silently dropped whole questions whenever a paper's
layout put two of them on one page (confirmed via
``0625_w24_ms_41.pdf``, where question 2's entire table was discarded this
way).
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

    Every table on every page that individually qualifies as a mark-scheme
    table (see module docstring) is kept — a page may legitimately contain
    more than one (e.g. a short question ending partway down a page,
    followed by the next question's table further down the same page).
    Non-qualifying tables (embedded grids) are dropped regardless of position.

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
        if all_tables:
            return all_tables

    return []
