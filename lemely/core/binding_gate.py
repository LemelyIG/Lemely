"""Gate checks that decide whether extracted answers are tied to the right questions.

Each check looks at one kind of evidence and returns a ``BindingCheck``. A check
that fails at paper scope means the binding as a whole cannot be trusted; one
that fails at question scope only names the questions to look at again.
``verdict`` turns the checks into pass, retry or hold.

Pure functions: nothing here reads files, logs or calls a model.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lemely.core.binding import BindingCheck, BindingVerdict
from lemely.core.binding_expect import (
    answer_shape,
    expected_numeric_values,
    expected_shape,
    matches_expected,
)
from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.text_agreement import text_agreement

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lemely.core.schemas import CorrectionResult, ExtractedAnswers

_SHOWN_IDS = 6
_AGREEMENT_FLOOR = 0.8
_UNALIGNED_PAPER_RATE = 0.10
_NEIGHBOURHOOD = 2


@dataclass(frozen=True)
class GateThresholds:
    """Provisional limits; a later measurement replaces the defaults."""

    shape_mismatch_rate: float = 0.25
    shift_min_matches: int = 3
    off_topic_count: int = 4
    off_topic_run: int = 3
    second_read_disagreement_rate: float = 0.10


def _leaves(mark_scheme: MarkScheme) -> list[Question]:
    return [q for q in mark_scheme.all_questions_flat() if not q.parts and q.marks > 0]


def _is_mcq(question: Question) -> bool:
    return question.type == QuestionType.MCQ or question.mcq_answer is not None


def _listed(ids: Iterable[str]) -> str:
    ordered = list(ids)
    text = ", ".join(ordered[:_SHOWN_IDS])
    return text + ", …" if len(ordered) > _SHOWN_IDS else text


def _answers_by_id(extracted: ExtractedAnswers) -> dict[str, str]:
    """First non-blank answer text per id."""
    found: dict[str, str] = {}
    for item in extracted.answers:
        if item.answer.strip():
            found.setdefault(item.question_id, item.answer)
    return found


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def check_unknown_ids(extracted: ExtractedAnswers, mark_scheme: MarkScheme) -> BindingCheck:
    """G1: fails when an answer carries an id that is not a leaf of the mark scheme."""
    known = {q.id for q in _leaves(mark_scheme)}
    unknown = list(
        dict.fromkeys(a.question_id for a in extracted.answers if a.question_id not in known)
    )
    if not unknown:
        return BindingCheck(
            id="G1", passed=True, scope="paper", detail="Every answer is on a question that exists."
        )
    return BindingCheck(
        id="G1",
        passed=False,
        scope="paper",
        question_ids=unknown,
        detail=f"{_plural(len(unknown), 'answer id')} not in the mark scheme: {_listed(unknown)}.",
    )


def check_duplicate_ids(extracted: ExtractedAnswers) -> BindingCheck:
    """G2: fails when two answers claim the same question id."""
    counts = Counter(a.question_id for a in extracted.answers)
    repeated = [qid for qid, n in counts.items() if n > 1]
    if not repeated:
        return BindingCheck(
            id="G2", passed=True, scope="paper", detail="No question has more than one answer."
        )
    return BindingCheck(
        id="G2",
        passed=False,
        scope="paper",
        question_ids=repeated,
        detail=(
            f"{_plural(len(repeated), 'question')} answered more than once: {_listed(repeated)}."
        ),
    )


def check_label_coverage(
    extracted: ExtractedAnswers,
    mark_scheme: MarkScheme,
    unaligned_ids: list[str],
    unmatched_markers: int,
) -> BindingCheck:
    """G5: fails when question labels on the page could not be lined up with the mark scheme.

    Paper scope when more than 10% of the leaves are unaligned or a marker matched
    no question. Otherwise question scope for unaligned leaves that still hold a
    non-blank answer.
    """
    leaf_ids = [q.id for q in _leaves(mark_scheme)]
    unaligned = [qid for qid in leaf_ids if qid in set(unaligned_ids)]
    answered = _answers_by_id(extracted)
    if leaf_ids and len(unaligned) / len(leaf_ids) > _UNALIGNED_PAPER_RATE:
        return BindingCheck(
            id="G5",
            passed=False,
            scope="paper",
            question_ids=unaligned,
            detail=(
                f"{len(unaligned)} of {len(leaf_ids)} questions could not be lined up "
                f"with a label on the page: {_listed(unaligned)}."
            ),
        )
    if unmatched_markers > 0:
        return BindingCheck(
            id="G5",
            passed=False,
            scope="paper",
            question_ids=unaligned,
            detail=(
                f"{_plural(unmatched_markers, 'label')} on the page matched no question "
                "in the mark scheme."
            ),
        )
    with_answer = [qid for qid in unaligned if qid in answered]
    if with_answer:
        return BindingCheck(
            id="G5",
            passed=False,
            scope="question",
            question_ids=with_answer,
            detail=(
                f"{_plural(len(with_answer), 'answered question')} had no label to line up with: "
                f"{_listed(with_answer)}."
            ),
        )
    return BindingCheck(
        id="G5",
        passed=True,
        scope="paper",
        detail="Every question lined up with a label on the page.",
    )


def check_shape(
    extracted: ExtractedAnswers, mark_scheme: MarkScheme, thresholds: GateThresholds
) -> BindingCheck:
    """G6: fails when too many answers are a different kind from what the question expects.

    Only answered, non-multiple-choice leaves with a known expected shape count; an
    answer whose shape is unknown never contradicts.
    """
    answered = _answers_by_id(extracted)
    shaped: list[str] = []
    contradicting: list[str] = []
    for leaf in _leaves(mark_scheme):
        if _is_mcq(leaf) or leaf.id not in answered:
            continue
        expected = expected_shape(leaf)
        if expected == "unknown":
            continue
        shaped.append(leaf.id)
        actual = answer_shape(answered[leaf.id])
        if actual != "unknown" and actual != expected:
            contradicting.append(leaf.id)
    rate = len(contradicting) / len(shaped) if shaped else 0.0
    if rate > thresholds.shape_mismatch_rate:
        return BindingCheck(
            id="G6",
            passed=False,
            scope="paper",
            question_ids=contradicting,
            detail=(
                f"{len(contradicting)} of {len(shaped)} answers are a different kind from what the "
                f"question asks for (a number, text or drawing): {_listed(contradicting)}."
            ),
        )
    return BindingCheck(
        id="G6",
        passed=True,
        scope="paper",
        detail=(
            f"{len(shaped) - len(contradicting)} of {len(shaped)} answers are the kind "
            "the question asks for."
        ),
    )


def check_shift(
    extracted: ExtractedAnswers, mark_scheme: MarkScheme, thresholds: GateThresholds
) -> list[BindingCheck]:
    """G7: fails when answers hold the value expected of a neighbouring question.

    Works over the non-multiple-choice leaves in manifest order. A leaf's neighbours
    on each side are the nearest leaves that have expected numeric values, skipping
    ones without, at most two on each side. An answered leaf "points away" in a
    direction when its answer matches one of the neighbours on that side and does
    not match its own leaf (an answer that matches its own leaf never points away,
    whatever its neighbours expect). An answer matching neighbours on both sides is
    ambiguous and ignored.

    For each direction, the paper-scope check fails when at least
    ``shift_min_matches`` leaves point that way and they outnumber the leaves that
    match themselves between the first and last of them. The failing check lists
    the pointing leaves. Leaves pointing away in a direction that does not fail
    that way are listed in a separate question-scope check. The paper-scope check
    is always first in the list.
    """
    answered = _answers_by_id(extracted)
    leaves = [q for q in _leaves(mark_scheme) if not _is_mcq(q)]
    valued = [bool(expected_numeric_values(q)) for q in leaves]

    def neighbours(index: int, step: int) -> list[Question]:
        found: list[Question] = []
        j = index + step
        while 0 <= j < len(leaves) and len(found) < _NEIGHBOURHOOD:
            if valued[j]:
                found.append(leaves[j])
            j += step
        return found

    own_match = [
        leaf.id in answered and matches_expected(answered[leaf.id], leaf) for leaf in leaves
    ]
    pointing: dict[str, list[int]] = {"previous": [], "next": []}
    for i, leaf in enumerate(leaves):
        if leaf.id not in answered or own_match[i]:
            continue
        text = answered[leaf.id]
        back = any(matches_expected(text, n) for n in neighbours(i, -1))
        forward = any(matches_expected(text, n) for n in neighbours(i, 1))
        if back != forward:
            pointing["previous" if back else "next"].append(i)

    paper_ids: list[int] = []
    paper_notes: list[str] = []
    leftover: list[int] = []
    for direction, indices in pointing.items():
        if not indices:
            continue
        span = range(indices[0], indices[-1] + 1)
        self_matching = sum(1 for i in span if own_match[i])
        if len(indices) >= thresholds.shift_min_matches and len(indices) > self_matching:
            paper_ids.extend(indices)
            paper_notes.append(
                f"{len(indices)} answers equal the {direction} question's expected value "
                f"while {self_matching} between them equal their own: "
                f"{_listed(leaves[i].id for i in indices)}"
            )
        else:
            leftover.extend(indices)

    checks: list[BindingCheck] = []
    if paper_ids:
        checks.append(
            BindingCheck(
                id="G7",
                passed=False,
                scope="paper",
                question_ids=[leaves[i].id for i in sorted(paper_ids)],
                detail="; ".join(paper_notes) + ".",
            )
        )
    else:
        checks.append(
            BindingCheck(
                id="G7",
                passed=True,
                scope="paper",
                detail="No run of answers holds the value expected of a neighbouring question.",
            )
        )
    if leftover:
        ids = [leaves[i].id for i in sorted(leftover)]
        checks.append(
            BindingCheck(
                id="G7",
                passed=False,
                scope="question",
                question_ids=ids,
                detail=(
                    f"{_plural(len(ids), 'answer')} equal a neighbouring question's expected value "
                    f"and not their own: {_listed(ids)}."
                ),
            )
        )
    return checks


def check_off_topic(correction: CorrectionResult, thresholds: GateThresholds) -> BindingCheck:
    """G8: fails when the marker says answers do not address their question.

    Paper scope at ``off_topic_count`` such questions, or ``off_topic_run`` in a row;
    below both, question scope for those questions.
    """
    flags = [q.addresses_question == "no" for q in correction.questions]
    off = [q.question_id for q, flag in zip(correction.questions, flags, strict=True) if flag]
    longest = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    if not off:
        return BindingCheck(
            id="G8", passed=True, scope="paper", detail="Every answer addresses its question."
        )
    if len(off) >= thresholds.off_topic_count or longest >= thresholds.off_topic_run:
        return BindingCheck(
            id="G8",
            passed=False,
            scope="paper",
            question_ids=off,
            detail=(
                f"{len(off)} answers were judged not to address their question, "
                f"{longest} of them in a row: {_listed(off)}."
            ),
        )
    return BindingCheck(
        id="G8",
        passed=False,
        scope="question",
        question_ids=off,
        detail=f"{_plural(len(off), 'answer')} judged not to address the question: {_listed(off)}.",
    )


def check_second_read(
    first: ExtractedAnswers, second: ExtractedAnswers, thresholds: GateThresholds
) -> BindingCheck:
    """G9: fails when a second read puts an answer's text under a different question.

    An id disagrees when the two reads' text for it agrees below 0.8 while the second
    read's text agrees at 0.8 or more with the first read's text for another id.
    Blank answers are ignored.
    """
    one = _answers_by_id(first)
    two = _answers_by_id(second)
    paired = [qid for qid in one if qid in two]
    disagreeing = [
        qid
        for qid in paired
        if text_agreement(one[qid], two[qid]) < _AGREEMENT_FLOOR
        and any(
            other != qid and text_agreement(two[qid], text) >= _AGREEMENT_FLOOR
            for other, text in one.items()
        )
    ]
    rate = len(disagreeing) / len(paired) if paired else 0.0
    if not disagreeing:
        return BindingCheck(
            id="G9",
            passed=True,
            scope="paper",
            detail="The two reads agree on which question each answer belongs to.",
        )
    scope = "paper" if rate > thresholds.second_read_disagreement_rate else "question"
    return BindingCheck(
        id="G9",
        passed=False,
        scope=scope,
        question_ids=disagreeing,
        detail=(
            f"{len(disagreeing)} of {len(paired)} answers in the second read match another "
            f"question's answer in the first read: {_listed(disagreeing)}."
        ),
    )


def verdict(checks: list[BindingCheck], *, retried: bool) -> BindingVerdict:
    """Pass when no paper-scope check failed; otherwise retry once, then hold."""
    if not any(c.scope == "paper" and not c.passed for c in checks):
        return "pass"
    return "hold" if retried else "retry"
