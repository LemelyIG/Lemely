"""Simulated students and corpus papers for measuring the pre-marking binding checks.

Shared by ``tests/test_binding_gate_sweep.py`` and ``scripts/sweep_binding_gate.py`` so
the tests and the threshold sweep measure the same papers. Everything is seeded.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from lemely.accuracy.metamorphic import drop_answer, shift_answers, split_answer
from lemely.core.binding_expect import expected_numeric_values
from lemely.core.binding_gate import (
    GateThresholds,
    check_duplicate_ids,
    check_shape,
    check_shift,
    check_unknown_ids,
)
from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.schemas import ExtractedAnswers

if TYPE_CHECKING:
    from collections.abc import Mapping

SEED = 20261009
ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus" / "mark-schemes"
STUDENT_TYPES = ("perfect", "weak-random", "weak-nearby")
WEAK_SHARE = 0.4
Scheme = tuple[str, MarkScheme]
_GUESS_TEXT = "I am not sure of this one"
_TRAILING_MARKS = re.compile(r"\s+\d+\s*$")


def leaves(scheme: MarkScheme) -> list[Question]:
    """The scheme's leaves in paper order, as the gate counts them."""
    return [q for q in scheme.all_questions_flat() if not q.parts and q.marks > 0]


def is_mcq(question: Question) -> bool:
    return question.type == QuestionType.MCQ or question.mcq_answer is not None


def valued_leaf_count(scheme: MarkScheme) -> int:
    """Non-multiple-choice leaves with a numeric expected answer: all the shift check sees."""
    return sum(1 for q in leaves(scheme) if not is_mcq(q) and expected_numeric_values(q))


def load_corpus(
    *, include_mcq_only: bool = False
) -> tuple[list[tuple[str, MarkScheme]], list[str]]:
    """Corpus schemes that have a non-MCQ leaf (in file-name order), and the files skipped.

    A file is skipped when it does not validate; a scheme with no non-MCQ leaf is
    left out of the list (unless ``include_mcq_only``) but is not a failure.
    """
    schemes: list[tuple[str, MarkScheme]] = []
    skipped: list[str] = []
    for path in sorted(CORPUS_DIR.glob("*.json")):
        try:
            scheme = MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            skipped.append(path.name)
            continue
        if include_mcq_only or any(not is_mcq(q) for q in leaves(scheme)):
            schemes.append((path.stem, scheme))
    return schemes, skipped


def perfect_answer(question: Question) -> str:
    """What a student who got the leaf right writes."""
    if question.mcq_answer is not None:
        return str(question.mcq_answer.value)
    values = expected_numeric_values(question)
    if values:
        return values[0]
    if not question.answer_points:
        return "see working"
    # A mark-scheme bullet ends with its mark count ("Resistors in parallel 1"); a student
    # does not write that digit. Left in, the gate reads the short prose as a bare number.
    return _TRAILING_MARKS.sub("", question.answer_points[0].point)


def _wrong_answer(question: Question, rng: random.Random) -> str:
    if question.mcq_answer is not None:
        letters = [letter for letter in "ABCD" if letter != question.mcq_answer.value]
        return rng.choice(letters)
    values = expected_numeric_values(question)
    if not values:
        return _GUESS_TEXT
    while True:
        guess = f"{rng.randint(1, 999)}" if rng.random() < 0.5 else f"{rng.uniform(1, 99):.1f}"
        if guess not in values:
            return guess


def perfect_student(scheme: MarkScheme) -> dict[str, str]:
    return {q.id: perfect_answer(q) for q in leaves(scheme)}


def weak_random_student(scheme: MarkScheme, rng: random.Random) -> dict[str, str]:
    """A seeded 40% of the answers replaced by a wrong value of the right shape."""
    answers = perfect_student(scheme)
    for q in leaves(scheme):
        if rng.random() < WEAK_SHARE:
            answers[q.id] = _wrong_answer(q, rng)
    return answers


def weak_nearby_student(scheme: MarkScheme, rng: random.Random) -> dict[str, str]:
    """A seeded 40% replaced by the answer of a leaf two to four positions away."""
    perfect = perfect_student(scheme)
    order = leaves(scheme)
    answers = dict(perfect)
    for i, q in enumerate(order):
        if rng.random() >= WEAK_SHARE:
            continue
        reachable = [j for d in (2, 3, 4) for j in (i - d, i + d) if 0 <= j < len(order)]
        if reachable:
            answers[q.id] = perfect[order[rng.choice(reachable)].id]
    return answers


def weak_adjacent_student(scheme: MarkScheme, rng: random.Random, share: float) -> dict[str, str]:
    """A seeded ``share`` of answers replaced by the answer of a leaf one or two positions away.

    Sensitivity only, never a false-hold limit: a paper whose answers sit on the
    neighbouring question is, by construction, indistinguishable from a short shift.
    """
    perfect = perfect_student(scheme)
    order = leaves(scheme)
    answers = dict(perfect)
    for i, q in enumerate(order):
        if rng.random() >= share:
            continue
        reachable = [j for d in (1, 2) for j in (i - d, i + d) if 0 <= j < len(order)]
        if reachable:
            answers[q.id] = perfect[order[rng.choice(reachable)].id]
    return answers


def adjacent_students(
    schemes: list[Scheme], share: float
) -> list[tuple[str, MarkScheme, dict[str, str]]]:
    """(scheme name, scheme, answers) for the weak-adjacent student at ``share``, seeded."""
    rng = random.Random(SEED)
    return [(name, sc, weak_adjacent_student(sc, rng, share)) for name, sc in schemes]


def student_answers(kind: str, scheme: MarkScheme, rng: random.Random) -> dict[str, str]:
    if kind == "perfect":
        return perfect_student(scheme)
    if kind == "weak-random":
        return weak_random_student(scheme, rng)
    if kind == "weak-nearby":
        return weak_nearby_student(scheme, rng)
    raise ValueError(kind)


def extracted_from(answers: Mapping[str, str]) -> ExtractedAnswers:
    return ExtractedAnswers.model_validate(
        {
            "paper_id": "sim",
            "source_scan": "sim.pdf",
            "answers": [
                {"question_id": qid, "answer": text, "confidence": 1.0}
                for qid, text in answers.items()
            ],
        }
    )


@dataclass(frozen=True)
class PaperBits:
    """Which pre-marking checks fail at paper scope, per threshold setting."""

    ids: bool
    shape: dict[tuple[float, int], bool]
    shift: dict[tuple[int, int], bool]


def paper_fails(
    extracted: ExtractedAnswers, scheme: MarkScheme, thresholds: GateThresholds | None = None
) -> bool:
    """True when G1, G2, G6 or G7 fails at paper scope."""
    limits = thresholds or GateThresholds()
    checks = [
        check_unknown_ids(extracted, scheme),
        check_duplicate_ids(extracted),
        check_shape(extracted, scheme, limits),
        *check_shift(extracted, scheme, limits),
    ]
    return any(c.scope == "paper" and not c.passed for c in checks)


def paper_bits(
    extracted: ExtractedAnswers,
    scheme: MarkScheme,
    shape_grid: list[tuple[float, int]],
    shift_grid: list[tuple[int, int]],
) -> PaperBits:
    """Evaluate the checks once per distinct setting of the parameters each one reads."""
    base = GateThresholds()
    ids = not (
        check_unknown_ids(extracted, scheme).passed and check_duplicate_ids(extracted).passed
    )
    shape = {
        (rate, count): not check_shape(
            extracted,
            scheme,
            replace(base, shape_mismatch_rate=rate, shape_min_count=count),
        ).passed
        for rate, count in shape_grid
    }
    shift = {
        (matches, gap): any(
            c.scope == "paper" and not c.passed
            for c in check_shift(
                extracted,
                scheme,
                replace(base, shift_min_matches=matches, shift_max_gap=gap),
            )
        )
        for matches, gap in shift_grid
    }
    return PaperBits(ids=ids, shape=shape, shift=shift)


WINDOWS = (3, 5, 10, 20)


def simulated_students(schemes: list[Scheme]) -> list[tuple[str, str, MarkScheme, dict[str, str]]]:
    """(student type, scheme name, scheme, answers): three students per scheme, seeded."""
    rng = random.Random(SEED)
    return [
        (kind, name, scheme, student_answers(kind, scheme, rng))
        for name, scheme in schemes
        for kind in STUDENT_TYPES
    ]


def whole_paper_shifts(
    schemes: list[Scheme],
) -> list[tuple[int, str, MarkScheme, dict[str, str]]]:
    """(by, scheme name, scheme, answers): the perfect student shifted a leaf later and earlier."""
    papers = []
    for name, scheme in schemes:
        order = [q.id for q in leaves(scheme)]
        perfect = perfect_student(scheme)
        papers.extend(
            (by, name, scheme, shift_answers(perfect, order, start=0, by=by)) for by in (1, -1)
        )
    return papers


def partial_shifts(
    schemes: list[Scheme],
) -> list[tuple[int, str, MarkScheme, dict[str, str]]]:
    """(window, scheme name, scheme, answers): a window of leaves one later, at a seeded start."""
    rng = random.Random(SEED)
    papers = []
    for name, scheme in schemes:
        order = [q.id for q in leaves(scheme)]
        perfect = perfect_student(scheme)
        for window in WINDOWS:
            if len(order) < window:
                continue
            start = rng.randint(0, len(order) - window)
            moved = shift_answers(perfect, order, start=start, by=1, length=window)
            papers.append((window, name, scheme, moved))
    return papers


def split_and_drops(
    schemes: list[Scheme],
) -> list[tuple[str, str, MarkScheme, dict[str, str]]]:
    """(``split`` or ``drop``, scheme name, scheme, answers) at a seeded leaf in the first half."""
    rng = random.Random(SEED)
    papers = []
    for name, scheme in schemes:
        order = [q.id for q in leaves(scheme)]
        if len(order) < 4:
            continue
        perfect = perfect_student(scheme)
        at = rng.randint(0, len(order) // 2)
        papers.append(("split", name, scheme, split_answer(perfect, order, at=at)))
        papers.append(("drop", name, scheme, drop_answer(perfect, order, at=at)))
    return papers
