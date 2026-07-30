"""Theory row state machine: builds nested ``Question`` objects from table rows.

Accuracy fixes compared to the original monolithic implementation:

1. **Mark-type notation** — uses ``parse_marks_cell`` so "B1"/"C1"/"A1" cells
   are correctly read as integer marks with ``math_mark_type`` populated.

2. **EITHER/OR sticky branching** — once a standalone OR row is seen, ALL
   subsequent answer points in the same question are tagged ``is_alternative=True``
   (not just the next one).  ``flush()`` sums only the primary (non-alternative)
   branch for the question's ``marks`` field, which keeps pydantic's
   ``validate_mark_point_sum`` happy.

3. **Zero Q-number guard** — Q-cells whose leading digit is ``0`` are rejected
   (no CAIE question is numbered 0), preventing truth-table values from being
   parsed as question numbers.

4. **Structural EITHER marker** — "EITHER" appearing as the answer on a Q-number
   row is treated as a structural bracket (signals q_row_had_answer so flush()
   recounts marks from the primary branch) but is NOT added as an AnswerPoint.

5. **math_mark_type** — propagated onto every AnswerPoint when the marks cell
   carries a type letter, improving transparency.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog

from lemely.core.loose_schemas import AnswerPoint, MathMarkType, Question, QuestionType
from lemely.io.det.marks import parse_marks_cell
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from lemely.io.det.columns import ColumnLayout

log = structlog.get_logger(__name__)

# Question-number column patterns (split-row / legacy format)
_LEVEL_2_RE = re.compile(r"^\([a-z]\)$")  # "(a)", "(b)"
_LEVEL_3_RE = re.compile(r"^\([ivx]+\)$")  # "(i)", "(ii)", "(iv)"

# Compound Q-number: digit prefix + zero or more parenthesised sub-parts
# Matches "1", "1(a)", "2(a)(i)", "1(g)(ii)" but rejects leading-zero (e.g. "0")
_COMPOUND_Q_RE = re.compile(r"^([1-9]\d*)((?:\([a-z]+\))*)$")

# ParseError triggers
_LEVEL_DESCRIPTOR_Q_RE = re.compile(r"^[Ll]evel\s+\d+$")
_BAND_LANGUAGE_RE = re.compile(r"descriptors|marks\s+available|AO\d", re.IGNORECASE)
_INDICATIVE_CONTENT_RE = re.compile(r"indicative\s+content", re.IGNORECASE)


def make_id(labels: list[str]) -> str:
    """Build a hierarchical question ID from the raw label stack.

    Examples::

        ["1"]               → "1"
        ["1", "(a)"]        → "1a"
        ["1", "(a)", "(i)"] → "1a_i"
    """
    result = ""
    for i, lbl in enumerate(labels):
        raw = re.sub(r"[()]", "", lbl)
        if i == 0:
            result = raw
        elif i == 1:
            result += raw
        else:
            result += "_" + raw
    return result


def decompose_compound_q(q_cell: str) -> list[str] | None:
    """Parse a compound Q-number into its component labels.

    Returns ``None`` for cells that don't match (no digit prefix, starts
    with 0, or purely parenthesised labels like "(a)").

    Examples::

        "1"        → ["1"]
        "1(a)"     → ["1", "(a)"]
        "2(a)(i)"  → ["2", "(a)", "(i)"]
        "0"        → None  (zero is never a valid CAIE Q-number)
        "(a)"      → None  (no digit prefix — handled by level patterns)
    """
    m = _COMPOUND_Q_RE.match(q_cell)
    if not m:
        return None
    parts: list[str] = [m.group(1)]
    for sub in re.findall(r"\([a-z]+\)", m.group(2)):
        parts.append(sub)
    return parts


def build_questions(
    rows: list[list[str | None]],
    layout: ColumnLayout,
    max_mark: int = 40,
    header_keywords: frozenset[str] | None = None,
) -> list[Question]:
    """Row-by-row state machine that builds nested :class:`Question` objects.

    This is the core theory-paper parser.  See module docstring for a summary
    of accuracy improvements over the previous implementation.

    Args:
        rows: Merged table rows (after header filtering and grid rejection).
        layout: Column indices from :func:`~lemely.io.det.columns.detect_columns`.
        max_mark: Upper bound for ``parse_marks_cell``; avoids false positives.
        header_keywords: Optional extra set of words to filter remaining header
            rows inline (in addition to the pre-filtering already done upstream).
    """
    _hkw = header_keywords or frozenset(
        {"question", "answer", "marks", "guidance", "notes", "input", "output"}
    )

    top_level: list[Question] = []
    stack: list[Question] = []
    labels: list[str] = []
    current_points: list[AnswerPoint] = []
    point_idx = 0
    q_row_had_answer = False  # True when the Q-number row itself carried answer text
    in_alt_branch = False  # True after a standalone OR until the next question

    q_col = layout.q_col
    answer_col_end = layout.answer_col_end
    guidance_col = layout.guidance_col
    marks_col = layout.marks_col

    # -----------------------------------------------------------------------
    # Inner helpers
    # -----------------------------------------------------------------------

    def flush() -> None:
        nonlocal point_idx, in_alt_branch, q_row_had_answer
        if stack and current_points:
            stack[-1].answer_points = list(current_points)
            if q_row_had_answer:
                # Sum only the PRIMARY branch (non-alternative points).
                # This correctly handles EITHER/OR: the alternative branch is
                # excluded, so the question's marks reflect only one method.
                primary_total = sum(
                    p.marks for p in current_points if p.marks and not p.is_alternative
                )
                if primary_total > 0:
                    stack[-1].marks = primary_total
        current_points.clear()
        point_idx = 0
        in_alt_branch = False
        q_row_had_answer = False

    def unwind_to(target_depth: int) -> None:
        while len(stack) > target_depth:
            popped = stack.pop()
            labels.pop()
            if stack:
                stack[-1].parts.append(popped)
            else:
                top_level.append(popped)

    def push_question(
        comp: str, is_leaf: bool, marks_int: int | None, guidance_cell: str | None
    ) -> None:
        labels.append(comp)
        new_id = make_id(labels)
        parent_id = make_id(labels[:-1]) if len(labels) > 1 else None
        q = Question(
            id=new_id,
            parent_id=parent_id,
            marks=marks_int if (is_leaf and marks_int is not None) else 0,
            type=QuestionType.RECALL,
            notes=guidance_cell if is_leaf else None,
        )
        stack.append(q)

    def make_point(
        text: str,
        marks_int: int | None,
        math_type: MathMarkType | None,
        is_alt: bool,
    ) -> AnswerPoint:
        nonlocal point_idx
        point_idx += 1
        return AnswerPoint(
            id=f"p{point_idx}",
            point=text,
            marks=marks_int if marks_int is not None else 1,
            math_mark_type=math_type,
            is_alternative=is_alt,
        )

    # -----------------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------------

    for row in rows:
        if not any((c or "").strip() for c in row):
            continue

        # --- Cell extraction ------------------------------------------------
        q_cell = ((row[q_col] if len(row) > q_col else None) or "").strip()

        answer_parts = [
            (row[ci] or "").strip()
            for ci in range(q_col + 1, min(answer_col_end, len(row)))
            if (row[ci] or "").strip()
        ]
        answer_cell = " ".join(answer_parts).strip()

        guidance_cell: str | None = None
        if guidance_col is not None and len(row) > guidance_col:
            guidance_cell = (row[guidance_col] or "").strip() or None

        marks_raw = ((row[marks_col] if len(row) > marks_col else None) or "").strip()
        parsed_mark = parse_marks_cell(marks_raw, max_mark)
        marks_int: int | None = parsed_mark.value if parsed_mark is not None else None
        math_type: MathMarkType | None = (
            parsed_mark.math_mark_type if parsed_mark is not None else None
        )

        # --- Skip remaining header rows (inline defence) --------------------
        cells_lower = {(c or "").strip().lower() for c in row}
        if cells_lower & _hkw and not q_cell:
            # Only skip if Q-cell is empty (a pure header row has no Q-number).
            continue

        # --- ParseError triggers --------------------------------------------
        if _LEVEL_DESCRIPTOR_Q_RE.match(q_cell) and _BAND_LANGUAGE_RE.search(answer_cell):
            raise ParseError(
                f"Level-descriptor row ('{q_cell}'): document uses levels-based "
                "marking — fall back to Gemini parser"
            )
        if _INDICATIVE_CONTENT_RE.search(answer_cell):
            raise ParseError("Indicative-content section detected: fall back to Gemini parser")

        # --- Determine if this row starts a new question --------------------
        components = decompose_compound_q(q_cell)

        if components is not None:
            flush()
            in_alt_branch = False

            # Find the common prefix between the new component path and the
            # current label stack to determine the unwind depth.
            common_len = 0
            for k, comp in enumerate(components[:-1]):
                if k < len(labels) and labels[k] == comp:
                    common_len = k + 1
                else:
                    break

            unwind_to(common_len)

            for k, comp in enumerate(components):
                if k < common_len:
                    continue
                is_leaf = k == len(components) - 1
                push_question(comp, is_leaf, marks_int, guidance_cell)

            upper = answer_cell.upper()
            if answer_cell and upper not in ("EITHER", "OR"):
                # Real answer on the Q row — add as a point.
                current_points.append(make_point(answer_cell, marks_int, math_type, False))
                q_row_had_answer = True
            elif upper in ("EITHER", "OR"):
                # Structural bracket: signals q_row_had_answer (so flush()
                # recounts from primary branch) but produces no AnswerPoint.
                q_row_had_answer = True

        elif _LEVEL_3_RE.match(q_cell):
            # Roman-numeral level — check before _LEVEL_2_RE because (i) also
            # matches _LEVEL_2_RE (single lowercase letter).
            flush()
            in_alt_branch = False
            unwind_to(2)
            push_question(q_cell, True, marks_int, guidance_cell)
            if answer_cell:
                current_points.append(make_point(answer_cell, marks_int, math_type, False))
                q_row_had_answer = True

        elif _LEVEL_2_RE.match(q_cell):
            flush()
            in_alt_branch = False
            unwind_to(1)
            push_question(q_cell, True, marks_int, guidance_cell)
            if answer_cell:
                current_points.append(make_point(answer_cell, marks_int, math_type, False))
                q_row_had_answer = True

        else:
            # Continuation row — add an AnswerPoint to the deepest question.
            if not answer_cell or not stack:
                continue

            upper = answer_cell.upper()

            # Standalone OR / EITHER: switch all remaining points to the alt branch.
            if upper in ("OR", "EITHER"):
                in_alt_branch = True
                continue

            is_alt = in_alt_branch
            text = answer_cell

            # Inline "OR <text>" / "EITHER <text>"
            if upper.startswith("OR "):
                text = answer_cell[3:].strip()
                is_alt = True
            elif upper.startswith("EITHER "):
                text = answer_cell[7:].strip()
                is_alt = True

            if not text:
                continue

            current_points.append(make_point(text, marks_int, math_type, is_alt))

    # Final flush and full unwind
    flush()
    unwind_to(0)

    if not top_level:
        raise ParseError("Theory table contained no questions after parsing")

    return top_level
