"""Misbinding transforms, and the rates the pre-marking binding checks can honestly promise."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from lemely.accuracy.harness import load_golden_cases
from lemely.accuracy.metamorphic import drop_answer, shift_answers, split_answer
from lemely.core.binding_gate import GateThresholds
from tests.binding_students import (
    STUDENT_TYPES,
    extracted_from,
    load_corpus,
    paper_fails,
    simulated_students,
    valued_leaf_count,
    whole_paper_shifts,
)

_GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

ORDER = ["1", "2", "3", "4", "5", "6"]
ANSWERS = {"1": "a1", "2": "a2", "3": "a3 a3", "4": "a4", "5": "a5", "6": "a6"}


def test_shift_split_drop_move_the_expected_answers() -> None:
    # Everything one leaf later; the first leaf is left without an answer.
    assert shift_answers(ANSWERS, ORDER, start=0, by=1) == {
        "2": "a1",
        "3": "a2",
        "4": "a3 a3",
        "5": "a4",
        "6": "a5",
    }
    # Everything one leaf earlier; the last leaf is left without an answer.
    assert shift_answers(ANSWERS, ORDER, start=0, by=-1) == {
        "1": "a2",
        "2": "a3 a3",
        "3": "a4",
        "4": "a5",
        "5": "a6",
    }
    # From leaf 3 on, one later; the earlier leaves keep their answers.
    assert shift_answers(ANSWERS, ORDER, start=2, by=1) == {
        "1": "a1",
        "2": "a2",
        "4": "a3 a3",
        "5": "a4",
        "6": "a5",
    }
    # A window of two leaves: the answer pushed past its end is lost.
    assert shift_answers(ANSWERS, ORDER, start=1, by=1, length=2) == {
        "1": "a1",
        "3": "a2",
        "4": "a4",
        "5": "a5",
        "6": "a6",
    }
    # Cut leaf 3's answer in two; the rest moves one later and the last falls off.
    assert split_answer(ANSWERS, ORDER, at=2) == {
        "1": "a1",
        "2": "a2",
        "3": "a3",
        "4": "a3",
        "5": "a4",
        "6": "a5",
    }
    # Lose leaf 2's answer; the rest moves one earlier.
    assert drop_answer(ANSWERS, ORDER, at=1) == {
        "1": "a1",
        "2": "a3 a3",
        "3": "a4",
        "4": "a5",
        "5": "a6",
    }


def test_split_and_drop_at_the_last_leaf() -> None:
    # Splitting the last answer ("a6" into "a" and "6"): the second half has no leaf and falls off.
    assert split_answer(ANSWERS, ORDER, at=5) == {**ANSWERS, "6": "a"}
    # Dropping the last answer: nothing after it moves.
    assert drop_answer(ANSWERS, ORDER, at=5) == {k: v for k, v in ANSWERS.items() if k != "6"}


def test_transforms_keep_gaps_and_leave_the_input_alone() -> None:
    answers = {"1": "x", "3": "y"}
    assert shift_answers(answers, ORDER, start=0, by=1) == {"2": "x", "4": "y"}
    assert drop_answer(answers, ORDER, at=0) == {"2": "y"}
    assert answers == {"1": "x", "3": "y"}


def test_gate_holds_no_unshifted_golden_case() -> None:
    cases = load_golden_cases(_GOLDEN_DIR)
    assert cases and not cases.unparseable
    held = [
        f"{case.paper_id}_{case.fixture_variant}"
        for case in cases
        if paper_fails(
            extracted_from({qid: a.student_answer for qid, a in case.ground_truth.items()}),
            case.mark_scheme,
        )
    ]
    assert held == []


def test_gate_holds_at_most_2_percent_of_simulated_correct_papers() -> None:
    # Measured with scripts/sweep_binding_gate.py at the default limits over the 210 corpus
    # schemes with a non-MCQ leaf (630 papers): perfect 0/210, weak-random 0/210, weak-nearby
    # 5/210 (2.4%, four G6 and one G7), overall 5/630 (0.8%). The weak-nearby student mostly
    # exercises G6: two thirds of its picks lie beyond G7's two-position window.
    schemes, skipped = load_corpus()
    assert not skipped and len(schemes) > 100
    papers = simulated_students(schemes)
    held = Counter(
        kind for kind, _n, scheme, answers in papers if paper_fails(extracted_from(answers), scheme)
    )
    total = Counter(kind for kind, *_ in papers)
    assert held["perfect"] == 0
    assert sum(held.values()) / len(papers) <= 0.02
    for kind in STUDENT_TYPES:
        assert held[kind] / total[kind] <= 0.05, kind


def test_gate_catches_whole_paper_shifts_where_it_can_see() -> None:
    # Measured over the 160 schemes (of 210 with a non-MCQ leaf) that have at least
    # shift_min_matches valued non-MCQ leaves, both directions: 314/320 = 98.1% caught
    # (later 98.8%, earlier 97.5%). The floor is that minus 2 points.
    # This is NOT the share of all shifted papers caught. Over the 210 schemes it is
    # 330/420 (78.6%); over all 289 validated schemes, 79 of them multiple-choice only
    # where these checks see nothing, it is 330/578 (57.1%), so 42.9% pass unnoticed.
    schemes, _ = load_corpus()
    minimum = GateThresholds().shift_min_matches
    papers = [
        (scheme, answers)
        for _by, _n, scheme, answers in whole_paper_shifts(schemes)
        if valued_leaf_count(scheme) >= minimum
    ]
    assert len(papers) == 320
    caught = sum(paper_fails(extracted_from(answers), scheme) for scheme, answers in papers)
    assert caught / len(papers) >= 0.961
