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
    from collections.abc import Iterable, Sequence

    from lemely.core.schemas import CorrectionResult, ExtractedAnswers

_SHOWN_IDS = 6


@dataclass(frozen=True)
class GateThresholds:
    """Limits for the gate checks.

    The G6 and G7 defaults come from ``scripts/sweep_binding_gate.py``: the setting with
    the most whole-paper shifts caught that holds no golden case and keeps false holds
    on simulated correct papers within limits. The rest are still provisional.
    """

    shape_mismatch_rate: float = 0.33
    shape_min_count: int = 3
    shift_min_matches: int = 3
    shift_max_gap: int = 6
    shift_max_offset: int = 2
    off_topic_count: int = 4
    off_topic_run: int = 3
    second_read_disagreement_rate: float = 0.10
    second_read_min_chars: int = 4
    second_read_min_disagreeing: int = 3
    second_read_presence_rate: float = 0.10
    agreement_floor: float = 0.8
    unaligned_rate: float = 0.10
    unplaced_labels_max: int = 2
    listing_suspects_min: int = 2


def _leaves(mark_scheme: MarkScheme) -> list[Question]:
    return [q for q in mark_scheme.all_questions_flat() if not q.parts and q.marks > 0]


def _is_mcq(question: Question) -> bool:
    return question.type == QuestionType.MCQ or question.mcq_answer is not None


def all_multiple_choice(mark_scheme: MarkScheme) -> bool:
    """Whether the paper has marked leaves and every one of them is multiple choice.

    The test of a multiple-choice leaf is the one G6, G7 and the text comparison of G9
    use to leave such leaves out: there is one such test in the gate, and this is it.
    """
    leaves = _leaves(mark_scheme)
    return bool(leaves) and all(_is_mcq(leaf) for leaf in leaves)


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


def suspect_group_leaves(mark_scheme: MarkScheme, suspects: Iterable[str]) -> list[str]:
    """The leaves of the listing-suspect groups ``suspects``, in paper order, each once.

    ``bind_stream`` names a suspect run of leaves by the question or part whose label
    opens it, or by its first leaf when it opens before any label. The run is the
    leaves listed after that label up to the next label of a question or part that has
    parts of its own. From the scheme tree that is: every leaf under the named id (or
    the leaf itself), and then each following leaf for as long as reaching it opens no
    such label, which is as long as all of its ancestors are ancestors of the named id.
    An id the scheme does not have names nothing.

    What this costs on a flat paper. On a scheme with no parts there is no label
    that ends a run, so a group named by its first leaf is every leaf from there to
    the end: with the trace at question 1, the whole paper. One block of writing
    above the first label (a name, say) together with one genuinely blank last
    question is that trace, and it sends every answer on such a paper to review
    (marked, marks kept, flagged). That is accepted: the same trace is exactly what a
    whole flat paper listed one out looks like, and nothing in the list tells the two
    apart. No flat paper has a recorded reply, so how often a reader reports writing
    above the first label is not known.
    """
    # The tree is read from the nesting of ``parts``, as ``bind_stream`` reads it, and
    # never from ``Question.parent_id``: that field is optional, filled by whichever
    # parser made the scheme and checked by nothing, and a group found through it
    # would be found only on schemes where it happens to be right.
    parent: dict[str, str | None] = {}
    stack: list[tuple[Question, str | None]] = [(q, None) for q in mark_scheme.questions]
    while stack:
        question, above_id = stack.pop()
        parent.setdefault(question.id, above_id)
        stack.extend((part, question.id) for part in question.parts)

    def ancestors(qid: str) -> list[str]:
        chain: list[str] = []
        up = parent.get(qid)
        while up is not None and up not in chain:
            chain.append(up)
            up = parent.get(up)
        return chain

    leaf_ids = list(dict.fromkeys(q.id for q in _leaves(mark_scheme)))
    grouped: set[str] = set()
    for suspect in suspects:
        if suspect not in parent:
            continue
        outer = set(ancestors(suspect))
        inside = False
        for leaf in leaf_ids:
            above = ancestors(leaf)
            if leaf == suspect or suspect in above:
                inside = True
                grouped.add(leaf)
            elif inside:
                if not set(above) <= outer:
                    break
                grouped.add(leaf)
    return [leaf for leaf in leaf_ids if leaf in grouped]


def check_label_coverage(
    extracted: ExtractedAnswers,
    mark_scheme: MarkScheme,
    unaligned_ids: list[str],
    unmatched_markers: int,
    thresholds: GateThresholds,
    *,
    listing_suspects: Sequence[str] = (),
    lost_items: int = 0,
) -> BindingCheck:
    """G5: fails when question labels on the page could not be lined up with the mark scheme.

    Paper scope on any of four things, each with its own sentence in ``detail``:

    - more than ``unaligned_rate`` of the leaves are unaligned;
    - more than ``unplaced_labels_max`` labels matched no question
      (``unmatched_markers``). One or two are ordinary: a number on the cover page, a
      note the student numbered;
    - at least ``listing_suspects_min`` groups of parts carry the trace left when
      writing is listed before its label (``listing_suspects``, the groups'
      ids as ``bind_stream`` names them), which the binding cannot see past;
    - ``lost_items`` is above zero: items of the reader's reply that could not be read
      and were left out. Any of them may have been writing, so a part may look blank
      that is not.

    Otherwise question scope when any leaf is unaligned or any group is suspect. A
    suspect group is never trusted, whatever the count: its answers sit one part out,
    so every leaf of it is listed (``suspect_group_leaves``), answered or not.

    An unaligned leaf carries no answer. ``bind_stream`` gives writing to a leaf only
    when its label is followed by the label the paper prints next, so where a label
    was missed the leaf just before the gap is unbound as well (its writing cannot be
    told from the missed part's) and is itself among the unaligned leaves. The
    question-scope check lists every unaligned leaf and, for each, the nearest aligned
    leaf before it in manifest order when that leaf has a non-blank answer: the last
    answer bound before the gap. That leaf is bracketed and is usually right. It is
    named because where several labels in a row were missed the labels after the gap
    can stand in for the missed ones, and it is then the answer standing nearest to
    what was misread.

    ``unmatched_markers`` is the number of labels in the list that no question
    accounts for (``BoundRead.unplaced_labels``); the name is from an earlier design.
    """
    # Each id once: a scheme that lists a question twice has one question the binder
    # could not match, not two, and G5 counts and names it once.
    leaf_ids = list(dict.fromkeys(q.id for q in _leaves(mark_scheme)))
    missing = set(unaligned_ids)
    unaligned = [qid for qid in leaf_ids if qid in missing]
    groups = list(dict.fromkeys(listing_suspects))
    unplaced = (
        f"{_plural(unmatched_markers, 'label')} on the page matched no question in the mark scheme"
    )
    suspects = (
        f"{_plural(len(groups), 'group')} of parts "
        f"{'shows' if len(groups) == 1 else 'show'} the trace of writing listed before "
        "its label (a block before the first part's label, the last part left blank)"
    )
    problems: list[str] = []
    within: list[str] = []
    if leaf_ids and len(unaligned) / len(leaf_ids) > thresholds.unaligned_rate:
        problems.append(
            f"{len(unaligned)} of {len(leaf_ids)} questions could not be lined up "
            f"with a label on the page: {_listed(unaligned)}"
        )
    if unmatched_markers > thresholds.unplaced_labels_max:
        problems.append(unplaced)
    elif unmatched_markers > 0:
        within.append(unplaced)
    if len(groups) >= thresholds.listing_suspects_min:
        problems.append(suspects)
    # A suspect group is never trusted. One that names no leaf of the scheme leaves
    # nothing to doubt in its place, so it cannot be left at question scope.
    nameless = [group for group in groups if not suspect_group_leaves(mark_scheme, [group])]
    if nameless:
        problems.append(
            f"{_plural(len(nameless), 'group')} of parts with that trace "
            f"{'names' if len(nameless) == 1 else 'name'} no question of the mark scheme: "
            f"{_listed(nameless)}"
        )
    if lost_items > 0:
        problems.append(
            f"{_plural(lost_items, 'item')} of the reader's reply could not be read and "
            f"{'was' if lost_items == 1 else 'were'} left out, so a part may look blank that is not"
        )
    if problems:
        return BindingCheck(
            id="G5",
            passed=False,
            scope="paper",
            question_ids=unaligned,
            detail="; ".join(problems) + ".",
        )
    if not unaligned and not groups:
        detail = "Every question lined up with a label on the page."
        if within:
            detail += " Within the limit: " + "; ".join(within) + "."
        return BindingCheck(id="G5", passed=True, scope="paper", detail=detail)
    answered = _answers_by_id(extracted)
    listed: set[str] = set(unaligned)
    previous_aligned: str | None = None
    for qid in leaf_ids:
        if qid in missing:
            if previous_aligned is not None and previous_aligned in answered:
                listed.add(previous_aligned)
        else:
            previous_aligned = qid
    listed.update(suspect_group_leaves(mark_scheme, groups))
    sentences: list[str] = []
    if unaligned:
        sentences.append(
            f"{_plural(len(unaligned), 'question')} had no label to line up with: "
            f"{_listed(unaligned)}; the writing for them may sit in the answer before"
        )
    if groups:
        sentences.append(f"{suspects}: {_listed(groups)}; each answer there may be the next part's")
    return BindingCheck(
        id="G5",
        passed=False,
        scope="question",
        question_ids=[qid for qid in leaf_ids if qid in listed],
        detail=". ".join(sentence[0].upper() + sentence[1:] for sentence in sentences) + ".",
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
        shaped  # with ``shape_min_count`` 0 an empty paper would divide by zero
        and len(contradicting) >= thresholds.shape_min_count
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
    judged = 0
    for question in correction.questions:
        if question.addresses_question is not None:
            judged += 1
        if question.addresses_question == "no":
            off.append(question.question_id)
            run += 1
            longest = max(longest, run)
        elif question.addresses_question == "yes":
            run = 0
    if not off:
        # The sentence gives the number judged: a pass over forty judgements and a
        # pass over none are different facts, and only the first is evidence.
        if judged == 0:
            detail = "The marker judged no answer, so this check had nothing to see."
        elif judged == 1:
            detail = "The 1 answer the marker judged was not off topic."
        else:
            detail = f"None of the {judged} answers the marker judged was off topic."
        return BindingCheck(id="G8", passed=True, scope="paper", detail=detail)
    told = (
        f"{len(off)} of {_plural(judged, 'answer')} judged "
        f"{'does not address its' if len(off) == 1 else 'do not address their'} question"
    )
    if len(off) >= thresholds.off_topic_count or longest >= thresholds.off_topic_run:
        in_a_row = f", {longest} in a row" if longest >= thresholds.off_topic_run else ""
        return BindingCheck(
            id="G8",
            passed=False,
            scope="paper",
            question_ids=off,
            detail=f"{told}{in_a_row}: {_listed(off)}.",
        )
    return BindingCheck(
        id="G8",
        passed=False,
        scope="question",
        question_ids=off,
        detail=f"{told}: {_listed(off)}.",
    )


def _normalised(answers: dict[str, str]) -> dict[str, str]:
    return {qid: " ".join(text.split()) for qid, text in answers.items()}


def _present(extracted: ExtractedAnswers) -> set[str]:
    """Ids that have writing in ``extracted``: a non-blank answer, or working alone."""
    return {
        item.question_id
        for item in extracted.answers
        if item.answer.strip() or (item.working_out or "").strip()
    }


def presence_disagreements(
    first: ExtractedAnswers,
    second: ExtractedAnswers,
    mark_scheme: MarkScheme,
    first_unaligned: Iterable[str],
    second_unaligned: Iterable[str],
) -> list[str]:
    """Leaves that have writing in exactly one of two reads, in paper order.

    Only leaves both reads aligned are compared: a leaf a read found no label for has
    no answer there because none could be bound, which says nothing about whether the
    student wrote one. Among the rest, a leaf with writing in one read and none in the
    other was either missed by one reader or invented by the other, and nothing says
    which, so it is trusted on neither side. Multiple-choice leaves are included: a
    letter one read saw and the other did not is writing all the same.
    """
    skipped = {*first_unaligned, *second_unaligned}
    one, two = _present(first), _present(second)
    return [
        q.id for q in _leaves(mark_scheme) if q.id not in skipped and (q.id in one) != (q.id in two)
    ]


def unread_in_one_read(
    first: ExtractedAnswers,
    second: ExtractedAnswers,
    mark_scheme: MarkScheme,
    first_unaligned: Iterable[str],
    second_unaligned: Iterable[str],
) -> list[str]:
    """Leaves with no writing in one read and no label lined up in the other, in paper order.

    One read aligned the leaf and reported nothing under its label; the other found no
    label for it and so could bind nothing to it, whatever it saw. Neither read holds
    an answer for the leaf, and that is not two reads agreeing on a blank: the second
    reader may have seen the writing and had nowhere to put it. A leaf unaligned in
    both reads is not listed (G5 reports it for each), nor is one that has writing in
    the read that aligned it.
    """
    one_missed, two_missed = set(first_unaligned), set(second_unaligned)
    one, two = _present(first), _present(second)
    return [
        q.id
        for q in _leaves(mark_scheme)
        if (q.id in one_missed and q.id not in two_missed and q.id not in two)
        or (q.id in two_missed and q.id not in one_missed and q.id not in one)
    ]


def check_second_read(
    first: ExtractedAnswers,
    second: ExtractedAnswers,
    mark_scheme: MarkScheme,
    thresholds: GateThresholds,
    *,
    first_unaligned: Iterable[str] | None = None,
    second_unaligned: Iterable[str] | None = None,
) -> BindingCheck:
    """G9: fails when two reads of one script disagree about where its answers are.

    Two comparisons, reported together.

    Moved text. Multiple-choice leaves are excluded, and an id is compared only when
    both reads hold at least ``second_read_min_chars`` characters for it after
    whitespace is collapsed. An id disagrees when the two reads agree below
    ``agreement_floor`` for it while the second read's text agrees at or above the
    floor with the first read's text for a different id whose first-read text
    itself differs (below the floor) from this id's. Two questions that legitimately
    share an answer are therefore never evidence. Paper scope when disagreeing ids
    exceed ``second_read_disagreement_rate`` of the compared ids and number at least
    ``second_read_min_disagreeing``.

    Presence (``presence_disagreements``), judged only when both ``first_unaligned``
    and ``second_unaligned`` are given, since without them a missing answer cannot be
    told from a missed label: a leaf both reads aligned that has writing in exactly
    one of them. Paper scope when such leaves exceed ``second_read_presence_rate`` of
    the compared leaves answered in either read and number at least
    ``second_read_min_disagreeing``.

    With the same two arguments, a leaf that has no writing in one read and no label
    lined up in the other (``unread_in_one_read``) is named at question scope: it is
    not known to be blank. This never fails the paper by itself.

    Otherwise question scope when any comparison names any id.
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
    lopsided: list[str] = []
    unread: list[str] = []
    answered_in_either = 0
    if first_unaligned is not None and second_unaligned is not None:
        one_missed, two_missed = list(first_unaligned), list(second_unaligned)
        skipped = {*one_missed, *two_missed}
        lopsided = presence_disagreements(first, second, mark_scheme, skipped, ())
        unread = unread_in_one_read(first, second, mark_scheme, one_missed, two_missed)
        answered_in_either = len((_present(first) | _present(second)) - skipped)
    if not disagreeing and not lopsided and not unread:
        return BindingCheck(
            id="G9",
            passed=True,
            scope="paper",
            detail="The two reads agree on which question each answer belongs to.",
        )
    paper = bool(disagreeing) and (
        len(disagreeing) / len(compared) > thresholds.second_read_disagreement_rate
        and len(disagreeing) >= thresholds.second_read_min_disagreeing
    )
    paper = paper or (
        bool(lopsided)  # with a minimum of 0, no leaf answered would divide by zero
        and len(lopsided) >= thresholds.second_read_min_disagreeing
        and len(lopsided) / answered_in_either > thresholds.second_read_presence_rate
    )
    sentences: list[str] = []
    if disagreeing:
        sentences.append(
            f"{len(disagreeing)} of {len(compared)} answers in the second read match another "
            f"question's answer in the first read: {_listed(disagreeing)}."
        )
    if lopsided:
        sentences.append(
            f"{_plural(len(lopsided), 'question')} {'was' if len(lopsided) == 1 else 'were'} "
            "answered in one reading of the scan and left blank in the other: "
            f"{_listed(lopsided)}."
        )
    if unread:
        sentences.append(
            f"{_plural(len(unread), 'question')} had no writing in one reading of the scan "
            f"and no label lined up in the other: {_listed(unread)}."
        )
    return BindingCheck(
        id="G9",
        passed=False,
        scope="paper" if paper else "question",
        question_ids=list(dict.fromkeys([*disagreeing, *lopsided, *unread])),
        detail=" ".join(sentences),
    )


def verdict(checks: list[BindingCheck], *, retried: bool) -> BindingVerdict:
    """Pass when no paper-scope check failed; otherwise retry once, then hold.

    For the checks made before marking, where a retry exists. After marking nothing
    retries: ``correct_paper`` turns a paper-scope failure into ``hold`` whatever
    ``retried`` was.
    """
    if not any(c.scope == "paper" and not c.passed for c in checks):
        return "pass"
    return "hold" if retried else "retry"
