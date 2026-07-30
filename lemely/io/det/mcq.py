"""MCQ answer-key parser."""

from __future__ import annotations

from lemely.core.loose_schemas import MCQAnswer, Question, QuestionType
from lemely.runtime.errors import ParseError

_MCQ_LETTERS: frozenset[str] = frozenset("ABCD")


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


def parse_mcq_tables(tables: list[list[list[str | None]]]) -> list[Question]:
    """Extract an MCQ answer key from tables whose answer column contains only A/B/C/D."""
    all_questions: list[Question] = []
    seen_ids: set[str] = set()

    for table in tables:
        if not table:
            continue
        data_rows = [r for r in table if r and sum(1 for c in r if (c or "").strip()) >= 2]
        if not data_rows:
            continue

        answer_col = find_mcq_answer_col(data_rows)
        if answer_col is None:
            continue

        for row in data_rows:
            if len(row) <= answer_col:
                continue
            q_cell = (row[0] or "").strip()
            ans_cell = (row[answer_col] or "").strip().upper()

            if not q_cell.isdigit() or ans_cell not in _MCQ_LETTERS:
                continue
            if q_cell in seen_ids:
                continue

            try:
                mcq_answer = MCQAnswer(ans_cell)
            except ValueError:
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

    if not all_questions:
        raise ParseError(
            "Could not find an MCQ answer-key table "
            "(expected a table with a column containing only A/B/C/D)"
        )
    return all_questions
