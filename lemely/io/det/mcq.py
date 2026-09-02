"""MCQ answer-key parser.

Every path that discards a table or a row here is instrumented (#94). The det
parser used to drop questions with no warning, no counter and no record, so a
scheme yielding 12 questions instead of 40 was indistinguishable from one that
legitimately has 12 — see :class:`MCQParseDiagnostics` for what is now counted
and :func:`describe_answer_col_rejection` for why a table was rejected.

**What was already reported before this instrumentation, and what was not.**
The *fact* of a shortfall is not new: ``lemely.io.det.reconcile`` compares the
parsed mark total against the cover page's ``maximum_mark`` and logs
``mark_total_mismatch_escalating`` (or ``…_warning`` when escalation is off).
What was missing is the *mechanism* — nothing said that a 29-row table had been
thrown away because one cell read ``QUESTION DISCOUNTED``. "This paper failed"
is a bucket; "this paper failed because one withdrawn question disqualified its
whole answer column" is a work order.

Two gaps the reconciler leaves that this instrumentation covers on its own:

- it compares **marks**, not question counts, so loss is only visible when the
  totals happen to disagree — a drop compensated by an overcount nets out;
- it is silent about rows discarded *inside* a table it accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from lemely.core.loose_schemas import MCQAnswer, Question, QuestionType
from lemely.runtime.errors import ParseError

log = structlog.get_logger()

_MCQ_LETTERS: frozenset[str] = frozenset("ABCD")

#: Cap on how many disqualifying values are recorded per rejected column. The
#: point of the diagnostic is to name the offender, not to reproduce the
#: column — an unbounded list would bury the log line it exists to make
#: readable.
_MAX_REPORTED_VALUES = 5


@dataclass
class MCQParseDiagnostics:
    """Countable record of everything :func:`parse_mcq_tables` discarded.

    Passed in by the caller and filled in place, so the return type of
    :func:`parse_mcq_tables` is unchanged and no existing call site has to move.
    A caller that wants only the log lines passes nothing.
    """

    tables_seen: int = 0
    tables_empty: int = 0
    """Tables with no rows at all."""

    tables_without_data_rows: int = 0
    """Tables whose rows all had fewer than two non-empty cells."""

    tables_without_answer_col: int = 0
    """Tables discarded because no column held only A/B/C/D — the #94 defect."""

    rows_discarded_in_kept_tables: int = 0
    """Rows dropped inside a table that WAS parsed (header rows, withdrawn
    questions, duplicates). Invisible to the mark-total reconciler, which sees
    only the final total."""

    rows_discarded_data: int = 0
    """Data rows lost with their tables (``tables_without_answer_col``)."""

    questions_parsed: int = 0

    rejections: list[dict[str, object]] = field(default_factory=list)
    """One entry per table rejected for want of an answer column, carrying the
    column index and the values that disqualified it."""

    def as_log_fields(self) -> dict[str, object]:
        """Flat, log-friendly summary — no nested list, so it greps cleanly."""
        return {
            "tables_seen": self.tables_seen,
            "tables_empty": self.tables_empty,
            "tables_without_data_rows": self.tables_without_data_rows,
            "tables_without_answer_col": self.tables_without_answer_col,
            "rows_discarded_data": self.rows_discarded_data,
            "rows_discarded_in_kept_tables": self.rows_discarded_in_kept_tables,
            "questions_parsed": self.questions_parsed,
        }


def find_mcq_answer_col(rows: list[list[str | None]]) -> int | None:
    """Return the rightmost column index whose non-empty values are all in A/B/C/D.

    Skips column 0 (Q-number column).
    """
    if not rows:
        return None
    num_cols = max(len(r) for r in rows)
    for col in range(num_cols - 1, 0, -1):
        values = [
            (r[col] or "").strip().upper() for r in rows if len(r) > col and (r[col] or "").strip()
        ]
        if values and all(v in _MCQ_LETTERS for v in values):
            return col
    return None


def describe_answer_col_rejection(rows: list[list[str | None]]) -> dict[str, object]:
    """Explain why :func:`find_mcq_answer_col` found no answer column.

    Kept separate from :func:`find_mcq_answer_col` so that function stays a
    pure ``rows -> index | None`` lookup with no diagnostic baggage, and so the
    explanation is only computed on the failing path.

    The reported column is the **densest** candidate — the one with the most
    non-empty values — because that is overwhelmingly the real answer column
    when a single anomalous cell has disqualified it. Reporting the rightmost
    instead would frequently name a one-cell header like ``MARKS`` and bury the
    actual offender.
    """
    if not rows:
        return {"reason": "no rows"}
    num_cols = max(len(r) for r in rows)
    best: dict[str, object] | None = None
    best_density = -1
    for col in range(1, num_cols):
        values = [
            (r[col] or "").strip().upper() for r in rows if len(r) > col and (r[col] or "").strip()
        ]
        if not values:
            continue
        offenders = [v for v in values if v not in _MCQ_LETTERS]
        if not offenders:
            continue  # would have been accepted; not a rejection cause
        if len(values) <= best_density:
            continue
        best_density = len(values)
        best = {
            "reason": "no column held only A/B/C/D",
            "column": col,
            "values_in_column": len(values),
            "disqualifying_count": len(offenders),
            "disqualifying_values": sorted(set(offenders))[:_MAX_REPORTED_VALUES],
        }
    return best or {"reason": "no candidate column had any values"}


def parse_mcq_tables(
    tables: list[list[list[str | None]]],
    *,
    source: str | None = None,
    diagnostics: MCQParseDiagnostics | None = None,
) -> list[Question]:
    """Extract an MCQ answer key from tables whose answer column contains only A/B/C/D.

    Args:
        tables: Raw pdfplumber tables.
        source: Document name, for the log lines only.
        diagnostics: Optional collector, filled in place (#94). Omitting it
            leaves behaviour identical apart from the log lines.
    """
    all_questions: list[Question] = []
    seen_ids: set[str] = set()
    diag = diagnostics if diagnostics is not None else MCQParseDiagnostics()
    ctx = {"source": source}

    for table_index, table in enumerate(tables):
        diag.tables_seen += 1
        if not table:
            diag.tables_empty += 1
            continue
        data_rows = [r for r in table if r and sum(1 for c in r if (c or "").strip()) >= 2]
        if not data_rows:
            diag.tables_without_data_rows += 1
            log.warning(
                "det_mcq_table_without_data_rows",
                table_index=table_index,
                rows=len(table),
                **ctx,
            )
            continue

        answer_col = find_mcq_answer_col(data_rows)
        if answer_col is None:
            rejection = describe_answer_col_rejection(data_rows)
            diag.tables_without_answer_col += 1
            diag.rows_discarded_data += len(data_rows)
            diag.rejections.append({"table_index": table_index, **rejection})
            # The #94 defect: one anomalous cell costs the whole table. This is
            # a warning rather than a debug line precisely because it is
            # invisible downstream — the reconciler sees a smaller total, never
            # the reason for it.
            log.warning(
                "det_mcq_table_discarded_no_answer_col",
                table_index=table_index,
                data_rows_discarded=len(data_rows),
                **rejection,
                **ctx,
            )
            continue

        for row in data_rows:
            if len(row) <= answer_col:
                diag.rows_discarded_in_kept_tables += 1
                continue
            q_cell = (row[0] or "").strip()
            ans_cell = (row[answer_col] or "").strip().upper()

            if not q_cell.isdigit() or ans_cell not in _MCQ_LETTERS:
                diag.rows_discarded_in_kept_tables += 1
                continue
            if q_cell in seen_ids:
                diag.rows_discarded_in_kept_tables += 1
                continue

            try:
                mcq_answer = MCQAnswer(ans_cell)
            except ValueError:
                diag.rows_discarded_in_kept_tables += 1
                continue

            seen_ids.add(q_cell)
            all_questions.append(
                Question(
                    id=q_cell,
                    marks=1,
                    type=QuestionType.MCQ,
                    mcq_answer=mcq_answer,
                )
            )

    diag.questions_parsed = len(all_questions)
    log.info("det_mcq_parse_summary", **diag.as_log_fields(), **ctx)

    if not all_questions:
        raise ParseError(
            "Could not find an MCQ answer-key table "
            "(expected a table with a column containing only A/B/C/D)"
        )
    return all_questions
