"""Unit tests for the golden-dataset accuracy measurement harness."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LoadGoldenCasesTests(unittest.TestCase):
    def _make_case_dir(self, root: Path, name: str = "0625_m20_qp_12") -> Path:
        case_dir = root / name
        case_dir.mkdir()
        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 1,
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            ],
        }
        (case_dir / "mark_scheme.json").write_text(json.dumps(ms))
        answers = {"1": {"student_answer": "A", "awarded_marks": 1}}
        (case_dir / "answers.json").write_text(json.dumps(answers))
        return case_dir

    def test_loads_single_case(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].paper_id, "0625_m20_qp_12")

    def test_ground_truth_parsed(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        gt = cases[0].ground_truth
        self.assertIn("1", gt)
        self.assertEqual(gt["1"].student_answer, "A")
        self.assertEqual(gt["1"].awarded_marks, 1)

    def test_scan_path_none_when_no_pdf(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertIsNone(cases[0].scan_path)

    def test_scan_path_set_when_pdf_present(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "scan.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(Path(tmp))
        self.assertIsNotNone(cases[0].scan_path)

    def test_skips_dir_without_required_files(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "incomplete").mkdir()
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)

    def test_notes_field_optional(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            answers = {"1": {"student_answer": "A", "awarded_marks": 1, "notes": "owtte"}}
            (case_dir / "answers.json").write_text(json.dumps(answers))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(cases[0].ground_truth["1"].notes, "owtte")

    def test_multiple_cases_sorted_order(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp), name="zzz_paper")
            self._make_case_dir(Path(tmp), name="aaa_paper")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].paper_id, "aaa_paper")
        self.assertEqual(cases[1].paper_id, "zzz_paper")

    def test_skips_malformed_answers_json(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "answers.json").write_text("{ not valid json }")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)


class MetricComputationTests(unittest.TestCase):
    def _qr(
        self, predicted: int, truth: int, confidence: float, review: bool, is_mcq: bool = False
    ) -> object:
        from lemely.accuracy.harness import QuestionResult

        return QuestionResult(
            question_id="q",
            question_type="mcq" if is_mcq else "theory",
            predicted_marks=predicted,
            truth_marks=truth,
            confidence_score=confidence,
            needs_teacher_review=review,
        )

    def test_all_correct_accuracy_is_1(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [self._qr(2, 2, 0.95, False), self._qr(1, 1, 0.92, False)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy, 1.0)

    def test_half_correct_accuracy(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [self._qr(2, 2, 0.95, False), self._qr(0, 2, 0.72, True)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy, 0.5)

    def test_theory_only_excludes_mcq(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [
            self._qr(1, 1, 1.0, False, is_mcq=True),  # MCQ correct
            self._qr(0, 2, 0.72, True, is_mcq=False),  # theory wrong
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy_theory, 0.0)

    def test_flag_precision_high(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [
            self._qr(2, 2, 0.95, False),  # confident + correct
            self._qr(0, 2, 0.91, False),  # confident + wrong
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_precision_high, 0.5)

    def test_flag_recall(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [
            self._qr(0, 2, 0.55, True),  # wrong + flagged
            self._qr(0, 2, 0.91, False),  # wrong + not flagged
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_recall, 0.5)

    def test_no_wrong_flag_recall_is_one(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [self._qr(2, 2, 0.97, False)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_recall, 1.0)

    def test_calibration_bucket_assignment(self):
        from lemely.accuracy.harness import _build_calibration

        results = [
            self._qr(1, 1, 0.95, False),  # 0.90–1.00 bucket, correct
            self._qr(0, 1, 0.85, True),  # 0.80–0.90 bucket, wrong
        ]
        buckets = _build_calibration(results)
        top = buckets[0]  # 0.90–1.00
        second = buckets[1]  # 0.80–0.90
        self.assertEqual(top.predictions, 1)
        self.assertEqual(top.correct, 1)
        self.assertEqual(second.predictions, 1)
        self.assertEqual(second.correct, 0)


class MeasureAccuracyTests(unittest.TestCase):
    """Tests for measure_accuracy()'s scan_path-gated extraction path.

    Mark schemes here are MCQ-only so `correct_paper` never needs a real (or
    mocked) Gemini client — the only Gemini-touching seam under test is
    `extract_answers`, which is mocked at its definition site
    (`lemely.web.services.grading.extract_answers`) since `measure_accuracy`
    lazily imports it by name on each call.
    """

    def _mark_scheme(self, question_ids: list[str]) -> object:
        from lemely.core.loose_schemas import MarkScheme

        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": len(question_ids),
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": qid, "marks": 1, "type": "mcq", "mcq_answer": "A"} for qid in question_ids
            ],
        }
        return MarkScheme.model_validate(ms)

    def test_no_scan_path_keeps_bypass_behaviour(self):
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy

        case = GoldenCase(
            paper_id="p1",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )

        with patch("lemely.web.services.grading.extract_answers") as mock_extract:
            result = measure_accuracy([case], gemini_client=None, settings=None)

        mock_extract.assert_not_called()
        self.assertIsNone(result.metrics.id_match_rate)
        self.assertEqual(len(result.question_results), 1)
        self.assertTrue(result.question_results[0].is_correct)

    def test_scan_path_case_uses_extracted_answers_not_ground_truth(self):
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        # Ground truth text is deliberately NOT a valid MCQ letter — if the
        # harness fed this into correct_paper instead of the extracted text,
        # both questions would be marked wrong.
        case = GoldenCase(
            paper_id="p2",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="ignored", awarded_marks=1),
                "2": GoldenAnswer(student_answer="ignored", awarded_marks=1),
            },
            scan_path=Path("/nonexistent/scan.pdf"),
        )
        fake_extracted = ExtractedAnswers(
            paper_id="p2",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="A", confidence=0.9),
            ],
        )

        with patch(
            "lemely.web.services.grading.extract_answers", return_value=fake_extracted
        ) as mock_extract:
            result = measure_accuracy([case], gemini_client=None, settings=None)

        mock_extract.assert_called_once()
        self.assertEqual(result.metrics.id_match_rate, 1.0)
        self.assertEqual(len(result.question_results), 2)
        self.assertTrue(all(r.is_correct for r in result.question_results))

    def test_scan_path_case_missing_id_reflected_in_id_match_rate(self):
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        case = GoldenCase(
            paper_id="p3",
            mark_scheme=self._mark_scheme(["1", "2", "3"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
                "3": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=Path("/nonexistent/scan2.pdf"),
        )
        # Extraction misses question "3" entirely.
        fake_extracted = ExtractedAnswers(
            paper_id="p3",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="A", confidence=0.9),
            ],
        )

        with patch("lemely.web.services.grading.extract_answers", return_value=fake_extracted):
            result = measure_accuracy([case], gemini_client=None, settings=None)

        self.assertAlmostEqual(result.metrics.id_match_rate, 2 / 3)
        # No QuestionResult for "3" — nothing to compare, no crash.
        self.assertEqual(len(result.question_results), 2)
        self.assertNotIn("3", {r.question_id for r in result.question_results})

    def test_mixed_batch_id_match_rate_only_from_extraction_case(self):
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        case_scan = GoldenCase(
            paper_id="p4",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=Path("/nonexistent/scan3.pdf"),
        )
        case_bypass = GoldenCase(
            paper_id="p5",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=None,
        )
        fake_extracted = ExtractedAnswers(
            paper_id="p4",
            source_scan="fake",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.9)],
        )

        with patch(
            "lemely.web.services.grading.extract_answers", return_value=fake_extracted
        ) as mock_extract:
            result = measure_accuracy([case_scan, case_bypass], gemini_client=None, settings=None)

        mock_extract.assert_called_once()
        self.assertEqual(result.metrics.id_match_rate, 1.0)
        self.assertEqual(len(result.question_results), 3)


class EvalRecordDerivationBitIdenticalTests(unittest.TestCase):
    """M0.1 acceptance line (spec §4): AccuracyMetrics reproduced bit-identically
    from ``list[EvalRecord]``.

    No literal saved 2026-08-04 JSON exists in the repo (checked), so this
    compares the legacy ``_compute_metrics(question_results)`` path against
    the new ``EvalRecord``-derived path over equivalent inputs, per the
    accepted risk-mitigation reading of that acceptance line.
    """

    def _qr(
        self, qid: str, predicted: int, truth: int, confidence: float, review: bool, is_mcq: bool
    ) -> object:
        from lemely.accuracy.harness import QuestionResult

        return QuestionResult(
            question_id=qid,
            question_type="mcq" if is_mcq else "theory",
            predicted_marks=predicted,
            truth_marks=truth,
            confidence_score=confidence,
            needs_teacher_review=review,
        )

    def test_synthetic_mixed_results_reproduce_bit_identically(self):
        from lemely.accuracy.harness import (
            _compute_metrics,
            _metrics_from_eval_records,
            question_result_to_eval_record,
        )

        results = [
            self._qr("1", 2, 2, 0.95, False, is_mcq=True),  # mcq, correct, confident
            self._qr("2", 0, 2, 0.55, True, is_mcq=False),  # theory, under, flagged
            self._qr("3", 3, 1, 0.91, False, is_mcq=False),  # theory, over, confident+wrong
            self._qr("4", 1, 1, 0.88, False, is_mcq=True),  # mcq, correct
        ]
        id_match_rate = 0.75

        legacy = _compute_metrics(results, id_match_rate=id_match_rate)

        eval_records = [
            question_result_to_eval_record(
                r, run_id="test-run", paper_id="paper-1", arm="extract+mark"
            )
            for r in results
        ]
        derived = _metrics_from_eval_records(eval_records, id_match_rate=id_match_rate)

        self.assertEqual(legacy, derived)

    def test_empty_results_reproduce_bit_identically(self):
        from lemely.accuracy.harness import _compute_metrics, _metrics_from_eval_records

        legacy = _compute_metrics([], id_match_rate=None)
        derived = _metrics_from_eval_records([], id_match_rate=None)
        self.assertEqual(legacy, derived)

    def test_all_correct_reproduces_bit_identically(self):
        from lemely.accuracy.harness import (
            _compute_metrics,
            _metrics_from_eval_records,
            question_result_to_eval_record,
        )

        results = [self._qr("1", 1, 1, 0.99, False, is_mcq=False)]
        legacy = _compute_metrics(results, id_match_rate=1.0)
        eval_records = [
            question_result_to_eval_record(
                r, run_id="test-run", paper_id="paper-1", arm="oracle+mark"
            )
            for r in results
        ]
        derived = _metrics_from_eval_records(eval_records, id_match_rate=1.0)
        self.assertEqual(legacy, derived)

    def test_measure_accuracy_pipeline_matches_legacy_compute_metrics(self):
        """Runs the real measure_accuracy() pipeline (both arms) and checks its
        reported AccuracyMetrics — now internally EvalRecord-derived — equal
        what _compute_metrics(question_results) would have computed for the
        same question_results, proving no behavioural drift end-to-end."""
        from lemely.accuracy.harness import (
            GoldenAnswer,
            GoldenCase,
            _compute_metrics,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        case_scan = GoldenCase(
            paper_id="p1",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=Path("/nonexistent/scan.pdf"),
        )
        case_bypass = GoldenCase(
            paper_id="p2",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )
        fake_extracted = ExtractedAnswers(
            paper_id="p1",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="B", confidence=0.9),  # wrong
            ],
        )

        with patch("lemely.web.services.grading.extract_answers", return_value=fake_extracted):
            result = measure_accuracy([case_scan, case_bypass], gemini_client=None, settings=None)

        expected = _compute_metrics(
            result.question_results, id_match_rate=result.metrics.id_match_rate
        )
        self.assertEqual(result.metrics, expected)

    def _mark_scheme(self, question_ids: list[str]) -> object:
        from lemely.core.loose_schemas import MarkScheme

        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": len(question_ids),
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": qid, "marks": 1, "type": "mcq", "mcq_answer": "A"} for qid in question_ids
            ],
        }
        return MarkScheme.model_validate(ms)
