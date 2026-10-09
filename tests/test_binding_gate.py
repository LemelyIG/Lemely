"""Binding gate checks G1, G2, G5-G9 and the verdict."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lemely.core.binding import BindingCheck
from lemely.core.binding_gate import (
    GateThresholds,
    check_duplicate_ids,
    check_label_coverage,
    check_off_topic,
    check_second_read,
    check_shape,
    check_shift,
    check_unknown_ids,
    verdict,
)
from lemely.core.loose_schemas import MarkScheme, Question
from lemely.core.schemas import CorrectionResult, ExtractedAnswers

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "binding" / "0625_w24_41"
DEFAULTS = GateThresholds()

FULL_SHIFTS = ["full_shift_lite", "full_shift_38_a", "full_shift_38_b", "full_shift_38_c"]
MISBOUND = [*FULL_SHIFTS, "chaotic", "partial_a", "partial_b"]


@pytest.fixture(scope="module")
def scheme() -> MarkScheme:
    path = ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text()))


def _fixture(name: str) -> ExtractedAnswers:
    return ExtractedAnswers.model_validate(json.loads((FIXTURES / f"{name}.json").read_text()))


def _extracted(pairs: list[tuple[str, str]]) -> ExtractedAnswers:
    return ExtractedAnswers.model_validate(
        {
            "answers": [
                {"question_id": qid, "answer": text, "confidence": 1.0} for qid, text in pairs
            ],
            "paper_id": "p",
            "source_scan": "x.pdf",
        }
    )


def _leaf(qid: str, value: str | None, *, mcq: bool = False, prose: bool = False) -> Question:
    if mcq:
        return Question.model_validate({"id": qid, "marks": 1, "type": "mcq", "mcq_answer": "A"})
    point = "Explain the idea in words" if prose else value
    points: list[dict[str, Any]] = [{"id": "p1", "marks": 1, "point": point}] if point else []
    return Question.model_validate(
        {"id": qid, "marks": 1, "type": "recall", "answer_points": points}
    )


def _scheme(leaves: list[Question]) -> MarkScheme:
    return MarkScheme.model_construct(questions=leaves)


def _by(checks: list[BindingCheck], check_id: str, scope: str) -> BindingCheck | None:
    return next((c for c in checks if c.id == check_id and c.scope == scope), None)


def _all_checks(extracted: ExtractedAnswers, scheme: MarkScheme) -> list[BindingCheck]:
    return [
        check_unknown_ids(extracted, scheme),
        check_duplicate_ids(extracted),
        check_shape(extracted, scheme, DEFAULTS),
        *check_shift(extracted, scheme, DEFAULTS),
    ]


# --- fixture-driven ---------------------------------------------------------


@pytest.mark.parametrize("name", FULL_SHIFTS)
def test_g7_fires_at_paper_scope_on_every_full_shift(name: str, scheme: MarkScheme) -> None:
    paper = _by(check_shift(_fixture(name), scheme, DEFAULTS), "G7", "paper")
    assert paper is not None and not paper.passed
    assert len(paper.question_ids) >= DEFAULTS.shift_min_matches


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # 1b is absent here: the model misread it as 2.0cm against an expected 20.
        ("partial_a", {"1a_ii", "1c_i", "1c_ii"}),
        ("partial_b", {"1a_ii", "1b", "1c_i", "1c_ii"}),
    ],
)
def test_g7_flags_the_shifted_leaves_of_a_partial_shift(
    name: str, expected: set[str], scheme: MarkScheme
) -> None:
    failed = [c for c in check_shift(_fixture(name), scheme, DEFAULTS) if not c.passed]
    assert failed
    listed = {qid for c in failed for qid in c.question_ids}
    assert listed.issuperset(expected)
    leaf_ids = [q.id for q in scheme.all_questions_flat() if not q.parts and q.marks > 0]
    bound_correctly = set(leaf_ids[leaf_ids.index("2a_i") :])
    assert not listed & bound_correctly


@pytest.mark.parametrize("name", ["chaotic", "partial_b"])
def test_g1_fires_on_invented_ids(name: str, scheme: MarkScheme) -> None:
    check = check_unknown_ids(_fixture(name), scheme)
    assert not check.passed and check.scope == "paper"
    assert check.question_ids


@pytest.mark.parametrize("name", ["chaotic", "partial_a"])
def test_g2_fires_on_duplicate_ids(name: str) -> None:
    check = check_duplicate_ids(_fixture(name))
    assert not check.passed and check.scope == "paper"
    assert check.question_ids


@pytest.mark.parametrize("name", MISBOUND)
def test_every_misbound_fixture_fails_at_least_one_check(name: str, scheme: MarkScheme) -> None:
    assert any(not c.passed for c in _all_checks(_fixture(name), scheme))


def test_aligned_fixture_passes_g1_g2_g6_g7(scheme: MarkScheme) -> None:
    checks = _all_checks(_fixture("aligned"), scheme)
    assert [c.id for c in checks if not c.passed] == []


# --- G1, G2, G5 -------------------------------------------------------------


def test_g1_g2_pass_on_clean_input() -> None:
    scheme = _scheme([_leaf("1", "5")])
    assert check_unknown_ids(_extracted([("1", "5")]), scheme).passed
    assert check_duplicate_ids(_extracted([("1", "5")])).passed


def test_g5_unaligned_leaf_with_answer_fails_at_question_scope() -> None:
    scheme = _scheme([_leaf(str(i), "5") for i in range(1, 21)])
    check = check_label_coverage(_extracted([("3", "5"), ("4", "")]), scheme, ["3", "4"], 0)
    assert not check.passed and check.scope == "question"
    assert check.question_ids == ["3"]


def test_g5_fails_at_paper_scope_on_many_unaligned_or_unmatched_markers() -> None:
    scheme = _scheme([_leaf(str(i), "5") for i in range(1, 11)])
    many = check_label_coverage(_extracted([]), scheme, ["1", "2"], 0)
    assert not many.passed and many.scope == "paper"
    marker = check_label_coverage(_extracted([]), scheme, [], 1)
    assert not marker.passed and marker.scope == "paper"
    assert check_label_coverage(_extracted([]), scheme, [], 0).passed


# --- G6 ---------------------------------------------------------------------


def test_g6_ignores_unknown_shapes() -> None:
    # Leaves 3 and 4 expect nothing readable, so whatever is written there cannot contradict.
    scheme = _scheme([_leaf("1", "5"), _leaf("2", "7"), _leaf("3", None), _leaf("4", None)])
    extracted = _extracted([("1", "5"), ("2", "7 m"), ("3", "words here"), ("4", "12")])
    check = check_shape(extracted, scheme, DEFAULTS)
    assert check.passed and "2 of 2" in check.detail
    assert check_shape(_extracted([("3", "words here")]), scheme, DEFAULTS).passed


def test_g6_fails_when_most_answers_are_the_wrong_kind() -> None:
    scheme = _scheme([_leaf("1", "5"), _leaf("2", "7")])
    extracted = _extracted([("1", "because of heat transfer"), ("2", "it moves slowly away")])
    check = check_shape(extracted, scheme, DEFAULTS)
    assert not check.passed and check.scope == "paper"
    assert check.question_ids == ["1", "2"]


def test_g6_skips_mcq_leaves() -> None:
    scheme = _scheme([_leaf("1", None, mcq=True), _leaf("2", "7")])
    assert check_shape(_extracted([("1", "B"), ("2", "7")]), scheme, DEFAULTS).passed


# --- G7 ---------------------------------------------------------------------


def _line(values: list[str]) -> MarkScheme:
    return _scheme([_leaf(str(i + 1), v) for i, v in enumerate(values)])


def test_g7_needs_more_shifted_than_self_matching_leaves() -> None:
    scheme = _line(["11", "22", "33", "44", "55", "66", "77", "88"])
    # 2, 5 and 8 hold the previous value; 3, 4, 6 and 7 hold their own.
    extracted = _extracted(
        [("1", "11"), ("2", "11"), ("3", "33"), ("4", "44"), ("5", "44"),
         ("6", "66"), ("7", "77"), ("8", "77")]
    )  # fmt: skip
    checks = check_shift(extracted, scheme, DEFAULTS)
    paper = _by(checks, "G7", "paper")
    assert paper is not None and paper.passed
    question = _by(checks, "G7", "question")
    assert question is not None and question.question_ids == ["2", "5", "8"]


def test_g7_two_shifted_leaves_fail_at_question_scope_only() -> None:
    scheme = _line(["11", "22", "33", "44"])
    extracted = _extracted([("1", "11"), ("2", "11"), ("3", "22"), ("4", "44")])
    checks = check_shift(extracted, scheme, DEFAULTS)
    paper = _by(checks, "G7", "paper")
    question = _by(checks, "G7", "question")
    assert paper is not None and paper.passed
    assert question is not None and not question.passed
    assert question.question_ids == ["2", "3"]


def test_g7_answer_matching_its_own_leaf_never_points_away() -> None:
    # Neighbouring questions share the value 5; every answer is correct for its own.
    scheme = _line(["5", "5", "5", "5", "5"])
    extracted = _extracted([(str(i), "5") for i in range(1, 6)])
    checks = check_shift(extracted, scheme, DEFAULTS)
    assert all(c.passed for c in checks) and len(checks) == 1


def test_g7_is_silent_when_a_student_is_simply_wrong() -> None:
    scheme = _line(["11", "22", "33", "44", "55"])
    extracted = _extracted([(str(i), "999") for i in range(1, 6)])
    assert all(c.passed for c in check_shift(extracted, scheme, DEFAULTS))


def test_g7_skips_leaves_without_expected_values_when_choosing_neighbours() -> None:
    scheme = _scheme(
        [_leaf("1", "11"), _leaf("2", None), _leaf("3", "33"), _leaf("4", None),
         _leaf("5", "55"), _leaf("6", None), _leaf("7", "77")]
    )  # fmt: skip
    # 3, 5 and 7 each hold the nearest valued previous leaf's value (across a gap).
    extracted = _extracted([("1", "11"), ("3", "11"), ("5", "33"), ("7", "55")])
    paper = _by(check_shift(extracted, scheme, DEFAULTS), "G7", "paper")
    assert paper is not None and not paper.passed
    assert paper.question_ids == ["3", "5", "7"]


def test_g7_looks_at_most_two_valued_leaves_away() -> None:
    scheme = _line(["11", "22", "33", "44", "55", "66", "77"])
    # Each answer holds the value three leaves back: out of reach.
    extracted = _extracted([("4", "11"), ("5", "22"), ("6", "33"), ("7", "44")])
    assert all(c.passed for c in check_shift(extracted, scheme, DEFAULTS))


def test_g7_excludes_mcq_leaves() -> None:
    scheme = _scheme(
        [_leaf("1", None, mcq=True), _leaf("2", "22"), _leaf("3", "33"), _leaf("4", "44")]
    )
    extracted = _extracted([("1", "B"), ("2", "22"), ("3", "22"), ("4", "33")])
    checks = check_shift(extracted, scheme, DEFAULTS)
    question = _by(checks, "G7", "question")
    assert question is not None and "1" not in question.question_ids


def test_g7_detects_a_shift_the_other_way() -> None:
    scheme = _line(["11", "22", "33", "44", "55"])
    extracted = _extracted([("1", "22"), ("2", "33"), ("3", "44"), ("4", "55")])
    paper = _by(check_shift(extracted, scheme, DEFAULTS), "G7", "paper")
    assert paper is not None and not paper.passed
    assert "next" in paper.detail


# --- G8 ---------------------------------------------------------------------


def _correction(flags: list[str]) -> CorrectionResult:
    return CorrectionResult.model_validate(
        {
            "questions": [
                {
                    "question_id": str(i + 1),
                    "awarded_marks": 0,
                    "maximum_marks": 1,
                    "confidence": "high",
                    "confidence_score": 0.9,
                    "needs_teacher_review": False,
                    "addresses_question": flag,
                }
                for i, flag in enumerate(flags)
            ],
            "metadata": {
                "subject_code": "0625",
                "paper_number": 4,
                "paper_variant": 1,
                "session_month": "Oct/Nov",
            },
        }
    )


def test_g8_counts_a_run_of_three() -> None:
    check = check_off_topic(_correction(["yes", "no", "no", "no", "yes"]), DEFAULTS)
    assert not check.passed and check.scope == "paper"
    assert check.question_ids == ["2", "3", "4"]


def test_g8_scattered_no_answers_below_the_count_fail_at_question_scope() -> None:
    check = check_off_topic(_correction(["no", "yes", "no", "yes", "no"]), DEFAULTS)
    assert not check.passed and check.scope == "question"
    check = check_off_topic(_correction(["no", "yes", "no", "yes", "no", "yes", "no"]), DEFAULTS)
    assert check.scope == "paper"
    assert check_off_topic(_correction(["yes", "unclear"]), DEFAULTS).passed


# --- G9 ---------------------------------------------------------------------


def test_g9_detects_text_agreeing_under_a_different_id() -> None:
    first = _extracted([("1", "the speed of the car"), ("2", "heat is lost to the air")])
    second = _extracted([("1", "heat is lost to the air"), ("2", "something else entirely")])
    check = check_second_read(first, second, DEFAULTS)
    assert not check.passed and check.scope == "paper"
    assert check.question_ids == ["1"]


def test_g9_ignores_a_plain_rereading_difference() -> None:
    first = _extracted([("1", "4.9 N"), ("2", "heat is lost")])
    second = _extracted([("1", "4.8 N"), ("2", "heat is lost")])
    assert check_second_read(first, second, DEFAULTS).passed
    unrelated = _extracted([("1", "zzzzzzzz"), ("2", "heat is lost")])
    assert check_second_read(first, unrelated, DEFAULTS).passed


def test_g9_few_disagreements_fail_at_question_scope() -> None:
    texts = [f"answer number {chr(97 + i) * 6}" for i in range(12)]
    first = _extracted([(str(i), t) for i, t in enumerate(texts)])
    swapped = list(texts)
    swapped[0] = texts[1]
    second = _extracted([(str(i), t) for i, t in enumerate(swapped)])
    thresholds = GateThresholds(second_read_disagreement_rate=0.5)
    check = check_second_read(first, second, thresholds)
    assert not check.passed and check.scope == "question"
    assert check.question_ids == ["0"]


# --- verdict ----------------------------------------------------------------


def _check(scope: str, *, passed: bool) -> BindingCheck:
    return BindingCheck.model_validate(
        {"id": "G7", "passed": passed, "scope": scope, "detail": "x"}
    )


def test_verdict_pass_retry_hold() -> None:
    assert verdict([_check("paper", passed=True)], retried=False) == "pass"
    assert verdict([_check("paper", passed=False)], retried=False) == "retry"
    assert verdict([_check("paper", passed=False)], retried=True) == "hold"


def test_question_scope_failures_do_not_hold_the_paper() -> None:
    checks = [_check("question", passed=False), _check("paper", passed=True)]
    assert verdict(checks, retried=False) == "pass"
    assert verdict(checks, retried=True) == "pass"
