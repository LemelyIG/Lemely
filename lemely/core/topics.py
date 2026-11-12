"""Syllabus topic taxonomy and the deterministic question→topic classifier (P4.2).

Why this exists
---------------
Phase 3 closed with an empty ``question_bank.topic`` column and D3.7 recording
why: a mark scheme carries marking points, not the syllabus topic a question
belongs to. P4.1 filled the bank with 273 real stems but deliberately left
``topic`` NULL rather than guessing (D4.1 §4). Everything Phase 4 promises —
practice targeting a student's weak topics, placement tests spanning topics,
flashcard decks per topic, a study plan naming a topic per session — needs that
column populated, and needs it populated from the **same vocabulary** the
weakness engine reports in, or the two sides never join.

So this module owns one vocabulary, meant for both sides:

* the bank side — ``question_bank.topic``, backfilled by
  ``lemely question-bank classify-topics``. **Wired up in P4.2.**
* the marking side — ``CorrectedQuestion.topic``, which today comes from
  ``topic_hint`` on the parsed mark scheme and is ``None`` on **every** one of
  the 637 questions across the 33 deterministically-parsed 0625 schemes in
  ``outputs/schemes/`` (measured, not assumed). So the weakness engine
  currently reports no topics at all for real papers. **Not wired up in P4.2**,
  deliberately: this module is in ``core`` and the taxonomy loader is in
  ``io``, so ``core.correction`` cannot reach it without either a signature
  change through every marking caller or a layering violation. The fill
  belongs at the db/io boundary where a ``CorrectionResult`` is persisted and
  the loader is reachable. P4.4 owns it — it is the task that initialises the
  weakness profile, and practice-targets-weakness (P4.5) does not join up
  until both sides speak this vocabulary.

Label format
------------
A label is ``"<syllabus code> <name>"`` — ``"4.3 Electric circuits"``,
``"14 Calculus"``. Self-describing in a UI chip, machine-parseable back to a
code, sorts in syllabus order, and hierarchically related to its parent by
code prefix. Subject scoping comes from the row/paper, not the label, so the
"Trigonometry" that exists in both 0580 and 0606 is never ambiguous in
practice: every query and every weakness report is already per-subject.

Honesty
-------
Scoring is keyword-based and deliberately conservative. A question that does
not clear the threshold, or that two topics claim about equally, is returned
as **no match** and its ``topic`` stays NULL. A wrong topic is worse than an
absent one here: it would silently point a student's practice at the wrong
material, and it would do so invisibly. This is UI spec §1.4 ("never invent
precision") applied to classification.

This module is pure: taxonomy models plus scoring, no IO. Loading the bundled
JSON is ``lemely.io.syllabus_topics``'s job.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from lemely.core.schemas import ConfidenceBand, StrictModel

if TYPE_CHECKING:
    from collections.abc import Iterable


def topic_sort_key(code: str) -> tuple[tuple[int, str], ...]:
    """Sort key putting syllabus codes in syllabus order.

    ``"2"`` before ``"10"``, and ``"1.2"`` before ``"1.10"``. Each dotted
    segment becomes ``(0, n)`` when numeric and ``(1, text)`` otherwise, so a
    non-numeric segment sorts after every number at that depth instead of
    raising a TypeError on a mixed comparison.
    """
    parts: list[tuple[int, str]] = []
    for segment in code.split("."):
        if segment.isdigit():
            # Zero-pad so the tuple compares numerically without int/str mixing.
            parts.append((0, f"{int(segment):09d}"))
        else:
            parts.append((1, segment))
    return tuple(parts)


# A `strong` term is a phrase distinctive enough that one hit alone is
# meaningful evidence ("half-life", "cumulative frequency"). A `keyword` is
# suggestive but shared across topics ("energy", "graph", "angle"), so it takes
# several to carry the same weight.
_STRONG_WEIGHT = 3
_KEYWORD_WEIGHT = 1

# One strong hit (3) clears this; three plain keywords also do. Two keywords do
# not — "graph" plus "angle" is not evidence of anything.
_MIN_SCORE = 3

# The winner must beat the best score from a *different parent topic* by this
# ratio, otherwise the question straddles two topics and we abstain at subtopic
# level. Tuned so a clear winner (6 vs 3) passes and a coin-flip (4 vs 3) does
# not.
_MARGIN_RATIO = 1.5


def _normalise(text: str) -> str:
    """Lowercase, flatten unicode punctuation, and collapse whitespace.

    Exam PDFs are full of en/em dashes, non-breaking spaces, and the Adobe
    SymbolEncoding artefacts ``lemely.io.det.symbols`` recovers. Matching
    happens on a flattened form so a taxonomy term can be written once, in
    plain ASCII, and still match an en-dashed ``speed-time`` and ``speed - time``.

    Hyphens become spaces. Measured against the real 0625 bank this is not
    cosmetic: CAIE writes ``double-insulated`` in one paper and ``double
    insulated`` in the next, and without this the term matched neither
    reliably. Both sides of the comparison are normalised identically, so the
    taxonomy can be authored either way.
    """
    folded = unicodedata.normalize("NFKC", text).lower()
    folded = folded.translate(_DASHES)
    return re.sub(r"\s+", " ", folded).strip()


_DASHES = str.maketrans(dict.fromkeys("\u2010\u2011\u2012\u2013\u2014-", " "))


class TopicNode(StrictModel):
    """One syllabus topic or subtopic plus its authored matching vocabulary."""

    code: str
    name: str
    strong: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    subtopics: list[TopicNode] = Field(default_factory=list)

    @field_validator("strong", "keywords", mode="after")
    @classmethod
    def _normalise_terms(cls, terms: list[str]) -> list[str]:
        """Hold the invariant that terms are stored pre-normalised.

        Both sides of every ``term in haystack`` test must have been through
        ``_normalise``, or a term containing a hyphen or a curly dash can never
        match. Enforcing it here rather than in the JSON loader means a
        hand-built ``TopicNode`` in a test obeys the same rule as the bundled
        data, and normalisation is paid once at load, not once per question.
        """
        return [n for n in (_normalise(term) for term in terms) if n]

    @property
    def label(self) -> str:
        """The canonical value written to ``question_bank.topic``."""
        return f"{self.code} {self.name}"

    def score(self, haystack: str) -> int:
        """Weighted count of this node's own terms present in ``haystack``.

        ``haystack`` must already be ``_normalise``d. Terms are counted once
        each however often they appear: a question repeating "resistor" eight
        times is not eight times more about resistors, and rewarding repetition
        would bias towards long stems.
        """
        total = 0
        for term in self.strong:
            if term in haystack:
                total += _STRONG_WEIGHT
        for term in self.keywords:
            if term in haystack:
                total += _KEYWORD_WEIGHT
        return total


TopicNode.model_rebuild()


class SyllabusTaxonomy(StrictModel):
    """The topic tree for one board+subject, transcribed from a syllabus PDF."""

    board: str
    subject_code: str
    subject_name: str
    syllabus_version: str
    source_url: str
    topics: list[TopicNode] = Field(default_factory=list)

    def labels(self) -> list[str]:
        """Every valid label, topics and subtopics, in syllabus order."""
        out: list[str] = []
        for topic in self.topics:
            out.append(topic.label)
            out.extend(sub.label for sub in topic.subtopics)
        return out


class TopicMatch(StrictModel):
    """A classification result. Only ever constructed for a confident match."""

    label: str
    code: str
    score: int
    runner_up_score: int
    confidence: ConfidenceBand
    granularity: Literal["subtopic", "topic"]


def _band(score: int, runner_up: int) -> ConfidenceBand:
    """Map the raw score and its margin onto the product-wide confidence bands.

    Deliberately coarse. This is evidence strength, not a probability, and
    dressing it up as one would be inventing precision.
    """
    if score >= 2 * _STRONG_WEIGHT and score >= 2 * max(runner_up, 1):
        return ConfidenceBand.HIGH
    if score >= _STRONG_WEIGHT + _KEYWORD_WEIGHT:
        return ConfidenceBand.MEDIUM
    if score >= _STRONG_WEIGHT and runner_up == 0:
        # An uncontested distinctive phrase. "Define specific heat capacity"
        # scores exactly one strong hit and nothing else in the syllabus scores
        # at all — thin, but there is no competing reading to be uncertain
        # between. Contested matches at the same score stay `low`, which is
        # what separates this from simply lowering the bar: the discriminator
        # is whether anything else claimed the question, not the raw total.
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


#: Bands allowed to be *written* to a topic column. Measured on the real 273-row
#: 0625 bank (D4.4): scoring classifies 245/273, but a hand-checked sample of the
#: 48 ``low``-band matches was materially worse than high/medium and contained
#: outright nonsense — a question about alpha, beta and gamma emission from
#: radioactive nuclei labelled "4.2 Electrical quantities".
#:
#: The decisive argument is not the error rate but that there is nowhere to put
#: the caveat: ``question_bank.topic`` is a bare string with no companion
#: confidence column, so a low-confidence label is indistinguishable downstream
#: from a certain one. Writing it would launder a guess into apparent fact and
#: silently point a student's practice at the wrong syllabus material (UI spec
#: §1.4). A future migration adding ``topic_confidence`` could reclaim the low
#: band by carrying its uncertainty forward; until then it stays NULL.
WRITABLE_BANDS: frozenset[ConfidenceBand] = frozenset({ConfidenceBand.HIGH, ConfidenceBand.MEDIUM})


def is_writable(match: TopicMatch | None) -> bool:
    """Whether a match is confident enough to persist. See ``WRITABLE_BANDS``."""
    return match is not None and match.confidence in WRITABLE_BANDS


def classify(text: str, taxonomy: SyllabusTaxonomy) -> TopicMatch | None:
    """Classify free text against ``taxonomy``, or return ``None`` if unsure.

    ``text`` should be everything known about the question — the stem, and the
    mark-scheme point text where available. Callers join those with newlines;
    scoring is order-insensitive.

    Two passes, most specific first:

    1. **Subtopic.** The best-scoring subtopic wins if it clears ``_MIN_SCORE``
       and beats the best subtopic *from another parent topic* by
       ``_MARGIN_RATIO``. The margin is measured across parents only —
       "1.5 Forces" narrowly outscoring "1.6 Momentum" on a collision question
       is a real near-tie worth abstaining on, but a question that scores on
       three subtopics of "4 Electricity and magnetism" is not ambiguous, it is
       just broad, and pass 2 will label it at topic level.
    2. **Topic.** Each topic's score is its own terms plus its subtopics'.
       Same threshold, margin measured against other topics.

    Anything that clears neither is unclassified — no label, no guess.
    """
    haystack = _normalise(text)
    if not haystack:
        return None

    sub_scores: list[tuple[int, str, TopicNode]] = [
        (sub.score(haystack), topic.code, sub)
        for topic in taxonomy.topics
        for sub in topic.subtopics
    ]
    best_sub = _best(sub_scores)
    if best_sub is not None:
        score, parent_code, node = best_sub
        rival = max((s for s, p, _ in sub_scores if p != parent_code), default=0)
        # A sibling tied on score means the evidence does not distinguish
        # between two subtopics of the same parent. Picking the lower-coded one
        # would be resolving it by file order and reporting the result as
        # though it were a finding; falling through to the topic pass says the
        # true thing instead — right topic, undetermined subtopic.
        sibling_tie = sum(1 for s, p, _ in sub_scores if p == parent_code and s == score) > 1
        if not sibling_tie and score >= _MIN_SCORE and score >= _MARGIN_RATIO * rival:
            return TopicMatch(
                label=node.label,
                code=node.code,
                score=score,
                runner_up_score=rival,
                confidence=_band(score, rival),
                granularity="subtopic",
            )

    topic_scores: list[tuple[int, str, TopicNode]] = [
        (
            topic.score(haystack) + sum(sub.score(haystack) for sub in topic.subtopics),
            topic.code,
            topic,
        )
        for topic in taxonomy.topics
    ]
    best_topic = _best(topic_scores)
    if best_topic is None:
        return None
    score, code, node = best_topic
    rival = max((s for s, c, _ in topic_scores if c != code), default=0)
    if score < _MIN_SCORE or score < _MARGIN_RATIO * rival:
        return None
    return TopicMatch(
        label=node.label,
        code=node.code,
        score=score,
        runner_up_score=rival,
        confidence=_band(score, rival),
        granularity="topic",
    )


def _best(scored: Iterable[tuple[int, str, TopicNode]]) -> tuple[int, str, TopicNode] | None:
    """Highest score, ties broken by syllabus order so the result is stable.

    ``max`` on the raw tuples would compare ``TopicNode`` objects on a tie and
    raise; comparing on the score alone keeps the first-seen (lowest-coded)
    node, which is what "syllabus order" means here.
    """
    best: tuple[int, str, TopicNode] | None = None
    for item in scored:
        if item[0] > 0 and (best is None or item[0] > best[0]):
            best = item
    return best


__all__ = [
    "WRITABLE_BANDS",
    "SyllabusTaxonomy",
    "TopicMatch",
    "TopicNode",
    "classify",
    "is_writable",
    "topic_sort_key",
]
