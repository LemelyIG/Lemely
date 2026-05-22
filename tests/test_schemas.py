import unittest

from pydantic import ValidationError

from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    confidence_band_for_score,
)


class SchemaTests(unittest.TestCase):
    def test_public_outputs_reject_extra_fields(self):
        with self.assertRaises(ValidationError):
            ExamMetadata(
                subject_code="0625",
                paper_number=1,
                paper_variant=2,
                session_month="Oct/Nov",
                session_year=2022,
                source_document="0625_w22_ms_12.pdf",
                unexpected=True,
            )

    def test_exam_metadata_rejects_unknown_sessions(self):
        with self.assertRaises(ValidationError):
            ExamMetadata(
                subject_code="0625",
                paper_number=1,
                paper_variant=2,
                session_month="Winter",
                session_year=2022,
            )

    def test_confidence_rating_thresholds_are_conservative(self):
        self.assertEqual(confidence_band_for_score(0.95), ConfidenceBand.HIGH)
        self.assertEqual(confidence_band_for_score(0.80), ConfidenceBand.MEDIUM)
        self.assertEqual(confidence_band_for_score(0.50), ConfidenceBand.LOW)

    def test_correction_result_calculates_totals(self):
        result = CorrectionResult(
            metadata=ExamMetadata(
                subject_code="0625",
                paper_number=1,
                paper_variant=2,
                session_month="Oct/Nov",
                session_year=2022,
                source_document="0625_w22_ms_12.pdf",
            ),
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
                ),
                CorrectedQuestion(
                    question_id="2",
                    awarded_marks=0,
                    maximum_marks=1,
                    confidence=ConfidenceBand.LOW,
                    confidence_score=0.0,
                    needs_teacher_review=True,
                    student_answer=None,
                    expected_answer="C",
                    review_reason="missing answer",
                ),
            ],
        )

        self.assertEqual(result.awarded_marks, 1)
        self.assertEqual(result.maximum_marks, 2)
        self.assertTrue(result.needs_teacher_review)

    def test_schema_json_export_for_public_models_forbids_extra(self):
        schema = AccuracyReport.model_json_schema()

        self.assertEqual(schema["additionalProperties"], False)
        self.assertIn("properties", schema)


if __name__ == "__main__":
    unittest.main()
