"""Unit tests for mark scheme structural validation."""

from __future__ import annotations

import unittest

from lemely.core.loose_schemas import MarkScheme


def _ms(questions: list[dict], total_marks: int | None = None) -> MarkScheme:
    tm = total_marks if total_marks is not None else sum(q.get("marks", 0) for q in questions)
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 4,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_extended",
                "maximum_mark": tm,
                "scheme_format": "point_based",
            },
            "questions": questions,
        }
    )


class ValidationTests(unittest.TestCase):
    def test_valid_mcq_no_warnings(self):
        from lemely.io.validation import validate_mark_scheme

        ms = _ms([{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}])
        self.assertEqual(validate_mark_scheme(ms), [])

    def test_theory_with_answer_points_no_warnings(self):
        from lemely.io.validation import validate_mark_scheme

        ms = _ms(
            [
                {
                    "id": "1",
                    "marks": 2,
                    "type": "explanation",
                    "answer_points": [
                        {"id": "p1", "point": "gravity acts", "marks": 1},
                        {"id": "p2", "point": "no friction", "marks": 1},
                    ],
                }
            ]
        )
        self.assertEqual(validate_mark_scheme(ms), [])

    def test_theory_leaf_with_no_mark_points_warns(self):
        from lemely.io.validation import validate_mark_scheme

        ms = _ms([{"id": "1", "marks": 2, "type": "explanation"}])
        warnings = validate_mark_scheme(ms)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].question_id, "1")
        self.assertIn("mark point", warnings[0].message)

    def test_mcq_with_no_answer_warns(self):
        # Bypass schema validator with model_construct to test the validation logic.
        from lemely.core.loose_schemas import Question, QuestionType
        from lemely.io.validation import ValidationWarning, _check_leaf_question

        q = Question.model_construct(
            id="5",
            marks=1,
            type=QuestionType.MCQ,
            mcq_answer=None,
            answer_points=[],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )
        warnings: list[ValidationWarning] = []
        _check_leaf_question(q, warnings)
        self.assertEqual(len(warnings), 1)
        self.assertIn("MCQ", warnings[0].message)

    def test_container_question_skipped(self):
        from lemely.io.validation import validate_mark_scheme

        ms = _ms(
            [
                {
                    "id": "1",
                    "marks": 0,
                    "type": "explanation",
                    "parts": [
                        {
                            "id": "1(a)",
                            "marks": 2,
                            "type": "explanation",
                            "parent_id": "1",
                            "answer_points": [
                                {"id": "p1", "point": "gravity", "marks": 1},
                                {"id": "p2", "point": "speed", "marks": 1},
                            ],
                        }
                    ],
                }
            ],
            total_marks=2,
        )
        self.assertEqual(validate_mark_scheme(ms), [])
