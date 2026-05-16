import unittest

from lemely_mvp.analytics import generate_quiz, predict_grade, summarize_weaknesses
from lemely_mvp.correction import correct_mcq_answers, parse_answer_input
from lemely_mvp.schemas import ConfidenceBand


def minimal_mcq_mark_scheme():
    return {
        "metadata": {
            "subject": "Physics",
            "subject_code": "0625",
            "paper_number": 1,
            "paper_variant": 2,
            "session_month": "Oct/Nov",
            "session_year": 2022,
            "paper_type": "mcq",
            "tier": None,
            "maximum_mark": 3,
            "scheme_format": "mcq",
            "assessment_objectives": [],
            "subject_specific_principles": [],
            "published": True,
            "source_document": "0625_w22_ms_12.pdf",
        },
        "abbreviation_legend": {},
        "questions": [
            {
                "id": "1",
                "marks": 1,
                "type": "mcq",
                "mcq_answer": "A",
                "topic_hint": "forces",
            },
            {
                "id": "2",
                "marks": 1,
                "type": "mcq",
                "mcq_answer": "C",
                "topic_hint": "electricity",
            },
            {
                "id": "3",
                "marks": 1,
                "type": "mcq",
                "mcq_answer": "D",
                "topic_hint": "electricity",
            },
        ],
    }


class CorrectionTests(unittest.TestCase):
    def test_parse_answer_input_accepts_text_and_json(self):
        self.assertEqual(parse_answer_input("1 A\n2: b"), {"1": "A", "2": "B"})
        self.assertEqual(parse_answer_input('{"1": "a", "2": "C"}'), {"1": "A", "2": "C"})

    def test_deterministic_mcq_correction_with_confidence(self):
        result = correct_mcq_answers(minimal_mcq_mark_scheme(), "1 A\n2 B\n3 D")

        self.assertEqual(result.awarded_marks, 2)
        self.assertEqual(result.maximum_marks, 3)
        self.assertEqual([q.awarded_marks for q in result.questions], [1, 0, 1])
        self.assertTrue(all(q.confidence == ConfidenceBand.HIGH for q in result.questions))

    def test_missing_answers_are_flagged_for_teacher_review(self):
        result = correct_mcq_answers(minimal_mcq_mark_scheme(), {"1": "A"})
        question_2 = next(q for q in result.questions if q.question_id == "2")

        self.assertTrue(question_2.needs_teacher_review)
        self.assertEqual(question_2.confidence, ConfidenceBand.LOW)
        self.assertIn("missing", question_2.review_reason)

    def test_invalid_text_answers_are_reviewed_without_aborting_correction(self):
        result = correct_mcq_answers(minimal_mcq_mark_scheme(), "1 E\n2 C\n3 D")
        question_1 = next(q for q in result.questions if q.question_id == "1")

        self.assertTrue(question_1.needs_teacher_review)
        self.assertEqual(question_1.confidence, ConfidenceBand.LOW)
        self.assertEqual(result.awarded_marks, 2)

    def test_topic_accuracy_counts_correct_and_lost_marks(self):
        correction = correct_mcq_answers(minimal_mcq_mark_scheme(), {"1": "A", "2": "B", "3": "D"})

        weaknesses = summarize_weaknesses(correction)
        electricity = next(area for area in weaknesses.weak_areas if area.topic == "electricity")

        self.assertEqual(electricity.maximum_marks, 2)
        self.assertEqual(electricity.lost_marks, 1)
        self.assertEqual(electricity.accuracy, 0.5)

    def test_custom_grade_boundaries_are_sorted_by_threshold(self):
        correction = correct_mcq_answers(minimal_mcq_mark_scheme(), {"1": "A", "2": "C", "3": "D"})

        prediction = predict_grade(correction, boundaries={"C": 60.0, "A": 80.0})

        self.assertEqual(prediction.grade, "A")

    def test_weakness_grade_and_quiz_generation_are_deterministic(self):
        correction = correct_mcq_answers(minimal_mcq_mark_scheme(), {"1": "A", "2": "B"})

        weaknesses = summarize_weaknesses(correction)
        prediction = predict_grade(correction)
        quiz = generate_quiz(weaknesses, question_count=2)

        self.assertEqual(weaknesses.weak_areas[0].topic, "electricity")
        self.assertEqual(prediction.grade, "U")
        self.assertEqual([q.topic for q in quiz.questions], ["electricity"])


if __name__ == "__main__":
    unittest.main()
