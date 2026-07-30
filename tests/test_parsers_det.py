"""Unit tests for the modular deterministic mark-scheme parser (``lemely.io.det``).

All tests use synthetic pdfplumber data — no real PDFs and no network required.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import (
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
from lemely.io.det.marks import ParsedMark, is_marks_column, parse_marks_cell
from lemely.io.det.mcq import find_mcq_answer_col, parse_mcq_tables
from lemely.io.det.metadata import extract_metadata
from lemely.io.det.profiles import SubjectProfile, get_profile, register_profile
from lemely.io.det.reconcile import check as reconcile_check
from lemely.io.det.rows import build_questions, decompose_compound_q, make_id
from lemely.io.det.tables import qualifies_as_mark_scheme_table
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
        self.assertEqual(parse_marks_cell("(A1)"), ParsedMark(1, MathMarkType.A))

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
