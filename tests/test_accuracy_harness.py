"""Unit tests for the golden-dataset accuracy measurement harness."""

from __future__ import annotations

import json
import os
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

    def test_fixture_variant_parsed_from_dir_suffix(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp), name="0625_s20_qp_31_theory_correct")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(cases[0].paper_id, "0625_s20_qp_31_theory")
        self.assertEqual(cases[0].fixture_variant, "correct")

    def test_fixture_variant_none_when_dir_has_no_variant_suffix(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp), name="0625_m20_qp_12_mcq")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(cases[0].paper_id, "0625_m20_qp_12_mcq")
        self.assertIsNone(cases[0].fixture_variant)

    def test_skips_malformed_answers_json(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "answers.json").write_text("{ not valid json }")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)

    def test_is_excerpt_defaults_false_when_marker_absent(self):
        """M0.8 (#32): a fixture with no case.json sidecar is not an excerpt."""
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertFalse(cases[0].is_excerpt)

    def test_is_excerpt_true_when_case_json_marker_present(self):
        """M0.8 (#32): case.json is a sidecar, never routed through MarkScheme
        validation, so it cannot silently be dropped as an unknown pydantic key."""
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "case.json").write_text(json.dumps({"is_excerpt": True}))
            cases = load_golden_cases(Path(tmp))
        self.assertTrue(cases[0].is_excerpt)

    def test_is_excerpt_string_false_does_not_coerce_to_true(self):
        """#32/#69: ``bool("false")`` is ``True`` in Python, so a JSON string
        value for ``is_excerpt`` must not be coerced with ``bool()`` -- that
        would silently flip a falsy-looking string into a truthy flag. A
        non-bool marker value falls into the existing fail-open handler
        (logged and defaulted to False), the same as any other malformed
        case.json, rather than being miscoerced."""
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "case.json").write_text(json.dumps({"is_excerpt": "false"}))
            cases = load_golden_cases(Path(tmp))
        self.assertFalse(cases[0].is_excerpt)


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

    def test_mcq_results_enter_the_calibration_curve(self) -> None:
        """MCQ QuestionResults must appear in a non-empty calibration bucket (D19, #36/M1.1).

        Before this change, ``_build_calibration`` filtered to
        ``question_type == "theory"`` only, silently dropping every MCQ
        result from the curve.
        """
        from lemely.accuracy.harness import _build_calibration

        results = [self._qr(1, 1, 0.95, False, is_mcq=True)]
        buckets = _build_calibration(results)
        total_predictions = sum(b.predictions for b in buckets)
        self.assertEqual(total_predictions, 1)


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

    def test_arm_override_forces_oracle_mark_even_with_scan_path(self):
        """#28/M0.4: passing arm="oracle+mark" explicitly must bypass
        extraction and use ground-truth text even when the case carries a
        scan_path — the arm parameter, not scan_path presence, decides.
        """
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy

        case = GoldenCase(
            paper_id="p-oracle-override",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=Path("/nonexistent/scan.pdf"),
        )

        with patch("lemely.web.services.grading.extract_answers") as mock_extract:
            result = measure_accuracy([case], gemini_client=None, settings=None, arm="oracle+mark")

        mock_extract.assert_not_called()
        self.assertEqual(len(result.eval_records), 1)
        self.assertEqual(result.eval_records[0].arm, "oracle+mark")

    def test_arm_override_extract_mark_without_scan_path_raises(self):
        """#28/M0.4: forcing arm="extract+mark" on a case with no scan_path
        must fail fast, before any Gemini spend, rather than silently
        falling back to the oracle bypass.
        """
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy

        case = GoldenCase(
            paper_id="p-no-scan",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )

        with self.assertRaises(ValueError) as ctx:
            measure_accuracy([case], gemini_client=None, settings=None, arm="extract+mark")

        self.assertIn("p-no-scan", str(ctx.exception))

    def test_both_arms_over_same_cases_produce_ablation_2x2_nonzero(self):
        """#28/M0.4: running both arms over the same case and feeding the
        concatenated records into ablation_2x2() must yield a non-degenerate
        (not-all-zero) cross-tabulation.
        """
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.eval.analyses import ablation_2x2

        case = GoldenCase(
            paper_id="p-ablation",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=Path("/nonexistent/scan.pdf"),
        )

        oracle_result = measure_accuracy(
            [case], gemini_client=None, settings=None, arm="oracle+mark"
        )

        # Extraction gets "1" right and "2" wrong.
        fake_extracted = ExtractedAnswers(
            paper_id="p-ablation",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="B", confidence=0.9),
            ],
        )
        with patch("lemely.web.services.grading.extract_answers", return_value=fake_extracted):
            extract_result = measure_accuracy(
                [case], gemini_client=None, settings=None, arm="extract+mark"
            )

        combined = oracle_result.eval_records + extract_result.eval_records
        table = ablation_2x2(combined)

        total = sum(table.values())
        self.assertEqual(total, 2)
        self.assertGreater(total, 0)
        self.assertFalse(all(v == 0 for v in table.values()))

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
        # No QuestionResult for "3" — QuestionResult stays matched-rows-only.
        self.assertEqual(len(result.question_results), 2)
        self.assertNotIn("3", {r.question_id for r in result.question_results})
        # But it is NOT silently dropped (D18): an EvalRecord for "3" exists,
        # recorded honestly as unmatched rather than vanishing from the
        # denominator.
        records_by_qid = {r.question_id: r for r in result.eval_records}
        self.assertIn("3", records_by_qid)
        self.assertEqual(records_by_qid["3"].outcome, "unmatched")
        self.assertEqual(records_by_qid["3"].id_match, "unmatched")
        self.assertIsNone(records_by_qid["3"].predicted_marks)

    def test_fewer_extracted_questions_cannot_score_higher(self):
        """D18 regression (#29): a run whose extractor returns FEWER answers
        must never score HIGHER than a run whose extractor returned more —
        answers it never returns cannot be silently dropped from the
        denominator, only the previously reachable id_match_rate.

        Run A gets all three ids back, one of them (``"2"``) wrong. Run B
        gets a strict subset — only ``"1"``, identical to run A's ``"1"`` and
        correct. Under the pre-fix `harness.py:596` ``continue``, run B's
        denominator shrinks to just the one id it got right, scoring 1.0 —
        strictly higher than run A's 2/3, even though B did no better work.
        """
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        def make_case() -> GoldenCase:
            return GoldenCase(
                paper_id="pD18",
                mark_scheme=self._mark_scheme(["1", "2", "3"]),
                ground_truth={
                    "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                    "2": GoldenAnswer(student_answer="A", awarded_marks=1),
                    "3": GoldenAnswer(student_answer="A", awarded_marks=1),
                },
                scan_path=Path("/nonexistent/scanD18.pdf"),
            )

        extracted_full = ExtractedAnswers(
            paper_id="pD18",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),  # correct
                ExtractedAnswer(question_id="2", answer="B", confidence=0.9),  # wrong
                ExtractedAnswer(question_id="3", answer="A", confidence=0.9),  # correct
            ],
        )
        extracted_subset = ExtractedAnswers(
            paper_id="pD18",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),  # correct
            ],
        )

        with patch("lemely.web.services.grading.extract_answers", return_value=extracted_full):
            result_a = measure_accuracy([make_case()], gemini_client=None, settings=None)
        with patch("lemely.web.services.grading.extract_answers", return_value=extracted_subset):
            result_b = measure_accuracy([make_case()], gemini_client=None, settings=None)

        self.assertLessEqual(result_b.metrics.mark_accuracy, result_a.metrics.mark_accuracy)

    def test_unmatched_question_id_stays_in_denominator(self):
        """A leaf the extractor never returned an answer for must produce an
        EvalRecord (outcome='unmatched', id_match='unmatched',
        predicted_marks=None) and must stay in the mark_accuracy denominator
        — never silently dropped (D18, spec §3.3 outcome table)."""
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        case = GoldenCase(
            paper_id="pUnmatched",
            mark_scheme=self._mark_scheme(["1", "2", "3"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
                "3": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=Path("/nonexistent/scanUnmatched.pdf"),
        )
        fake_extracted = ExtractedAnswers(
            paper_id="pUnmatched",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="A", confidence=0.9),
                # "3" never returned by extraction.
            ],
        )

        with patch("lemely.web.services.grading.extract_answers", return_value=fake_extracted):
            result = measure_accuracy([case], gemini_client=None, settings=None)

        records_by_qid = {r.question_id: r for r in result.eval_records}
        self.assertIn("3", records_by_qid)
        rec3 = records_by_qid["3"]
        self.assertEqual(rec3.outcome, "unmatched")
        self.assertEqual(rec3.id_match, "unmatched")
        self.assertIsNone(rec3.predicted_marks)

        # Denominator includes all three leaves; "3" counts as not-correct.
        self.assertEqual(len(result.eval_records), 3)
        self.assertAlmostEqual(result.metrics.mark_accuracy, 2 / 3)

    def test_never_attempted_leaf_is_excluded_not_unmatched(self):
        """A ground-truth leaf with no corresponding correct_paper output at
        all (not a marked leaf in the mark scheme) is recorded
        outcome='excluded' and is absent from the scored denominator —
        distinct from 'unmatched', which is an attempted-but-not-returned
        leaf (spec §3.3 outcome table)."""
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy
        from lemely.eval.analyses import exclusion_funnel

        case = GoldenCase(
            paper_id="pExcluded",
            mark_scheme=self._mark_scheme(["1"]),  # mark scheme has only leaf "1"
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "99": GoldenAnswer(student_answer="A", awarded_marks=1),  # not a scheme leaf
            },
            scan_path=None,
        )

        result = measure_accuracy([case], gemini_client=None, settings=None)

        records_by_qid = {r.question_id: r for r in result.eval_records}
        self.assertIn("99", records_by_qid)
        self.assertEqual(records_by_qid["99"].outcome, "excluded")
        self.assertNotEqual(records_by_qid["1"].outcome, "excluded")

        funnel = exclusion_funnel(result.eval_records)
        self.assertEqual(funnel["excluded"], 1)
        self.assertEqual(funnel["scored"], 1)

        # D18/Blocker 1: the excluded leaf "99" must not enter the
        # mark_accuracy denominator or be scored as wrong. Only the one
        # attempted+correct leaf "1" is scored, so mark_accuracy is 1.0 —
        # not 0.5, which is what you get if the excluded row is counted as
        # a wrong answer alongside the correct one.
        self.assertEqual(result.metrics.mark_accuracy, 1.0)

        # The excluded row must also not collapse flag_recall: flag_recall
        # is computed over `wrong` records, and if "99" (excluded, treated
        # as id_match="unmatched", not flagged for review) were counted as
        # wrong, flag_recall would be 0/1 = 0.0 instead of the excluded-free
        # baseline of 1.0 (no wrong records at all -> vacuous 1.0).
        self.assertEqual(result.metrics.flag_recall, 1.0)

    def test_printed_funnel_chain_never_rises(self):
        """The printed exclusion funnel must be monotonically non-increasing.

        A funnel that rises mid-chain reads as a denominator *growing*, which
        is the opposite of what an exclusion funnel documents and exactly the
        confusion M0.5 exists to remove. `extracted` is deliberately NOT a
        stage of the chain: it counts leaves the extractor returned an id
        for, while `matched` counts leaves `correct_paper` produced a
        CorrectedQuestion for — neither implies the other, so putting them in
        sequence could print `extracted=2 -> matched=3`.
        """
        import itertools
        import re

        from lemely.accuracy.harness import (
            GoldenAnswer,
            GoldenCase,
            format_report,
            measure_accuracy,
        )

        # Leaf "99" is a ground-truth leaf with no corresponding mark-scheme
        # leaf, so `correct_paper` produces no CorrectedQuestion for it and it
        # is recorded `excluded`. This fixture yields
        # FunnelCounts(leaves=3, extracted=3, matched=2, marked=2) — note
        # extracted > matched here, because `scan_path=None` is oracle mode and
        # harness.py sets `extracted_ids = set(case.ground_truth)`.
        #
        # So this fixture does NOT reproduce the extracted < matched case that
        # motivated removing `extracted` from the chain; that needs a
        # scan_path-backed run where extraction genuinely misses an id. The
        # assertions below are therefore deliberately structural (exact stage
        # list, `extracted` absent from the chain) rather than relying on this
        # fixture to produce a rise — an earlier monotonicity-only version of
        # this test passed against the un-fixed code for exactly that reason.
        case = GoldenCase(
            paper_id="pFunnel",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
                "99": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=None,
        )

        from lemely.runtime.config import Settings

        report = format_report(
            measure_accuracy([case], gemini_client=None, settings=None),
            Settings().accuracy_eval,
        )

        chain_line = next(line for line in report.splitlines() if "Exclusion funnel:" in line)

        # `extracted` must not appear in the chain at all. This is the
        # load-bearing assertion: it is the only one that fails
        # deterministically if `extracted` is put back between `leaves` and
        # `matched`, regardless of whether this particular fixture happens
        # to produce extracted < matched.
        self.assertNotIn(
            "extracted", chain_line, f"`extracted` is not a funnel stage: {chain_line!r}"
        )
        self.assertEqual(
            [n for n, _ in re.findall(r"(\w+)=(\d+)", chain_line)],
            ["leaves", "matched", "marked", "scored"],
            f"unexpected funnel stages in {chain_line!r}",
        )

        stages = [int(n) for n in re.findall(r"=(\d+)", chain_line)]
        for earlier, later in itertools.pairwise(stages):
            self.assertGreaterEqual(
                earlier, later, f"funnel chain rises: {chain_line!r} -> {stages}"
            )

        # …and it is still reported, just not as a stage.
        self.assertIn("extracted=", report)

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

    def test_leaf_key_sets_identical_between_arms_over_golden_corpus(self):
        """#28/M0.4: the set of (paper_id, question_id) leaves the harness
        iterates over must be identical between arms — a structural property
        of the harness's leaf loop (it always iterates ``case.ground_truth``,
        regardless of ``case_arm``), independent of what extraction/marking
        actually return. Both extraction and marking are mocked so no live
        Gemini calls are ever made, and to sidestep correct_paper's
        ConfigError for non-MCQ leaves when gemini_client=None.
        """
        from lemely.accuracy.harness import load_golden_cases, measure_accuracy
        from lemely.core.schemas import CorrectionResult, ExamMetadata, ExtractedAnswers

        golden_dir = Path(__file__).resolve().parent / "golden"
        cases = load_golden_cases(golden_dir)
        self.assertGreater(len(cases), 0)

        def _fake_correct_paper(mark_scheme, extracted_answers, *, gemini_client=None, **kwargs):
            md = mark_scheme.metadata
            return CorrectionResult(
                metadata=ExamMetadata(
                    subject_code=md.subject_code,
                    paper_number=md.paper_number,
                    paper_variant=md.paper_variant,
                    session_month=md.session_month,
                    session_year=md.session_year,
                ),
                questions=[],
            )

        def _fake_extract_answers(scan_path, mark_scheme, *, gemini_client=None):
            return ExtractedAnswers(paper_id="fake", source_scan="fake", answers=[])

        with (
            patch("lemely.io.correction_ai.correct_paper", side_effect=_fake_correct_paper),
            patch(
                "lemely.web.services.grading.extract_answers",
                side_effect=_fake_extract_answers,
            ),
        ):
            oracle_result = measure_accuracy(
                cases, gemini_client=None, settings=None, arm="oracle+mark"
            )
            extract_result = measure_accuracy(
                cases, gemini_client=None, settings=None, arm="extract+mark"
            )

        oracle_keys = {(r.paper_id, r.question_id) for r in oracle_result.eval_records}
        extract_keys = {(r.paper_id, r.question_id) for r in extract_result.eval_records}
        self.assertTrue(oracle_keys)
        self.assertEqual(oracle_keys, extract_keys)


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

    def test_extraction_conf_propagates_from_question_result(self) -> None:
        """question_result_to_eval_record must not hardcode extraction_conf=None (#36/M1.1)."""
        from lemely.accuracy.harness import QuestionResult, question_result_to_eval_record

        result = QuestionResult(
            question_id="1",
            question_type="mcq",
            predicted_marks=1,
            truth_marks=1,
            confidence_score=0.95,
            needs_teacher_review=False,
            extraction_confidence=0.77,
        )
        record = question_result_to_eval_record(
            result, run_id="test-run", paper_id="paper-1", arm="extract+mark"
        )
        self.assertEqual(record.extraction_conf, 0.77)

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


class RunManifestTests(unittest.TestCase):
    """M0.1/#25: run_id is the join key between EvalRecord rows and a
    RunManifest (spec §3.3); it must not be a hardcoded literal."""

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

    def _case(self) -> object:
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase

        return GoldenCase(
            paper_id="p1",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )

    def test_default_run_id_varies_between_runs(self):
        from lemely.accuracy.harness import measure_accuracy

        r1 = measure_accuracy([self._case()], gemini_client=None, settings=None)
        r2 = measure_accuracy([self._case()], gemini_client=None, settings=None)
        self.assertNotEqual(r1.manifest.run_id, r2.manifest.run_id)

    def test_explicit_run_id_propagates_to_manifest_and_eval_records(self):
        from lemely.accuracy.harness import measure_accuracy

        result = measure_accuracy(
            [self._case()], gemini_client=None, settings=None, run_id="run-explicit-1"
        )
        self.assertEqual(result.manifest.run_id, "run-explicit-1")
        self.assertTrue(result.eval_records)
        self.assertTrue(all(r.run_id == "run-explicit-1" for r in result.eval_records))

    def test_measure_accuracy_populates_eval_records(self):
        """AccuracyResult.eval_records must expose the records already built
        inside measure_accuracy (#72): before this fix they fell out of scope
        and were unobservable outside the function."""
        from lemely.accuracy.harness import measure_accuracy
        from lemely.eval.records import EvalRecord

        result = measure_accuracy([self._case()], gemini_client=None, settings=None)

        self.assertIsInstance(result.eval_records, list)
        self.assertTrue(result.eval_records)
        for record in result.eval_records:
            self.assertIsInstance(record, EvalRecord)
        self.assertEqual(len(result.eval_records), len(result.question_results))

    def _settings_with_models(self, **models):
        """Minimal stand-in for Settings.gemini with controllable per-task models."""
        from types import SimpleNamespace

        defaults = {"mark_scheme": "m-a", "extraction": "m-a", "correction": "m-a"}
        defaults.update(models)
        gemini = SimpleNamespace(
            temperature=0.0,
            top_p=1.0,
            seed=7,
            thinking_budget_for={"extraction": 100},
            model_for=lambda task: defaults[task],
        )
        return SimpleNamespace(gemini=gemini)

    def test_params_fingerprint_distinguishes_different_models(self):
        """Two runs on different models must NOT share a params_fingerprint.

        Regression test for the false-zero-delta trap: the fingerprint omitted
        the model entirely, so an A/B across models recorded identical
        parameters and M0.3 would read the difference as noise from the
        instrument rather than a real change (spec §3.3).
        """
        from lemely.accuracy.harness import measure_accuracy

        a = measure_accuracy(
            [self._case()], gemini_client=None, settings=self._settings_with_models()
        )
        b = measure_accuracy(
            [self._case()],
            gemini_client=None,
            settings=self._settings_with_models(extraction="m-DIFFERENT"),
        )
        self.assertNotEqual(
            a.manifest.params_fingerprint,
            b.manifest.params_fingerprint,
            "a different extraction model must change the run's params_fingerprint",
        )

    def test_params_fingerprint_is_stable_for_identical_settings(self):
        """The fingerprint must be deterministic, or every run looks like a change."""
        from lemely.accuracy.harness import measure_accuracy

        a = measure_accuracy(
            [self._case()], gemini_client=None, settings=self._settings_with_models()
        )
        b = measure_accuracy(
            [self._case()], gemini_client=None, settings=self._settings_with_models()
        )
        self.assertEqual(a.manifest.params_fingerprint, b.manifest.params_fingerprint)

    def test_params_fingerprint_covers_max_output_tokens(self):
        """``_MAX_OUTPUT_TOKENS`` is part of the hashed input, as it is canonically."""
        import lemely.accuracy.harness as harness_mod
        from lemely.accuracy.harness import measure_accuracy

        settings = self._settings_with_models()
        before = measure_accuracy(
            [self._case()], gemini_client=None, settings=settings
        ).manifest.params_fingerprint

        original = harness_mod._MAX_OUTPUT_TOKENS
        try:
            harness_mod._MAX_OUTPUT_TOKENS = original + 1
            after = measure_accuracy(
                [self._case()], gemini_client=None, settings=settings
            ).manifest.params_fingerprint
        finally:
            harness_mod._MAX_OUTPUT_TOKENS = original

        self.assertNotEqual(before, after)

    def test_params_fingerprint_distinguishes_arms(self):
        """The two arms of an M0.4 ablation sweep (#28) must archive
        distinguishable manifests. Before this fix ``arm`` was not part of
        ``fingerprint_raw`` at all, so ``oracle+mark`` and ``extract+mark``
        runs -- identical in every other knob -- hashed to the same
        ``params_fingerprint``, and the pair of archived runs #28 exists to
        produce would be indistinguishable evidence the moment M0.3's
        cross-run comparator reads them.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings = self._settings_with_models()
        oracle = _build_run_manifest(
            "run-oracle",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
            arm="oracle+mark",
        )
        extract = _build_run_manifest(
            "run-extract",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
            arm="extract+mark",
        )
        self.assertNotEqual(
            oracle.params_fingerprint,
            extract.params_fingerprint,
            "the arm override must change the run's params_fingerprint",
        )

    def test_params_fingerprint_for_no_arm_override_is_unchanged(self):
        """``arm=None`` (today's default -- no override, per-case selection by
        ``scan_path``) must reproduce the exact pre-change fingerprint for
        otherwise-identical inputs. Pinned as a literal (not re-derived by
        calling ``_build_run_manifest`` again) so a future change to the hash
        inputs is caught by this test rather than silently accepted.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings = self._settings_with_models()
        manifest = _build_run_manifest(
            "run-x",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        self.assertEqual(manifest.params_fingerprint, "e81756064e0f")

    def test_manifest_is_a_run_manifest_instance(self):
        from lemely.accuracy.harness import measure_accuracy
        from lemely.eval.manifest import RunManifest

        result = measure_accuracy([self._case()], gemini_client=None, settings=None)
        self.assertIsInstance(result.manifest, RunManifest)
        self.assertEqual(result.manifest.split, "dev")
        self.assertEqual(
            result.manifest.prompt_versions.keys(), {"extraction", "correction", "mark_scheme"}
        )

    def _bypass_gemini_client(self, tmp: str):
        """A real GeminiClient instantiated with a non-default cache mode.

        The genai SDK client is mocked out (``_genai_client``) so no network
        call can happen; the point under test is purely that the client's own
        configured default cache mode — not the literal "read_write" — is
        what ends up in the manifest.
        """
        from unittest.mock import MagicMock

        from lemely.io.gemini import GeminiClient
        from lemely.runtime.config import PathsSettings, load_settings

        with patch.dict(os.environ, {}, clear=False):
            for k in [k for k in os.environ if k.startswith("LEMELY_")]:
                del os.environ[k]
            settings = load_settings(toml_path=None, cwd=Path(tmp))
        settings = settings.model_copy(
            update={
                "paths": PathsSettings(
                    cache_dir=Path(tmp) / ".cache",
                    output_dir=Path(tmp) / "outputs",
                )
            }
        )
        return GeminiClient(
            settings,
            _genai_client=MagicMock(),
            default_cache_mode="bypass",
        )

    def test_manifest_cache_mode_reads_client_bypass_default(self):
        """manifest.cache_mode must reflect the client's configured default,
        not the harness's own hardcoded "read_write" literal (#73)."""
        from lemely.accuracy.harness import measure_accuracy

        with tempfile.TemporaryDirectory() as tmp:
            client = self._bypass_gemini_client(tmp)
            result = measure_accuracy([self._case()], gemini_client=client, settings=None)

        self.assertEqual(result.manifest.cache_mode, "bypass")

    def test_authorised_test_split_records_split_test(self):
        """An authorised split="test" run must record manifest.split == "test",
        and must append EXACTLY ONE entry to the test-touch ledger (#73).

        The ledger is pointed at a tmp path, never the real
        ``reports/accuracy/test-touch-ledger.jsonl``: this test does not touch
        the test split in any meaningful sense, and letting it append to the
        real M0.7a audit artefact on every unit-test run would forge audit
        history — the artefact would record test-split touches that never
        happened. The exactly-one assertion also pins the fix for the
        double-gating bug: authorising in both ``measure_accuracy`` and
        ``_build_run_manifest`` would write two entries for one run.
        """
        from lemely.accuracy.harness import measure_accuracy

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "test-touch-ledger.jsonl"
            with patch.dict(os.environ, {"LEMELY_TEST_SPLIT_TOKEN": "shh-secret"}):
                result = measure_accuracy(
                    [self._case()],
                    gemini_client=None,
                    settings=None,
                    split="test",
                    test_split_token="shh-secret",
                    ledger_path=ledger,
                )

            self.assertEqual(result.manifest.split, "test")
            entries = ledger.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(entries), 1, f"expected exactly one ledger entry, got {entries}")

    def test_unauthorised_test_split_raises_before_reading_or_spending(self):
        """No/wrong token for split="test" must raise TestSplitAccessError, not
        silently record "dev" or "test" (#73).

        Crucially it must raise BEFORE the corpus is read or a single Gemini
        call is made. The gate originally lived in ``_build_run_manifest``,
        which runs only in ``measure_accuracy``'s final ``return`` — so an
        unauthorised test-split run read the whole split and spent real budget
        before being refused, which defeats the entire point of M0.7a. The
        spy below is what pins the ordering; without it this test passes even
        with the gate at the very end.
        """
        from lemely.accuracy.harness import measure_accuracy
        from lemely.eval.test_touch import TestSplitAccessError

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEMELY_TEST_SPLIT_TOKEN", None)
            with patch("lemely.io.correction_ai.correct_paper") as correct_spy:
                with self.assertRaises(TestSplitAccessError):
                    measure_accuracy(
                        [self._case()],
                        gemini_client=None,
                        settings=None,
                        split="test",
                        test_split_token=None,
                    )
                correct_spy.assert_not_called()


class SaveResultRoundTripTests(unittest.TestCase):
    """#72: save_result must persist manifest and eval_records, not just the
    legacy metrics/calibration/question_results keys -- both were computed
    inside measure_accuracy but discarded before this fix, making the
    run_id -> RunManifest join unobservable outside the function."""

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

    def _case(self) -> object:
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase

        return GoldenCase(
            paper_id="p1",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )

    def test_save_result_round_trips_manifest_and_eval_records(self):
        from lemely.accuracy.harness import measure_accuracy, save_result
        from lemely.eval.analyses import review_rate
        from lemely.eval.manifest import RunManifest
        from lemely.eval.records import EvalRecord

        result = measure_accuracy(
            [self._case()], gemini_client=None, settings=None, run_id="run-round-trip-1"
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_path = save_result(result, Path(tmp))
            data = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertIn("manifest", data)
        self.assertIn("eval_records", data)

        manifest = RunManifest.model_validate(data["manifest"])
        self.assertEqual(manifest, result.manifest)

        records = [EvalRecord.model_validate(r) for r in data["eval_records"]]
        self.assertEqual(records, result.eval_records)
        self.assertTrue(all(r.run_id == "run-round-trip-1" for r in records))

        # Point the instrument at something real: a pure analysis over the
        # records reconstructed from disk, not the in-memory objects.
        #
        # The assertions below are deliberately exact rather than bounds.
        # ``0.0 <= review_rate_total <= 1.0`` holds *by construction* and
        # passes on an EMPTY record list — as does ``all(...)`` above — so a
        # regression that made ``save_result`` write ``"eval_records": []``
        # would sail straight through a bounds check while destroying the very
        # thing #72 exists to deliver. Pinning ``n`` to the record count is
        # what makes this test fail if the records stop arriving.
        self.assertTrue(records, "eval_records round-tripped empty — #72's whole point")
        rate = review_rate(records)
        self.assertEqual(rate["n"], len(records))
        self.assertEqual(rate["review_rate_total"], 0.0)
        self.assertEqual(rate["review_rate_signal"], 0.0)


class CoherenceTriggerWiringTests(unittest.TestCase):
    """M1.5 (#40) SHOULD-FIX: the correction_ai -> harness coherence-trigger
    wiring is stringly-typed (``_review_triggers`` substring-matches every
    ``_check_coherence`` review_reason against
    ``lemely.io.correction_ai.COHERENCE_TRIGGER_MARKER``). A reworded message
    on one side without updating the other would make
    ``coherence_trigger_rate`` silently read 0.0 with every unit test still
    green, because the two sides were never exercised together end to end.
    This test drives the REAL production message through
    ``_build_ai_corrected`` -> ``QuestionResult`` -> ``_review_triggers`` (via
    ``question_result_to_eval_record``), rather than hand-typing a literal
    review_reason string, so it fails if either side of the wiring drifts.
    """

    def test_real_coherence_review_reason_produces_coherence_mismatch_trigger(self) -> None:
        from lemely.accuracy.harness import QuestionResult, question_result_to_eval_record
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType
        from lemely.core.schemas import AIMarkResponse
        from lemely.io.correction_ai import _build_ai_corrected

        question = Question.model_construct(
            id="2",
            marks=2,
            type=QuestionType.EXPLANATION,
            answer_points=[
                AnswerPoint(id="p1", point="method", marks=1),
                AnswerPoint(id="p2", point="final answer", marks=1),
            ],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )
        mark = AIMarkResponse(
            awarded_marks=2,
            confidence=1.0,
            matched_point_ids=["p1"],  # implies [1, 1]; awarded_marks=2 is outside it.
            feedback="test",
        )
        cq = _build_ai_corrected(question, "answer", mark)
        self.assertTrue(cq.needs_teacher_review)  # sanity: the gate actually fired

        result = QuestionResult(
            question_id="2",
            question_type="theory",
            predicted_marks=cq.awarded_marks,
            truth_marks=1,
            confidence_score=mark.confidence,
            needs_teacher_review=cq.needs_teacher_review,
            review_reason=cq.review_reason,
        )
        record = question_result_to_eval_record(
            result, run_id="wiring-test", paper_id="p1", arm="extract+mark"
        )
        self.assertIn("coherence_mismatch", record.triggers)
        self.assertIn("needs_teacher_review", record.triggers)

    def test_review_reason_without_the_marker_does_not_fire_coherence_trigger(self) -> None:
        """Negative control: a review reason from a DIFFERENT gate (e.g. low
        confidence) must not spuriously carry the coherence trigger."""
        from lemely.accuracy.harness import QuestionResult, question_result_to_eval_record

        result = QuestionResult(
            question_id="1",
            question_type="theory",
            predicted_marks=1,
            truth_marks=1,
            confidence_score=0.5,
            needs_teacher_review=True,
            review_reason="confidence 0.50 is below review threshold 0.90",
        )
        record = question_result_to_eval_record(
            result, run_id="wiring-test", paper_id="p1", arm="extract+mark"
        )
        self.assertNotIn("coherence_mismatch", record.triggers)
        self.assertIn("needs_teacher_review", record.triggers)
