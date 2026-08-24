"""Unit tests for the label-free metamorphic marker properties (M1.8, #58).

Every test here runs with an injected marking function, so the suite is free
and offline. The live golden-set run under ``cache_mode=bypass`` that the
issue's fourth acceptance bullet asks for is a separate, costed step.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from typing import cast

from lemely.accuracy.harness import GoldenAnswer, GoldenCase
from lemely.accuracy.metamorphic import (
    PROPERTY_RENAME,
    PROPERTY_REORDER,
    PROPERTY_WHITESPACE,
    MarkFn,
    MetamorphicReport,
    check_case,
    normalise_answer_whitespace,
    rename_mark_point_ids,
    reorder_mark_points,
)
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
)


def _scheme(questions: list[dict[str, object]], *, maximum_mark: int = 5) -> MarkScheme:
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
                "maximum_mark": maximum_mark,
                "scheme_format": "point_based",
            },
            "questions": questions,
        }
    )


def _plain_question(qid: str = "1(a)") -> dict[str, object]:
    return {
        "id": qid,
        "marks": 3,
        "type": "explanation",
        "question_command": "explain why",
        "answer_points": [
            {"id": "p1", "point": "due to gravity", "marks": 1},
            {"id": "p2", "point": "acting downward", "marks": 1},
            {"id": "p3", "point": "on the mass", "marks": 1},
        ],
    }


def _ids(scheme: MarkScheme, qid: str) -> list[str]:
    question = scheme.get_question_by_id(qid)
    assert question is not None
    return [p.id for p in question.answer_points]


def _points(scheme: MarkScheme, qid: str) -> list[str]:
    question = scheme.get_question_by_id(qid)
    assert question is not None
    return [p.point for p in question.answer_points]


class TestReorderMarkPoints(unittest.TestCase):
    def test_reverses_the_order_of_a_plain_questions_mark_points(self) -> None:
        scheme, skipped = reorder_mark_points(_scheme([_plain_question()]))
        self.assertEqual(
            _points(scheme, "1(a)"),
            ["on the mass", "acting downward", "due to gravity"],
        )
        self.assertEqual(skipped, {})

    def test_preserves_every_point_id_and_its_marks(self) -> None:
        before = _scheme([_plain_question()])
        after, _ = reorder_mark_points(before)
        self.assertEqual(sorted(_ids(after, "1(a)")), sorted(_ids(before, "1(a)")))
        question = after.get_question_by_id("1(a)")
        assert question is not None
        self.assertEqual([p.marks for p in question.answer_points], [1, 1, 1])

    def test_skips_a_question_whose_points_carry_is_alternative(self) -> None:
        """``is_alternative`` means "alternative to the *previous* point", so
        the list is order-dependent and reordering is not meaning-preserving.
        Permuting it anyway would manufacture a false violation."""
        question = _plain_question()
        points = question["answer_points"]
        assert isinstance(points, list)
        points[1]["is_alternative"] = True
        scheme, skipped = reorder_mark_points(_scheme([question]))
        self.assertIn("1(a)", skipped)
        self.assertIn("is_alternative", skipped["1(a)"])
        self.assertEqual(_points(scheme, "1(a)"), _points(_scheme([question]), "1(a)"))

    def test_skips_a_question_with_fewer_than_two_mark_points(self) -> None:
        question = _plain_question()
        question["marks"] = 1
        question["answer_points"] = [{"id": "p1", "point": "only one", "marks": 1}]
        _, skipped = reorder_mark_points(_scheme([question]))
        self.assertIn("1(a)", skipped)

    def test_reorders_nested_sub_parts_too(self) -> None:
        parent: dict[str, object] = {
            "id": "1",
            "marks": 3,
            "type": "explanation",
            "parts": [_plain_question("1(a)")],
        }
        scheme, skipped = reorder_mark_points(_scheme([parent]))
        self.assertNotIn("1(a)", skipped)
        self.assertEqual(_points(scheme, "1(a)")[0], "on the mass")
        # The non-leaf parent carries no mark points of its own, so it is
        # reported as skipped. Only leaves reach a QuestionOutcome.
        self.assertIn("1", skipped)


class TestRenameMarkPointIds(unittest.TestCase):
    def test_rewrites_every_point_id(self) -> None:
        scheme, skipped = rename_mark_point_ids(_scheme([_plain_question()]))
        self.assertEqual(skipped, {})
        self.assertNotIn("p1", _ids(scheme, "1(a)"))
        self.assertEqual(len(set(_ids(scheme, "1(a)"))), 3)

    def test_preserves_order_and_marks(self) -> None:
        scheme, _ = rename_mark_point_ids(_scheme([_plain_question()]))
        self.assertEqual(
            _points(scheme, "1(a)"),
            ["due to gravity", "acting downward", "on the mass"],
        )

    def test_skips_a_question_whose_free_text_references_a_point_id(self) -> None:
        """A ``notes``/``marking_guidance`` string naming ``p2`` would be left
        dangling by a rename, which changes what the marker reads."""
        question = _plain_question()
        question["marking_guidance"] = "award p2 only if p1 was given"
        _, skipped = rename_mark_point_ids(_scheme([question]))
        self.assertIn("1(a)", skipped)
        self.assertIn("referenced", skipped["1(a)"].lower())


class TestNormaliseAnswerWhitespace(unittest.TestCase):
    def test_collapses_runs_and_strips(self) -> None:
        self.assertEqual(
            normalise_answer_whitespace({"1(a)": "  the   ball \n\n falls  "}),
            {"1(a)": "the ball falls"},
        )

    def test_leaves_an_already_normal_answer_untouched(self) -> None:
        self.assertEqual(
            normalise_answer_whitespace({"1(a)": "the ball falls"}),
            {"1(a)": "the ball falls"},
        )


def _case(scheme: MarkScheme, answers: dict[str, str]) -> GoldenCase:
    return GoldenCase(
        paper_id="0625_s20_qp_41",
        mark_scheme=scheme,
        ground_truth={
            qid: GoldenAnswer(student_answer=text, awarded_marks=0) for qid, text in answers.items()
        },
    )


def _marker(marks_by_call: list[dict[str, int]]) -> MarkFn:
    """Return a marking function that yields *marks_by_call* in call order."""
    calls = iter(marks_by_call)

    def mark(scheme: MarkScheme, answers: Mapping[str, str]) -> CorrectionResult:
        awarded = next(calls)
        return CorrectionResult(
            metadata=ExamMetadata(
                subject_code="0625",
                paper_number=4,
                paper_variant=1,
                session_month="May/June",
                session_year=2020,
            ),
            questions=[
                CorrectedQuestion(
                    question_id=qid,
                    awarded_marks=value,
                    maximum_marks=3,
                    confidence=ConfidenceBand.HIGH,
                    confidence_score=0.95,
                    needs_teacher_review=False,
                    marker_source="ai",
                )
                for qid, value in awarded.items()
            ],
        )

    return mark


class TestCheckCase(unittest.TestCase):
    def test_reports_held_when_the_perturbation_does_not_move_marks(self) -> None:
        case = _case(_scheme([_plain_question()]), {"1(a)": "gravity pulls it down"})
        outcomes = check_case(
            case,
            mark=_marker([{"1(a)": 2}, {"1(a)": 2}]),
            properties=(PROPERTY_REORDER,),
        )
        self.assertEqual([o.status for o in outcomes], ["held"])
        self.assertEqual(outcomes[0].baseline_marks, 2)
        self.assertEqual(outcomes[0].perturbed_marks, 2)

    def test_reports_a_violation_with_both_mark_values(self) -> None:
        case = _case(_scheme([_plain_question()]), {"1(a)": "gravity pulls it down"})
        outcomes = check_case(
            case,
            mark=_marker([{"1(a)": 2}, {"1(a)": 1}]),
            properties=(PROPERTY_REORDER,),
        )
        self.assertEqual([o.status for o in outcomes], ["violated"])
        self.assertEqual(outcomes[0].baseline_marks, 2)
        self.assertEqual(outcomes[0].perturbed_marks, 1)
        self.assertEqual(outcomes[0].property_name, PROPERTY_REORDER)

    def test_reports_per_question_rather_than_one_pass_fail(self) -> None:
        """Acceptance bullet 5: one violating leaf must not mask its siblings."""
        scheme = _scheme(
            [_plain_question("1(a)"), _plain_question("1(b)")],
            maximum_mark=6,
        )
        case = _case(scheme, {"1(a)": "a", "1(b)": "b"})
        outcomes = check_case(
            case,
            mark=_marker([{"1(a)": 2, "1(b)": 3}, {"1(a)": 2, "1(b)": 1}]),
            properties=(PROPERTY_REORDER,),
        )
        by_id = {o.question_id: o for o in outcomes}
        self.assertEqual(by_id["1(a)"].status, "held")
        self.assertEqual(by_id["1(b)"].status, "violated")

    def test_records_a_skipped_question_with_its_reason(self) -> None:
        question = _plain_question()
        points = question["answer_points"]
        assert isinstance(points, list)
        points[1]["is_alternative"] = True
        case = _case(_scheme([question]), {"1(a)": "gravity"})
        outcomes = check_case(
            case,
            mark=_marker([{"1(a)": 2}, {"1(a)": 2}]),
            properties=(PROPERTY_REORDER,),
        )
        self.assertEqual([o.status for o in outcomes], ["skipped"])
        self.assertIsNotNone(outcomes[0].skip_reason)
        self.assertIsNone(outcomes[0].baseline_marks)

    def test_a_leaf_the_marker_did_not_return_is_skipped_not_counted_correct(self) -> None:
        case = _case(_scheme([_plain_question()]), {"1(a)": "gravity"})
        outcomes = check_case(
            case,
            mark=_marker([{}, {}]),
            properties=(PROPERTY_REORDER,),
        )
        self.assertEqual([o.status for o in outcomes], ["skipped"])
        assert outcomes[0].skip_reason is not None
        self.assertIn("not marked", outcomes[0].skip_reason)


class TestMetamorphicReport(unittest.TestCase):
    def test_violations_exposes_only_the_violating_outcomes(self) -> None:
        scheme = _scheme(
            [_plain_question("1(a)"), _plain_question("1(b)")],
            maximum_mark=6,
        )
        case = _case(scheme, {"1(a)": "a", "1(b)": "b"})
        report = MetamorphicReport(
            outcomes=tuple(
                check_case(
                    case,
                    mark=_marker([{"1(a)": 2, "1(b)": 3}, {"1(a)": 2, "1(b)": 1}]),
                    properties=(PROPERTY_REORDER,),
                )
            )
        )
        self.assertEqual([v.question_id for v in report.violations], ["1(b)"])

    def test_to_dict_round_trips_every_outcome(self) -> None:
        case = _case(_scheme([_plain_question()]), {"1(a)": "gravity"})
        report = MetamorphicReport(
            outcomes=tuple(
                check_case(
                    case,
                    mark=_marker([{"1(a)": 2}, {"1(a)": 2}]),
                    properties=(PROPERTY_REORDER,),
                )
            )
        )
        payload = report.to_dict()
        counts = cast("dict[str, int]", payload["counts"])
        outcomes = cast("list[object]", payload["outcomes"])
        self.assertEqual(counts["held"], 1)
        self.assertEqual(len(outcomes), 1)

    def test_the_three_property_names_are_the_three_acceptance_properties(self) -> None:
        self.assertEqual(
            {PROPERTY_REORDER, PROPERTY_RENAME, PROPERTY_WHITESPACE},
            {"reorder_mark_points", "rename_mark_point_ids", "normalise_answer_whitespace"},
        )


if __name__ == "__main__":
    unittest.main()
