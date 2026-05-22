import unittest

from pydantic import ValidationError

from lemely.core.schemas import (
    AIMarkResponse,
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    ExtractedAnswer,
    ExtractedAnswers,
    SubjectResult,
    WeaknessReport,
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


class ExtractedAnswerTests(unittest.TestCase):
    def test_valid_extracted_answer(self) -> None:
        ea = ExtractedAnswer(question_id="1(a)(i)", answer="42 m/s", confidence=0.95)
        self.assertEqual(ea.question_id, "1(a)(i)")
        self.assertEqual(ea.answer, "42 m/s")
        self.assertIsNone(ea.source_region)

    def test_confidence_out_of_range_raises(self) -> None:
        with self.assertRaises(ValidationError):
            ExtractedAnswer(question_id="1", answer="A", confidence=1.5)

    def test_extracted_answers_round_trip(self) -> None:
        ea = ExtractedAnswers(
            paper_id="0625_MayJune_2020_p12",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="B", confidence=0.9),
                ExtractedAnswer(question_id="2(a)", answer="osmosis", confidence=0.8),
            ],
        )
        restored = ExtractedAnswers.model_validate(ea.model_dump(mode="json"))
        self.assertEqual(restored.paper_id, ea.paper_id)
        self.assertEqual(len(restored.answers), 2)


class AIMarkResponseTests(unittest.TestCase):
    def test_valid_response(self) -> None:
        r = AIMarkResponse(awarded_marks=2, confidence=0.85, matched_point_ids=["p1"], feedback="ok")
        self.assertEqual(r.awarded_marks, 2)

    def test_negative_marks_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AIMarkResponse(awarded_marks=-1, confidence=0.5, matched_point_ids=[], feedback="")


class CorrectedQuestionMarkerSourceTests(unittest.TestCase):
    def test_default_marker_source_is_deterministic(self) -> None:
        cq = CorrectedQuestion(
            question_id="1", awarded_marks=1, maximum_marks=1,
            confidence=ConfidenceBand.HIGH, confidence_score=1.0,
            needs_teacher_review=False,
        )
        self.assertEqual(cq.marker_source, "deterministic")
        self.assertIsNone(cq.feedback)
        self.assertEqual(cq.matched_point_ids, [])

    def test_ai_marked_question_accepts_feedback(self) -> None:
        cq = CorrectedQuestion(
            question_id="1", awarded_marks=2, maximum_marks=3,
            confidence=ConfidenceBand.MEDIUM, confidence_score=0.8,
            needs_teacher_review=False, marker_source="ai",
            feedback="Missed point p3.", matched_point_ids=["p1", "p2"],
        )
        self.assertEqual(cq.marker_source, "ai")
        self.assertEqual(cq.feedback, "Missed point p3.")


class SubjectResultTests(unittest.TestCase):
    def _paper(self, awarded: int, maximum: int) -> CorrectionResult:
        return CorrectionResult(
            metadata=ExamMetadata(
                subject_code="0625", paper_number=2, paper_variant=1,
                session_month="May/June", session_year=2020,
            ),
            questions=[
                CorrectedQuestion(
                    question_id="q1",
                    awarded_marks=awarded, maximum_marks=maximum,
                    confidence=ConfidenceBand.HIGH, confidence_score=1.0,
                    needs_teacher_review=False,
                )
            ],
        )

    def test_subject_result_sums_marks(self) -> None:
        sr = SubjectResult(
            subject_code="0625", session_month="May/June", session_year=2020,
            paper_results=[self._paper(30, 40), self._paper(60, 80), self._paper(35, 40)],
            weaknesses=WeaknessReport(weak_areas=[]),
        )
        self.assertEqual(sr.awarded_marks, 125)
        self.assertEqual(sr.maximum_marks, 160)
        self.assertAlmostEqual(sr.percentage, 78.125, places=2)
        self.assertEqual(sr.grade, "B")  # 78% with default boundaries A=80, B=70

    def test_subject_result_rejects_mismatched_subject(self) -> None:
        p1 = self._paper(10, 10)
        p2_meta = ExamMetadata(
            subject_code="0972", paper_number=2, paper_variant=1,
            session_month="May/June", session_year=2020,
        )
        p2 = CorrectionResult(metadata=p2_meta, questions=p1.questions)
        with self.assertRaises(ValidationError):
            SubjectResult(
                subject_code="0625", session_month="May/June", session_year=2020,
                paper_results=[p1, p2],
                weaknesses=WeaknessReport(weak_areas=[]),
            )


if __name__ == "__main__":
    unittest.main()
