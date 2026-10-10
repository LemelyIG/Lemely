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
    # Measured with scripts/sweep_binding_gate.py at the default limits over 210 corpus schemes:
    # perfect 0.5%, weak-random 0.0%, weak-nearby 3.8%, overall 1.4%.
    schemes, skipped = load_corpus()
    assert not skipped and len(schemes) > 100
    papers = simulated_students(schemes)
    held = Counter(
        kind for kind, _n, scheme, answers in papers if paper_fails(extracted_from(answers), scheme)
    )
    total = Counter(kind for kind, *_ in papers)
    assert sum(held.values()) / len(papers) <= 0.02
    for kind in STUDENT_TYPES:
        assert held[kind] / total[kind] <= 0.05, kind


def test_gate_catches_whole_paper_shifts_where_it_can_see() -> None:
    # Measured over the 160 schemes (of 210) with at least shift_min_matches valued
    # non-MCQ leaves, both directions: 97.8% caught (later 98.8%, earlier 96.9%).
    # The floor is that minus 2 points. Schemes with fewer valued leaves are not asserted:
    # the pre-marking checks cannot see a shift there (see the sweep report).
    schemes, _ = load_corpus()
    minimum = GateThresholds().shift_min_matches
    papers = [
        (scheme, answers)
        for _by, _n, scheme, answers in whole_paper_shifts(schemes)
        if valued_leaf_count(scheme) >= minimum
    ]
    assert len(papers) == 320
    caught = sum(paper_fails(extracted_from(answers), scheme) for scheme, answers in papers)
    assert caught / len(papers) >= 0.958
    assert caught / len(papers) >= 0.90
