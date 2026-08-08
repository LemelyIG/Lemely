"""Placement-test assembly: a pure, deterministic selection over bank candidates (P4.4, D4.6 §5).

The placement test is quiz-shaped and reuses the quiz engine wholesale
(MISSION §4, D4.6). What is *not* reusable is which questions go in it, and
that is the whole of this module: given a pool of candidate questions and the
per-paper timing facts, choose a breadth-first subset that lands inside a
~15-minute budget, or say plainly that it cannot.

Three properties this module exists to guarantee, each of which was a
deliberate decision rather than an implementation detail:

**Duration is a marks-derived proxy, never a stored guess.** There is no
per-question duration column and there will not be one — nothing could
populate it except a guess, and a guess in a column acquires the authority of
a fact (the laundering D4.4 §5 refused for low-confidence topics). Instead a
question's estimate is ``total_marks * rate(its paper)`` where the rate is
``duration_minutes / total_marks`` **computed** from
``lemely/data/paper_timing.json``, whose two numbers are transcribed from the
syllabus. A question whose paper has no timing entry is *ineligible*, not
estimated from a subject average — an average across papers is a guess wearing
a measurement's clothes.

**Only topiced questions are eligible.** An untopiced question cannot
contribute to a topic-keyed weakness profile, which is the entire reason the
test is taken. Including one would inflate the question count while
contributing nothing to the output.

**A short test is refused, not padded.** Assembly succeeds only above a
viability floor (:data:`MIN_TOPICS`/:data:`MIN_QUESTIONS`/:data:`MIN_MINUTES`);
below it the caller gets an :class:`Unavailable` carrying a machine-readable
:class:`UnavailableReason`, and S-03 says so per subject. Never a silently
short test, never a padded one (UI spec §1.4).

Pure by construction: no DB, no IO, no clock. The caller supplies candidates
and timings; this module only chooses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable, Mapping, Sequence

# ── The ~15-minute budget and the viability floor (D4.6 §5) ──────────────

TARGET_MINUTES = 15.0
"""What S-03 promises the student. An estimate, not a limit — ``time_limit_minutes``
stays NULL on a placement quiz and S-04 shows *elapsed* time."""

MAX_MINUTES = 18.0
"""Greedy fill stops when the next question would cross this (+20% of target)."""

MIN_MINUTES = 12.0
"""Below this the assembled set is not a 15-minute test and is refused (-20%)."""

MIN_TOPICS = 4
"""A profile built from three topics is not a profile of a subject."""

MIN_QUESTIONS = 6


class UnavailableReason(StrEnum):
    """Why placement could not be assembled.

    Machine-readable, so S-03 can say something specific per subject rather
    than fail generically.
    """

    no_questions = "no_questions"
    """The pool was empty before any constraint was applied — no ingested
    questions for this subject at all. Today this is 0580 and 0606."""

    no_eligible_questions = "no_eligible_questions"
    """The pool was non-empty but every question was filtered out — untopiced,
    on a paper with no timing entry, or already seen in a prior placement.
    Distinct from ``no_questions`` because the fix is different: classify or
    transcribe, not ingest."""

    insufficient_topics = "insufficient_topics"
    insufficient_questions = "insufficient_questions"
    insufficient_duration = "insufficient_duration"


@dataclass(frozen=True, slots=True)
class PaperTiming:
    """The two transcribed facts about a paper, and the rate derived from them."""

    board: str
    subject_code: str
    paper_number: int
    duration_minutes: int
    total_marks: int
    practical: bool
    source_document: str
    syllabus_version: str

    @property
    def minutes_per_mark(self) -> float:
        """Computed, never stored. See the module docstring."""
        return self.duration_minutes / self.total_marks


@dataclass(frozen=True, slots=True)
class Candidate:
    """One bank question offered to the assembler.

    ``topic`` is ``str | None`` and ``paper_number`` is ``int | None`` because
    that is what the database actually holds — the caller passes rows through
    unfiltered and lets :func:`assemble` apply the eligibility rules in one
    place, so "why was this excluded" has a single answer.
    """

    question_bank_id: uuid.UUID
    topic: str | None
    paper_number: int | None
    total_marks: int
    difficulty: str


@dataclass(frozen=True, slots=True)
class Selected:
    """A chosen question and the estimate that chose it."""

    candidate: Candidate
    estimated_minutes: float


@dataclass(frozen=True, slots=True)
class Assembly:
    """A viable placement test."""

    selected: list[Selected]
    estimated_minutes: float
    topics: list[str]
    """Distinct topic *labels* covered, in syllabus-code order. A mix of
    top-level and subtopic labels, because that is what D4.2's classifier
    writes — so ``len(topics)`` is a count of labels, not of syllabus topics."""
    syllabus_topic_count: int
    """Distinct **top-level** syllabus topics covered (see
    :func:`_syllabus_group`). This is the number that means "how broad is this
    test"; ``len(topics)`` overstates it whenever subtopics are involved."""

    @property
    def question_count(self) -> int:
        return len(self.selected)

    @property
    def spans_multiple_bands(self) -> bool:
        """Whether S-05 may show a working-level estimate (D4.6 §5).

        A sample drawn from one difficulty band cannot locate a student on a
        scale; S-05 shows strongest/weakest topics instead and says the sample
        was too narrow. This is the flag that keeps it from inventing one.
        """
        return len({s.candidate.difficulty for s in self.selected}) >= 2


@dataclass(frozen=True, slots=True)
class Unavailable:
    """Placement cannot be assembled, and why.

    Carries the counts so S-03 can be concrete ("12 questions across 3 topics
    — not enough for a placement test") rather than merely negative.
    """

    reason: UnavailableReason
    eligible_questions: int
    eligible_topics: int
    estimated_minutes: float


def _topic_sort_key(topic: str) -> tuple[list[int], str]:
    """Order topics by syllabus code, numerically.

    Labels are ``"<code> <name>"`` (D4.4), e.g. ``"4.3 Electric circuits"``.
    A plain string sort puts ``"10.1"`` before ``"2.1"``; splitting the code on
    ``.`` and comparing integers does not. A label that does not start with a
    dotted numeric code sorts last, by name — deterministic either way, which
    is what assembly reproducibility needs.
    """
    code = topic.split(" ", 1)[0]
    parts = code.split(".")
    if all(p.isdigit() for p in parts) and parts != [""]:
        return ([int(p) for p in parts], topic)
    return ([10**6], topic)


def _syllabus_group(topic: str) -> str:
    """The top-level syllabus topic a label belongs to.

    D4.2's classifier writes whichever level it matched, so the bank holds a
    mix of top-level labels (``"3 Waves"``) and subtopic labels
    (``"1.2 Motion"``). Counting those as peers makes breadth a lie: an
    orchestrator measurement against the real 0625 bank produced a set
    reported as "13 topics" of which **nine questions sat under physics topic
    1**. Breadth is therefore measured on this key — the code before the first
    ``.`` — and only depth is measured on the full label.

    A label with no dotted numeric code is its own group; two such labels are
    never silently merged.
    """
    code = topic.split(" ", 1)[0]
    head = code.split(".", 1)[0]
    return head if head.isdigit() else topic


def assemble(
    candidates: Iterable[Candidate],
    timings: Mapping[int, PaperTiming],
    *,
    exclude_bank_ids: frozenset[uuid.UUID] = frozenset(),
    target_minutes: float = TARGET_MINUTES,
    max_minutes: float = MAX_MINUTES,
    min_minutes: float = MIN_MINUTES,
    min_topics: int = MIN_TOPICS,
    min_questions: int = MIN_QUESTIONS,
) -> Assembly | Unavailable:
    """Choose a ~15-minute, topic-broad question set, or explain why not.

    ``timings`` is keyed by ``paper_number`` for the subject being assembled;
    a candidate whose paper is absent from it is ineligible.

    ``exclude_bank_ids`` carries the questions this student has already seen in
    a prior placement for this subject: a retake is a fresh sample, not the
    same paper again (D4.6 §4). The exclusion is applied *before* the viability
    floor, so a student who has exhausted the pool is told the pool is
    exhausted rather than handed a repeat.

    Selection is **breadth first**: one question per distinct topic in syllabus
    order, then a second per topic, and so on, taking whichever question in a
    topic is closest to the remaining per-topic time share so the set does not
    fill up on one long question. Greedy — it stops when the next candidate
    would cross ``max_minutes``.
    """
    pool = list(candidates)
    if not pool:
        return Unavailable(UnavailableReason.no_questions, 0, 0, 0.0)

    by_topic: dict[str, list[Selected]] = {}
    for candidate in pool:
        if candidate.question_bank_id in exclude_bank_ids:
            continue
        if candidate.topic is None:
            continue
        if candidate.paper_number is None:
            continue
        timing = timings.get(candidate.paper_number)
        if timing is None:
            continue
        estimate = candidate.total_marks * timing.minutes_per_mark
        if estimate <= 0 or estimate > max_minutes:
            # A single question that alone blows the budget can never be part
            # of a ~15-minute test; excluding it here keeps the greedy fill
            # from stalling on it every round.
            continue
        by_topic.setdefault(candidate.topic, []).append(Selected(candidate, estimate))

    eligible_count = sum(len(v) for v in by_topic.values())
    if eligible_count == 0:
        return Unavailable(UnavailableReason.no_eligible_questions, 0, 0, 0.0)

    # Breadth is measured across top-level syllabus topics, depth across the
    # subtopic labels inside one — see :func:`_syllabus_group`. Grouping first
    # is what stops "1.1", "1.2", ..., "1.8" from reading as eight topics.
    labels_by_group: dict[str, list[str]] = {}
    for label in by_topic:
        labels_by_group.setdefault(_syllabus_group(label), []).append(label)
    for labels in labels_by_group.values():
        labels.sort(key=_topic_sort_key)
    groups_in_order = sorted(labels_by_group, key=lambda g: _topic_sort_key(labels_by_group[g][0]))

    if len(groups_in_order) < min_topics:
        return Unavailable(
            UnavailableReason.insufficient_topics, eligible_count, len(groups_in_order), 0.0
        )

    # Aim each top-level topic at an even share of the budget, so "closest to
    # the share" prefers a question that leaves room for the other topics
    # rather than the longest one that still fits.
    share = target_minutes / len(groups_in_order)
    for options in by_topic.values():
        options.sort(
            key=lambda s: (abs(s.estimated_minutes - share), str(s.candidate.question_bank_id))
        )

    selected: list[Selected] = []
    spent = 0.0
    cursors = dict.fromkeys(by_topic, 0)
    label_cursors = dict.fromkeys(groups_in_order, 0)
    progressed = True

    def _keep_going() -> bool:
        """Whether the greedy fill should take another question.

        Fill to the target — but keep going past it, up to ``max_minutes``,
        while the set is still short of ``min_questions``.

        Without the second clause a pool of mark-heavy questions stops on the
        target with too few questions and is then refused, when one more
        question inside the tolerance would have made it viable. It is still a
        refusal if the extra question does not fit: the tolerance is a
        tolerance, not a licence to overrun.
        """
        return spent < target_minutes or len(selected) < min_questions

    def _take_from_group(group: str) -> Selected | None:
        """One question from ``group``, rotating through its subtopic labels.

        The inner rotation is what keeps a group's share spread across its
        subtopics instead of drilling into whichever one happens to be first.
        """
        labels = labels_by_group[group]
        for offset in range(len(labels)):
            label = labels[(label_cursors[group] + offset) % len(labels)]
            index = cursors[label]
            if index >= len(by_topic[label]):
                continue
            choice = by_topic[label][index]
            if spent + choice.estimated_minutes > max_minutes:
                continue
            cursors[label] = index + 1
            label_cursors[group] = (label_cursors[group] + offset + 1) % len(labels)
            return choice
        return None

    while progressed and _keep_going():
        progressed = False
        for group in groups_in_order:
            choice = _take_from_group(group)
            if choice is None:
                continue
            selected.append(choice)
            spent += choice.estimated_minutes
            progressed = True
            if not _keep_going():
                break

    covered_groups = {_syllabus_group(s.candidate.topic or "") for s in selected}
    if len(covered_groups) < min_topics:
        return Unavailable(
            UnavailableReason.insufficient_topics, eligible_count, len(groups_in_order), spent
        )
    if len(selected) < min_questions:
        return Unavailable(
            UnavailableReason.insufficient_questions, eligible_count, len(groups_in_order), spent
        )
    if spent < min_minutes:
        return Unavailable(
            UnavailableReason.insufficient_duration, eligible_count, len(groups_in_order), spent
        )

    ordered = sorted(
        selected,
        key=lambda s: (_topic_sort_key(s.candidate.topic or ""), str(s.candidate.question_bank_id)),
    )
    covered = sorted(
        {s.candidate.topic for s in selected if s.candidate.topic}, key=_topic_sort_key
    )
    return Assembly(
        selected=ordered,
        estimated_minutes=spent,
        topics=covered,
        syllabus_topic_count=len(covered_groups),
    )


def estimated_minutes_for(
    marks: Sequence[int], paper_numbers: Sequence[int | None], timings: Mapping[int, PaperTiming]
) -> float:
    """Recompute a test's estimate from frozen question marks.

    D4.6 §5: the displayed estimate is derived on read from
    ``quiz_questions.total_marks``, not stored, so it stays true if a question
    is ever removed and costs no column. Questions whose paper has no timing
    contribute zero rather than a guessed average — the same rule assembly used
    to exclude them.
    """
    total = 0.0
    for mark, paper_number in zip(marks, paper_numbers, strict=True):
        if paper_number is None:
            continue
        timing = timings.get(paper_number)
        if timing is not None:
            total += mark * timing.minutes_per_mark
    return total
