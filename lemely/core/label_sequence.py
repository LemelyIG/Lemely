"""The label sequence a mark scheme implies, and the alignment of seen labels to it.

A reader that looks at a scanned script reports only the question labels it can
see on each page ("1", "(a)", "(i)", "Q3 b") and where. It never decides which
question an answer belongs to. This module decides: it walks the mark scheme into
the sequence of labels the paper must contain (``expected_steps``), reads each
seen label into steps (``parse_marker``), and aligns the two as a longest common
subsequence (``align``).

The alignment is built to say "I don't know" rather than guess:

* a leaf is aligned only when every label on its path (number, letter, roman) is;
* a number that cannot be the start of its question is a numbered answer line
  ("1. no weight is attached", "2. a weight of 5.6 N") and is dropped from the
  stream, never matched forward;
* a label the scheme has no place for, or whose leaf has an incomplete path, is
  returned as unmatched, and its neighbours keep their own alignment.

Pure functions: no I/O, no logging.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from lemely.core.binding import LabelMarker
    from lemely.core.loose_schemas import MarkScheme, Question

Level = Literal["number", "letter", "roman"]

# Roman numerals up to xx are enough for any question part. Longer alternatives
# first, or "iv" and "ix" are consumed by "i" and fail the full match.
_ROMAN = re.compile(r"(?:x{0,2})(?:ix|iv|v?i{0,3})")
# A leading "Q" or "Question" only counts as a prefix when a number follows it.
_PREFIX = re.compile(r"\s*(?:question|q)\s*\.?\s*(?=\d)", re.IGNORECASE)
_TOKEN = re.compile(r"\d+|[A-Za-z]+")
# Single characters that are both a roman numeral and a letter.
_AMBIGUOUS = frozenset("ivx")


class LabelDecompositionError(ValueError):
    """A question id that the label sequence cannot decompose into steps."""


@dataclass(frozen=True, slots=True)
class LabelStep:
    """One label a reader meets: the number, a letter, or a roman numeral."""

    level: Level
    token: str


@dataclass(frozen=True, slots=True)
class AlignedLeaf:
    """A leaf question whose label was seen, and where."""

    question_id: str
    page: int
    top: int
    label_seen: str


@dataclass(frozen=True, slots=True)
class _Node:
    step: LabelStep
    leaf_id: str | None
    parent: int | None
    depth: int


@dataclass(frozen=True, slots=True)
class _Slot:
    """One step read off one marker; ``options`` holds every reading it allows."""

    marker: int
    options: frozenset[LabelStep]


def _is_roman(token: str) -> bool:
    return bool(token) and _ROMAN.fullmatch(token) is not None


def _own_token(question: Question, parent: Question | None) -> str:
    """The suffix this question's id adds to its parent's id."""
    if parent is None:
        if not question.id.isdigit():
            raise LabelDecompositionError(f"top-level id {question.id!r} is not a number")
        return question.id
    if not question.id.startswith(parent.id) or question.id == parent.id:
        raise LabelDecompositionError(
            f"id {question.id!r} does not extend its parent id {parent.id!r}"
        )
    token = question.id[len(parent.id) :].removeprefix("_")
    if not token.isalnum() or token != token.lower():
        raise LabelDecompositionError(f"id {question.id!r} adds {token!r}, not a label token")
    return token


def _level(
    question: Question, token: str, parent_level: Level | None, index: int, prev: Level | None
) -> Level:
    """Classify a token by its form and its parent, not by depth alone."""
    if parent_level is None:
        return "number"
    if token.isdigit():
        raise LabelDecompositionError(f"id {question.id!r} nests a number under a label")
    if parent_level == "number":
        if len(token) > 1:
            if _is_roman(token):
                return "roman"
            raise LabelDecompositionError(f"id {question.id!r}: {token!r} is not a label")
        # "i" opens a roman run; "v" or "x" continue one. After "h", "i" is a letter.
        opens_run = index == 0 and token == "i"  # noqa: S105 (a roman numeral, not a secret)
        if token in _AMBIGUOUS and (opens_run or prev == "roman"):
            return "roman"
        return "letter"
    if parent_level == "letter":
        if _is_roman(token):
            return "roman"
        raise LabelDecompositionError(f"id {question.id!r}: {token!r} under a letter is not roman")
    if len(token) == 1:
        return "letter"  # a fourth level: a letter under a roman
    raise LabelDecompositionError(f"id {question.id!r} nests {token!r} under a roman")


def _decompose(mark_scheme: MarkScheme) -> list[_Node]:
    nodes: list[_Node] = []

    def visit(
        questions: list[Question],
        parent: Question | None,
        parent_index: int | None,
        parent_level: Level | None,
        depth: int,
    ) -> None:
        prev: Level | None = None
        for index, question in enumerate(questions):
            token = _own_token(question, parent)
            level = _level(question, token, parent_level, index, prev)
            node_index = len(nodes)
            leaf_id = None if question.parts else question.id
            nodes.append(_Node(LabelStep(level, token), leaf_id, parent_index, depth))
            visit(question.parts, question, node_index, level, depth + 1)
            prev = level

    visit(mark_scheme.questions, None, None, None, 0)
    counts = Counter(n.leaf_id for n in nodes if n.leaf_id is not None)
    for leaf_id, count in counts.items():
        if count > 1:
            # Two leaves with one id cannot be told apart, so neither could be bound.
            raise LabelDecompositionError(f"leaf id {leaf_id!r} appears {count} times")
    return nodes


def expected_steps(mark_scheme: MarkScheme) -> list[tuple[LabelStep, str | None]]:
    """The label steps a reader meets walking the paper.

    Each step is paired with the leaf id it completes, or ``None`` for a
    container. Raises ``LabelDecompositionError`` for an id it cannot decompose.
    """
    return [(node.step, node.leaf_id) for node in _decompose(mark_scheme)]


def _readings(text: str) -> list[frozenset[LabelStep]] | None:
    """Every reading of each token of ``text``; ``None`` when it is not a label."""
    body = _PREFIX.sub("", text, count=1)
    tokens = _TOKEN.findall(body)
    if not 1 <= len(tokens) <= 4:
        return None
    if _TOKEN.sub("", body).strip(" \t().:-"):
        return None  # brackets, commas, words around the label
    readings: list[frozenset[LabelStep]] = []
    for position, token in enumerate(tokens):
        if token.isdigit():
            if position != 0 or len(token) > 2:
                return None
            readings.append(frozenset({LabelStep("number", token)}))
        elif token != token.lower():
            return None  # "(A)" is an MCQ option, not a question part
        elif len(token) == 1:
            letter = LabelStep("letter", token)
            if token in _AMBIGUOUS:
                readings.append(frozenset({LabelStep("roman", token), letter}))
            else:
                readings.append(frozenset({letter}))
        elif _is_roman(token):
            readings.append(frozenset({LabelStep("roman", token)}))
        else:
            return None
    return readings


def parse_marker(text: str) -> list[LabelStep]:
    """The label steps in ``text``, or ``[]`` when it is not a question label.

    Roman numerals are tried before single letters, so "(i)", "(v)" and "(x)"
    are romans; ``align`` is what lets them be letters when the paper says so.
    """
    readings = _readings(text)
    if readings is None:
        return []
    return [min(options, key=lambda step: step.level != "roman") for options in readings]


def _eligible_number(
    slots: list[_Slot], position: int, nodes: list[_Node], number_nodes: dict[str, int]
) -> bool:
    """Whether the number at ``position`` can be the start of its question.

    A question number is followed by the first label of that question. A
    numbered answer line ("1.", "2.") is followed by the rest of the part it is
    inside, so it fails this test and is never taken for a question.
    """
    (step,) = (s for s in slots[position].options if s.level == "number")
    node = number_nodes.get(step.token)
    if node is None:
        return False
    following = slots[position + 1] if position + 1 < len(slots) else None
    has_children = node + 1 < len(nodes) and nodes[node + 1].parent == node
    if has_children:
        return following is not None and nodes[node + 1].step in following.options
    return following is None or any(o.level == "number" for o in following.options)


def _match(slots: list[_Slot], nodes: list[_Node]) -> dict[int, int]:
    """Align the slots to the expected steps; maps node index to slot index.

    A longest common subsequence in which a node may match only when its parent
    does too. Counting a match whose path is broken would let a stray label
    outbid its neighbours, so the path rule is part of the score, not a filter
    applied afterwards. The state carries one bit per ancestor of the node being
    decided (was that ancestor matched), so the table is
    ``nodes x slots x 2**depth``.
    """
    rows, cols = len(slots), len(nodes)
    depth = max((n.depth for n in nodes), default=0)
    # first[j][i]: the first slot at or after i that reads as node j, else rows.
    first = [[rows] * (rows + 1) for _ in range(cols)]
    for j, node in enumerate(nodes):
        for i in range(rows - 1, -1, -1):
            first[j][i] = i if node.step in slots[i].options else first[j][i + 1]
    best = [[[0] * (1 << depth) for _ in range(rows + 1)] for _ in range(cols + 1)]
    keep = [(1 << nodes[j + 1].depth) - 1 if j + 1 < cols else 0 for j in range(cols)]
    for j in range(cols - 1, -1, -1):
        d = nodes[j].depth
        for i in range(rows + 1):
            k = first[j][i]
            for mask in range(1 << d):
                value = best[j + 1][i][mask & keep[j]]
                if k < rows and (d == 0 or mask >> (d - 1) & 1):
                    value = max(value, 1 + best[j + 1][k + 1][(mask | 1 << d) & keep[j]])
                best[j][i][mask] = value
    matched: dict[int, int] = {}
    i = mask = 0
    for j in range(cols):
        d = nodes[j].depth
        k = first[j][i]
        taken = (mask | 1 << d) & keep[j]
        parent_matched = d == 0 or mask >> (d - 1) & 1
        if k < rows and parent_matched and 1 + best[j + 1][k + 1][taken] == best[j][i][mask]:
            matched[j] = k
            i, mask = k + 1, taken
        else:
            mask &= keep[j]
    return matched


def align(
    markers: list[LabelMarker], mark_scheme: MarkScheme
) -> tuple[list[AlignedLeaf], list[str], list[LabelMarker]]:
    """Align seen labels to the paper's label sequence.

    Returns the aligned leaves in reading order, the ids of leaves with no
    aligned label, and the markers that matched nothing.
    """
    nodes = _decompose(mark_scheme)
    number_nodes = {n.step.token: k for k, n in enumerate(nodes) if n.step.level == "number"}
    order = sorted(range(len(markers)), key=lambda k: (markers[k].page, markers[k].top))

    slots: list[_Slot] = []
    for k in order:
        readings = _readings(markers[k].text)
        if readings is not None:
            slots.extend(_Slot(k, options) for options in readings)

    # Numbered answer lines leave the stream before the alignment sees it.
    kept = [
        slot
        for position, slot in enumerate(slots)
        if all(s.level != "number" for s in slot.options)
        or _eligible_number(slots, position, nodes, number_nodes)
    ]

    aligned_nodes = _match(kept, nodes)

    aligned: list[AlignedLeaf] = []
    for j, i in aligned_nodes.items():
        leaf_id = nodes[j].leaf_id
        if leaf_id is not None:
            marker = markers[kept[i].marker]
            aligned.append(AlignedLeaf(leaf_id, marker.page, marker.top, marker.text))
    aligned_ids = {leaf.question_id for leaf in aligned}
    unaligned = [n.leaf_id for n in nodes if n.leaf_id is not None and n.leaf_id not in aligned_ids]

    used = {kept[i].marker for i in aligned_nodes.values()}
    unmatched = [markers[k] for k in order if k not in used]
    return aligned, unaligned, unmatched
