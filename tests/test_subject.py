"""Tests for lemely.io.subject.aggregate_subject."""

from __future__ import annotations

import unittest

from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    SubjectResult,
)
from lemely.io.subject import aggregate_subject
from lemely.runtime.errors import UsageError


def _paper(paper_number: int, awarded: int, maximum: int, topic: str = "kinematics") -> CorrectionResult:
    return CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=paper_number,
            paper_variant=1,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[
            CorrectedQuestion(
                question_id=f"p{paper_number}_q1",
                awarded_marks=awarded,
                maximum_marks=maximum,
                confidence=ConfidenceBand.HIGH,
                confidence_score=1.0,
                needs_teacher_review=False,
                topic=topic,
            )
        ],
    )


class AggregateSubjectTests(unittest.TestCase):
    def test_aggregate_three_papers_into_subject_result(self) -> None:
        p2 = _paper(2, 30, 40)
        p4 = _paper(4, 56, 80)
        p6 = _paper(6, 30, 40)
        result = aggregate_subject([p2, p4, p6])
        self.assertIsInstance(result, SubjectResult)
        self.assertEqual(result.subject_code, "0625")
        self.assertEqual(result.awarded_marks, 116)
        self.assertEqual(result.maximum_marks, 160)
        self.assertAlmostEqual(result.percentage, 72.5, places=1)
        self.assertEqual(result.grade, "B")

    def test_mismatched_subject_raises_usage_error(self) -> None:
        p1 = _paper(2, 10, 10)
        p2_meta = ExamMetadata(
            subject_code="9701", paper_number=2, paper_variant=1,
            session_month="May/June", session_year=2020,
        )
        p2 = CorrectionResult(metadata=p2_meta, questions=p1.questions)
        with self.assertRaises(UsageError):
            aggregate_subject([p1, p2])

    def test_weaknesses_aggregated_across_papers(self) -> None:
        p2 = _paper(2, 0, 10, topic="dynamics")
        p4 = _paper(4, 5, 10, topic="dynamics")
        result = aggregate_subject([p2, p4])
        topics = {w.topic for w in result.weaknesses.weak_areas}
        self.assertIn("dynamics", topics)

    def test_empty_list_raises_usage_error(self) -> None:
        with self.assertRaises(UsageError):
            aggregate_subject([])
