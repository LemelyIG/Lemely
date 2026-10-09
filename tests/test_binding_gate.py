"""Binding gate checks G1, G2, G5-G9 and the verdict."""

from __future__ import annotations

import json
from dataclasses import replace
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
GOLDEN = ROOT / "tests" / "golden"
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
            "paper_id": "p",
            "source_scan": "x.pdf",
            "answers": [
                {"question_id": qid, "answer": text, "confidence": 1.0} for qid, text in pairs
            ],
        }
    )


def _leaf(
    qid: str,
    value: str | None,
    *,
    mcq: bool = False,
    prose: bool = False,
    drawing: bool = False,
) -> Question:
    """A one-mark leaf expecting ``value``; ``mcq`` leaves may carry a numeric-looking key."""
    body: dict[str, Any] = {"id": qid, "marks": 1, "type": "mcq" if mcq else "recall"}
    if mcq:
        body["mcq_answer"] = "A"
    point = "Explain the idea in words" if prose else value
    if point:
        body["answer_points"] = [{"id": "p1", "marks": 1, "point": point}]
    if drawing:
        body["type"] = "diagram"
        body["drawing_criteria"] = [
            {
                "id": "d1",
                "criterion": "A labelled diagram",
                "requirement": "A labelled diagram",
                "marks": 1,
            }
        ]
    return Question.model_validate(body)


def _scheme(leaves: list[Question]) -> MarkScheme:
    return MarkScheme.model_construct(questions=leaves)


def _line(values: list[str | None]) -> MarkScheme:
    return _scheme([_leaf(str(i + 1), v) for i, v in enumerate(values)])


def _by(checks: list[BindingCheck], check_id: str, scope: str) -> BindingCheck | None:
    return next((c for c in checks if c.id == check_id and c.scope == scope), None)


def _premarking(extracted: ExtractedAnswers, scheme: MarkScheme) -> list[BindingCheck]:
    return [
        check_unknown_ids(extracted, scheme),
        check_duplicate_ids(extracted),
        check_shape(extracted, scheme, DEFAULTS),
        *check_shift(extracted, scheme, DEFAULTS),
    ]


def _golden_cases() -> list[tuple[str, MarkScheme, ExtractedAnswers]]:
    cases = []
    for directory in sorted(p for p in GOLDEN.iterdir() if (p / "answers.json").exists()):
        mark_scheme = MarkScheme.model_validate(
            json.loads((directory / "mark_scheme.json").read_text())
        )
        raw = json.loads((directory / "answers.json").read_text())
        pairs = [
            (qid, str(entry["student_answer"]))
            for qid, entry in raw.items()
            if isinstance(entry, dict) and entry.get("student_answer")
        ]
        cases.append((directory.name, mark_scheme, _extracted(pairs)))
    return cases


GOLDEN_CASES = _golden_cases()


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
    checks = _premarking(_fixture(name), scheme)
    assert verdict(checks, retried=False) != "pass"


def test_aligned_fixture_passes_g1_g2_g6_g7(scheme: MarkScheme) -> None:
    checks = _premarking(_fixture("aligned"), scheme)
    assert [c.id for c in checks if not c.passed] == []


def test_second_read_separates_aligned_from_every_full_shift(scheme: MarkScheme) -> None:
    aligned = _fixture("aligned")
    for name in FULL_SHIFTS:
        check = check_second_read(aligned, _fixture(name), scheme, DEFAULTS)
        assert not check.passed and check.scope == "paper", name
    assert check_second_read(aligned, aligned, scheme, DEFAULTS).passed


# --- golden: correct bindings are never held ---------------------------------


@pytest.mark.parametrize(("name", "golden_scheme", "extracted"), GOLDEN_CASES)
def test_golden_cases_pass_g1_g2_g6_g7_at_paper_scope(
    name: str, golden_scheme: MarkScheme, extracted: ExtractedAnswers
) -> None:
    paper_failures = [
        c.id for c in _premarking(extracted, golden_scheme) if c.scope == "paper" and not c.passed
    ]
    assert paper_failures == [], name


def test_there_are_golden_cases() -> None:
    assert len(GOLDEN_CASES) >= 12


# --- G1, G2 -----------------------------------------------------------------


def test_g1_g2_pass_on_clean_input() -> None:
    scheme = _scheme([_leaf("1", "5")])
    assert check_unknown_ids(_extracted([("1", "5")]), scheme).passed
    assert check_duplicate_ids(_extracted([("1", "5")])).passed


# --- G5 ---------------------------------------------------------------------


def _g5(
    extracted: ExtractedAnswers,
    leaves: int,
    unaligned: list[str],
    markers: int = 0,
    thresholds: GateThresholds = DEFAULTS,
) -> BindingCheck:
    scheme = _scheme([_leaf(str(i), "5") for i in range(1, leaves + 1)])
    return check_label_coverage(extracted, scheme, unaligned, markers, thresholds)


def test_g5_lists_the_leaf_before_an_unaligned_leaf_when_it_is_answered() -> None:
    check = _g5(_extracted([("2", "5"), ("3", "5")]), 20, ["3", "9"])
    assert not check.passed and check.scope == "question"
    # 3 is unaligned; its writing sits in the answer to 2. 9 is unaligned; 8 is blank.
    assert check.question_ids == ["2", "3", "9"]


def test_g5_does_not_list_a_blank_predecessor() -> None:
    check = _g5(_extracted([("1", "5")]), 20, ["4"])
    assert not check.passed and check.scope == "question"
    assert check.question_ids == ["4"]


def test_g5_predecessor_is_the_nearest_aligned_leaf() -> None:
    # 4 and 5 are unaligned; the nearest aligned leaf before both is 3.
    check = _g5(_extracted([("3", "5"), ("4", "5")]), 30, ["4", "5"])
    assert check.question_ids == ["3", "4", "5"]


def test_g5_first_leaf_unaligned_has_no_predecessor() -> None:
    check = _g5(_extracted([("1", "5")]), 30, ["1"])
    assert check.question_ids == ["1"]


def test_g5_passes_when_everything_lined_up() -> None:
    assert _g5(_extracted([("1", "5")]), 20, []).passed


def test_g5_paper_scope_on_many_unaligned() -> None:
    check = _g5(_extracted([]), 10, ["1", "2"])
    assert not check.passed and check.scope == "paper"
    assert check.question_ids == ["1", "2"]


def test_g5_unaligned_rate_boundary_and_threshold() -> None:
    # Exactly 10% (1 of 10) is not above the limit.
    assert _g5(_extracted([]), 10, ["1"]).scope == "question"
    strict = replace(DEFAULTS, unaligned_rate=0.05)
    assert _g5(_extracted([]), 10, ["1"], thresholds=strict).scope == "paper"


def test_g5_paper_scope_on_an_unmatched_marker() -> None:
    check = _g5(_extracted([]), 20, [], markers=1)
    assert not check.passed and check.scope == "paper"
    assert "1 label" in check.detail


# --- G6 ---------------------------------------------------------------------


def test_g6_number_leaf_answered_with_working_is_not_a_contradiction() -> None:
    # Leaf 5b of golden 0625_s20_qp_31_theory_correct.
    working = (
        "clockwise moments = anticlockwise moments. 200 = (2.0 x 10) + (F x 60). "
        "F = (200-20) / 60 = 180 / 60 = 3.0 N"
    )
    scheme = _scheme([_leaf("5b", "3"), _leaf("5c", "4"), _leaf("5d", "6")])
    extracted = _extracted([("5b", working), ("5c", working), ("5d", working)])
    assert check_shape(extracted, scheme, DEFAULTS).passed


def test_g6_number_leaf_answered_without_any_digit_contradicts() -> None:
    scheme = _scheme([_leaf(str(i), "5") for i in range(1, 5)])
    extracted = _extracted([(str(i), "because of heat transfer") for i in range(1, 5)])
    check = check_shape(extracted, scheme, DEFAULTS)
    assert not check.passed and check.scope == "paper"
    assert check.question_ids == ["1", "2", "3", "4"]


def test_g6_a_superscript_is_not_a_digit() -> None:
    scheme = _scheme([_leaf(str(i), "5") for i in range(1, 5)])
    extracted = _extracted([(str(i), "m/s\u00b2") for i in range(1, 5)])
    assert not check_shape(extracted, scheme, DEFAULTS).passed


def test_g6_text_leaf_answered_with_a_number_contradicts() -> None:
    scheme = _scheme([_leaf(str(i), None, prose=True) for i in range(1, 5)])
    extracted = _extracted([(str(i), "42") for i in range(1, 5)])
    check = check_shape(extracted, scheme, DEFAULTS)
    assert not check.passed and check.question_ids == ["1", "2", "3", "4"]


def test_g6_drawing_and_unknown_leaves_never_contradict() -> None:
    scheme = _scheme([_leaf(str(i), None, drawing=(i % 2 == 0)) for i in range(1, 7)])
    extracted = _extracted([(str(i), "plain words") for i in range(1, 7)])
    assert check_shape(extracted, scheme, DEFAULTS).passed


def test_g6_needs_a_minimum_count() -> None:
    scheme = _scheme([_leaf("1", "5"), _leaf("2", "7")])
    extracted = _extracted([("1", "words"), ("2", "more words")])
    assert check_shape(extracted, scheme, DEFAULTS).passed  # 2 of 2, but below 3
    lower = replace(DEFAULTS, shape_min_count=2)
    assert not check_shape(extracted, scheme, lower).passed


def test_g6_rate_is_over_shaped_answered_leaves_only() -> None:
    # 3 contradictions among 3 shaped answered leaves; 20 leaves with no expected
    # shape and 5 unanswered shaped leaves must not dilute the rate.
    leaves = [_leaf(f"a{i}", "5") for i in range(3)]
    leaves += [_leaf(f"u{i}", None) for i in range(20)]
    leaves += [_leaf(f"b{i}", "5") for i in range(5)]
    answers = [(f"a{i}", "words") for i in range(3)]
    answers += [(f"u{i}", "42") for i in range(20)]
    check = check_shape(_extracted(answers), _scheme(leaves), DEFAULTS)
    assert not check.passed


def test_g6_rate_boundary() -> None:
    # 3 contradictions out of 12 shaped = exactly 25%: not above the limit.
    scheme = _scheme([_leaf(str(i), "5") for i in range(12)])
    answers = [(str(i), "words" if i < 3 else "5") for i in range(12)]
    assert check_shape(_extracted(answers), scheme, DEFAULTS).passed
    answers = [(str(i), "words" if i < 4 else "5") for i in range(12)]
    assert not check_shape(_extracted(answers), scheme, DEFAULTS).passed


def test_g6_ignores_blank_answers() -> None:
    scheme = _scheme([_leaf(str(i), "5") for i in range(1, 5)])
    extracted = _extracted([(str(i), "  ") for i in range(1, 5)])
    check = check_shape(extracted, scheme, DEFAULTS)
    assert check.passed and "0 of 0" not in check.detail


def test_g6_skips_mcq_leaves() -> None:
    # The MCQ leaves carry numeric-looking keys, so only the exclusion keeps them out.
    scheme = _scheme([_leaf(str(i), "5", mcq=True) for i in range(1, 5)])
    extracted = _extracted([(str(i), "B") for i in range(1, 5)])
    assert check_shape(extracted, scheme, DEFAULTS).passed


# --- G7 ---------------------------------------------------------------------


def test_g7_extra_pointing_leaf_never_cancels_a_run() -> None:
    values = [str(11 * (i + 1)) for i in range(15)]
    scheme = _line(values)
    base = [("1", "11"), ("2", "11"), ("3", "22"), ("4", "33")]
    base += [(str(i), values[i - 1]) for i in range(5, 15)]
    for last in ("999", values[13]):  # wrong, then the previous neighbour's value
        extracted = _extracted([*base, ("15", last)])
        paper = _by(check_shift(extracted, scheme, DEFAULTS), "G7", "paper")
        assert paper is not None and not paper.passed, last


def test_g7_correctly_bound_weak_student_is_not_held() -> None:
    scheme = _line(["9.6", "28.89", "81.1", "7", "12", "30"])
    extracted = _extracted(
        [
            ("1", "9.6"),
            ("2", "9.6 x 2 = 19.2"),
            ("3", "9.6 + 1 = 10.6"),
            ("4", "3"),
            ("5", "12"),
            ("6", "12 x 2 = 24"),
        ]
    )
    assert all(c.passed for c in check_shift(extracted, scheme, DEFAULTS))


def test_g7_neighbour_is_the_true_manifest_neighbour() -> None:
    leaves = [_leaf("1", "11")]
    leaves += [_leaf(f"f{i}", None, prose=True) for i in range(3)]
    leaves += [_leaf(f"p{i}", None, prose=True) for i in range(3)]
    extracted = _extracted([(f"p{i}", "11") for i in range(3)])
    assert all(c.passed for c in check_shift(extracted, _scheme(leaves), DEFAULTS))


def test_g7_needs_more_pointing_leaves_than_the_minimum() -> None:
    scheme = _line(["11", "22", "33", "44"])
    extracted = _extracted([("1", "11"), ("2", "11"), ("3", "22"), ("4", "44")])
    checks = check_shift(extracted, scheme, DEFAULTS)
    assert checks[0].scope == "paper" and checks[0].passed
    question = _by(checks, "G7", "question")
    assert question is not None and not question.passed
    assert question.question_ids == ["2", "3"]


def test_g7_a_run_of_the_minimum_fails_at_paper_scope_and_lists_its_leaves() -> None:
    scheme = _line(["11", "22", "33", "44", "55"])
    extracted = _extracted([("1", "11"), ("2", "11"), ("3", "22"), ("4", "33"), ("5", "55")])
    checks = check_shift(extracted, scheme, DEFAULTS)
    assert checks[0].scope == "paper" and not checks[0].passed
    assert checks[0].question_ids == ["2", "3", "4"]
    assert len(checks) == 1


def test_g7_respects_non_default_min_matches() -> None:
    scheme = _line(["11", "22", "33", "44", "55"])
    extracted = _extracted([("1", "11"), ("2", "11"), ("3", "22"), ("4", "33"), ("5", "55")])
    strict = replace(DEFAULTS, shift_min_matches=4)
    checks = check_shift(extracted, scheme, strict)
    assert checks[0].passed
    question = _by(checks, "G7", "question")
    assert question is not None and question.question_ids == ["2", "3", "4"]
    lenient = replace(DEFAULTS, shift_min_matches=2)
    assert not check_shift(_extracted([("1", "11"), ("2", "11"), ("3", "22")]), scheme, lenient)[
        0
    ].passed


def test_g7_gap_larger_than_shift_max_gap_splits_a_run() -> None:
    values = [str(11 * (i + 1)) for i in range(10)]
    scheme = _line(values)
    extracted = _extracted(
        [("1", "11"), ("2", "11"), ("3", "22"), ("7", "66"), ("8", "77")]
    )  # 4, 5, 6 absent: the pointing leaves 3 and 7 are four apart
    assert check_shift(extracted, scheme, DEFAULTS)[0].passed
    wide = replace(DEFAULTS, shift_max_gap=4)
    joined = check_shift(extracted, scheme, wide)[0]
    assert not joined.passed and joined.question_ids == ["2", "3", "7", "8"]


def test_g7_none_leaves_inside_a_run_are_allowed() -> None:
    scheme = _line(["11", "22", "33", "44", "55", "66", "77"])
    # 2, 3 and 5 point previous; 4 is blank and so contributes nothing.
    extracted = _extracted([("1", "11"), ("2", "11"), ("3", "22"), ("5", "44")])
    paper = check_shift(extracted, scheme, DEFAULTS)[0]
    assert not paper.passed and paper.question_ids == ["2", "3", "5"]


def test_g7_shift_by_two_is_detected() -> None:
    scheme = _line([str(11 * (i + 1)) for i in range(8)])
    extracted = _extracted([(str(i), str(11 * (i - 2))) for i in range(3, 9)])
    paper = check_shift(extracted, scheme, DEFAULTS)[0]
    assert not paper.passed and paper.question_ids == ["3", "4", "5", "6", "7", "8"]
    assert "two" in paper.detail


def test_g7_shift_by_two_the_other_way_is_detected() -> None:
    scheme = _line([str(11 * (i + 1)) for i in range(8)])
    extracted = _extracted([(str(i), str(11 * (i + 2))) for i in range(1, 6)])
    paper = check_shift(extracted, scheme, DEFAULTS)[0]
    assert not paper.passed and paper.question_ids == ["1", "2", "3", "4", "5"]


def test_g7_shift_by_three_is_out_of_reach() -> None:
    scheme = _line([str(11 * (i + 1)) for i in range(8)])
    extracted = _extracted([(str(i), str(11 * (i - 3))) for i in range(4, 9)])
    assert all(c.passed for c in check_shift(extracted, scheme, DEFAULTS))


def test_g7_leaf_pointing_both_ways_counts_in_both_offsets_and_is_listed_once() -> None:
    scheme = _line(["5", "7", "5", "7", "5", "7"])
    extracted = _extracted([("2", "5"), ("3", "7"), ("4", "5"), ("5", "7")])
    paper = check_shift(extracted, scheme, DEFAULTS)[0]
    assert not paper.passed
    assert paper.question_ids == ["2", "3", "4", "5"]
    assert "previous" in paper.detail and "next" in paper.detail


def test_g7_leaf_matching_own_and_neighbour_does_not_break_a_run() -> None:
    # Questions 2 and 3 share the value 22; everything is shifted later by one.
    scheme = _line(["11", "22", "22", "44", "55", "66"])
    extracted = _extracted(
        [("1", "11"), ("2", "11"), ("3", "22"), ("4", "22"), ("5", "44"), ("6", "55")]
    )
    paper = check_shift(extracted, scheme, DEFAULTS)[0]
    assert not paper.passed
    assert paper.question_ids == ["2", "4", "5", "6"]


def test_g7_own_only_match_breaks_a_run() -> None:
    scheme = _line(["11", "22", "33", "44", "55", "66"])
    extracted = _extracted(
        [("1", "11"), ("2", "11"), ("3", "22"), ("4", "44"), ("5", "44"), ("6", "55")]
    )
    assert check_shift(extracted, scheme, DEFAULTS)[0].passed


def test_g7_opposite_pointer_inside_a_real_run_does_not_split_it() -> None:
    scheme = _line([str(11 * (i + 1)) for i in range(8)])
    extracted = _extracted([("2", "11"), ("3", "22"), ("4", "55"), ("5", "44"), ("6", "55")])
    checks = check_shift(extracted, scheme, DEFAULTS)
    assert not checks[0].passed
    assert checks[0].question_ids == ["2", "3", "5", "6"]
    question = _by(checks, "G7", "question")
    assert question is not None and question.question_ids == ["4"]


def test_g7_leaf_already_in_a_paper_run_is_not_repeated_at_question_scope() -> None:
    # Leaf 4 holds 33: previous leaf's value (a run of three) and next leaf's (alone).
    scheme = _line(["11", "22", "33", "44", "33"])
    extracted = _extracted([("2", "11"), ("3", "22"), ("4", "33")])
    checks = check_shift(extracted, scheme, DEFAULTS)
    assert checks[0].question_ids == ["2", "3", "4"]
    assert len(checks) == 1


def test_g7_runs_are_per_offset() -> None:
    scheme = _line([str(11 * (i + 1)) for i in range(7)])
    # One leaf each pointing previous (3), next (5) and two back (7).
    extracted = _extracted([("3", "22"), ("5", "66"), ("7", "55")])
    checks = check_shift(extracted, scheme, DEFAULTS)
    assert checks[0].passed
    question = _by(checks, "G7", "question")
    assert question is not None and question.question_ids == ["3", "5", "7"]


def test_g7_supports_a_larger_max_offset() -> None:
    scheme = _line([str(11 * (i + 1)) for i in range(7)])
    extracted = _extracted([("4", "11"), ("5", "22"), ("6", "33"), ("7", "44")])
    wide = replace(DEFAULTS, shift_max_offset=3)
    paper = check_shift(extracted, scheme, wide)[0]
    assert not paper.passed and paper.question_ids == ["4", "5", "6", "7"]
    assert "three before it" in paper.detail
    assert check_shift(extracted, scheme, DEFAULTS)[0].passed


def test_g7_larger_offset_on_the_other_side_is_worded() -> None:
    scheme = _line([str(11 * (i + 1)) for i in range(7)])
    extracted = _extracted([("1", "44"), ("2", "55"), ("3", "66")])
    wide = replace(DEFAULTS, shift_max_offset=4)
    assert "three after it" in check_shift(extracted, scheme, wide)[0].detail


def test_g7_answer_matching_its_own_leaf_never_points_away() -> None:
    scheme = _line(["5", "5", "5", "5", "5"])
    extracted = _extracted([(str(i), "5") for i in range(1, 6)])
    checks = check_shift(extracted, scheme, DEFAULTS)
    assert all(c.passed for c in checks) and len(checks) == 1


def test_g7_is_silent_when_a_student_is_simply_wrong() -> None:
    scheme = _line(["11", "22", "33", "44", "55"])
    extracted = _extracted([(str(i), "999") for i in range(1, 6)])
    assert all(c.passed for c in check_shift(extracted, scheme, DEFAULTS))


def test_g7_shifted_shape_with_extra_working_is_ignored() -> None:
    scheme = _line(["11", "22", "33", "44", "55"])
    extracted = _extracted([("2", "11 x 2 = 22"), ("3", "22 + 1 = 23"), ("4", "33 + 1 = 34")])
    assert all(c.passed for c in check_shift(extracted, scheme, DEFAULTS))


def test_g7_paper_check_comes_first() -> None:
    scheme = _line(["11", "22", "33", "44"])
    extracted = _extracted([("1", "11"), ("2", "11"), ("3", "22"), ("4", "44")])
    assert check_shift(extracted, scheme, DEFAULTS)[0].scope == "paper"


def test_g7_excludes_mcq_leaves() -> None:
    # Three MCQ leaves with numeric-looking keys, answered with a neighbour's number:
    # without the exclusion they form a run.
    leaves = [_leaf("1", "11"), _leaf("2", "22", mcq=True), _leaf("3", "33", mcq=True)]
    leaves.append(_leaf("4", "44", mcq=True))
    extracted = _extracted([("1", "11"), ("2", "11"), ("3", "22"), ("4", "33")])
    assert all(c.passed for c in check_shift(extracted, _scheme(leaves), DEFAULTS))


def test_g7_mcq_leaf_is_not_a_neighbour() -> None:
    # With the MCQ leaf removed, leaf 3 sits next to leaf 1; both orders must be silent.
    leaves = [_leaf("1", "11"), _leaf("2", "22", mcq=True), _leaf("3", "33")]
    extracted = _extracted([("3", "22")])
    assert all(c.passed for c in check_shift(extracted, _scheme(leaves), DEFAULTS))


def test_g7_details_name_the_right_neighbour() -> None:
    scheme = _line(["11", "22", "33", "44", "55"])
    later = _extracted([("1", "22"), ("2", "33"), ("3", "44"), ("4", "55")])
    paper = check_shift(later, scheme, DEFAULTS)[0]
    assert not paper.passed and "next" in paper.detail and "previous" not in paper.detail
    earlier = _extracted([("2", "11"), ("3", "22"), ("4", "33")])
    paper = check_shift(earlier, scheme, DEFAULTS)[0]
    assert "previous" in paper.detail and "next" not in paper.detail


def test_g7_question_scope_detail_is_grammatical_for_one_leaf() -> None:
    scheme = _line(["11", "22", "33"])
    check = _by(check_shift(_extracted([("2", "11")]), scheme, DEFAULTS), "G7", "question")
    assert check is not None and "1 answer holds" in check.detail


# --- G8 ---------------------------------------------------------------------


def _correction(flags: list[str | None]) -> CorrectionResult:
    return CorrectionResult.model_validate(
        {
            "metadata": {
                "subject_code": "0625",
                "paper_number": 4,
                "paper_variant": 1,
                "session_month": "Oct/Nov",
            },
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
        }
    )


def test_g8_counts_a_run_of_three() -> None:
    check = check_off_topic(_correction(["yes", "no", "no", "no", "yes"]), DEFAULTS)
    assert not check.passed and check.scope == "paper"
    assert check.question_ids == ["2", "3", "4"]


@pytest.mark.parametrize(
    "flags",
    [["no", "no", None, "no"], ["no", "unclear", "no", "no"]],
)
def test_g8_unjudged_leaves_do_not_break_a_run(flags: list[str | None]) -> None:
    check = check_off_topic(_correction(flags), DEFAULTS)
    assert not check.passed and check.scope == "paper"


def test_g8_only_yes_breaks_a_run() -> None:
    check = check_off_topic(_correction(["no", "yes", "no", "no"]), DEFAULTS)
    assert not check.passed and check.scope == "question"


def test_g8_unjudged_leaves_do_not_count_toward_the_total() -> None:
    flags: list[str | None] = ["no", "yes", "no", "yes", "no", None, "unclear", None]
    check = check_off_topic(_correction(flags), DEFAULTS)
    assert check.scope == "question" and check.question_ids == ["1", "3", "5"]


def test_g8_count_threshold_and_pass() -> None:
    scattered: list[str | None] = ["no", "yes", "no", "yes", "no", "yes", "no"]
    check = check_off_topic(_correction(scattered), DEFAULTS)
    assert check.scope == "paper"
    assert "in a row" not in check.detail
    assert check_off_topic(_correction(["yes", "unclear", None]), DEFAULTS).passed


def test_g8_run_detail_names_the_run() -> None:
    check = check_off_topic(_correction(["no", "no", "no"]), DEFAULTS)
    assert "3 in a row" in check.detail


# --- G9 ---------------------------------------------------------------------

SENTENCES = [
    "the car slows down because of friction",
    "heat is lost to the surrounding air",
    "the current is the same everywhere",
    "light bends when it enters the glass",
    "the pressure increases with the depth",
    "sound needs a medium to travel through",
    "the magnet attracts the iron nail",
    "energy is transferred by the moving charge",
    "the wave reflects off the smooth surface",
    "the gas expands when it is heated up",
]


def _reads(rotated: int, ids: list[str] | None = None) -> tuple[ExtractedAnswers, ExtractedAnswers]:
    ids = ids or [f"q{i}" for i in range(len(SENTENCES))]
    first = _extracted(list(zip(ids, SENTENCES, strict=True)))
    texts = list(SENTENCES)
    for i in range(rotated):
        texts[i] = SENTENCES[(i + 1) % rotated]
    return first, _extracted(list(zip(ids, texts, strict=True)))


def _text_scheme(ids: list[str] | None = None, *, mcq: bool = False) -> MarkScheme:
    names = ids or [f"q{i}" for i in range(len(SENTENCES))]
    return _scheme([_leaf(n, "5", mcq=mcq) for n in names])


def test_g9_detects_text_agreeing_under_a_different_id() -> None:
    first, second = _reads(4)
    check = check_second_read(first, second, _text_scheme(), DEFAULTS)
    assert not check.passed and check.scope == "paper"
    assert check.question_ids == ["q0", "q1", "q2", "q3"]


def test_g9_few_disagreements_fail_at_question_scope() -> None:
    first, second = _reads(2)
    check = check_second_read(first, second, _text_scheme(), DEFAULTS)
    assert not check.passed and check.scope == "question"
    assert check.question_ids == ["q0", "q1"]


def test_g9_rate_must_exceed_the_limit_for_paper_scope() -> None:
    first, second = _reads(4)
    lenient = replace(DEFAULTS, second_read_disagreement_rate=0.4)  # 4 of 10 is not above 0.4
    assert check_second_read(first, second, _text_scheme(), lenient).scope == "question"
    few = replace(DEFAULTS, second_read_min_disagreeing=5)
    assert check_second_read(first, second, _text_scheme(), few).scope == "question"


def test_g9_ignores_a_plain_rereading_difference() -> None:
    first = _extracted([("q0", "the speed is 4.9 N"), ("q1", "heat is lost quickly")])
    second = _extracted([("q0", "the speed is 4.8 N"), ("q1", "heat is lost quickly")])
    scheme = _text_scheme(["q0", "q1"])
    assert check_second_read(first, second, scheme, DEFAULTS).passed
    unrelated = _extracted([("q0", "zzzzzzzzzzzzzz"), ("q1", "heat is lost quickly")])
    assert check_second_read(first, unrelated, scheme, DEFAULTS).passed


def test_g9_excludes_mcq_leaves() -> None:
    ids = [f"q{i}" for i in range(len(SENTENCES))]
    first, second = _reads(4)
    check = check_second_read(first, second, _text_scheme(ids, mcq=True), DEFAULTS)
    assert check.passed


def test_g9_ignores_short_answers() -> None:
    ids = [f"q{i}" for i in range(6)]
    words = ["cat", "dog", "pig", "hen", "cow", "owl"]
    first = _extracted(list(zip(ids, words, strict=True)))
    second = _extracted(list(zip(ids, [*words[1:4], words[0], *words[4:]], strict=True)))
    assert check_second_read(first, second, _text_scheme(ids), DEFAULTS).passed
    short = replace(DEFAULTS, second_read_min_chars=3)
    assert not check_second_read(first, second, _text_scheme(ids), short).passed


def test_g9_ignores_blank_and_whitespace_only_answers() -> None:
    first, second = _reads(4)
    blank = _extracted([("q0", "   "), ("q1", "")])
    scheme = _text_scheme()
    assert check_second_read(blank, second, scheme, DEFAULTS).passed
    assert check_second_read(first, blank, scheme, DEFAULTS).passed


def test_g9_normalises_whitespace_before_measuring_length() -> None:
    ids = [f"q{i}" for i in range(6)]
    words = ["cat", "dog", "pig", "hen", "cow", "owl"]
    padded = [f"  {w}    " for w in words]  # long raw, three characters once collapsed
    first = _extracted(list(zip(ids, padded, strict=True)))
    swapped = [*padded[1:4], padded[0], *padded[4:]]
    second = _extracted(list(zip(ids, swapped, strict=True)))
    assert check_second_read(first, second, _text_scheme(ids), DEFAULTS).passed


def test_g9_shared_answers_are_not_evidence() -> None:
    near_a = "the force acts upward on the box"
    near_b = "the force acts upwards on the box"
    reread = "the force pushes upwards on the box"
    first = _extracted([("q0", near_a), ("q1", near_b)])
    second = _extracted([("q0", reread), ("q1", near_b)])
    scheme = _text_scheme(["q0", "q1"])
    floor = replace(DEFAULTS, agreement_floor=0.875)
    # q0's re-read matches q1's first answer, but q1 says the same as q0 did.
    assert check_second_read(first, second, scheme, floor).passed


def test_g9_pass_detail_and_empty_input() -> None:
    check = check_second_read(_extracted([]), _extracted([]), _text_scheme(), DEFAULTS)
    assert check.passed and check.scope == "paper"


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


def test_g7_reproduction_shared_value_shift_fails_at_paper_scope() -> None:
    scheme = _line(["11", "22", "22", "44", "55", "66"])
    extracted = _extracted(
        [("1", "11"), ("2", "11"), ("3", "22"), ("4", "22"), ("5", "44"), ("6", "55")]
    )
    assert not check_shift(extracted, scheme, DEFAULTS)[0].passed
