"""Unit tests for the deterministic mark scheme parser.

All tests use synthetic pdfplumber data — no real PDFs required.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import MCQAnswer, PaperType, QuestionType, SessionMonth
from lemely.io.parsers_det import (
    DeterministicMarkSchemeParser,
    _find_mcq_answer_col,
    _make_id,
    _run_theory_state_machine,
)
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


# ---------------------------------------------------------------------------
# Cover page text helpers
# ---------------------------------------------------------------------------

_MCQ_COVER_40 = """\
Cambridge IGCSE™
Physics
0625/12 Mark Scheme February/March 2020
Maximum Mark: 40
Published
"""


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
# _make_id
# ---------------------------------------------------------------------------


class MakeIdTests(unittest.TestCase):
    def test_level_0(self) -> None:
        self.assertEqual(_make_id(["1"]), "1")

    def test_level_1(self) -> None:
        self.assertEqual(_make_id(["1", "(a)"]), "1a")

    def test_level_2(self) -> None:
        self.assertEqual(_make_id(["1", "(a)", "(i)"]), "1a_i")

    def test_level_2_multi_digit(self) -> None:
        self.assertEqual(_make_id(["12", "(b)", "(ii)"]), "12b_ii")

    def test_empty(self) -> None:
        self.assertEqual(_make_id([]), "")


# ---------------------------------------------------------------------------
# _find_mcq_answer_col
# ---------------------------------------------------------------------------


class FindMCQAnswerColTests(unittest.TestCase):
    def test_identifies_rightmost_abcd_column(self) -> None:
        rows = [
            ["1", "A"],
            ["2", "B"],
            ["3", "C"],
        ]
        self.assertEqual(_find_mcq_answer_col(rows), 1)

    def test_returns_none_when_no_abcd_column(self) -> None:
        rows = [["1", "some text"], ["2", "more text"]]
        self.assertIsNone(_find_mcq_answer_col(rows))

    def test_skips_column_zero(self) -> None:
        # Even if all of column 0 were A/B/C/D, we want column 1
        rows = [["A", "A"], ["B", "B"], ["C", "C"]]
        # Column 1 has A/B/C — should find it
        self.assertEqual(_find_mcq_answer_col(rows), 1)

    def test_empty_rows(self) -> None:
        self.assertIsNone(_find_mcq_answer_col([]))


# ---------------------------------------------------------------------------
# MCQ extraction
# ---------------------------------------------------------------------------


class MCQExtractionTests(unittest.TestCase):
    def _make_mcq_pdf(self, num_questions: int = 40) -> MagicMock:
        answer_cycle = ["A", "B", "C", "D"]
        table = [[str(i + 1), answer_cycle[i % 4]] for i in range(num_questions)]
        pages = [
            _fake_page(text=_mcq_cover(num_questions)),  # cover (mark matches count)
            _fake_page(),  # GMP page 1
            _fake_page(),  # GMP page 2
            _fake_page(tables=[table]),  # question table
        ]
        return _fake_pdf(pages)

    def test_extracts_correct_count(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_mcq_pdf(40)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_m20_ms_12.pdf"))
        self.assertEqual(len(result.questions), 40)

    def test_all_questions_are_mcq_type(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_mcq_pdf(10)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_m20_ms_12.pdf"))
        for q in result.questions:
            self.assertEqual(q.type, QuestionType.MCQ)

    def test_all_questions_have_mcq_answer(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_mcq_pdf(10)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_m20_ms_12.pdf"))
        for q in result.questions:
            self.assertIsNotNone(q.mcq_answer)

    def test_answer_values_cycle_correctly(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_mcq_pdf(4)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_m20_ms_12.pdf"))
        answers = [q.mcq_answer for q in result.questions]
        self.assertEqual(answers, [MCQAnswer.A, MCQAnswer.B, MCQAnswer.C, MCQAnswer.D])

    def test_each_mcq_question_has_one_mark(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_mcq_pdf(5)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_m20_ms_12.pdf"))
        for q in result.questions:
            self.assertEqual(q.marks, 1)

    def test_metadata_paper_type_is_mcq(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_mcq_pdf(5)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_m20_ms_12.pdf"))
        self.assertEqual(result.metadata.paper_type, PaperType.MCQ)

    def test_raises_parse_error_when_no_abcd_table(self) -> None:
        pages = [
            _fake_page(text=_mcq_cover(2)),
            _fake_page(),
            _fake_page(),
            _fake_page(tables=[[["1", "some text"], ["2", "other text"]]]),
        ]
        parser = DeterministicMarkSchemeParser()
        with patch("pdfplumber.open", return_value=_fake_pdf(pages)), self.assertRaises(ParseError):
            parser(Path("0625_m20_ms_12.pdf"))


# ---------------------------------------------------------------------------
# Theory extraction
# ---------------------------------------------------------------------------


def _make_theory_table() -> list[list[str | None]]:
    """Synthetic 3-column theory table:

    Q-num | Answer / mark point | Marks
    ------+---------------------+------
    1     |                     | 0
          | First mark point    | 1
          | Second mark point   | 1
    (a)   |                     | 3
          | Sub-point one       | 1
          | Sub-point two       | 1
          | OR                  |
          | Alternative point   | 1
    2     | Simple question     | 2
          | Another point       | 1
    """
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
    def _run(self, table: list[list[str | None]]) -> list:
        # 3-column table: col 0 = Q-num, col 1 = answer, col 2 = marks.
        # answer_col_end is the exclusive upper bound for the answer range,
        # which equals marks_col so range(1, 2) picks only col 1.
        return _run_theory_state_machine(
            rows=table,
            q_col=0,
            answer_col_end=2,
            guidance_col=None,
            marks_col=2,
        )

    def test_top_level_question_count(self) -> None:
        questions = self._run(_make_theory_table())
        self.assertEqual(len(questions), 2)

    def test_q1_has_correct_marks(self) -> None:
        questions = self._run(_make_theory_table())
        self.assertEqual(questions[0].marks, 0)  # container; marks from sub-parts

    def test_q1_has_subpart_a(self) -> None:
        questions = self._run(_make_theory_table())
        q1 = questions[0]
        self.assertEqual(len(q1.parts), 1)
        self.assertEqual(q1.parts[0].id, "1a")

    def test_q1_top_level_answer_points(self) -> None:
        questions = self._run(_make_theory_table())
        q1 = questions[0]
        self.assertEqual(len(q1.answer_points), 2)
        self.assertEqual(q1.answer_points[0].point, "First mark point")
        self.assertEqual(q1.answer_points[1].point, "Second mark point")

    def test_subpart_a_answer_points(self) -> None:
        questions = self._run(_make_theory_table())
        qa = questions[0].parts[0]
        self.assertEqual(len(qa.answer_points), 3)

    def test_or_block_sets_is_alternative(self) -> None:
        questions = self._run(_make_theory_table())
        qa = questions[0].parts[0]
        # p1 = "Sub-point one", p2 = "Sub-point two", p3 = "Alternative point"
        self.assertFalse(qa.answer_points[0].is_alternative)
        self.assertFalse(qa.answer_points[1].is_alternative)
        self.assertTrue(qa.answer_points[2].is_alternative)

    def test_q2_id(self) -> None:
        questions = self._run(_make_theory_table())
        self.assertEqual(questions[1].id, "2")

    def test_q2_answer_points(self) -> None:
        questions = self._run(_make_theory_table())
        q2 = questions[1]
        self.assertEqual(len(q2.answer_points), 2)

    def test_ids_are_hierarchical(self) -> None:
        questions = self._run(_make_theory_table())
        q1 = questions[0]
        self.assertEqual(q1.id, "1")
        self.assertEqual(q1.parts[0].id, "1a")

    def test_parent_id_set_on_subpart(self) -> None:
        questions = self._run(_make_theory_table())
        q1a = questions[0].parts[0]
        self.assertEqual(q1a.parent_id, "1")

    def test_continuation_row_without_question_adds_point(self) -> None:
        table = [
            ["1", "First point", "1"],
            [None, "Continuation point", "1"],
        ]
        questions = _run_theory_state_machine(table, 0, 2, None, 2)
        self.assertEqual(len(questions[0].answer_points), 2)

    def test_marks_on_answer_point_from_marks_column(self) -> None:
        table = [
            ["1", "Point text", "3"],
        ]
        questions = _run_theory_state_machine(table, 0, 2, None, 2)
        self.assertEqual(questions[0].answer_points[0].marks, 3)

    def test_raises_parse_error_on_level_descriptor(self) -> None:
        table = [
            ["Level 1", "descriptors marks available", "3"],
        ]
        with self.assertRaises(ParseError):
            _run_theory_state_machine(table, 0, 2, None, 2)

    def test_raises_parse_error_on_indicative_content(self) -> None:
        table = [
            ["1", "Indicative content section header", "0"],
        ]
        with self.assertRaises(ParseError):
            _run_theory_state_machine(table, 0, 2, None, 2)

    def test_raises_parse_error_on_empty_table(self) -> None:
        with self.assertRaises(ParseError):
            _run_theory_state_machine([], 0, 1, None, 2)

    def test_or_inline_text_creates_alternative_point(self) -> None:
        table = [
            ["1", "Main point", "1"],
            [None, "OR alternative text", "1"],
        ]
        questions = _run_theory_state_machine(table, 0, 2, None, 2)
        pts = questions[0].answer_points
        self.assertTrue(pts[1].is_alternative)
        self.assertEqual(pts[1].point, "alternative text")

    def test_guidance_column_stored_in_notes(self) -> None:
        # 4-column table: Q | Answer | Guidance | Marks
        table = [
            ["1", "Point text", "See guidance here", "2"],
        ]
        questions = _run_theory_state_machine(
            rows=table,
            q_col=0,
            answer_col_end=2,  # guidance is at col 2; answer range is [1,2) = col 1
            guidance_col=2,
            marks_col=3,
        )
        self.assertEqual(questions[0].notes, "See guidance here")

    def test_three_levels_of_nesting(self) -> None:
        table = [
            ["1", None, "0"],
            ["(a)", None, "0"],
            ["(i)", "Deepest point", "1"],
        ]
        questions = _run_theory_state_machine(table, 0, 2, None, 2)
        q1 = questions[0]
        q1a = q1.parts[0]
        q1a_i = q1a.parts[0]
        self.assertEqual(q1a_i.id, "1a_i")
        self.assertEqual(q1a_i.answer_points[0].point, "Deepest point")


# ---------------------------------------------------------------------------
# ChainedMarkSchemeParser
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
        result = chain(Path("test.pdf"))
        self.assertIs(result, expected)

    def test_returns_fallback_result_on_parse_error(self) -> None:
        from lemely.io.parsers import ChainedMarkSchemeParser

        expected = MagicMock()
        primary = MagicMock(side_effect=ParseError("levels-based"))
        fallback = MagicMock(return_value=expected)
        chain = ChainedMarkSchemeParser(primary=primary, fallback=fallback)
        result = chain(Path("test.pdf"))
        self.assertIs(result, expected)

    def test_non_parse_error_from_primary_propagates(self) -> None:
        from lemely.io.parsers import ChainedMarkSchemeParser

        primary = MagicMock(side_effect=ValueError("unexpected"))
        fallback = MagicMock()
        chain = ChainedMarkSchemeParser(primary=primary, fallback=fallback)
        with self.assertRaises(ValueError):
            chain(Path("test.pdf"))
        fallback.assert_not_called()


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


class MetadataExtractionTests(unittest.TestCase):
    def _make_minimal_theory_pdf(self, cover_text: str) -> MagicMock:
        table = [["1", "A mark point", "1"]]
        pages = [
            _fake_page(text=cover_text),
            _fake_page(),
            _fake_page(),
            _fake_page(tables=[table]),
        ]
        return _fake_pdf(pages)

    def test_subject_code_from_filename(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(_THEORY_COVER)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertEqual(result.metadata.subject_code, "0625")

    def test_paper_number_from_filename(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(_THEORY_COVER)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertEqual(result.metadata.paper_number, 4)

    def test_paper_variant_from_filename(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(_THEORY_COVER)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertEqual(result.metadata.paper_variant, 2)

    def test_session_month_from_filename(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(_THEORY_COVER)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertEqual(result.metadata.session_month, SessionMonth.MAY_JUNE)

    def test_session_year_from_filename(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(_THEORY_COVER)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertEqual(result.metadata.session_year, 2019)

    def test_maximum_mark_from_cover_page(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(_THEORY_COVER)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertEqual(result.metadata.maximum_mark, 80)

    def test_raises_parse_error_when_maximum_mark_missing(self) -> None:
        bad_cover = "Cambridge IGCSE\n0625/42 Mark Scheme\nPublished\n"
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(bad_cover)
        with patch("pdfplumber.open", return_value=pdf), self.assertRaises(ParseError):
            parser(Path("0625_s19_ms_42.pdf"))

    def test_raises_parse_error_when_no_tables(self) -> None:
        pages = [_fake_page(text=_THEORY_COVER), _fake_page(), _fake_page(), _fake_page()]
        parser = DeterministicMarkSchemeParser()
        with patch("pdfplumber.open", return_value=_fake_pdf(pages)), self.assertRaises(ParseError):
            parser(Path("0625_s19_ms_42.pdf"))

    def test_published_flag_detected(self) -> None:
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(_THEORY_COVER)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertTrue(result.metadata.published)

    def test_unpublished_flag_when_not_in_cover(self) -> None:
        cover = _THEORY_COVER.replace("Published", "Confidential")
        parser = DeterministicMarkSchemeParser()
        pdf = self._make_minimal_theory_pdf(cover)
        with patch("pdfplumber.open", return_value=pdf):
            result = parser(Path("0625_s19_ms_42.pdf"))
        self.assertFalse(result.metadata.published)


# ---------------------------------------------------------------------------
# Live integration tests (real PDFs, no API key needed)
# ---------------------------------------------------------------------------


@unittest.skip("live: run manually with real PDFs in Sources/Physics/MarkingSchemes/")
class LiveParserTests(unittest.TestCase):
    """Integration tests against real CAIE Physics mark scheme PDFs.

    Run with::

        uv run pytest tests/test_parsers_det.py::LiveParserTests -v -s
    """

    MCQ_PDF = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json")

    def test_mcq_paper_produces_valid_mark_scheme(self) -> None:
        pdf = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.pdf")
        if not pdf.exists():
            self.skipTest(f"PDF not found: {pdf}")
        parser = DeterministicMarkSchemeParser()
        result = parser(pdf)
        self.assertIsNotNone(result)
        self.assertEqual(result.metadata.paper_type, PaperType.MCQ)
        self.assertEqual(len(result.questions), 40)
        for q in result.questions:
            self.assertIsNotNone(q.mcq_answer)

    def test_mcq_metadata_matches_filename(self) -> None:
        pdf = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.pdf")
        if not pdf.exists():
            self.skipTest(f"PDF not found: {pdf}")
        parser = DeterministicMarkSchemeParser()
        result = parser(pdf)
        self.assertEqual(result.metadata.subject_code, "0625")
        self.assertEqual(result.metadata.paper_number, 1)
        self.assertEqual(result.metadata.paper_variant, 2)
        self.assertEqual(result.metadata.session_year, 2020)
        self.assertEqual(result.metadata.session_month, SessionMonth.FEB_MAR)


if __name__ == "__main__":
    unittest.main()
