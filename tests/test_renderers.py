"""Tests for human-mode CLI renderers."""

from __future__ import annotations

import unittest

from rich.console import Console

from lemely.app import renderers
from lemely.core.schemas import (
    BatchParseItem,
    BatchParseResult,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    CostEstimate,
    ExamMetadata,
    ExtractedAnswer,
    ExtractedAnswers,
    SubjectResult,
    WeaknessReport,
)


def _render_to_str(obj: object) -> str:
    console = Console(record=True, width=120)
    console.print(obj)
    return console.export_text()


def _metadata() -> ExamMetadata:
    return ExamMetadata(
        subject_code="9702",
        paper_number=4,
        paper_variant=2,
        session_month="May/June",
        session_year=2023,
    )


class RendererTests(unittest.TestCase):
    def test_render_cost_estimate_includes_totals(self) -> None:
        est = CostEstimate(
            source_root="Sources",
            mark_scheme_pdfs=10,
            cached_json=7,
            needs_parsing=3,
            estimated_pdf_pages=None,
            token_policy="...",
        )
        out = _render_to_str(renderers.render_cost_estimate(est))
        self.assertIn("10", out)
        self.assertIn("7", out)
        self.assertIn("3", out)

    def test_render_correction_result_lists_each_question(self) -> None:
        result = CorrectionResult(
            metadata=_metadata(),
            questions=[
                CorrectedQuestion(
                    question_id="1",
                    awarded_marks=1,
                    maximum_marks=1,
                    confidence=ConfidenceBand.HIGH,
                    confidence_score=1.0,
                    needs_teacher_review=False,
                    student_answer="A",
                    expected_answer="A",
                    topic="kinematics",
                ),
                CorrectedQuestion(
                    question_id="2",
                    awarded_marks=0,
                    maximum_marks=1,
                    confidence=ConfidenceBand.HIGH,
                    confidence_score=1.0,
                    needs_teacher_review=False,
                    student_answer="B",
                    expected_answer="C",
                    topic="forces",
                ),
                CorrectedQuestion(
                    question_id="3",
                    awarded_marks=0,
                    maximum_marks=1,
                    confidence=ConfidenceBand.LOW,
                    confidence_score=0.0,
                    needs_teacher_review=True,
                    student_answer=None,
                    expected_answer="D",
                    topic="forces",
                    review_reason="missing answer",
                ),
            ],
        )
        out = _render_to_str(renderers.render_correction(result))
        self.assertIn("1", out)
        self.assertIn("2", out)
        self.assertIn("3", out)
        self.assertIn("kinematics", out)
        self.assertIn("forces", out)
        self.assertIn("yes", out)
        self.assertIn("A", out)
        self.assertIn("C", out)

    def test_render_batch_result_uses_computed_fields(self) -> None:
        result = BatchParseResult(
            items=[
                BatchParseItem(source_path="a.pdf", output_path="a.json", status="parsed"),
                BatchParseItem(source_path="b.pdf", output_path="b.json", status="parsed"),
                BatchParseItem(source_path="c.pdf", output_path=None, status="skipped_existing"),
                BatchParseItem(
                    source_path="d.pdf", output_path=None, status="failed", message="boom"
                ),
                BatchParseItem(source_path="e.pdf", output_path=None, status="invalid_existing"),
            ],
        )
        out = _render_to_str(renderers.render_batch_result(result))
        self.assertIn("Batch parse summary", out)
        self.assertIn("Total", out)
        self.assertIn("Parsed", out)
        self.assertIn("Skipped (existing)", out)
        self.assertIn("Failed", out)
        self.assertEqual(result.failed, 2)
        self.assertIn(" 2 ", out)


class ExtractedAnswersRendererTests(unittest.TestCase):
    def test_renders_low_confidence_highlighted(self) -> None:
        ea = ExtractedAnswers(
            paper_id="0625_test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
                ExtractedAnswer(question_id="2(a)", answer="osmosis", confidence=0.6),
            ],
        )
        out = _render_to_str(renderers.render_extracted_answers(ea))
        self.assertIn("1", out)
        self.assertIn("2(a)", out)
        self.assertIn("osmosis", out)


class SubjectResultRendererTests(unittest.TestCase):
    def test_renders_subject_grade_and_papers(self) -> None:
        meta = ExamMetadata(
            subject_code="0625",
            paper_number=2,
            paper_variant=1,
            session_month="May/June",
            session_year=2020,
        )
        paper = CorrectionResult(
            metadata=meta,
            questions=[
                CorrectedQuestion(
                    question_id="q1",
                    awarded_marks=8,
                    maximum_marks=10,
                    confidence=ConfidenceBand.HIGH,
                    confidence_score=1.0,
                    needs_teacher_review=False,
                ),
            ],
        )
        sr = SubjectResult(
            subject_code="0625",
            session_month="May/June",
            session_year=2020,
            paper_results=[paper],
            weaknesses=WeaknessReport(weak_areas=[]),
        )
        tables = renderers.render_subject_result(sr)
        out = "".join(_render_to_str(t) for t in tables)
        self.assertIn("0625", out)
        self.assertIn("80", out)  # 80% or 8/10


if __name__ == "__main__":
    unittest.main()
