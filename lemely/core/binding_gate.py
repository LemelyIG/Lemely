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
    answer_matches_only,
    answer_shape,
    expected_shape,
    matches_expected,
)
from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.text_agreement import text_agreement

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lemely.core.schemas import CorrectionResult, ExtractedAnswers

_SHOWN_IDS = 6


@dataclass(frozen=True)
class GateThresholds:
    """Provisional limits; a later measurement replaces the defaults."""

    shape_mismatch_rate: float = 0.25
    shape_min_count: int = 3
    shift_min_matches: int = 3
    shift_max_gap: int = 3
    shift_max_offset: int = 2
    off_topic_count: int = 4
    off_topic_run: int = 3
    second_read_disagreement_rate: float = 0.10
    second_read_min_chars: int = 4
    second_read_min_disagreeing: int = 3
    agreement_floor: float = 0.8
    unaligned_rate: float = 0.10


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
    thresholds: GateThresholds,
) -> BindingCheck:
    """G5: fails when question labels on the page could not be lined up with the mark scheme.

    Paper scope when more than ``unaligned_rate`` of the leaves are unaligned or a
    marker matched no question. Otherwise question scope when any leaf is unaligned.

    An unaligned leaf cannot carry an answer, because answers attach to aligned
    labels; whatever the student wrote for it was attached to the aligned leaf
    before it. So the question-scope check lists every unaligned leaf, and for
    each the nearest aligned leaf before it in manifest order when that leaf has a
    non-blank answer.
    """
    leaf_ids = [q.id for q in _leaves(mark_scheme)]
    missing = set(unaligned_ids)
    unaligned = [qid for qid in leaf_ids if qid in missing]
    problems: list[str] = []
    if leaf_ids and len(unaligned) / len(leaf_ids) > thresholds.unaligned_rate:
        problems.append(
            f"{len(unaligned)} of {len(leaf_ids)} questions could not be lined up "
            f"with a label on the page: {_listed(unaligned)}"
        )
    if unmatched_markers > 0:
        problems.append(
            f"{_plural(unmatched_markers, 'label')} on the page matched no question "
            "in the mark scheme"
        )
    if problems:
        return BindingCheck(
            id="G5",
            passed=False,
            scope="paper",
            question_ids=unaligned,
            detail="; ".join(problems) + ".",
        )
    if not unaligned:
        return BindingCheck(
            id="G5",
            passed=True,
            scope="paper",
            detail="Every question lined up with a label on the page.",
        )
    answered = _answers_by_id(extracted)
    listed: set[str] = set(unaligned)
    previous_aligned: str | None = None
    for qid in leaf_ids:
        if qid in missing:
            if previous_aligned is not None and previous_aligned in answered:
                listed.add(previous_aligned)
        else:
            previous_aligned = qid
    ids = [qid for qid in leaf_ids if qid in listed]
    return BindingCheck(
        id="G5",
        passed=False,
        scope="question",
        question_ids=ids,
        detail=(
            f"{_plural(len(unaligned), 'question')} had no label to line up with: "
            f"{_listed(unaligned)}; the writing for them may sit in the answer before."
        ),
    )


def check_shape(
    extracted: ExtractedAnswers, mark_scheme: MarkScheme, thresholds: GateThresholds
) -> BindingCheck:
    """G6: fails when many answers are plainly the wrong kind for their question.

    Counts answered, non-multiple-choice leaves whose expected shape is known. An
    answer contradicts only when the leaf expects a number and the answer holds no
    digit at all, or the leaf expects text and the answer reads as a plain number.
    Working that contains digits is never a contradiction. Fails at paper scope
    when there are at least ``shape_min_count`` contradictions and they exceed
    ``shape_mismatch_rate`` of the counted leaves.
    """
    answered = _answers_by_id(extracted)
    shaped = 0
    contradicting: list[str] = []
    for leaf in _leaves(mark_scheme):
        if _is_mcq(leaf) or leaf.id not in answered:
            continue
        expected = expected_shape(leaf)
        if expected == "unknown":
            continue
        shaped += 1
        text = answered[leaf.id]
        if (expected == "number" and not any(ch in "0123456789" for ch in text)) or (
            expected == "text" and answer_shape(text) == "number"
        ):
            contradicting.append(leaf.id)
    if (
        len(contradicting) >= thresholds.shape_min_count
        and len(contradicting) / shaped > thresholds.shape_mismatch_rate
    ):
        return BindingCheck(
            id="G6",
            passed=False,
            scope="paper",
            question_ids=contradicting,
            detail=(
                f"{len(contradicting)} of {shaped} answers are plainly the wrong kind "
                f"(no number where one is asked for, or only a number where words are): "
                f"{_listed(contradicting)}."
            ),
        )
    if not shaped:
        detail = "No answer could be compared with the kind its question asks for."
    else:
        detail = (
            f"{len(contradicting)} of {shaped} answers are plainly the wrong kind, "
            "which is within the limit."
        )
    return BindingCheck(id="G6", passed=True, scope="paper", detail=detail)


_NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def _offset_words(offset: int) -> str:
    """How an answer's neighbour is named in a detail sentence."""
    if offset == -1:
        return "the previous question"
    if offset == 1:
        return "the next question"
    distance = abs(offset)
    count = _NUMBER_WORDS[distance] if distance < len(_NUMBER_WORDS) else str(distance)
    return f"the question {count} {'before' if offset < 0 else 'after'} it"


def _offset_runs(
    answered: dict[str, str], leaves: list[Question], offset: int, thresholds: GateThresholds
) -> list[list[int]]:
    """Runs of leaves whose answers hold the value of the leaf ``offset`` positions away.

    A leaf points at the offset when its answer matches, value for value, the leaf
    that far away and it does not match its own leaf. A leaf matching its own leaf
    breaks a run, unless its answer also matches the leaf that far away (two
    neighbouring questions share a value), when it is compatible: it neither breaks
    nor counts. Every other leaf is neutral. Consecutive pointing leaves in a run
    are at most ``shift_max_gap`` positions apart.
    """
    runs: list[list[int]] = []
    current: list[int] | None = None
    for i, leaf in enumerate(leaves):
        text = answered.get(leaf.id)
        if text is None:
            continue
        target = i + offset
        matches_away = 0 <= target < len(leaves) and answer_matches_only(text, leaves[target])
        if matches_expected(text, leaf):
            if not matches_away:
                current = None
        elif matches_away:
            if current is not None and i - current[-1] <= thresholds.shift_max_gap:
                current.append(i)
            else:
                current = [i]
                runs.append(current)
    return runs


def _plural_verb(count: int) -> str:
    return "holds" if count == 1 else "hold"


def check_shift(
    extracted: ExtractedAnswers, mark_scheme: MarkScheme, thresholds: GateThresholds
) -> list[BindingCheck]:
    """G7: fails when runs of answers hold the value expected of a neighbouring question.

    Works over the non-multiple-choice leaves in manifest order, for each offset
    from -``shift_max_offset`` to ``shift_max_offset`` (not 0) separately. An
    answered leaf points at an offset when its answer does not match its own leaf
    and matches only the expected values of the leaf that many positions away,
    every value read from it; it may point at several offsets and counts in each.

    A run at an offset is a stretch of leaves with no leaf in it matching its own
    question alone (a leaf matching its own question and also the leaf at that
    offset is compatible and does not break it), with at most ``shift_max_gap``
    positions between pointing leaves. Runs of at least ``shift_min_matches``
    pointing leaves fail at paper scope and list those leaves; pointing leaves
    only in shorter runs fail at question scope. Each leaf is listed once. The
    paper-scope check is always first in the list.
    """
    answered = _answers_by_id(extracted)
    leaves = [q for q in _leaves(mark_scheme) if not _is_mcq(q)]
    offsets = [o for step in range(1, thresholds.shift_max_offset + 1) for o in (-step, step)]
    long_runs: list[tuple[int, list[int]]] = []
    short_runs: list[list[int]] = []
    for offset in offsets:
        for run in _offset_runs(answered, leaves, offset, thresholds):
            if len(run) >= thresholds.shift_min_matches:
                long_runs.append((offset, run))
            else:
                short_runs.append(run)

    if long_runs:
        notes = [
            f"{len(run)} answers hold the value expected of {_offset_words(offset)}: "
            + _listed(leaves[i].id for i in run)
            for offset, run in long_runs
        ]
        flagged = sorted({i for _, run in long_runs for i in run})
        paper = BindingCheck(
            id="G7",
            passed=False,
            scope="paper",
            question_ids=[leaves[i].id for i in flagged],
            detail="; ".join(notes) + ".",
        )
    else:
        flagged = []
        paper = BindingCheck(
            id="G7",
            passed=True,
            scope="paper",
            detail="No run of answers holds the value expected of a neighbouring question.",
        )
    checks = [paper]
    minor = sorted({i for run in short_runs for i in run} - set(flagged))
    if minor:
        ids = [leaves[i].id for i in minor]
        checks.append(
            BindingCheck(
                id="G7",
                passed=False,
                scope="question",
                question_ids=ids,
                detail=(
                    f"{_plural(len(ids), 'answer')} {_plural_verb(len(ids))} the value expected "
                    f"of a neighbouring question and not their own: {_listed(ids)}."
                ),
            )
        )
    return checks


def check_off_topic(correction: CorrectionResult, thresholds: GateThresholds) -> BindingCheck:
    """G8: fails when the marker says answers do not address their question.

    Only ``"yes"`` breaks a run of ``"no"``. A question the marker left as ``None``
    or ``"unclear"`` neither breaks a run nor counts toward a run or toward
    ``off_topic_count``. Paper scope at ``off_topic_count`` such questions, or
    ``off_topic_run`` in a row; below both, question scope for those questions.
    """
    off: list[str] = []
    longest = run = 0
    for question in correction.questions:
        if question.addresses_question == "no":
            off.append(question.question_id)
            run += 1
            longest = max(longest, run)
        elif question.addresses_question == "yes":
            run = 0
    if not off:
        return BindingCheck(
            id="G8", passed=True, scope="paper", detail="No answer was judged off topic."
        )
    if len(off) >= thresholds.off_topic_count or longest >= thresholds.off_topic_run:
        in_a_row = f", {longest} in a row" if longest >= thresholds.off_topic_run else ""
        return BindingCheck(
            id="G8",
            passed=False,
            scope="paper",
            question_ids=off,
            detail=(
                f"{len(off)} answers were judged not to address their question{in_a_row}: "
                f"{_listed(off)}."
            ),
        )
    return BindingCheck(
        id="G8",
        passed=False,
        scope="question",
        question_ids=off,
        detail=(
            f"{_plural(len(off), 'answer')} judged not to address the question: {_listed(off)}."
        ),
    )


def _normalised(answers: dict[str, str]) -> dict[str, str]:
    return {qid: " ".join(text.split()) for qid, text in answers.items()}


def check_second_read(
    first: ExtractedAnswers,
    second: ExtractedAnswers,
    mark_scheme: MarkScheme,
    thresholds: GateThresholds,
) -> BindingCheck:
    """G9: fails when a second read puts an answer's text under a different question.

    Multiple-choice leaves are excluded, and an id is compared only when both
    reads hold at least ``second_read_min_chars`` characters for it after
    whitespace is collapsed. An id disagrees when the two reads agree below
    ``agreement_floor`` for it while the second read's text agrees at or above the
    floor with the first read's text for a different id whose first-read text
    itself differs (below the floor) from this id's. Two questions that legitimately
    share an answer are therefore never evidence. Paper scope when disagreeing ids
    exceed ``second_read_disagreement_rate`` of the compared ids and number at least
    ``second_read_min_disagreeing``; otherwise question scope.
    """
    floor = thresholds.agreement_floor
    eligible = {q.id for q in _leaves(mark_scheme) if not _is_mcq(q)}
    long_enough = {
        qid: text
        for qid, text in _normalised(_answers_by_id(first)).items()
        if qid in eligible and len(text) >= thresholds.second_read_min_chars
    }
    one = long_enough
    two = {
        qid: text
        for qid, text in _normalised(_answers_by_id(second)).items()
        if qid in eligible and len(text) >= thresholds.second_read_min_chars
    }
    compared = [qid for qid in one if qid in two]
    disagreeing = [
        qid
        for qid in compared
        if text_agreement(one[qid], two[qid]) < floor
        and any(
            text_agreement(two[qid], text) >= floor and text_agreement(text, one[qid]) < floor
            for text in one.values()
        )
    ]
    if not disagreeing:
        return BindingCheck(
            id="G9",
            passed=True,
            scope="paper",
            detail="The two reads agree on which question each answer belongs to.",
        )
    paper = (
        len(disagreeing) / len(compared) > thresholds.second_read_disagreement_rate
        and len(disagreeing) >= thresholds.second_read_min_disagreeing
    )
    return BindingCheck(
        id="G9",
        passed=False,
        scope="paper" if paper else "question",
        question_ids=disagreeing,
        detail=(
            f"{len(disagreeing)} of {len(compared)} answers in the second read match another "
            f"question's answer in the first read: {_listed(disagreeing)}."
        ),
    )


def verdict(checks: list[BindingCheck], *, retried: bool) -> BindingVerdict:
    """Pass when no paper-scope check failed; otherwise retry once, then hold."""
    if not any(c.scope == "paper" and not c.passed for c in checks):
        return "pass"
    return "hold" if retried else "retry"
