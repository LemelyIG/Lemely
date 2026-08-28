"""Unit tests for the modular deterministic mark-scheme parser (``lemely.io.det``).

All tests use synthetic pdfplumber data — no real PDFs and no network required.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from structlog.testing import capture_logs

from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkSchemeMetadata,
    MathMarkType,
    MCQAnswer,
    PaperType,
    Question,
    QuestionType,
    SchemeFormat,
    SessionMonth,
    Tier,
)
from lemely.io.det import DeterministicMarkSchemeParser
from lemely.io.det.columns import ColumnLayout, detect_columns
from lemely.io.det.gmp import extract_gmp
from lemely.io.det.marks import (
    ParsedMark,
    extract_trailing_mark_code,
    is_marks_column,
    parse_marks_cell,
)
from lemely.io.det.mcq import find_mcq_answer_col, parse_mcq_tables
from lemely.io.det.metadata import extract_metadata
from lemely.io.det.profiles import SubjectProfile, get_profile, register_profile
from lemely.io.det.reconcile import check as reconcile_check
from lemely.io.det.rows import (
    build_questions,
    decompose_compound_q,
    make_id,
    split_on_alternative_marker,
)
from lemely.io.det.tables import qualifies_as_mark_scheme_table, select_tables
from lemely.runtime.config import DetParserSettings
from lemely.runtime.errors import ParseError

# ---------------------------------------------------------------------------
# Helpers to build fake pdfplumber Page / PDF objects
# ---------------------------------------------------------------------------


def _fake_page(text: str = "", tables: list | None = None) -> MagicMock:
    page = MagicMock()
    page.extract_text.return_value = text
    page.extract_tables.return_value = tables or []
    return page


def _fake_pdf(pages: list[MagicMock]) -> MagicMock:
    pdf = MagicMock()
    pdf.pages = pages
    # pdfplumber.open() is used as a context manager; __enter__ must return the pdf.
    pdf.__enter__ = MagicMock(return_value=pdf)
    pdf.__exit__ = MagicMock(return_value=None)
    return pdf


def _layout(
    q_col: int = 0,
    answer_col_end: int = 2,
    guidance_col: int | None = None,
    marks_col: int = 2,
) -> ColumnLayout:
    """Build a ColumnLayout for driving ``build_questions`` directly."""
    return ColumnLayout(
        q_col=q_col,
        answer_col_end=answer_col_end,
        guidance_col=guidance_col,
        marks_col=marks_col,
    )


def _run_theory(
    rows: list[list[str | None]],
    q_col: int = 0,
    answer_col_end: int = 2,
    guidance_col: int | None = None,
    marks_col: int = 2,
) -> list[Question]:
    """Thin wrapper around ``build_questions`` with an explicit ColumnLayout."""
    return build_questions(
        rows,
        _layout(q_col, answer_col_end, guidance_col, marks_col),
    )


# ---------------------------------------------------------------------------
# Cover page text helpers
# ---------------------------------------------------------------------------


def _mcq_cover(n: int) -> str:
    """Cover page text whose Maximum Mark matches n questions × 1 mark each."""
    return (
        "Cambridge IGCSE™\nPhysics\n"
        f"0625/12 Mark Scheme February/March 2020\nMaximum Mark: {n}\nPublished\n"
    )


_THEORY_COVER = """\
Cambridge IGCSE™
Physics
0625/42 Mark Scheme May/June 2019
Maximum Mark: 80
Published
"""


# ---------------------------------------------------------------------------
# rows.make_id
# ---------------------------------------------------------------------------


class MakeIdTests(unittest.TestCase):
    def test_level_0(self) -> None:
        self.assertEqual(make_id(["1"]), "1")

    def test_level_1(self) -> None:
        self.assertEqual(make_id(["1", "(a)"]), "1a")

    def test_level_2(self) -> None:
        self.assertEqual(make_id(["1", "(a)", "(i)"]), "1a_i")

    def test_level_2_multi_digit(self) -> None:
        self.assertEqual(make_id(["12", "(b)", "(ii)"]), "12b_ii")

    def test_empty(self) -> None:
        self.assertEqual(make_id([]), "")


# ---------------------------------------------------------------------------
# rows.decompose_compound_q
# ---------------------------------------------------------------------------


class DecomposeCompoundQTests(unittest.TestCase):
    def test_bare_number(self) -> None:
        self.assertEqual(decompose_compound_q("1"), ["1"])

    def test_single_subpart(self) -> None:
        self.assertEqual(decompose_compound_q("1(a)"), ["1", "(a)"])

    def test_two_subparts(self) -> None:
        self.assertEqual(decompose_compound_q("2(a)(i)"), ["2", "(a)", "(i)"])

    def test_zero_is_rejected(self) -> None:
        self.assertIsNone(decompose_compound_q("0"))

    def test_pure_paren_label_rejected(self) -> None:
        self.assertIsNone(decompose_compound_q("(a)"))


# ---------------------------------------------------------------------------
# marks.parse_marks_cell / is_marks_column
# ---------------------------------------------------------------------------


class ParseMarksCellTests(unittest.TestCase):
    def test_bare_integer(self) -> None:
        self.assertEqual(parse_marks_cell("2"), ParsedMark(2, None))

    def test_b_mark(self) -> None:
        self.assertEqual(parse_marks_cell("B1"), ParsedMark(1, MathMarkType.B))

    def test_c_mark(self) -> None:
        self.assertEqual(parse_marks_cell("C1"), ParsedMark(1, MathMarkType.C))

    def test_a_mark_parenthesised(self) -> None:
        # The bracket is CAIE's ALTERNATIVE-route notation (#136 mechanism
        # (D)) — the value and letter are unchanged, and is_alternative is
        # what keeps it out of the primary sum.
        self.assertEqual(
            parse_marks_cell("(A1)"), ParsedMark(1, MathMarkType.A, is_alternative=True)
        )

    def test_m_mark(self) -> None:
        self.assertEqual(parse_marks_cell("M2"), ParsedMark(2, MathMarkType.M))

    def test_lowercase_letter(self) -> None:
        self.assertEqual(parse_marks_cell("b1"), ParsedMark(1, MathMarkType.B))

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(parse_marks_cell(""))

    def test_non_matching_returns_none(self) -> None:
        self.assertIsNone(parse_marks_cell("abc"))

    def test_exceeds_max_returns_none(self) -> None:
        self.assertIsNone(parse_marks_cell("2019"))

    def test_letter_without_digit_returns_none(self) -> None:
        self.assertIsNone(parse_marks_cell("B"))

    def test_custom_max_value(self) -> None:
        self.assertIsNone(parse_marks_cell("50", max_value=40))
        self.assertEqual(parse_marks_cell("50", max_value=80), ParsedMark(50, None))


class IsMarksColumnTests(unittest.TestCase):
    def test_all_integer_column(self) -> None:
        self.assertTrue(is_marks_column(["1", "2", "3"]))

    def test_mark_type_column(self) -> None:
        self.assertTrue(is_marks_column(["B1", "C1", "(A1)"]))

    def test_empty_column_is_false(self) -> None:
        self.assertFalse(is_marks_column(["", "  ", ""]))

    def test_mixed_column_is_false(self) -> None:
        self.assertFalse(is_marks_column(["1", "some text", "2"]))

    def test_ignores_empty_cells(self) -> None:
        self.assertTrue(is_marks_column(["1", "", "2", "  "]))


# ---------------------------------------------------------------------------
# columns.detect_columns
# ---------------------------------------------------------------------------


class DetectColumnsTests(unittest.TestCase):
    def test_three_column_layout(self) -> None:
        rows: list[list[str | None]] = [
            ["1", "First point", "1"],
            [None, "Second point", "2"],
        ]
        layout = detect_columns(rows)
        self.assertEqual(layout.q_col, 0)
        self.assertEqual(layout.marks_col, 2)
        self.assertIsNone(layout.guidance_col)
        self.assertEqual(layout.answer_col_end, 2)

    def test_four_column_layout_has_guidance(self) -> None:
        rows: list[list[str | None]] = [
            ["1", "Point text", "Guidance note", "2"],
            [None, "Another", "More guidance", "1"],
        ]
        layout = detect_columns(rows)
        self.assertEqual(layout.marks_col, 3)
        self.assertEqual(layout.guidance_col, 2)
        self.assertEqual(layout.answer_col_end, 2)

    def test_empty_rows_fallback(self) -> None:
        layout = detect_columns([])
        self.assertEqual(layout.q_col, 0)
        self.assertEqual(layout.marks_col, 1)


# ---------------------------------------------------------------------------
# mcq.find_mcq_answer_col
# ---------------------------------------------------------------------------


class FindMCQAnswerColTests(unittest.TestCase):
    def test_identifies_rightmost_abcd_column(self) -> None:
        rows: list[list[str | None]] = [
            ["1", "A"],
            ["2", "B"],
            ["3", "C"],
        ]
        self.assertEqual(find_mcq_answer_col(rows), 1)

    def test_returns_none_when_no_abcd_column(self) -> None:
        rows: list[list[str | None]] = [["1", "some text"], ["2", "more text"]]
        self.assertIsNone(find_mcq_answer_col(rows))

    def test_skips_column_zero(self) -> None:
        # Even if all of column 0 were A/B/C/D, we want column 1.
        rows: list[list[str | None]] = [["A", "A"], ["B", "B"], ["C", "C"]]
        self.assertEqual(find_mcq_answer_col(rows), 1)

    def test_empty_rows(self) -> None:
        self.assertIsNone(find_mcq_answer_col([]))

    def test_prefers_rightmost_column(self) -> None:
        rows: list[list[str | None]] = [
            ["1", "A", "B"],
            ["2", "B", "C"],
        ]
        self.assertEqual(find_mcq_answer_col(rows), 2)


# ---------------------------------------------------------------------------
# mcq.parse_mcq_tables
# ---------------------------------------------------------------------------


class ParseMCQTablesTests(unittest.TestCase):
    def test_extracts_answer_key(self) -> None:
        table: list[list[str | None]] = [["1", "A"], ["2", "B"], ["3", "C"]]
        questions = parse_mcq_tables([table])
        self.assertEqual([q.id for q in questions], ["1", "2", "3"])
        self.assertEqual([q.mcq_answer for q in questions], [MCQAnswer.A, MCQAnswer.B, MCQAnswer.C])

    def test_all_questions_mcq_type_and_one_mark(self) -> None:
        table: list[list[str | None]] = [["1", "A"], ["2", "D"]]
        questions = parse_mcq_tables([table])
        for q in questions:
            self.assertEqual(q.type, QuestionType.MCQ)
            self.assertEqual(q.marks, 1)

    def test_deduplicates_repeated_ids(self) -> None:
        table: list[list[str | None]] = [["1", "A"], ["1", "B"]]
        questions = parse_mcq_tables([table])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].mcq_answer, MCQAnswer.A)

    def test_raises_when_no_abcd_table(self) -> None:
        table: list[list[str | None]] = [["1", "text"], ["2", "more"]]
        with self.assertRaises(ParseError):
            parse_mcq_tables([table])


# ---------------------------------------------------------------------------
# mcq silent-loss instrumentation (#94)
# ---------------------------------------------------------------------------


class MCQSilentLossInstrumentationTests(unittest.TestCase):
    """#94: a discarded table must say WHY, not just shrink the total.

    The premise #94 was opened on has been corrected by measurement and the
    correction is encoded here rather than left on the issue. The *fact* of a
    shortfall was never silent: ``reconcile`` compares the parsed mark total
    against ``maximum_mark`` and logs ``mark_total_mismatch_escalating``. What
    was silent is the *mechanism* — that a 29-row table was thrown away because
    one cell read ``QUESTION DISCOUNTED``. These tests assert the mechanism is
    reported; they deliberately do NOT re-assert the shortfall, which other
    machinery already owns.
    """

    def test_rejected_table_names_the_disqualifying_value(self) -> None:
        from lemely.io.det.mcq import describe_answer_col_rejection

        rows: list[list[str | None]] = [["1", "A"], ["2", "B"], ["3", "QUESTION DISCOUNTED"]]
        rejection = describe_answer_col_rejection(rows)

        self.assertEqual(rejection["column"], 1)
        self.assertEqual(rejection["disqualifying_values"], ["QUESTION DISCOUNTED"])
        self.assertEqual(rejection["disqualifying_count"], 1)
        self.assertEqual(rejection["values_in_column"], 3)

    def test_rejection_names_the_densest_column_not_the_rightmost(self) -> None:
        """A one-cell header must not be reported as the offending column.

        The real answer column is the dense one; naming the rightmost instead
        would report ``MARKS`` and bury the cell that actually caused the loss.
        This is the shape the real 0625_s24_ms_21 table has.
        """
        from lemely.io.det.mcq import describe_answer_col_rejection

        rows: list[list[str | None]] = [
            ["QUESTION", "ANSWER", "MARKS"],
            ["1", "A", None],
            ["2", "B", None],
            ["3", "QUESTION DISCOUNTED", None],
        ]
        rejection = describe_answer_col_rejection(rows)

        self.assertEqual(rejection["column"], 1, "the dense answer column, not the MARKS header")
        self.assertIn("QUESTION DISCOUNTED", rejection["disqualifying_values"])

    def test_discarded_table_rows_are_counted(self) -> None:
        from lemely.io.det.mcq import MCQParseDiagnostics, parse_mcq_tables

        good: list[list[str | None]] = [["1", "A"], ["2", "B"]]
        lost: list[list[str | None]] = [["3", "C"], ["4", "D"], ["5", "QUESTION DISCOUNTED"]]
        diag = MCQParseDiagnostics()

        questions = parse_mcq_tables([good, lost], source="synthetic", diagnostics=diag)

        self.assertEqual(len(questions), 2)
        self.assertEqual(diag.tables_without_answer_col, 1)
        self.assertEqual(diag.rows_discarded_data, 3, "the whole table, not just the bad row")
        self.assertEqual(diag.questions_parsed, 2)
        self.assertEqual(diag.rejections[0]["table_index"], 1)

    def test_rows_dropped_inside_a_kept_table_are_counted(self) -> None:
        """The reconciler cannot see these at all — it only sees the total."""
        from lemely.io.det.mcq import MCQParseDiagnostics, parse_mcq_tables

        # Column 1 stays clean (A/B/C) so the table is ACCEPTED — the point
        # is loss inside a table that parsed, not a rejected one.
        table: list[list[str | None]] = [
            ["1", "A"],
            ["1", "B"],  # duplicate id
            ["Q", "C"],  # q_cell not a digit
        ]
        diag = MCQParseDiagnostics()

        questions = parse_mcq_tables([table], source="synthetic", diagnostics=diag)

        self.assertEqual(len(questions), 1)
        self.assertEqual(diag.rows_discarded_in_kept_tables, 2)

    def test_diagnostics_are_optional_and_behaviour_is_unchanged_without_them(self) -> None:
        from lemely.io.det.mcq import parse_mcq_tables

        table: list[list[str | None]] = [["1", "A"], ["2", "B"]]
        self.assertEqual([q.id for q in parse_mcq_tables([table])], ["1", "2"])


class MCQSilentLossRealPaperTests(unittest.TestCase):
    """The confirmed instance from #94, against the real PDF when it is present.

    Skipped rather than failed when the source PDF is absent: it lives in the
    PaperScraper corpus outside this repo, and a test that fails on a checkout
    without it would be a broken gate, not a real signal.
    """

    PDF = Path("/home/sico/PaperScraper/papers/CAIE/igcse/physics-0625/2024/s24/0625_s24_ms_21.pdf")

    def test_0625_s24_ms_21_reports_the_reason_for_its_28_question_loss(self) -> None:
        if not self.PDF.exists():
            self.skipTest(f"corpus PDF not present: {self.PDF}")
        try:
            import pdfplumber
        except ImportError:  # pragma: no cover - pdfplumber is a hard dep here
            self.skipTest("pdfplumber not installed")

        from lemely.io.det.mcq import MCQParseDiagnostics, parse_mcq_tables

        with pdfplumber.open(self.PDF) as pdf:
            tables: list[list[list[str | None]]] = []
            for page in pdf.pages[1:]:
                tables.extend(page.extract_tables())

        diag = MCQParseDiagnostics()
        questions = parse_mcq_tables(tables, source=self.PDF.name, diagnostics=diag)

        # The measured facts, asserted rather than described: 12 of 40 parse,
        # and the 28 lost go with ONE discarded table.
        self.assertEqual(len(questions), 12)
        self.assertEqual(diag.tables_without_answer_col, 1)
        self.assertEqual(diag.rows_discarded_data, 29, "28 questions plus the header row")

        rejection = diag.rejections[0]
        self.assertEqual(rejection["column"], 3)
        self.assertEqual(rejection["disqualifying_values"], ["QUESTION DISCOUNTED"])
        self.assertEqual(
            rejection["disqualifying_count"],
            1,
            "a SINGLE anomalous cell costs the entire table — the whole point of #94",
        )


# ---------------------------------------------------------------------------
# tables.qualifies_as_mark_scheme_table
# ---------------------------------------------------------------------------


class QualifiesAsMarkSchemeTableTests(unittest.TestCase):
    def test_qualifies_with_marks_column(self) -> None:
        table: list[list[str | None]] = [
            ["1", "Point", "2"],
            [None, "Another", "1"],
        ]
        self.assertTrue(qualifies_as_mark_scheme_table(table))

    def test_qualifies_with_header_row(self) -> None:
        table: list[list[str | None]] = [
            ["Question", "Answer", "Marks"],
            ["1", "Some text answer", "one mark"],
        ]
        self.assertTrue(qualifies_as_mark_scheme_table(table))

    def test_rejects_grid_without_marks_or_header(self) -> None:
        # No marks column and no mark-scheme header tokens -> not a mark table.
        grid: list[list[str | None]] = [["high", "low"], ["low", "high"]]
        self.assertFalse(qualifies_as_mark_scheme_table(grid))

    def test_rejects_too_few_data_rows(self) -> None:
        table: list[list[str | None]] = [["1", "2"]]
        self.assertFalse(qualifies_as_mark_scheme_table(table))


# ---------------------------------------------------------------------------
# tables.select_tables — page-level table selection
# ---------------------------------------------------------------------------


class SelectTablesTests(unittest.TestCase):
    """Regression tests for B2 (0625_w24_ms_41): a physical page can hold more
    than one independently-qualifying mark-scheme table — e.g. a short
    question ending partway down a page immediately followed by the next
    question's table further down the same page. ``select_tables`` used to
    keep only the first qualifying table per page and silently drop any
    subsequent one, which is exactly what happened to question 2 of
    0625_w24_ms_41.pdf (confirmed against the real PDF: pdfplumber returns
    two separate table objects for that page, one per question).
    """

    def test_keeps_multiple_qualifying_tables_on_same_page(self) -> None:
        table_q1 = [
            ["Question", "Answer", "Marks"],
            ["1", "First answer", "1"],
            [None, "continuation", "1"],
        ]
        table_q2 = [
            ["Question", "Answer", "Marks"],
            ["2", "Second answer", "1"],
            [None, "continuation", "1"],
        ]
        pdf = _fake_pdf([_fake_page(tables=[table_q1, table_q2])])
        tables = select_tables(pdf, page_start=0, max_mark=40)
        self.assertEqual(tables, [table_q1, table_q2])

    def test_still_drops_non_qualifying_second_table(self) -> None:
        # A genuine embedded grid (no marks column, no header tokens) must
        # still be excluded even though the one-per-page cap is gone — the
        # qualification check, not page position, is what filters it out.
        table_q1 = [
            ["Question", "Answer", "Marks"],
            ["1", "First answer", "1"],
            [None, "continuation", "1"],
        ]
        grid: list[list[str | None]] = [["high", "low"], ["low", "high"]]
        pdf = _fake_pdf([_fake_page(tables=[table_q1, grid])])
        tables = select_tables(pdf, page_start=0, max_mark=40)
        self.assertEqual(tables, [table_q1])

    def test_symbol_font_glyphs_are_recovered_in_cells(self) -> None:
        """CAIE embeds a Symbol subset font; pdfplumber returns U+F0xx for it.

        Left raw, "Δ" reaches the marking engine (and the P4 question bank)
        as an unreadable private-use codepoint — 26 banked rows carried
        mangled marking points before this. Converting at selection time
        fixes every downstream consumer at once.
        """
        table = [
            ["Question", "Answer", "Marks"],
            ["1", "t = 2 s and 3, 4", "1"],
            [None, "continuation", "1"],
        ]
        pdf = _fake_pdf([_fake_page(tables=[table])])
        tables = select_tables(pdf, page_start=0, max_mark=40)
        self.assertEqual(tables[0][1][1], "Δt = 2 s and {3, 4}")

    def test_unmappable_glyph_is_dropped_not_emitted_raw(self) -> None:
        # 0xF0E1 is one of the glyph-assembly fragments used to draw a
        # multi-line bracket; it has no single-character Unicode equivalent,
        # so it is deliberately absent from the table. Emitting the raw
        # codepoint would be corrupt text either way.
        table = [
            ["Question", "Answer", "Marks"],
            ["1", "ab", "1"],
            [None, "continuation", "1"],
        ]
        pdf = _fake_pdf([_fake_page(tables=[table])])
        tables = select_tables(pdf, page_start=0, max_mark=40)
        self.assertEqual(tables[0][1][1], "ab")


# ---------------------------------------------------------------------------
# rows.build_questions — theory state machine
# ---------------------------------------------------------------------------


def _make_theory_table() -> list[list[str | None]]:
    """Synthetic 3-column theory table (Q-num | answer/point | marks)."""
    return [
        ["1", None, "0"],
        [None, "First mark point", "1"],
        [None, "Second mark point", "1"],
        ["(a)", None, "3"],
        [None, "Sub-point one", "1"],
        [None, "Sub-point two", "1"],
        [None, "OR", None],
        [None, "Alternative point", "1"],
        ["2", "Simple question", "2"],
        [None, "Another point", "1"],
    ]


class TheoryExtractionTests(unittest.TestCase):
    def test_top_level_question_count(self) -> None:
        questions = _run_theory(_make_theory_table())
        self.assertEqual(len(questions), 2)

    def test_q1_has_subpart_a(self) -> None:
        questions = _run_theory(_make_theory_table())
        q1 = questions[0]
        self.assertEqual(len(q1.parts), 1)
        self.assertEqual(q1.parts[0].id, "1a")

    def test_q1_top_level_answer_points(self) -> None:
        questions = _run_theory(_make_theory_table())
        q1 = questions[0]
        self.assertEqual(len(q1.answer_points), 2)
        self.assertEqual(q1.answer_points[0].point, "First mark point")
        self.assertEqual(q1.answer_points[1].point, "Second mark point")

    def test_subpart_a_answer_points(self) -> None:
        questions = _run_theory(_make_theory_table())
        qa = questions[0].parts[0]
        self.assertEqual(len(qa.answer_points), 3)

    def test_or_block_sets_is_alternative(self) -> None:
        questions = _run_theory(_make_theory_table())
        qa = questions[0].parts[0]
        # p1 = "Sub-point one", p2 = "Sub-point two", p3 = "Alternative point".
        self.assertFalse(qa.answer_points[0].is_alternative)
        self.assertFalse(qa.answer_points[1].is_alternative)
        self.assertTrue(qa.answer_points[2].is_alternative)

    def test_q2_id(self) -> None:
        questions = _run_theory(_make_theory_table())
        self.assertEqual(questions[1].id, "2")

    def test_q2_answer_points(self) -> None:
        questions = _run_theory(_make_theory_table())
        self.assertEqual(len(questions[1].answer_points), 2)

    def test_ids_are_hierarchical(self) -> None:
        questions = _run_theory(_make_theory_table())
        q1 = questions[0]
        self.assertEqual(q1.id, "1")
        self.assertEqual(q1.parts[0].id, "1a")

    def test_parent_id_set_on_subpart(self) -> None:
        questions = _run_theory(_make_theory_table())
        self.assertEqual(questions[0].parts[0].parent_id, "1")

    def test_continuation_row_without_question_adds_point(self) -> None:
        table: list[list[str | None]] = [
            ["1", "First point", "1"],
            [None, "Continuation point", "1"],
        ]
        questions = _run_theory(table)
        self.assertEqual(len(questions[0].answer_points), 2)

    def test_marks_on_answer_point_from_marks_column(self) -> None:
        table: list[list[str | None]] = [["1", "Point text", "3"]]
        questions = _run_theory(table)
        self.assertEqual(questions[0].answer_points[0].marks, 3)

    def test_math_mark_type_propagated_to_point(self) -> None:
        table: list[list[str | None]] = [["1", "Method point", "B1"]]
        questions = _run_theory(table)
        pt = questions[0].answer_points[0]
        self.assertEqual(pt.marks, 1)
        self.assertEqual(pt.math_mark_type, MathMarkType.B)

    def test_or_inline_text_creates_alternative_point(self) -> None:
        table: list[list[str | None]] = [
            ["1", "Main point", "1"],
            [None, "OR alternative text", "1"],
        ]
        questions = _run_theory(table)
        pts = questions[0].answer_points
        self.assertTrue(pts[1].is_alternative)
        self.assertEqual(pts[1].point, "alternative text")

    def test_either_inline_text_creates_alternative_point(self) -> None:
        table: list[list[str | None]] = [
            ["1", "Main point", "1"],
            [None, "EITHER other method", "1"],
        ]
        questions = _run_theory(table)
        pts = questions[0].answer_points
        self.assertTrue(pts[1].is_alternative)
        self.assertEqual(pts[1].point, "other method")

    # -----------------------------------------------------------------------
    # Compensatory C marks (B2 / 0625_w24_ms_41 root cause)
    #
    # CAIE's own Generic Marking Principles define the C mark as
    # "Compensatory mark which may be scored when the final answer (A) mark
    # for a question has not been awarded" (M3 acronym table). A C-type row
    # that follows an A-type row within the same leaf question is therefore
    # an alternative, partial-credit route to the SAME allocation as that A
    # mark — not an additional mark on top of it — even though the source
    # PDF carries no textual "OR"/"EITHER" marker on that row. Confirmed
    # against the real 0625_w24_ms_41.pdf: e.g. question 1(b) is "0.28 N / cm
    # A2" followed by a plain continuation row "k = F / x ... C1" with no OR
    # keyword; the part is worth 2 marks total, not 3.
    # -----------------------------------------------------------------------

    def test_c_mark_after_a_mark_is_compensatory_not_additive(self) -> None:
        # Mirrors 0625_w24_ms_41.pdf question 1(b): "0.28 N / cm  A2" then a
        # plain continuation row "k = F / x ...  C1" (no OR keyword).
        table: list[list[str | None]] = [
            ["1", "0.28 N / cm", "A2"],
            [None, "k = F / x", "C1"],
        ]
        questions = _run_theory(table)
        q1 = questions[0]
        self.assertEqual(len(q1.answer_points), 2)
        self.assertFalse(q1.answer_points[0].is_alternative)
        self.assertTrue(q1.answer_points[1].is_alternative)
        self.assertEqual(q1.answer_points[1].math_mark_type, MathMarkType.C)
        # 2, not 3: the C1 compensates for the A2, it does not add to it.
        self.assertEqual(q1.marks, 2)

    def test_multiple_c_marks_after_a_mark_all_compensatory(self) -> None:
        # Mirrors 0625_w24_ms_41.pdf question 1(c)(ii): "3.2(0) m/s2  A3"
        # followed by two plain C1 continuation rows (two alternative partial
        # -credit routes). Worth 3 marks total, not 5.
        table: list[list[str | None]] = [
            ["1", "3.2(0) m / s2", "A3"],
            [None, "F = ma", "C1"],
            [None, "resultant force = 6.5 - 4.9", "C1"],
        ]
        questions = _run_theory(table)
        q1 = questions[0]
        self.assertFalse(q1.answer_points[0].is_alternative)
        self.assertTrue(q1.answer_points[1].is_alternative)
        self.assertTrue(q1.answer_points[2].is_alternative)
        self.assertEqual(q1.marks, 3)

    def test_c_mark_without_preceding_a_mark_stays_additive(self) -> None:
        # A C mark only compensates for an A mark it follows within the same
        # leaf. Without a preceding A mark there is nothing to compensate
        # for, so it must remain an ordinary, additive point (e.g. a B mark
        # then an independent C-coded point).
        table: list[list[str | None]] = [
            ["1", "some point", "B1"],
            [None, "another point", "C1"],
        ]
        questions = _run_theory(table)
        q1 = questions[0]
        self.assertFalse(q1.answer_points[0].is_alternative)
        self.assertFalse(q1.answer_points[1].is_alternative)
        self.assertEqual(q1.marks, 2)

    def test_b_mark_after_a_mark_stays_additive(self) -> None:
        # Only C marks are compensatory. A B mark (independent, per GMP)
        # following an A mark in the same leaf is a separate, additive point
        # — mirrors 0625_w24_ms_41.pdf question 3(a): "... A2" / alternative
        # "... C1" / then a genuinely separate "(it measures the) turning
        # effect ... B1".
        table: list[list[str | None]] = [
            ["1", "force x perpendicular distance", "A2"],
            [None, "reference to perpendicular distance", "C1"],
            [None, "measures the turning effect", "B1"],
        ]
        questions = _run_theory(table)
        q1 = questions[0]
        self.assertFalse(q1.answer_points[0].is_alternative)  # A2
        self.assertTrue(q1.answer_points[1].is_alternative)  # C1, compensatory
        self.assertFalse(q1.answer_points[2].is_alternative)  # B1, additive
        self.assertEqual(q1.marks, 3)  # A2 + B1; C1 excluded

    def test_guidance_column_stored_in_notes(self) -> None:
        # 4-column table: Q | Answer | Guidance | Marks
        table: list[list[str | None]] = [
            ["1", "Point text", "See guidance here", "2"],
        ]
        questions = _run_theory(table, q_col=0, answer_col_end=2, guidance_col=2, marks_col=3)
        self.assertEqual(questions[0].notes, "See guidance here")

    def test_three_levels_of_nesting(self) -> None:
        table: list[list[str | None]] = [
            ["1", None, "0"],
            ["(a)", None, "0"],
            ["(i)", "Deepest point", "1"],
        ]
        questions = _run_theory(table)
        q1a_i = questions[0].parts[0].parts[0]
        self.assertEqual(q1a_i.id, "1a_i")
        self.assertEqual(q1a_i.answer_points[0].point, "Deepest point")

    def test_compound_q_number_decomposed(self) -> None:
        table: list[list[str | None]] = [
            ["1(a)(i)", "Deep answer", "1"],
        ]
        questions = _run_theory(table)
        # 1 -> (a) -> (i) nesting produced from a single compound cell.
        q1a_i = questions[0].parts[0].parts[0]
        self.assertEqual(q1a_i.id, "1a_i")

    def test_either_on_q_row_is_structural_not_a_point(self) -> None:
        table: list[list[str | None]] = [
            ["1", "EITHER", "0"],
            [None, "Method one", "2"],
            [None, "OR", None],
            [None, "Method two", "2"],
        ]
        questions = _run_theory(table)
        q1 = questions[0]
        # "EITHER" on the Q row produces no AnswerPoint.
        self.assertEqual([p.point for p in q1.answer_points], ["Method one", "Method two"])
        # Primary branch sums to 2 (alternative branch excluded).
        self.assertEqual(q1.marks, 2)

    def test_raises_parse_error_on_level_descriptor(self) -> None:
        table: list[list[str | None]] = [
            ["Level 1", "descriptors marks available", "3"],
        ]
        with self.assertRaises(ParseError):
            _run_theory(table)

    def test_raises_parse_error_on_indicative_content(self) -> None:
        table: list[list[str | None]] = [
            ["1", "Indicative content section header", "0"],
        ]
        with self.assertRaises(ParseError):
            _run_theory(table)

    def test_raises_parse_error_on_empty_table(self) -> None:
        with self.assertRaises(ParseError):
            _run_theory([])

    def test_raises_parse_error_when_no_questions_found(self) -> None:
        # Rows with only continuation text and no question numbers.
        table: list[list[str | None]] = [
            [None, "orphan point", "1"],
        ]
        with self.assertRaises(ParseError):
            _run_theory(table)


# ---------------------------------------------------------------------------
# reconcile.check
# ---------------------------------------------------------------------------


def _metadata(maximum_mark: int) -> MarkSchemeMetadata:
    return MarkSchemeMetadata(
        subject="Physics",
        subject_code="0625",
        paper_number=4,
        paper_variant=2,
        session_month=SessionMonth.MAY_JUNE,
        session_year=2019,
        paper_type=PaperType.THEORY_EXTENDED,
        maximum_mark=maximum_mark,
        scheme_format=SchemeFormat.POINT_BASED,
        source_document="0625_s19_ms_42.pdf",
    )


def _leaf_q(qid: str, marks: int) -> Question:
    return Question(id=qid, marks=marks, type=QuestionType.RECALL)


class ReconcileTests(unittest.TestCase):
    def test_exact_match_returns(self) -> None:
        questions = [_leaf_q("1", 40), _leaf_q("2", 40)]
        # Should not raise.
        reconcile_check(questions, _metadata(80))

    def test_within_tolerance_returns(self) -> None:
        questions = [_leaf_q("1", 79)]
        reconcile_check(questions, _metadata(80), mark_reconcile_tolerance=1)

    def test_mismatch_beyond_tolerance_raises(self) -> None:
        questions = [_leaf_q("1", 88)]
        with self.assertRaises(ParseError):
            reconcile_check(questions, _metadata(80))

    def test_warn_only_does_not_raise(self) -> None:
        questions = [_leaf_q("1", 88)]
        # escalate_on_mark_mismatch=False -> warning only, no exception.
        reconcile_check(questions, _metadata(80), escalate_on_mark_mismatch=False)

    def test_sums_leaf_marks_recursively(self) -> None:
        parent = Question(
            id="1",
            marks=0,
            type=QuestionType.RECALL,
            parts=[_leaf_q("1a", 40), _leaf_q("1b", 40)],
        )
        # Parent's own marks (0) are ignored; only leaves are summed.
        reconcile_check([parent], _metadata(80))


# ---------------------------------------------------------------------------
# metadata.extract_metadata
# ---------------------------------------------------------------------------


class MetadataExtractionTests(unittest.TestCase):
    def _pdf_with_cover(self, cover_text: str) -> MagicMock:
        return _fake_pdf([_fake_page(text=cover_text)])

    def test_subject_from_profile(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("0625_s19_ms_42.pdf"))
        self.assertEqual(md.subject, "Physics")

    def test_subject_code_from_filename(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("0625_s19_ms_42.pdf"))
        self.assertEqual(md.subject_code, "0625")

    def test_paper_number_and_variant_from_filename(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("0625_s19_ms_42.pdf"))
        self.assertEqual(md.paper_number, 4)
        self.assertEqual(md.paper_variant, 2)

    def test_session_month_from_filename(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("0625_s19_ms_42.pdf"))
        self.assertEqual(md.session_month, SessionMonth.MAY_JUNE)

    def test_session_year_from_filename(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("0625_s19_ms_42.pdf"))
        self.assertEqual(md.session_year, 2019)

    def test_maximum_mark_from_cover(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("0625_s19_ms_42.pdf"))
        self.assertEqual(md.maximum_mark, 80)

    def test_paper_type_theory(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("0625_s19_ms_42.pdf"))
        self.assertEqual(md.paper_type, PaperType.THEORY_EXTENDED)

    def test_paper_type_mcq(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_mcq_cover(40)), Path("0625_m20_ms_12.pdf"))
        self.assertEqual(md.paper_type, PaperType.MCQ)
        self.assertEqual(md.scheme_format, SchemeFormat.MCQ)

    def test_published_flag_detected(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("0625_s19_ms_42.pdf"))
        self.assertTrue(md.published)

    def test_unpublished_when_not_in_cover(self) -> None:
        cover = _THEORY_COVER.replace("Published", "Confidential")
        md = extract_metadata(self._pdf_with_cover(cover), Path("0625_s19_ms_42.pdf"))
        self.assertFalse(md.published)

    def test_raises_when_maximum_mark_missing(self) -> None:
        bad_cover = "Cambridge IGCSE\n0625/42 Mark Scheme\nPublished\n"
        with self.assertRaises(ParseError):
            extract_metadata(self._pdf_with_cover(bad_cover), Path("0625_s19_ms_42.pdf"))

    def test_paper_code_fallback_from_cover_when_filename_uncoded(self) -> None:
        # Filename does not match the CAIE pattern, so subject_code / paper
        # number / variant must be recovered from the cover-page code line.
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("uncoded-name.pdf"))
        self.assertEqual(md.subject_code, "0625")
        self.assertEqual(md.paper_number, 4)
        self.assertEqual(md.paper_variant, 2)

    def test_session_month_from_cover_when_filename_uncoded(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("uncoded-name.pdf"))
        self.assertEqual(md.session_month, SessionMonth.MAY_JUNE)

    def test_session_year_from_cover_when_filename_uncoded(self) -> None:
        md = extract_metadata(self._pdf_with_cover(_THEORY_COVER), Path("uncoded-name.pdf"))
        self.assertEqual(md.session_year, 2019)

    def test_specimen_session_has_no_year(self) -> None:
        cover = (
            "Cambridge IGCSE™\nChemistry\n"
            "0620/42 Mark Scheme Specimen\nMaximum Mark: 80\nExtended\nPublished\n"
        )
        md = extract_metadata(self._pdf_with_cover(cover), Path("uncoded-name.pdf"))
        self.assertEqual(md.session_month, SessionMonth.SPECIMEN)
        self.assertIsNone(md.session_year)

    def test_subject_name_from_cover_for_unknown_code(self) -> None:
        # Unknown subject code -> default profile has empty name, so the subject
        # name is taken from the cover page (first non-boilerplate line).
        cover = (
            "Cambridge IGCSE™\nBiology\n"
            "0610/42 Mark Scheme May/June 2019\nMaximum Mark: 80\nExtended\nPublished\n"
        )
        md = extract_metadata(self._pdf_with_cover(cover), Path("uncoded-name.pdf"))
        self.assertEqual(md.subject, "Biology")

    def test_tier_extended_detected(self) -> None:
        cover = (
            "Cambridge IGCSE™\nBiology\n"
            "0610/42 Mark Scheme May/June 2019\nMaximum Mark: 80\nExtended\nPublished\n"
        )
        md = extract_metadata(self._pdf_with_cover(cover), Path("uncoded-name.pdf"))
        self.assertEqual(md.tier, Tier.EXTENDED)

    def test_tier_core_detected(self) -> None:
        cover = (
            "Cambridge IGCSE™\nBiology\n"
            "0610/22 Mark Scheme May/June 2019\nMaximum Mark: 80\nCore\nPublished\n"
        )
        md = extract_metadata(self._pdf_with_cover(cover), Path("uncoded-name.pdf"))
        self.assertEqual(md.tier, Tier.CORE)


# ---------------------------------------------------------------------------
# gmp.extract_gmp
# ---------------------------------------------------------------------------


class GmpExtractionTests(unittest.TestCase):
    def test_extracts_numbered_principles(self) -> None:
        gmp_text = (
            "Generic Marking Principles\n"
            "1. Marks must be awarded positively.\n\n"
            "2. Marks are not deducted for errors.\n\n"
            "3. Marks awarded in line with the standard.\n\n"
        )
        pdf = _fake_pdf([_fake_page(), _fake_page(text=gmp_text)])
        md = _metadata(80)
        extract_gmp(pdf, md, pages_start=1, pages_end=4)
        self.assertEqual(len(md.generic_marking_principles), 3)
        self.assertEqual(md.generic_marking_principles[0], "Marks must be awarded positively.")

    def test_no_principles_leaves_field_untouched(self) -> None:
        pdf = _fake_pdf([_fake_page(), _fake_page(text="No numbered markers here")])
        md = _metadata(80)
        before = list(md.generic_marking_principles)
        extract_gmp(pdf, md, pages_start=1, pages_end=4)
        self.assertEqual(md.generic_marking_principles, before)


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------


class ProfileTests(unittest.TestCase):
    def test_known_code_returns_named_profile(self) -> None:
        profile = get_profile("0625")
        self.assertEqual(profile.name, "Physics")

    def test_unknown_code_returns_default_profile(self) -> None:
        profile = get_profile("9999")
        self.assertEqual(profile.name, "")

    def test_paper_type_by_number(self) -> None:
        profile = get_profile("0625")
        self.assertEqual(profile.paper_type(1), PaperType.MCQ)
        self.assertEqual(profile.paper_type(5), PaperType.PRACTICAL)

    def test_paper_type_from_cover_multiple_choice(self) -> None:
        profile = get_profile("9999")
        self.assertEqual(profile.paper_type(2, "This is a Multiple Choice paper"), PaperType.MCQ)

    def test_paper_type_from_cover_alternative_to_practical(self) -> None:
        profile = get_profile("9999")
        self.assertEqual(
            profile.paper_type(2, "Alternative to Practical"),
            PaperType.ALTERNATIVE_PRACTICAL,
        )

    def test_paper_type_from_cover_practical(self) -> None:
        profile = get_profile("9999")
        self.assertEqual(profile.paper_type(2, "Practical Test"), PaperType.PRACTICAL)

    def test_paper_type_from_cover_core(self) -> None:
        profile = get_profile("9999")
        self.assertEqual(profile.paper_type(2, "Core paper"), PaperType.THEORY_CORE)

    def test_paper_type_from_cover_extended(self) -> None:
        profile = get_profile("9999")
        self.assertEqual(profile.paper_type(2, "Extended paper"), PaperType.THEORY_EXTENDED)

    def test_paper_type_default_is_extended(self) -> None:
        profile = get_profile("9999")
        self.assertEqual(profile.paper_type(2, ""), PaperType.THEORY_EXTENDED)

    def test_0625_paper_2_is_mcq(self) -> None:
        """0625 Paper 2 is "Multiple Choice (Extended)", not Theory (Core).

        ``profiles.py`` mapped ``2: THEORY_CORE`` from the day the file was
        created (810ac08) and never changed. Confirmed against the real
        0625_s23_ms_22.pdf, whose cover page reads "Paper 2 Multiple Choice
        (Extended) May/June 2023".
        """
        profile = get_profile("0625")
        self.assertEqual(profile.paper_type(2), PaperType.MCQ)

    def test_cover_text_wins_over_a_contradicting_number_map(self) -> None:
        """The actual defect: the number map used to short-circuit the cover.

        A wrong constant silently overrode correct evidence sitting right there
        in the document, and the next wrong constant would have done the same.
        Paper 4 is mapped THEORY_EXTENDED; a cover that says otherwise wins.
        """
        profile = get_profile("0625")
        self.assertEqual(
            profile.paper_type(4, "Paper 4 Multiple Choice (Extended)"),
            PaperType.MCQ,
        )
        self.assertEqual(
            profile.paper_type(1, "Paper 1 Theory (Core)"),
            PaperType.THEORY_CORE,
        )

    def test_number_map_still_used_when_the_cover_says_nothing(self) -> None:
        """No cover evidence must fall back to the table, not to the default."""
        profile = get_profile("0625")
        self.assertEqual(profile.paper_type(5), PaperType.PRACTICAL)
        self.assertEqual(profile.paper_type(5, ""), PaperType.PRACTICAL)

    def test_0625_paper_3_falls_back_to_core_theory_not_extended(self) -> None:
        """B7: the 0625 paper-3 constant is THEORY_CORE, not THEORY_EXTENDED.

        CAIE 0625 Paper 3 is Theory (Core); the table said Extended from the
        file's creation until 2026-08-26. This pins the **fallback**, which is
        the only thing the constant still governs — when a real cover page is
        present it says "Paper 3 Core Theory" and outranks the table anyway,
        which is why correcting the constant is causally inert for parsing
        (``scheme_format`` is POINT_BASED either way). The case that changes
        is a scheme whose cover text is missing or unreadable: it used to
        default to the wrong tier.
        """
        profile = get_profile("0625")
        self.assertEqual(profile.paper_type(3), PaperType.THEORY_CORE)
        self.assertEqual(profile.paper_type(3, ""), PaperType.THEORY_CORE)
        # Paper 4 genuinely is Extended — guard against an over-broad fix.
        self.assertEqual(profile.paper_type(4), PaperType.THEORY_EXTENDED)

    def test_unrecognised_cover_text_falls_back_to_the_number_map(self) -> None:
        """Cover text only wins where it carries an actual paper-type keyword.

        Otherwise a cover page whose wording we do not model would silently
        demote every paper to the THEORY_EXTENDED default.
        """
        profile = get_profile("0625")
        self.assertEqual(
            profile.paper_type(5, "Cambridge IGCSE — May/June 2023 — 45 minutes"),
            PaperType.PRACTICAL,
        )

    def test_register_profile_roundtrip(self) -> None:
        register_profile(
            SubjectProfile(code="9998", name="TestSubject", paper_type_by_number={1: PaperType.MCQ})
        )
        profile = get_profile("9998")
        self.assertEqual(profile.name, "TestSubject")
        self.assertEqual(profile.paper_type(1), PaperType.MCQ)


# ---------------------------------------------------------------------------
# DeterministicMarkSchemeParser.__call__ — end-to-end
# ---------------------------------------------------------------------------


class DeterministicParserTests(unittest.TestCase):
    def _make_mcq_pdf(self, num_questions: int) -> MagicMock:
        answer_cycle = ["A", "B", "C", "D"]
        table = [[str(i + 1), answer_cycle[i % 4]] for i in range(num_questions)]
        pages = [
            _fake_page(text=_mcq_cover(num_questions)),  # cover
            _fake_page(),  # GMP page 1
            _fake_page(),  # GMP page 2
            _fake_page(tables=[table]),  # question table
        ]
        return _fake_pdf(pages)

    def test_default_cfg_used_when_omitted(self) -> None:
        parser = DeterministicMarkSchemeParser()
        self.assertIsInstance(parser._cfg, DetParserSettings)

    def test_mcq_end_to_end(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_mcq_pdf(40)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_m20_ms_12.pdf"))
        self.assertEqual(result.metadata.paper_type, PaperType.MCQ)
        self.assertEqual(len(result.questions), 40)
        for q in result.questions:
            self.assertEqual(q.type, QuestionType.MCQ)
            self.assertIsNotNone(q.mcq_answer)
            self.assertEqual(q.marks, 1)

    def test_mcq_answer_values_cycle(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_mcq_pdf(4)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_m20_ms_12.pdf"))
        answers = [q.mcq_answer for q in result.questions]
        self.assertEqual(answers, [MCQAnswer.A, MCQAnswer.B, MCQAnswer.C, MCQAnswer.D])

    def test_mcq_raises_when_no_abcd_table(self) -> None:
        pages = [
            _fake_page(text=_mcq_cover(2)),
            _fake_page(),
            _fake_page(),
            _fake_page(tables=[[["1", "some text"], ["2", "other text"]]]),
        ]
        parser = DeterministicMarkSchemeParser()
        with (
            patch("pdfplumber.open", return_value=_fake_pdf(pages)),
            self.assertRaises(ParseError),
        ):
            parser(Path("0625_m20_ms_12.pdf"))

    def test_theory_reconciliation_escalates_on_mark_mismatch(self) -> None:
        # Theory table whose leaf marks sum to 2 but the cover says max 80.
        # The Stage-4 reconciler must raise ParseError (escalate to Gemini).
        table = [["1", "A mark point", "1"], ["2", "Another point", "1"]]
        pages = [
            _fake_page(text=_THEORY_COVER),
            _fake_page(),
            _fake_page(),
            _fake_page(tables=[table]),
        ]
        parser = DeterministicMarkSchemeParser()
        with (
            patch("pdfplumber.open", return_value=_fake_pdf(pages)),
            self.assertRaises(ParseError),
        ):
            parser(Path("0625_s19_ms_42.pdf"))

    def test_theory_warn_only_cfg_does_not_escalate(self) -> None:
        # With escalation disabled, a mark mismatch is tolerated and a
        # MarkScheme is still returned.
        table = [["1", "A mark point", "1"], ["2", "Another point", "1"]]
        pages = [
            _fake_page(text=_THEORY_COVER),
            _fake_page(),
            _fake_page(),
            _fake_page(tables=[table]),
        ]
        cfg = DetParserSettings(escalate_on_mark_mismatch=False)
        parser = DeterministicMarkSchemeParser(cfg=cfg)
        with patch("pdfplumber.open", return_value=_fake_pdf(pages)):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertEqual(result.metadata.maximum_mark, 80)
        self.assertEqual(len(result.questions), 2)

    def test_theory_raises_when_no_tables(self) -> None:
        pages = [_fake_page(text=_THEORY_COVER), _fake_page(), _fake_page(), _fake_page()]
        parser = DeterministicMarkSchemeParser()
        with (
            patch("pdfplumber.open", return_value=_fake_pdf(pages)),
            self.assertRaises(ParseError),
        ):
            parser(Path("0625_s19_ms_42.pdf"))

    def test_theory_two_tables_one_page_plus_compensatory_c_mark_reconciles(self) -> None:
        """End-to-end regression pin for B2 (0625_w24_ms_41.pdf).

        Two independent bugs combined to make that real PDF fail mark-total
        reconciliation (parsed 83 vs stated max 80):

        1. ``select_tables`` kept only the *first* qualifying table per
           page, so question 2's entire table — a second, independently
           qualifying table on the same physical page as question 1's — was
           silently dropped.
        2. ``build_questions`` summed CAIE's compensatory C marks (see GMP
           M3: "C mark: Compensatory mark which may be scored when the final
           answer (A) mark ... has not been awarded") additively on top of
           the A mark they follow, instead of treating them as an
           alternative route to the same allocation.

        This test reproduces both conditions on a minimal synthetic PDF: two
        qualifying tables on one page (question 1 and question 2), with
        question 1 also carrying a plain (no "OR" keyword) C1 continuation
        row after its A2. Before the fix this raised ``ParseError`` either
        way (question 2 missing, or the C1 double-counted); after the fix it
        must parse cleanly to exactly the stated maximum mark.
        """
        cover = (
            "Cambridge IGCSE™\nPhysics\n"
            "0625/41 Mark Scheme October/November 2024\nMaximum Mark: 4\nPublished\n"
        )
        table_q1 = [
            ["Question", "Answer", "Marks"],
            ["1", "0.28 N / cm", "A2"],
            [None, "k = F / x", "C1"],
        ]
        table_q2 = [
            ["Question", "Answer", "Marks"],
            ["2", "some other point", "2"],
        ]
        pages = [
            _fake_page(text=cover),
            _fake_page(),
            _fake_page(),
            _fake_page(tables=[table_q1, table_q2]),
        ]
        parser = DeterministicMarkSchemeParser()
        with patch("pdfplumber.open", return_value=_fake_pdf(pages)):
            result = parser(Path("0625_w24_ms_41.pdf"))
        self.assertEqual(len(result.questions), 2)
        self.assertEqual(result.questions[0].marks, 2)  # A2 only; C1 compensatory
        self.assertEqual(result.questions[1].marks, 2)
        self.assertEqual(sum(q.marks for q in result.questions), result.metadata.maximum_mark)


# ---------------------------------------------------------------------------
# ChainedMarkSchemeParser wiring
# ---------------------------------------------------------------------------


class ChainedParserTests(unittest.TestCase):
    def test_primary_success_means_fallback_not_called(self) -> None:
        from lemely.io.parsers import ChainedMarkSchemeParser

        primary = MagicMock(return_value=MagicMock())
        fallback = MagicMock()
        chain = ChainedMarkSchemeParser(primary=primary, fallback=fallback)
        chain(Path("test.pdf"))
        primary.assert_called_once_with(Path("test.pdf"))
        fallback.assert_not_called()

    def test_primary_parse_error_triggers_fallback(self) -> None:
        from lemely.io.parsers import ChainedMarkSchemeParser

        primary = MagicMock(side_effect=ParseError("unsupported type"))
        fallback = MagicMock(return_value=MagicMock())
        chain = ChainedMarkSchemeParser(primary=primary, fallback=fallback)
        chain(Path("test.pdf"))
        fallback.assert_called_once_with(Path("test.pdf"))

    def test_returns_primary_result_when_successful(self) -> None:
        from lemely.io.parsers import ChainedMarkSchemeParser

        expected = MagicMock()
        primary = MagicMock(return_value=expected)
        fallback = MagicMock()
        chain = ChainedMarkSchemeParser(primary=primary, fallback=fallback)
        self.assertIs(chain(Path("test.pdf")), expected)

    def test_returns_fallback_result_on_parse_error(self) -> None:
        from lemely.io.parsers import ChainedMarkSchemeParser

        expected = MagicMock()
        primary = MagicMock(side_effect=ParseError("levels-based"))
        fallback = MagicMock(return_value=expected)
        chain = ChainedMarkSchemeParser(primary=primary, fallback=fallback)
        self.assertIs(chain(Path("test.pdf")), expected)

    def test_non_parse_error_from_primary_propagates(self) -> None:
        from lemely.io.parsers import ChainedMarkSchemeParser

        primary = MagicMock(side_effect=ValueError("unexpected"))
        fallback = MagicMock()
        chain = ChainedMarkSchemeParser(primary=primary, fallback=fallback)
        with self.assertRaises(ValueError):
            chain(Path("test.pdf"))
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestMarksDefaultedProvenance(unittest.TestCase):
    """#38 (M1.3): `make_point` mints a 1-mark point when the marks cell is
    unparseable. Until now the parser never recorded that it had guessed, so a
    minted mark was indistinguishable from one read off the page.

    These pin the provenance flag only. They deliberately do NOT assert any
    change to `marks` — the value is unchanged by design; what is new is that
    the guess is countable.
    """

    def test_parsed_marks_cell_is_not_defaulted(self) -> None:
        """A readable marks cell yields marks_defaulted=False."""
        rows: list[list[str | None]] = [["1(a)", "the answer", "2"]]
        qs = _run_theory(rows)
        point = qs[0].parts[0].answer_points[0]
        self.assertEqual(point.marks, 2)
        self.assertFalse(point.marks_defaulted)

    def test_unparseable_marks_cell_is_flagged_defaulted(self) -> None:
        """An empty marks cell mints 1 mark AND records that it did."""
        rows: list[list[str | None]] = [["1(a)", "the answer", ""]]
        qs = _run_theory(rows)
        point = qs[0].parts[0].answer_points[0]
        self.assertEqual(point.marks, 1, "value is unchanged — still the minted default")
        self.assertTrue(point.marks_defaulted, "but it is now recorded as minted")

    def test_leaked_multi_mark_code_is_now_recovered_not_defaulted(self) -> None:
        """The DA21 mechanism (B) case — FIXED by #136, so this test inverted.

        It used to assert that ``B3`` silently became 1 and was flagged as
        minted: that was the defect being pinned so it stayed countable. #136
        recovers the code from the answer text instead, so the value is now
        read rather than guessed, and ``marks_defaulted`` must be False — a
        recovered mark is not a minted one, and flagging it would overstate the
        defaulted-mark rate #38 measures.
        """
        rows: list[list[str | None]] = [["5(a)", "centre of mass is where lines cross B3", ""]]
        qs = _run_theory(rows)
        point = qs[0].parts[0].answer_points[0]
        self.assertEqual(point.marks, 3, "B3 is now read, not minted as 1")
        self.assertFalse(point.marks_defaulted)
        self.assertEqual(point.point, "centre of mass is where lines cross")

    def test_single_mark_code_leak_is_also_recovered(self) -> None:
        """The case that made the bug invisible: the minted 1 happened to be right.

        The value is the same before and after the fix, which is exactly why
        this one is worth keeping — it is now right for the right reason, and
        the flag distinguishes the two.
        """
        rows: list[list[str | None]] = [["5(b)", "marked on line of symmetry B1", ""]]
        qs = _run_theory(rows)
        point = qs[0].parts[0].answer_points[0]
        self.assertEqual(point.marks, 1, "same value as before, now read rather than guessed")
        self.assertFalse(point.marks_defaulted)
        self.assertEqual(point.point, "marked on line of symmetry")

    def test_defaulted_flag_defaults_false_on_the_schema(self) -> None:
        """A point built without the flag is not silently marked as a guess."""
        self.assertFalse(AnswerPoint(id="p1", point="x", marks=1).marks_defaulted)


# ---------------------------------------------------------------------------
# #136 / DA21 — the two one-directional mark-loss mechanisms in rows.py
# ---------------------------------------------------------------------------


class ExtractTrailingMarkCodeTests(unittest.TestCase):
    """Mechanism (B): the marks column merges into the answer cell.

    In the 3-column geometry some CAIE papers use, pdfplumber puts the mark
    code at the END of the answer text instead of in its own cell. The marks
    cell then parses as empty and ``make_point`` mints 1 — right by luck for
    every single-mark code, wrong for every multi-mark one.
    """

    def test_recovers_a_multi_mark_code_and_strips_it(self) -> None:
        got = extract_trailing_mark_code("centre of mass is where lines cross B3")
        assert got is not None
        text, mark = got
        self.assertEqual(text, "centre of mass is where lines cross")
        self.assertEqual(mark, ParsedMark(value=3, math_mark_type=MathMarkType.B))

    def test_recovers_each_caie_letter(self) -> None:
        for letter, expected in (
            ("B", MathMarkType.B),
            ("C", MathMarkType.C),
            ("A", MathMarkType.A),
            ("M", MathMarkType.M),
        ):
            got = extract_trailing_mark_code(f"some answer {letter}2")
            assert got is not None, letter
            self.assertEqual(got[0], "some answer")
            self.assertEqual(got[1], ParsedMark(value=2, math_mark_type=expected))

    def test_a_bare_trailing_integer_is_NOT_a_mark_code(self) -> None:
        # The single most dangerous false positive: an answer that legitimately
        # ends in a number ("the reading is 12") would otherwise be rewritten
        # into a 12-mark point. Only letter-prefixed codes are recovered.
        for text in ("the reading is 12", "answer = 4", "300 000 000 m/s 3"):
            self.assertIsNone(extract_trailing_mark_code(text))

    def test_a_letter_glued_to_the_preceding_word_is_not_a_code(self) -> None:
        # "...vitaminB2" must not be read as a B2 mark.
        self.assertIsNone(extract_trailing_mark_code("contains vitaminB2"))

    def test_a_code_not_at_the_end_is_left_alone(self) -> None:
        self.assertIsNone(extract_trailing_mark_code("B1 is awarded for the method"))

    def test_zero_valued_code_is_rejected(self) -> None:
        self.assertIsNone(extract_trailing_mark_code("no marks here B0"))

    def test_empty_and_whitespace(self) -> None:
        self.assertIsNone(extract_trailing_mark_code(""))
        self.assertIsNone(extract_trailing_mark_code("   "))

    def test_a_code_that_is_the_entire_cell_is_not_stripped_to_nothing(self) -> None:
        # Stripping would leave an AnswerPoint with no text at all, which is
        # unmarkable. Better to leave it for the caller's default.
        self.assertIsNone(extract_trailing_mark_code("B3"))


class LeakedMarkCodeRecoveryTests(unittest.TestCase):
    """Mechanism (B) end to end through ``build_questions``."""

    def test_leaked_code_sets_the_real_value_not_the_minted_1(self) -> None:
        rows: list[list[str | None]] = [
            ["1(a)", "centre of mass is where lines cross B3", ""],
        ]
        leaf = _run_theory(rows)[0].parts[0]
        (point,) = leaf.answer_points or []
        self.assertEqual(point.marks, 3)
        self.assertEqual(point.point, "centre of mass is where lines cross")
        self.assertEqual(point.math_mark_type, MathMarkType.B)

    def test_recovered_marks_are_not_flagged_as_defaulted(self) -> None:
        # marks_defaulted means "this 1 was minted, not read" (#38/M1.3). A
        # recovered code WAS read, just from the wrong column — flagging it
        # would overstate the defaulted-mark rate #38 is measuring.
        rows: list[list[str | None]] = [["1(a)", "some answer B2", ""]]
        (point,) = _run_theory(rows)[0].parts[0].answer_points or []
        self.assertFalse(point.marks_defaulted)

    def test_a_real_marks_cell_always_wins_over_the_text(self) -> None:
        # Recovery must only ever fire when the marks cell gave nothing. If
        # both are present the column is authoritative.
        rows: list[list[str | None]] = [["1(a)", "some answer B3", "1"]]
        (point,) = _run_theory(rows)[0].parts[0].answer_points or []
        self.assertEqual(point.marks, 1)
        self.assertEqual(point.point, "some answer B3")

    def test_question_marks_reflect_the_recovered_value(self) -> None:
        rows: list[list[str | None]] = [["1(a)", "answer text B4", ""]]
        self.assertEqual(_run_theory(rows)[0].parts[0].marks, 4)


class MarksOnlyContinuationRowTests(unittest.TestCase):
    """Mechanism (A): a continuation row with marks but no answer text.

    ``rows.py``'s blank-row guard fired before the marks column was consulted,
    so a row carrying a real ``B1`` and an empty answer cell was discarded with
    its mark. Real case: ``0625_w21_ms_32`` 6(a), where pdfplumber merges a
    whole matching table into the first cell and leaves three bare ``B1`` rows
    behind — the parser emitted 1 mark where the paper prints 4.
    """

    def test_marks_only_rows_are_added_to_the_preceding_point(self) -> None:
        rows: list[list[str | None]] = [
            ["6(a)", "conductor copper wire; insulator cotton cloth", "B1"],
            ["", "", "B1"],
            ["", "", "B1"],
            ["", "", "B1"],
        ]
        leaf = _run_theory(rows)[0].parts[0]
        (point,) = leaf.answer_points or []
        self.assertEqual(point.marks, 4)
        self.assertEqual(leaf.marks, 4)

    def test_the_text_stays_on_the_point_that_earned_it(self) -> None:
        # The marks are merged INTO the existing point rather than becoming
        # textless points of their own — an AnswerPoint with no text cannot be
        # matched against a candidate's answer, so it would be unmarkable.
        rows: list[list[str | None]] = [
            ["6(a)", "the merged cell text", "B1"],
            ["", "", "B1"],
        ]
        points = _run_theory(rows)[0].parts[0].answer_points or []
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].point, "the merged cell text")

    def test_a_genuinely_blank_row_still_adds_nothing(self) -> None:
        rows: list[list[str | None]] = [
            ["6(a)", "an answer", "B1"],
            ["", "", ""],
        ]
        self.assertEqual(_run_theory(rows)[0].parts[0].marks, 1)

    def test_a_marks_only_row_with_no_preceding_point_is_dropped(self) -> None:
        # Stated limit, not an oversight: with nothing to attach to, the
        # alternative is inventing a textless point. Dropping is the
        # conservative direction — it can only ever understate.
        rows: list[list[str | None]] = [
            ["6(a)", "", "B1"],
            ["", "", "B1"],
        ]
        # The question's OWN marks cell still reads B1 — that is read off the
        # page, not invented. What must not happen is the second row's mark
        # also landing here.
        self.assertEqual(_run_theory(rows)[0].parts[0].marks, 1)

    def test_marks_only_row_does_not_leak_across_a_question_boundary(self) -> None:
        # The stray mark must attach within its own question, never to the
        # previous question's last point.
        rows: list[list[str | None]] = [
            ["1(a)", "first answer", "B1"],
            ["1(b)", "", ""],
            ["", "", "B1"],
        ]
        questions = _run_theory(rows)
        parts = questions[0].parts or []
        # 1(b) has no point of its own, so the stray B1 has nothing to attach
        # to and is dropped. It must NOT drift back onto 1(a)'s point.
        self.assertEqual([p.marks for p in parts], [1, 0])


class NumericDataRowsAreNotAnswerPointsTests(unittest.TestCase):
    """#136 mechanism (C): an OVERCOUNT, the opposite direction to (A)/(B).

    Some papers embed a data table — stem-and-leaf, a frequency table, a list of
    readings — inside a question's rows. pdfplumber emits each of its lines as a
    row with numeric text and NO marks cell, so ``make_point`` minted 1 mark per
    line. Real case: ``0580_s23_ms_22`` parsed to 73 against a printed 70,
    entirely from three such rows (``'(1 3) 4 5 5 8'``, ``'1 2'``, ``'3 4'``).

    The rule is narrow on purpose: suppression needs BOTH an unparseable marks
    cell AND text with no alphabetic content. A genuine numeric answer that
    carries its own marks cell is untouched, and a minted mark is a guess
    either way — declining to guess understates, which is the safe direction.
    """

    def test_a_numeric_row_with_no_marks_cell_mints_nothing(self) -> None:
        rows: list[list[str | None]] = [
            ["8(a)", "the real answer", "2"],
            ["", "(1 3) 4 5 5 8", ""],
        ]
        leaf = _run_theory(rows)[0].parts[0]
        self.assertEqual(leaf.marks, 2)
        self.assertEqual(len(leaf.answer_points or []), 1)

    def test_a_numeric_answer_WITH_a_marks_cell_is_untouched(self) -> None:
        # The guard must not eat legitimate numeric answers. This is the case
        # that makes a blanket "digits are not answers" rule wrong.
        rows: list[list[str | None]] = [["8(b)", "3.5", "2"]]
        leaf = _run_theory(rows)[0].parts[0]
        self.assertEqual(leaf.marks, 2)
        (point,) = leaf.answer_points or []
        self.assertEqual(point.point, "3.5")

    def test_text_with_any_letter_is_still_an_answer_point(self) -> None:
        rows: list[list[str | None]] = [
            ["8(c)", "first", "1"],
            ["", "2 cm", ""],
        ]
        leaf = _run_theory(rows)[0].parts[0]
        self.assertEqual(len(leaf.answer_points or []), 2)
        self.assertEqual(leaf.marks, 2)

    def test_a_numeric_answer_on_a_LABELLED_sub_part_row_survives(self) -> None:
        # Measured regression, caught by the corpus before/after rather than by
        # reasoning: `0625_s20_ms_61` 1(a) answers "0.025, 0.037, 0.050,
        # 0.063, 0.075" — numeric, no marks cell, entirely genuine. Suppressing
        # it cost the paper a mark it had before. A labelled part is an answer
        # row; a data-table line is not labelled.
        rows: list[list[str | None]] = [
            ["1(a)", "0.025, 0.037, 0.050, 0.063, 0.075", ""],
        ]
        leaf = _run_theory(rows)[0].parts[0]
        self.assertEqual(len(leaf.answer_points or []), 1)
        self.assertEqual(leaf.marks, 1)

    def test_a_numeric_row_read_as_a_new_question_carries_no_marks(self) -> None:
        # A data-table line beginning with a number is decomposed as a new
        # top-level question (that id defect is #110's, deliberately not fixed
        # here). What must not happen is it also minting a mark.
        rows: list[list[str | None]] = [
            ["8(a)", "the real answer", "2"],
            ["1", "2", ""],
            ["3", "4", ""],
        ]
        total = sum(
            leaf.marks or 0
            for root in _run_theory(rows)
            for leaf in ([root] if not root.parts else root.parts)
        )
        self.assertEqual(total, 2)


class BracketedMarksAreAlternativeRoutesTests(unittest.TestCase):
    """#136 mechanism (D): ``mark_aggregation_overcount``.

    CAIE brackets a mark belonging to an ALTERNATIVE route to the same
    allocation, printed under an "Or"/"Alternative" heading. The parser read
    "(A1)" as identical to "A1" and summed both routes. ``0606_s23_ms_12``
    parsed to 116 against a printed 80 — and its 23 bracketed rows total
    exactly 36, which is exactly the discrepancy.
    """

    def test_a_balanced_bracket_marks_an_alternative(self) -> None:
        for cell in ("(A1)", "(M1)", "(3)", "(B2)"):
            parsed = parse_marks_cell(cell)
            assert parsed is not None, cell
            self.assertTrue(parsed.is_alternative, cell)

    def test_an_unbracketed_cell_is_primary(self) -> None:
        for cell in ("A1", "M1", "3", "B2"):
            parsed = parse_marks_cell(cell)
            assert parsed is not None, cell
            self.assertFalse(parsed.is_alternative, cell)

    def test_a_one_sided_paren_is_NOT_treated_as_an_alternative(self) -> None:
        # An extraction artefact must not silently delete a real mark from the
        # total. Only a balanced pair is CAIE notation.
        for cell in ("(A1", "A1)"):
            parsed = parse_marks_cell(cell)
            assert parsed is not None, cell
            self.assertFalse(parsed.is_alternative, cell)

    def test_bracketed_cells_still_qualify_as_a_marks_column(self) -> None:
        # The bracket changes AGGREGATION, not parseability — column detection
        # must be unaffected, or the whole table stops being found.
        self.assertTrue(is_marks_column(["B1", "C1", "(A1)", "(3)"]))

    def test_an_alternative_route_is_excluded_from_the_question_total(self) -> None:
        rows: list[list[str | None]] = [
            ["9", "primary method", "2"],
            ["", "final answer", "A1"],
            ["", "Or alternative method", "(2)"],
            ["", "alternative final answer", "(A1)"],
        ]
        leaf = _run_theory(rows)[0]
        self.assertEqual(leaf.marks, 3, "2 + A1, with the bracketed route excluded")

    def test_the_alternative_points_are_KEPT_not_discarded(self) -> None:
        # They are a real marking route a candidate may have taken — excluding
        # them from the TOTAL must not delete them from the scheme.
        rows: list[list[str | None]] = [
            ["9", "primary method", "2"],
            ["", "Or alternative method", "(2)"],
        ]
        points = _run_theory(rows)[0].answer_points or []
        self.assertEqual(len(points), 2)
        self.assertEqual([p.is_alternative for p in points], [False, True])

    def test_a_bracketed_mark_on_the_question_row_sets_no_tariff(self) -> None:
        rows: list[list[str | None]] = [["9", "an alternative opening", "(2)"]]
        self.assertEqual(_run_theory(rows)[0].marks, 0)

    def test_a_bracketed_marks_only_row_is_not_merged_into_a_primary_point(self) -> None:
        # Mechanism (A) recovers marks from textless rows; it must not pull an
        # ALTERNATIVE mark into the primary point and reintroduce the overcount
        # this mechanism removes.
        rows: list[list[str | None]] = [
            ["9", "primary method", "B1"],
            ["", "", "(B2)"],
        ]
        self.assertEqual(_run_theory(rows)[0].marks, 1)


class SplitOnAlternativeMarkerTests(unittest.TestCase):
    """#112 — the alternative-branch detector missed three shapes.

    ``rows.py`` fired only when the answer cell **equalled** ``OR``/``EITHER``
    or **started** with the marker plus a **space**. pdfplumber returns the
    marker and the following working in ONE cell separated by a **newline**, so
    neither branch matched and mutually exclusive routes were summed.
    """

    def test_marker_alone_on_the_first_line(self) -> None:
        # Sub-defect 1: marker followed by \n, the shape 0606_s23_ms_12 uses.
        got = split_on_alternative_marker("Or\n4 2\n1 + - x dx")
        assert got is not None
        before, after, marker = got
        self.assertEqual(before, "")
        self.assertEqual(after, "4 2\n1 + - x dx")
        self.assertEqual(marker, "OR")

    def test_alternative_is_in_the_vocabulary(self) -> None:
        # Sub-defect 2: "Alternative" is the word CAIE 0606 actually prints and
        # it was not a recognised marker at all.
        for word in ("Alternative", "ALTERNATIVE", "Alternatively"):
            got = split_on_alternative_marker(f"{word}\n3y2 - 14y + 11 (=0)")
            assert got is not None, word
            self.assertEqual(got[1], "3y2 - 14y + 11 (=0)")

    def test_marker_not_at_cell_start_splits_the_cell(self) -> None:
        # Sub-defect 3, and the cell-splitting decision B15 asked for. The real
        # case is 0606_s23_ms_12 leaf 33b, where an operator fragment from the
        # previous row precedes the marker. Text BEFORE the marker belongs to
        # the primary branch; text after is the alternative. Keeping both is
        # what makes this a split rather than a reclassification.
        got = split_on_alternative_marker("⩽ ⩽\nAlternative\n9x2 - 28x + 3 * 0")
        assert got is not None
        before, after, _ = got
        self.assertEqual(before, "⩽ ⩽")
        self.assertEqual(after, "9x2 - 28x + 3 * 0")

    def test_an_inline_OR_between_expressions_is_NOT_a_marker(self) -> None:
        # The false positive that matters. CAIE writes "accept either form" as
        # an inline OR inside ONE mark point — 0625_s22_ms_33 carries
        # "4000 / 10 OR 4000 / 9.8". Treating that as a branch marker would
        # split a single point in half and drop half its text.
        self.assertIsNone(split_on_alternative_marker("4000 / 10 OR 4000 / 9.8"))
        self.assertIsNone(split_on_alternative_marker("same as (c)(i) OR 0.4(0) A"))

    def test_a_word_merely_containing_a_marker_is_not_one(self) -> None:
        self.assertIsNone(split_on_alternative_marker("ORA applies here"))
        self.assertIsNone(split_on_alternative_marker("Order of magnitude"))

    def test_no_marker_returns_none(self) -> None:
        self.assertIsNone(split_on_alternative_marker("just an ordinary answer"))
        self.assertIsNone(split_on_alternative_marker(""))

    def test_trailing_punctuation_on_the_marker_line_is_tolerated(self) -> None:
        got = split_on_alternative_marker("Alternative:\nsecond method")
        assert got is not None
        self.assertEqual(got[1], "second method")


class AlternativeRouteBranchingTests(unittest.TestCase):
    """#112 end to end: mutually exclusive routes must not be summed."""

    def test_newline_marker_puts_the_second_route_in_the_alt_branch(self) -> None:
        rows: list[list[str | None]] = [
            ["9", "primary method", "2"],
            [None, "Or\nalternative method", "2"],
        ]
        leaf = _run_theory(rows)[0]
        points = leaf.answer_points or []
        self.assertEqual([p.is_alternative for p in points], [False, True])
        self.assertEqual(leaf.marks, 2, "the alternative route must not be summed in")

    def test_alternative_keyword_behaves_the_same(self) -> None:
        rows: list[list[str | None]] = [
            ["9", "primary method", "3"],
            [None, "Alternative\nsecond route", "3"],
        ]
        leaf = _run_theory(rows)[0]
        self.assertEqual(leaf.marks, 3)

    def test_a_split_cell_keeps_both_halves_each_carrying_the_rows_mark(self) -> None:
        # The cell-splitting decision (B15). A cell holding
        # "primary working / OR / alternative working" carries ONE mark awarded
        # for EITHER route, so both halves take the row's mark and only the
        # alternative is excluded from the primary sum. Merging `before` as
        # text-only instead was measured and reconciled WORSE (304 schemes
        # exact against 329).
        rows: list[list[str | None]] = [
            ["9", "opening", "1"],
            [None, "tail of the primary working\nAlternative\nsecond route", "1"],
        ]
        leaf = _run_theory(rows)[0]
        points = leaf.answer_points or []
        self.assertEqual(
            [(p.point, p.marks, p.is_alternative) for p in points],
            [
                ("opening", 1, False),
                ("tail of the primary working", 1, False),
                ("second route", 1, True),
            ],
        )
        self.assertEqual(leaf.marks, 2, "both primary points count; the alternative does not")

    def test_a_leading_fragment_with_nothing_to_attach_to_takes_the_mark(self) -> None:
        rows: list[list[str | None]] = [
            ["9", "", "0"],
            [None, "leading working\nOr\nsecond route", "2"],
        ]
        points = _run_theory(rows)[0].answer_points or []
        self.assertEqual(
            [(p.point, p.marks, p.is_alternative) for p in points],
            [("leading working", 2, False), ("second route", 2, True)],
        )

    def test_a_split_cell_on_a_BRACKETED_row_stays_wholly_alternative(self) -> None:
        # #136 mechanism (D) and #112 can fire on the SAME row. A bracketed
        # marks cell means the whole row is an alternative route, so neither
        # half of a split cell may be counted as primary. Missing this pushed
        # 0606_s23_ms_12 from an exact 80 to 82.
        rows: list[list[str | None]] = [
            ["9", "primary route", "2"],
            [None, "alternative working\nOr\nyet another form", "(2)"],
        ]
        leaf = _run_theory(rows)[0]
        points = leaf.answer_points or []
        self.assertEqual([p.is_alternative for p in points], [False, True, True])
        self.assertEqual(leaf.marks, 2)

    def test_EITHER_opens_the_PRIMARY_route_not_the_alternative(self) -> None:
        # The Q-row branch already treats EITHER as structural (see
        # test_either_on_q_row_is_structural_not_a_point). The continuation
        # branch did the opposite and switched INTO the alternative on EITHER,
        # so an "EITHER ... OR ..." pair scored neither route as primary.
        rows: list[list[str | None]] = [
            ["9", "opening working", "1"],
            [None, "Either\nfirst route", "2"],
            [None, "Or\nsecond route", "2"],
        ]
        leaf = _run_theory(rows)[0]
        points = leaf.answer_points or []
        self.assertEqual([p.is_alternative for p in points], [False, False, True])
        self.assertEqual(leaf.marks, 3, "opening + the EITHER route; the OR route excluded")


class DuplicateTopLevelIdTests(unittest.TestCase):
    """#110 — the parser emitted duplicate top-level ids, breaking DA6 leaf identity.

    Leaf identity is ``(paper_id, question_id)``, so a duplicate id WITHIN a
    paper collapses two different questions into one leaf. Measured over 477
    parsed source schemes: **34 (7.13%) carry duplicates and 57 leaves collapse**
    — and **14 of those schemes reconcile with their printed maximum exactly**,
    so `mark_total_mismatch_escalating` cannot catch it.

    Two mechanisms were found. This class covers the unambiguous one: CAIE
    repeats the question number at the top of each continuation page, and the
    parser opened a fresh question each time. `0606_w23_ms_13` opens question
    `10` four times that way.
    """

    def test_a_repeated_top_level_number_continues_the_open_question(self) -> None:
        rows: list[list[str | None]] = [
            ["10", "first page working", "2"],
            # continuation page: CAIE reprints the number
            ["10", "second page working", "3"],
        ]
        questions = _run_theory(rows)
        self.assertEqual([q.id for q in questions], ["10"])
        self.assertEqual(
            [p.point for p in questions[0].answer_points or []],
            ["first page working", "second page working"],
        )
        self.assertEqual(questions[0].marks, 5)

    def test_a_genuinely_new_question_still_opens(self) -> None:
        rows: list[list[str | None]] = [
            ["10", "answer ten", "2"],
            ["11", "answer eleven", "3"],
        ]
        self.assertEqual([q.id for q in _run_theory(rows)], ["10", "11"])

    def test_a_reprinted_number_before_its_own_subparts_does_not_duplicate(self) -> None:
        rows: list[list[str | None]] = [
            ["10(a)", "part a", "1"],
            ["10", "continuation working", "1"],
            ["10(b)", "part b", "1"],
        ]
        questions = _run_theory(rows)
        self.assertEqual([q.id for q in questions], ["10"])
        leaf_ids = [p.id for p in questions[0].parts or []]
        self.assertEqual(len(leaf_ids), len(set(leaf_ids)), f"duplicate leaves: {leaf_ids}")

    def test_going_back_to_an_earlier_number_is_NOT_treated_as_continuation(self) -> None:
        # The second mechanism — a stray non-question table whose first column
        # holds small integers, e.g. 0580_w21_ms_22 emitting 2,3,5 between
        # questions 20 and 20(b). That is NOT a page-break continuation and must
        # not be silently folded into question 2; it stays a distinct question so
        # the loud detector can see it.
        rows: list[list[str | None]] = [
            ["2", "answer two", "1"],
            ["20", "answer twenty", "1"],
            ["2", "stray table row", "1"],
        ]
        self.assertEqual([q.id for q in _run_theory(rows)], ["2", "20", "2"])


class DuplicateLeafIdDetectorTests(unittest.TestCase):
    """#110 bullet 4 — duplicate leaf ids must fail LOUDLY, not flow into a join.

    They are invisible to the mark-total gate: 14 of the 333 schemes that
    reconcile with their printed maximum exactly still carry duplicates.
    """

    def test_duplicate_leaf_ids_are_reported(self) -> None:
        dup = [
            Question(id="1", marks=40, type=QuestionType.RECALL),
            Question(id="1", marks=40, type=QuestionType.RECALL),
        ]
        with capture_logs() as logs:
            reconcile_check(dup, _metadata(80))
        events = [entry.get("event") for entry in logs]
        self.assertIn("duplicate_leaf_ids", events)
        entry = next(e for e in logs if e.get("event") == "duplicate_leaf_ids")
        self.assertEqual(entry["duplicate_ids"], ["1"])
        self.assertEqual(entry["leaves_lost_to_collapse"], 1)

    def test_distinct_leaf_ids_are_silent(self) -> None:
        ok = [
            Question(id="1", marks=40, type=QuestionType.RECALL),
            Question(id="2", marks=40, type=QuestionType.RECALL),
        ]
        with capture_logs() as logs:
            reconcile_check(ok, _metadata(80))
        self.assertNotIn("duplicate_leaf_ids", [entry.get("event") for entry in logs])

    def test_it_escalates_only_when_armed(self) -> None:
        # Unarmed by default, deliberately. Escalating routes the paper to the
        # Gemini fallback, which #166 measured failing on ~50% of the schemes
        # det cannot parse — so arming is a cost AND coverage decision, not a
        # tidy-up. Same treatment as escalate_on_defaulted_marks.
        dup = [
            Question(id="1", marks=40, type=QuestionType.RECALL),
            Question(id="1", marks=40, type=QuestionType.RECALL),
        ]
        reconcile_check(dup, _metadata(80))  # must not raise
        with self.assertRaises(ParseError):
            reconcile_check(dup, _metadata(80), escalate_on_duplicate_leaf_ids=True)

    def test_duplicates_are_caught_even_when_the_marks_reconcile(self) -> None:
        # The whole point: this defect is orthogonal to mark totals.
        dup = [
            Question(id="1", marks=40, type=QuestionType.RECALL),
            Question(id="1", marks=40, type=QuestionType.RECALL),
        ]
        with self.assertRaises(ParseError) as ctx:
            reconcile_check(dup, _metadata(80), escalate_on_duplicate_leaf_ids=True)
        self.assertIn("1", str(ctx.exception))


class PhantomLeafTests(unittest.TestCase):
    """#110 mechanism 2, the part that CAN be repaired without inventing identity.

    A data-table line beginning with a number is decomposed as a new top-level
    question. #136 mechanism (C) already stops those rows minting a mark, which
    leaves them as **empty shells**: no marks, no answer points, and an id that
    collides with the real question of the same number.

    Dropping them is not deduping and not renumbering — it removes a node with
    no content. Measured: 11 of the 71 leaves involved in duplicate ids are such
    shells, and in `0580_s23_ms_22` (a golden-corpus scheme) each duplicate pair
    is exactly one real question plus one shell, so dropping the shells clears
    the collision entirely.
    """

    def test_an_empty_phantom_leaf_is_dropped(self) -> None:
        rows: list[list[str | None]] = [
            ["8(a)", "the real answer", "2"],
            # data-table lines: numeric first cell, numeric text, no marks cell
            ["1", "2", ""],
            ["3", "4", ""],
        ]
        self.assertEqual([q.id for q in _run_theory(rows)], ["8"])

    def test_dropping_shells_clears_the_duplicate_id_collision(self) -> None:
        # The 0580_s23_ms_22 shape: real questions 1 and 2, then a data table
        # whose rows re-open ids 1 and 2 as empty shells.
        rows: list[list[str | None]] = [
            ["1", "first answer", "1"],
            ["2", "second answer", "1"],
            ["8(a)", "eighth answer", "2"],
            ["1", "2", ""],
            ["2", "3", ""],
        ]
        ids = [q.id for q in _run_theory(rows)]
        self.assertEqual(ids, ["1", "2", "8"])
        self.assertEqual(len(ids), len(set(ids)), "no duplicate top-level ids remain")

    def test_a_question_with_marks_but_no_points_is_KEPT(self) -> None:
        # Only a node with NEITHER marks NOR points is contentless. A question
        # whose tariff was read off the page is real even if its answer text
        # did not parse — dropping it would silently shrink the paper.
        rows: list[list[str | None]] = [["7", "", "3"]]
        questions = _run_theory(rows)
        self.assertEqual([q.id for q in questions], ["7"])
        self.assertEqual(questions[0].marks, 3)

    def test_a_parent_whose_subparts_are_real_is_KEPT(self) -> None:
        rows: list[list[str | None]] = [
            ["9(a)", "part a", "1"],
            ["9(b)", "part b", "1"],
        ]
        questions = _run_theory(rows)
        self.assertEqual([q.id for q in questions], ["9"])
        self.assertEqual([p.id for p in questions[0].parts or []], ["9a", "9b"])

    def test_dropping_shells_cannot_change_the_mark_total(self) -> None:
        rows: list[list[str | None]] = [
            ["1", "real", "5"],
            ["2", "3", ""],
        ]
        questions = _run_theory(rows)
        self.assertEqual(sum(q.marks or 0 for q in questions), 5)
