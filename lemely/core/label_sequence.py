"""Bind a reading-order stream of question labels and student writing to questions.

A reader that looks at a scanned script returns one list, in reading order, of the
question labels it sees ("1", "(a)", "(i)", "Q3 b") and the blocks of student writing.
It never says which question a label is or which question a block answers. This module
decides both, from the mark scheme and the order of the list alone. Coordinates take no
part in any decision here.

The governing rule: bind only what the list determines. A leaf with no label, and
writing with no leaf, are safe outcomes. Writing on another question's leaf is the bug
this module exists to prevent, so wherever two readings of the list do equally well,
neither is taken.

How a list is bound (``bind_stream``):

1. Labels become steps (``parse_label``). A label with several steps is one chain,
   parent to child, or it is nothing. The same label twice in a row is one label.
2. Question numbers are chosen as anchors so that the paper as a whole aligns best. An
   anchor is kept only when it beats every other candidate for its question by two
   points, and beats leaving the question out by more than the number itself is worth.
3. Between an anchor and the next, the question's parts are aligned in order, parent
   before child. A restart of the question's top-level labels ends the question: what
   follows is an orphan segment and is never absorbed. A restart lower down ends the
   part. A leaf is bound to a label only when every best alignment binds it there,
   and only when the readings in which the restart is a stray label bind it there too.
4. A question whose number was not seen is aligned from an orphan segment only when it
   sits between two anchored neighbours and every label of the segment is its own.
5. Writing is given to the leaf whose label it follows. A container label, an unplaced
   label and an "uncertain" flag all leave it unbound. So does a label the paper prints
   next and the reader did not list: the writing of the missed part sits in the same
   place, and nothing in the list separates the two.

What the list cannot show: a label listed after the writing it belongs to, or before
the writing of the part above it. The labels are then in paper order and each is
followed by writing, exactly as on a clean script. The one trace such a move leaves is
handled (a leaf with two blocks beside a leaf with none); a move that leaves no trace
puts writing on the neighbouring leaf, and only a check on what the writing says can
catch it.

Pure functions: no I/O, no logging.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from lemely.core.binding import SeenLabel, SeenWriting, UnboundReason, UnboundWriting

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.core.binding import StreamItem
    from lemely.core.loose_schemas import MarkScheme, Question

Level = Literal["number", "letter", "roman"]

DOUBT_NUMBER_NOT_SEEN = "question number not seen"
DOUBT_NEXT_NUMBER_NOT_SEEN = "next question number not seen"
DOUBT_PREVIOUS_PAGE = "continues from the previous page"
DOUBT_ARROW = "tied by an arrow"
# Every doubt a leaf can carry, in the order they are listed on it.
DOUBTS = (DOUBT_NUMBER_NOT_SEEN, DOUBT_NEXT_NUMBER_NOT_SEEN, DOUBT_PREVIOUS_PAGE, DOUBT_ARROW)
# The two things a doubt can mean. A content doubt: the leaf's own label was seen, and it
# may hold writing that is someone else's. An inference doubt: the writing follows the
# leaf's label, and which question that label belongs to was inferred on strong evidence.
CONTENT_DOUBTS = (DOUBT_NEXT_NUMBER_NOT_SEEN, DOUBT_PREVIOUS_PAGE, DOUBT_ARROW)
INFERENCE_DOUBTS = (DOUBT_NUMBER_NOT_SEEN,)

# Roman numerals up to xxix: more than any question has parts.
_ROMAN = re.compile(r"x{0,2}(?:ix|iv|v?i{0,3})")
# A leading "Q" or "Question" only counts as a prefix when a number follows it.
_PREFIX = re.compile(r"\s*(?:question|qn|q)\s*\.?\s*(?=[0-9])", re.IGNORECASE)
_TOKEN = re.compile(r"[0-9]+|[A-Za-z]+")
_PUNCTUATION = re.compile(r"[\s().:\-]*")
# Single characters that are both a roman numeral and a letter.
_AMBIGUOUS = frozenset("ivx")
# No label is longer than this; anything longer is not parsed at all.
_MAX_LABEL_CHARS = 40
_MAX_STEPS = 4
# An anchor must beat every other candidate for its question by this many points.
_ANCHOR_MARGIN = 2


@dataclass(frozen=True, slots=True)
class LabelStep:
    """One label a reader meets: the number, a letter, or a roman numeral."""

    level: Level
    token: str


@dataclass(frozen=True, slots=True)
class BoundLeaf:
    """A leaf question whose label was seen, and the writing that follows that label.

    ``writings`` is empty for a blank answer. ``doubts`` holds strings from ``DOUBTS``.
    """

    question_id: str
    label_seen: str
    number_inferred: bool
    writings: list[SeenWriting]
    doubts: list[str]


@dataclass(frozen=True, slots=True)
class BoundStream:
    """What a reading-order list determines, and what it leaves open.

    ``leaves`` are the aligned leaves in paper order. ``unaligned_ids`` are the other
    leaves, each once: no label was aligned to them, or their label was aligned and
    the writing after it could not be told from a neighbour's. ``unplaced_labels`` are
    the label items no question accounts for.

    ``listing_suspects`` is an observation and changes no binding. Binding rests on the
    reader listing a label before the writing under it. A reader that lists the writing
    first leaves one trace: in a run of leaves that follows a container label, the
    first block falls straight after the container (unbound) and the last leaf of the
    run is blank. Each such run is named by the id of the question or part whose label
    opens it; a run that opens before any label, by the first leaf listed in it.
    """

    leaves: list[BoundLeaf]
    unbound: list[UnboundWriting]
    unaligned_ids: list[str]
    unplaced_labels: list[SeenLabel]
    inferred_numbers: list[str]
    listing_suspects: list[str]


# --------------------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------------------
_Readings = tuple[frozenset[LabelStep], ...]


def _is_roman(token: str) -> bool:
    return bool(token) and _ROMAN.fullmatch(token) is not None


def _single(char: str) -> frozenset[LabelStep]:
    letter = LabelStep("letter", char)
    if char.lower() in _AMBIGUOUS:
        return frozenset({LabelStep("roman", char), letter})
    return frozenset({letter})


def _letters(run: str) -> list[frozenset[LabelStep]] | None:
    """Every reading of a run of letters: "a", "ii", or "bii" as (b)(ii)."""
    low = run.lower()
    if len(run) == 1:
        return [_single(run)]
    if _is_roman(low):
        return [frozenset({LabelStep("roman", run)})]
    if _is_roman(low[1:]):
        rest = run[1:]
        tail = _single(rest) if len(rest) == 1 else frozenset({LabelStep("roman", rest)})
        return [frozenset({LabelStep("letter", run[0])}), tail]
    return None  # a word


def _readings(text: str) -> _Readings | None:
    """Every reading of each step of ``text``; ``None`` when it is not a label.

    Case is kept: the paper prints its parts in lower case, so "(A)" is a label that
    matches no part. It still marks a place where one answer ends.
    """
    if len(text) > _MAX_LABEL_CHARS:
        return None
    body = _PREFIX.sub("", text, count=1)
    if _PUNCTUATION.fullmatch(_TOKEN.sub("", body)) is None:
        return None  # brackets, commas, other scripts around the label
    steps: list[frozenset[LabelStep]] = []
    for position, token in enumerate(_TOKEN.findall(body)):
        if token.isdigit():
            if position != 0 or len(token) > 2 or token.startswith("0"):
                return None  # "Fig. 1.2", "130", "0", "007"
            steps.append(frozenset({LabelStep("number", token)}))
            continue
        run = _letters(token)
        if run is None:
            return None
        steps.extend(run)
    if not 1 <= len(steps) <= _MAX_STEPS:
        return None
    return tuple(steps)


def parse_label(text: str) -> list[LabelStep]:
    """The steps of one label's text, or ``[]`` when it is not a question label.

    Roman numerals are tried before single letters, so "(i)", "(v)" and "(x)" are
    romans here; ``bind_stream`` lets them be letters where the paper says so.
    """
    readings = _readings(text)
    if readings is None:
        return []
    return [min(options, key=lambda step: step.level != "roman") for options in readings]


@dataclass(frozen=True, slots=True)
class _Label:
    """A label item that parsed, with the items after it that repeat it."""

    index: int
    item: SeenLabel
    readings: _Readings
    number: str | None  # the question number it opens with, if any
    repeats: tuple[int, ...]
    joined: bool  # nothing was written between the label before it and this one


def _labels(items: Sequence[StreamItem]) -> list[_Label]:
    out: list[_Label] = []
    previous: int | None = None  # index of the last label item, when it parsed
    joined = False
    for index, item in enumerate(items):
        if not isinstance(item, SeenLabel):
            joined = False
            continue
        readings = _readings(item.text)
        if readings is None:
            continue
        if out and previous == index - 1 and out[-1].readings == readings:
            # The same label twice with nothing between: one label, read twice.
            last = out[-1]
            repeats = (*last.repeats, index)
            out[-1] = _Label(last.index, last.item, readings, last.number, repeats, last.joined)
        else:
            number = next((s.token for s in readings[0] if s.level == "number"), None)
            out.append(_Label(index, item, readings, number, (), joined and bool(out)))
        previous = index
        joined = True
    return out


# --------------------------------------------------------------------------------------
# The paper the mark scheme implies
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Node:
    """One question or part, at its place in paper order."""

    question_id: str
    step: LabelStep | None  # None: an id no label can name
    leaf_id: str | None  # the id a label here binds; None for a container or a doubled id
    path: tuple[int, ...]  # from the question number down to this node
    container: bool


@dataclass(slots=True)
class _Draft:
    question_id: str
    step: LabelStep | None
    container: bool = False
    doubled: bool = False
    parts: dict[str, _Draft] = field(default_factory=dict)


@dataclass(slots=True)
class _Paper:
    nodes: list[_Node] = field(default_factory=list)
    roots: list[int] = field(default_factory=list)
    by_number: dict[str, int] = field(default_factory=dict)
    kids: dict[tuple[int, LabelStep], int] = field(default_factory=dict)
    within: dict[tuple[int, LabelStep], list[int]] = field(default_factory=dict)
    leaf_ids: list[str] = field(default_factory=list)
    chain_cache: dict[tuple[int, _Readings], tuple[tuple[int, ...], ...]] = field(
        default_factory=dict
    )

    def chains(self, root: int, readings: _Readings) -> tuple[tuple[int, ...], ...]:
        """Every parent-to-child run of nodes of question ``root`` that ``readings`` names."""
        key = (root, readings)
        found = self.chain_cache.get(key)
        if found is None:
            if any(step.level == "number" for step in readings[0]):
                starts = [root] if self.nodes[root].step in readings[0] else []
            else:
                starts = [n for step in readings[0] for n in self.within.get((root, step), [])]
            runs: list[tuple[int, ...]] = [(start,) for start in starts]
            for options in readings[1:]:
                runs = [
                    (*run, self.kids[run[-1], step])
                    for run in runs
                    for step in options
                    if (run[-1], step) in self.kids
                ]
            found = self.chain_cache[key] = tuple(sorted(runs))
        return found


def _leaf_ids(mark_scheme: MarkScheme) -> list[str]:
    return [q.id for q in mark_scheme.all_questions_flat() if not q.parts]


def duplicate_leaf_ids(mark_scheme: MarkScheme) -> list[str]:
    """Leaf ids that appear more than once, in paper order, each listed once.

    Two leaves with one id cannot be told apart, so ``bind_stream`` never binds to it.
    """
    counts = Counter(_leaf_ids(mark_scheme))
    return [leaf_id for leaf_id, count in counts.items() if count > 1]


def _own_step(
    question: Question, parent: _Draft | None, siblings: list[_Draft]
) -> LabelStep | None:
    """The label this id adds to its parent's, or ``None`` when no label can name it."""
    own = question.id
    if parent is None:
        if own.isascii() and own.isdigit() and not own.startswith("0"):
            return LabelStep("number", own)
        return None
    if parent.step is None or not own.startswith(parent.question_id):
        return None
    token = own[len(parent.question_id) :].removeprefix("_")
    if not (token.isascii() and token.isalpha() and token.islower()):
        return None  # "1a_i_A", a nested number, an empty suffix
    under = parent.step.level
    if under == "number":
        if len(token) > 1:
            return LabelStep("roman", token) if _is_roman(token) else None
        # "i" opens a roman run; "v" or "x" continue one. After "h", "i" is a letter.
        previous = siblings[-1].step if siblings else None
        after_roman = previous is not None and previous.level == "roman"
        opens_run = not siblings and token == "i"  # noqa: S105 (a roman numeral, not a secret)
        if token in _AMBIGUOUS and (opens_run or after_roman):
            return LabelStep("roman", token)
        return LabelStep("letter", token)
    if under == "letter":
        return LabelStep("roman", token) if _is_roman(token) else None
    return LabelStep("letter", token) if len(token) == 1 else None  # a letter under a roman


def _grow(questions: list[Question], parent: _Draft | None, into: dict[str, _Draft]) -> None:
    for question in questions:
        draft = into.get(question.id)
        if draft is None:
            step = _own_step(question, parent, list(into.values()))
            for sibling in into.values():
                if step is not None and sibling.step == step:
                    # Two ids, one printed label: neither can be told from the other.
                    sibling.doubled = True
                    step = None
            draft = into[question.id] = _Draft(question.id, step)
        else:
            # The id again: one printed label as far as the page goes.
            draft.doubled = True
        draft.container = draft.container or bool(question.parts)
        _grow(question.parts, draft, draft.parts)


def _build(mark_scheme: MarkScheme) -> _Paper:
    top: dict[str, _Draft] = {}
    _grow(mark_scheme.questions, None, top)
    doubled = set(duplicate_leaf_ids(mark_scheme))
    paper = _Paper(leaf_ids=list(dict.fromkeys(_leaf_ids(mark_scheme))))

    def place(draft: _Draft, above: tuple[int, ...]) -> None:
        index = len(paper.nodes)
        path = (*above, index)
        binds = draft.step is not None and not draft.container and not draft.doubled
        leaf_id = draft.question_id if binds and draft.question_id not in doubled else None
        paper.nodes.append(_Node(draft.question_id, draft.step, leaf_id, path, draft.container))
        if draft.step is not None:
            if above:
                paper.kids[above[-1], draft.step] = index
                paper.within.setdefault((path[0], draft.step), []).append(index)
            else:
                paper.by_number[draft.step.token] = index
        for part in draft.parts.values():
            place(part, path)

    for draft in top.values():
        paper.roots.append(len(paper.nodes))
        place(draft, ())
    return paper


# --------------------------------------------------------------------------------------
# Rule 3: one question against the labels after its number
# --------------------------------------------------------------------------------------
def _fit(
    paper: _Paper, path: list[int], depth: int, readings: _Readings, deepest: int
) -> list[int] | None:
    """The place of a label under ``path[depth]``, reading forward from where the list is.

    Each step must be a part of the one before it. A step may name the part the list
    is already in (a label written with its path: "(b)(ii)" under "(b)"), as long as a
    later step is new. The first new part must come after the one the list is in at
    that level, and no deeper than ``deepest``.
    """
    out = path[: depth + 1]
    new = False
    for offset, options in enumerate(readings):
        child = next((paper.kids[out[-1], s] for s in options if (out[-1], s) in paper.kids), None)
        if child is None:
            return None
        here = depth + 1 + offset
        if not new:
            if here < len(path) and child < path[here]:
                return None  # a part already passed
            if here >= len(path) or child > path[here]:
                if here > deepest:
                    return None
                new = True
        out.append(child)
    return out if new else None


@dataclass(frozen=True, slots=True)
class _Span:
    """The stretch of labels one question is read from."""

    end: int  # the question's labels stop before this position
    restarted: bool  # ... because its top-level labels started again
    orphans: frozenset[int]  # labels inside it that belong to a part whose label was not seen


def _span(
    paper: _Paper,
    root: int,
    start: tuple[int, ...],
    labels: list[_Label],
    lo: int,
    hi: int,
    stops: frozenset[int],
    ignore: int | None = None,
) -> _Span:
    """Read ``labels[lo:hi]`` as the question that starts at ``start``, as far as it goes.

    The list is followed down the question's tree: a label is tried first as a part of
    the deepest part the list is in, then of each part above it. A label that names a
    part at or before the one the list is already in, at some level, is a restart:

    * at the top level ("(a)" after "(c)") another question's labels have begun, and
      the question ends there;
    * lower down ("(i)" after "(ii)" under one letter) the part above has ended and a
      part whose own label was not seen has begun. Its labels are orphans, up to the
      next label that continues the question at a higher level.

    A label may be written with its path, from the question number ("3(b)(ii)") or
    from a part ("(b)(ii)"): the steps the list is already in are named again, and the
    label is followed for the step that is new.

    A position in ``stops`` (a number that may open a question with no anchor) also
    ends the question. The label at ``ignore`` is read as a stray: it ends nothing.
    """
    path = list(paper.nodes[start[-1]].path)
    closed: int | None = None  # the level whose part has ended, while orphans are read
    orphans: set[int] = set()
    loose: list[int] = []  # parts further on that the last label with no place may be
    for position in range(lo, hi):
        if position == ignore:
            continue
        if position in stops:
            return _Span(position, False, frozenset(orphans))
        label = labels[position]
        first = label.readings[0]
        deepest = len(path) if closed is None else closed
        if label.number is not None:
            # A number that is no anchor is a stray, unless it is this question's own
            # number at the head of a path that goes on from where the list is.
            if paper.nodes[root].step in first and len(label.readings) > 1:
                onward = _fit(paper, path, 0, label.readings[1:], deepest)
                if onward is not None:
                    path, closed, loose = onward, None, []
            continue
        if any((part, step) in paper.kids for part in loose for step in first):
            # The label before had no place; if a part's own label was missed before
            # it, this one sits under it. The question is not followed further.
            return _Span(position, False, frozenset(orphans))
        placed: list[int] | None = None
        for depth in range(len(path) - 1, -1, -1):
            placed = _fit(paper, path, depth, label.readings, deepest)
            if placed is not None:
                break
        if placed is not None:
            path, closed, loose = placed, None, []
            continue
        # The shallowest level at which this label names a part already passed. While
        # orphans are read, only the top level is looked at.
        for depth in range(len(path) - 1 if closed is None else min(1, len(path) - 1)):
            options = ((path[depth], step) for step in first)
            part = next((paper.kids[key] for key in options if key in paper.kids), None)
            if part is not None and part <= path[depth + 1]:
                if depth == 0:
                    return _Span(position, True, frozenset(orphans))
                closed, path = depth, path[: depth + 1]
                break
        if closed is not None:
            orphans.add(position)
        loose = [
            part
            for step in label.readings[-1]
            for part in paper.within.get((root, step), [])
            if part > path[-1]
        ]
    return _Span(hi, False, frozenset(orphans))


# One binding of a best alignment: (label position, the nodes it names), linked to the
# bindings before it.
_Trail = tuple[int, tuple[int, ...], "_Trail"] | None


def _solve(
    paper: _Paper,
    root: int,
    start: tuple[int, ...],
    labels: list[_Label],
    lo: int,
    hi: int,
    skip: frozenset[int] = frozenset(),
    forbid: tuple[int, int] | None = None,
) -> tuple[list[int], _Trail]:
    """Align question ``root`` to ``labels[lo:hi]``; the best score after each label.

    The score is the number of nodes given a label. A node is matched only under a
    matched parent, each node at most once, in paper order. That makes the state the
    last matched node alone: the next match must hang from it or from one of its
    ancestors, and come after it.

    A label with several steps names a parent-to-child run of nodes. The run may begin
    with nodes already matched, on the path to the last matched node (a label written
    with its path); they are named again, not matched again, and only the rest of the
    run scores. Labels in ``skip`` are passed over; ``forbid`` rules out one
    (label, node) binding.
    """
    nodes = paper.nodes
    table: dict[int, tuple[int, _Trail]] = {start[-1]: (0, None)}
    best = 0
    scores = [0]
    for position in range(lo, hi):
        chains = () if position in skip else paper.chains(root, labels[position].readings)
        if chains:
            before = list(table.items())
            for chain in chains:
                end = chain[-1]
                if forbid == (position, end):
                    continue
                for last, (score, trail) in before:
                    path = nodes[last].path
                    named = 0  # steps that name parts the list is already in
                    while named < len(chain) and chain[named] in path:
                        named += 1
                    if named == len(chain):
                        continue  # nothing new
                    new = chain[named]
                    if new <= last or nodes[new].path[-2] not in path:
                        continue
                    total = score + len(chain) - named
                    if end not in table or total > table[end][0]:
                        table[end] = (total, (position, chain, trail))
                        best = max(best, total)
        scores.append(best)
    winner = max(table.values(), key=lambda entry: entry[0])
    return scores, winner[1]


def _bindings(trail: _Trail) -> dict[int, tuple[int, ...]]:
    out: dict[int, tuple[int, ...]] = {}
    while trail is not None:
        out[trail[0]] = trail[1]
        trail = trail[2]
    return out


def _determined(
    paper: _Paper,
    root: int,
    start: tuple[int, ...],
    labels: list[_Label],
    lo: int,
    hi: int,
    skip: frozenset[int] = frozenset(),
) -> dict[int, tuple[int, ...]]:
    """The bindings every best alignment makes: label position to the nodes it names.

    A binding is kept only when forbidding it lowers the best score. Where another
    label does as well, nothing says which is the part's label, and neither is taken.

    A part with sub-parts is held to more. If, with its label forbidden, the next best
    alignment binds under the part a label that the best alignment leaves unbound, the
    part is on another label there (a sub-part is matched only under a matched part),
    and there are two places that each look like that part, each with sub-parts of its
    own. Which aligns more does not say which is the real one: the part and everything
    under it are not bound.
    """
    scores, trail = _solve(paper, root, start, labels, lo, hi, skip)
    best = _bindings(trail)
    kept: dict[int, tuple[int, ...]] = {}
    rivalled: set[int] = set()  # parts with two places
    for position, chain in best.items():
        part = chain[-1]
        without, other = _solve(paper, root, start, labels, lo, hi, skip, (position, part))
        if without[-1] < scores[-1]:
            kept[position] = chain
        if any(
            p not in best and part in paper.nodes[nodes[-1]].path[:-1]
            for p, nodes in _bindings(other).items()
        ):
            rivalled.add(part)
    return {
        position: chain
        for position, chain in kept.items()
        if not rivalled.intersection(paper.nodes[chain[-1]].path)
    }


# --------------------------------------------------------------------------------------
# Rule 2: question numbers
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Candidate:
    position: int
    root: int
    chain: tuple[int, ...]  # the nodes the label names: the number, then any parts


def _candidates(paper: _Paper, labels: list[_Label]) -> list[_Candidate]:
    out = []
    for position, label in enumerate(labels):
        root = paper.by_number.get(label.number) if label.number is not None else None
        if root is None:
            continue
        chains = paper.chains(root, label.readings)
        if len(chains) == 1:
            out.append(_Candidate(position, root, chains[0]))
    return out


def _opens_unanchored(paper: _Paper, label: _Label, kept: dict[int, _Candidate]) -> bool:
    """Whether a label opens with the number of a question that has no anchor."""
    root = paper.by_number.get(label.number) if label.number is not None else None
    return root is not None and root not in kept


def _anchors(paper: _Paper, labels: list[_Label]) -> dict[int, _Candidate]:
    """The question numbers the list determines: question to the label that opens it.

    Candidates are chosen, at most one per question and in paper order, to maximise one
    point per anchor plus the points each question earns between its anchor and the
    next. An anchor is kept when (a) no other candidate for its question comes within
    ``_ANCHOR_MARGIN`` of the best total, and none claims parts of its own, unless
    that candidate is a label of the question's own span, written with its path from
    the number; (b) the best total without the question is lower by more than the
    number alone accounts for; and (c) it is not the last of a run of numbered lines.
    """
    cands = _candidates(paper, labels)
    if not cands:
        return {}
    order = {root: k for k, root in enumerate(paper.roots)}
    count = len(labels)
    earned: list[list[int]] = []
    for cand in cands:
        if paper.nodes[cand.root].container:
            lo = cand.position + 1
            read = _span(paper, cand.root, cand.chain, labels, lo, count, frozenset())
            scores, _ = _solve(paper, cand.root, cand.chain, labels, lo, read.end, read.orphans)
        else:
            scores = [0]
        earned.append(scores)

    def span(i: int, position: int) -> int:
        """What candidate i earns from the labels before ``position``."""
        scores = earned[i]
        return scores[min(position - cands[i].position - 1, len(scores) - 1)]

    size = len(cands)
    rank = [order[cand.root] for cand in cands]
    worth = [len(cand.chain) for cand in cands]  # the number, and any parts named with it
    ahead = [0] * size  # best total from candidate i on, i chosen
    following: list[int | None] = [None] * size  # the next anchor on that best choice
    for i in range(size - 1, -1, -1):
        most, nxt = span(i, count), None
        for j in range(i + 1, size):
            if rank[j] > rank[i] and span(i, cands[j].position) + ahead[j] > most:
                most, nxt = span(i, cands[j].position) + ahead[j], j
        ahead[i] = worth[i] + most
        following[i] = nxt
    behind = [0] * size  # best total before candidate i, i chosen
    preceding: list[int | None] = [None] * size  # the anchor before it on that best choice
    for i in range(size):
        for h in range(i):
            total = behind[h] + worth[h] + span(h, cands[i].position)
            if rank[h] < rank[i] and total > behind[i]:
                behind[i], preceding[i] = total, h
    through = [behind[i] + ahead[i] for i in range(size)]
    best = max(through)

    # The best total that leaves a question out: the last anchor before it and the
    # first after it stand next to each other, or one of the two is missing.
    questions = len(paper.roots)
    bridged = [[0] * questions for _ in range(questions)]
    for h in range(size):
        for j in range(h + 1, size):
            if rank[j] > rank[h]:
                total = behind[h] + worth[h] + span(h, cands[j].position) + ahead[j]
                bridged[rank[h]][rank[j]] = max(bridged[rank[h]][rank[j]], total)
    for low in range(questions):
        for high in range(questions - 1, -1, -1):
            if low:
                bridged[low][high] = max(bridged[low][high], bridged[low - 1][high])
            if high + 1 < questions:
                bridged[low][high] = max(bridged[low][high], bridged[low][high + 1])

    def without(question: int) -> int:
        total = 0
        if 0 < question < questions - 1:
            total = bridged[question - 1][question + 1]
        for i in range(size):
            if rank[i] > question:
                total = max(total, ahead[i])
            elif rank[i] < question:
                total = max(total, behind[i] + worth[i] + span(i, count))
        return total

    def bound_by(i: int, hi: int, *, cut: bool) -> set[int]:
        """The labels before ``hi`` that candidate i binds as its question's anchor.

        With ``cut`` the question stops where its labels restart, as it will be read;
        without, it runs on to ``hi``, which is the most the candidate could claim.
        """
        cand = cands[i]
        lo, end, skip = cand.position + 1, hi, frozenset[int]()
        if cut:
            read = _span(paper, cand.root, cand.chain, labels, lo, hi, frozenset())
            end, skip = read.end, read.orphans
        return set(_bindings(_solve(paper, cand.root, cand.chain, labels, lo, end, skip)[1]))

    bound_on: dict[tuple[int, ...], set[int]] = {}  # per choice of anchors, the labels bound

    def best_choice(i: int) -> tuple[set[int], int, int]:
        """The best choice of anchors through candidate i.

        Returns every label some question binds on it, and the positions of the
        anchors on either side of i: another start for i's question has to lie
        between them.
        """
        chain = [i]
        while (before := preceding[chain[0]]) is not None:
            chain.insert(0, before)
        while (after := following[chain[-1]]) is not None:
            chain.append(after)
        taken = bound_on.get(tuple(chain))
        if taken is None:
            taken = bound_on[tuple(chain)] = {cands[k].position for k in chain}
            for k, nxt in zip(chain, [*chain[1:], None], strict=True):
                taken |= bound_by(k, cands[nxt].position if nxt is not None else count, cut=True)
        at = chain.index(i)
        left = cands[chain[at - 1]].position if at else -1
        right = cands[chain[at + 1]].position if at + 1 < len(chain) else count
        return taken, left, right

    kept: dict[int, _Candidate] = {}
    for root in paper.roots:
        mine = [i for i in range(size) if cands[i].root == root]
        tops = [i for i in mine if through[i] == best]
        needed = _ANCHOR_MARGIN if paper.nodes[root].container else 1
        if not tops or best - without(order[root]) < needed:
            continue
        chosen = cands[tops[0]]
        # A rival is another candidate that comes within the margin of the best total,
        # or that claims parts of its own whatever the margin: it stands where the
        # question could start (between the anchors of the questions on either side)
        # and, as the anchor, could be followed by parts that the best choice of
        # anchors leaves to no question. Two places that each look like the start of the
        # question are not settled by which earns more. (A stray number that would
        # only take its parts from a neighbour claims nothing.)
        rivals = [i for i in mine if i != tops[0] and through[i] > best - _ANCHOR_MARGIN]
        others = [i for i in mine if i != tops[0] and i not in rivals]
        if others:
            taken, left, right = best_choice(tops[0])
            for i in others:
                # Its own stretch of the list: up to the chosen anchor if that comes
                # after it, else up to the next question's anchor.
                at = cands[i].position
                end = chosen.position if at < chosen.position else right
                if left < at < right and not bound_by(i, end, cut=False) <= taken:
                    rivals.append(i)
        if rivals:
            # A paper labelled with full paths ("1(a)(i)", "1(a)(ii)", "1b") gives every
            # part a label that opens with the number. Those after the first are no
            # rivals for the anchor: they are determined labels of its own span.
            nxt = following[tops[0]]
            hi = cands[nxt].position if nxt is not None else count
            lo = chosen.position + 1
            read = _span(paper, root, chosen.chain, labels, lo, hi, frozenset())
            own = _determined(paper, root, chosen.chain, labels, lo, read.end, read.orphans)
            if any(cands[i].position not in own for i in rivals):
                continue  # two places for the number: neither
        kept[root] = chosen

    # Numbered lines listed as labels ("1.", "2." under one part) are numbers too. An
    # anchor that comes straight after the bare number one below it, with nothing
    # written between them, is the last of such a run when that number is no anchor
    # itself. ("1b" before "2a" is a part of question 1, not a numbered line.)
    dropped = True
    while dropped:
        dropped = False
        anchors = {cand.position for cand in kept.values()}
        for root, cand in list(kept.items()):
            before = cand.position - 1
            if before < 0 or not labels[cand.position].joined or before in anchors:
                continue
            number, step = labels[before].number, paper.nodes[root].step
            if number is None or step is None or len(labels[before].readings) > 1:
                continue
            if int(number) + 1 == int(step.token):
                del kept[root]
                dropped = True
    return kept


# --------------------------------------------------------------------------------------
# Rules 3 and 4 over the whole list
# --------------------------------------------------------------------------------------
@dataclass(slots=True)
class _Alignment:
    placed: dict[int, tuple[int, ...]] = field(default_factory=dict)  # label position -> nodes
    inferred: list[int] = field(default_factory=list)  # questions aligned without a number
    # question -> the last label in its stretch that is a part of an unseen later question
    foreign: dict[int, int] = field(default_factory=dict)


def _align(paper: _Paper, labels: list[_Label]) -> _Alignment:
    kept = _anchors(paper, labels)
    out = _Alignment()
    # A number that names a question with no anchor may be that question's number:
    # the question before it ends there.
    stops = frozenset(
        position for position, label in enumerate(labels) if _opens_unanchored(paper, label, kept)
    )
    anchored = sorted(kept.values(), key=lambda cand: cand.position)
    spans: dict[int, tuple[int, int, _Span]] = {}  # question -> first label, next anchor, span
    own: dict[int, dict[int, tuple[int, ...]]] = {}
    for k, cand in enumerate(anchored):
        hi = anchored[k + 1].position if k + 1 < len(anchored) else len(labels)
        lo = cand.position + 1
        read = _span(paper, cand.root, cand.chain, labels, lo, hi, stops)
        spans[cand.root] = (lo, hi, read)
        own[cand.root] = _determined(
            paper, cand.root, cand.chain, labels, lo, read.end, read.orphans
        )
        out.placed[cand.position] = cand.chain

    # Rule 4: a question between two anchored neighbours, its number not seen.
    explained: set[int] = set()  # questions whose restart is the next question's start
    for k in range(1, len(paper.roots) - 1):
        root, before, after = paper.roots[k], paper.roots[k - 1], paper.roots[k + 1]
        if root in kept or before not in kept or after not in kept:
            continue
        if not spans[before][2].restarted or not paper.nodes[root].container:
            continue
        # A candidate for the number would have ended the question before at a stop,
        # not at a restart, or stands in the segment, where it aligns to nothing.
        lo, hi = spans[before][2].end, kept[after].position
        read = _span(paper, root, (root,), labels, lo, hi, frozenset())
        if read.end != hi:
            continue  # a second orphan segment
        segment = _determined(paper, root, (root,), labels, lo, hi, read.orphans)
        if len(segment) != hi - lo:
            continue  # a label of the segment is not this question's
        if not any(paper.nodes[chain[-1]].leaf_id for chain in segment.values()):
            continue
        out.placed.update(segment)
        out.inferred.append(root)
        explained.add(before)

    # A cut is one reading of the list. The other is that a label near it is a stray
    # and the question (or the part) runs on. A binding stands only when the rival
    # readings make it too:
    # * with orphans in the span: no part began unseen, and they are the question's own;
    # * the label at the cut is a stray: the question runs on up to and including the
    #   label that would cut it next;
    # * the question runs on as far as the next number, when that aligns more of it
    #   (the cut left a part unlabelled that a later label can fill).
    # Rule 4 settles what follows a restart, so the last two are no rivals then.
    for root, (lo, hi, read) in spans.items():
        chain = kept[root].chain
        rivals = [read.end] if read.orphans else []
        if read.end < hi and root not in explained:
            again = _span(paper, root, chain, labels, lo, hi, stops, read.end)
            rivals.append(min(again.end + 1, hi))
            numbers = (p for p in range(read.end, hi) if labels[p].number is not None)
            far = next(numbers, hi)
            cut_score = _solve(paper, root, chain, labels, lo, read.end, read.orphans)[0][-1]
            if _solve(paper, root, chain, labels, lo, far)[0][-1] > cut_score:
                rivals.append(far)
        for limit in dict.fromkeys(rivals):
            runs_on = _determined(paper, root, chain, labels, lo, limit)
            own[root] = {
                position: nodes
                for position, nodes in own[root].items()
                if position in runs_on and runs_on[position][-1] == nodes[-1]
            }
        out.placed.update(own[root])

    # A part label the question does not have, and that a question after it with no
    # anchor does have, shows that question's labels inside this one's stretch.
    for k, cand in enumerate(anchored):
        nxt = anchored[k + 1].root if k + 1 < len(anchored) else len(paper.nodes)
        unseen = [r for r in paper.roots if cand.root < r < nxt and r not in out.inferred]
        lo, _, read = spans[cand.root]
        for position in range(lo, read.end):
            readings = labels[position].readings
            if labels[position].number is not None or paper.chains(cand.root, readings):
                continue
            if any(paper.chains(other, readings) for other in unseen):
                out.foreign[cand.root] = position
    return out


# --------------------------------------------------------------------------------------
# Rule 5: writing
# --------------------------------------------------------------------------------------
def _names_part_of(paper: _Paper, label: _Label, node: int) -> bool:
    """Whether a part label names something under ``node``: a part of it, at any depth."""
    if label.number is not None:
        return False
    root = paper.nodes[node].path[0]
    named = (part for step in label.readings[0] for part in paper.within.get((root, step), []))
    return any(part != node and node in paper.nodes[part].path for part in named)


def _open_leaves(
    paper: _Paper, alignment: _Alignment, labels: list[_Label], written_under: set[int]
) -> tuple[set[int], set[int], set[int]]:
    """Leaves whose writing the list brackets: the open ones, the doubted, the unreadable.

    Writing after a leaf's label is that leaf's only if the next placed label is the
    one the paper prints next: the next part, the container above the next part, or
    the next question's number. If a label between them was not seen, the writing of
    the missed part lies in the same stretch of the list. The one label that may be
    absent is the number of an inferred question: the leaf before it keeps its
    writing, with a doubt, because anything written beside the unseen number lands
    there too. The last leaf of the paper has nothing after it to wait for, and is
    open as long as no label at all is listed after its own.

    Where the only ids between the two labels are ones no label can name, the leaf is
    not open either, and is returned as unreadable: the list can never bracket it.

    A part label with no place can show that the two placed labels around it are not
    the neighbours they seem:

    * it names a part of the next one ("(ii)" listed before the "(c)" it belongs under):
      that part began before its label, and the leaf before it is not separated;
    * it has writing under it (``written_under``), so it is a part the reader got
      wrong, and the paper has no part between the two for it to be: neither of the
      two keeps its writing;
    * it is a part the leaf's question does not have and a later question with no
      anchor does, and it stands after the leaf's next label: that question's labels
      are in this one's stretch, and the next label may be one of them.
    """
    inferred = set(alignment.inferred)
    order = sorted(alignment.placed)
    ends = [alignment.placed[position][-1] for position in order]
    shut: set[int] = set()
    doubted: set[int] = set()
    unreadable: set[int] = set()
    for k in range(len(order)):
        last = k + 1 == len(order)
        chain = () if last else alignment.placed[order[k + 1]]
        until = len(paper.nodes) if last else ends[k + 1]
        gap = [n for n in range(ends[k] + 1, until) if n not in chain]
        skipped = [n for n in gap if n not in inferred]
        between = range(order[k] + 1, len(labels) if last else order[k + 1])
        written = not last and any(p in written_under for p in between)
        early = not last and any(_names_part_of(paper, labels[p], until) for p in between)
        # After the last leaf of the paper any label at all is one too many.
        missing = bool(skipped) or until <= ends[k] or (last and len(between) > 0)
        # The next label may be an unseen question's when a part of that question, which
        # this one does not have, is listed further on in this question's stretch.
        foreign = alignment.foreign.get(paper.nodes[ends[k]].path[0], -1)
        if not last and order[k + 1] < foreign:
            shut.add(ends[k])
        if missing or written or early:
            shut.add(ends[k])
            if skipped and all(paper.nodes[n].step is None for n in skipped):
                unreadable.add(ends[k])
        elif gap:
            doubted.add(ends[k])  # only an inferred number lies between
        if written and not missing:
            shut.add(ends[k + 1])
    opened = {end for end in ends if paper.nodes[end].leaf_id is not None and end not in shut}
    return opened, doubted & opened, unreadable - opened


def _beside_a_blank(
    paper: _Paper, items: Sequence[StreamItem], node_at: dict[int, int | None], repeats: set[int]
) -> tuple[set[int], set[int]]:
    """Leaves holding two blocks or more next to a label holding none, and those neighbours.

    "(i) (ii) writing writing" and "(i) writing writing (ii)" are what a list looks like
    when a label is listed a little before or after its place: one block is the blank
    neighbour's. Nothing in the list says which, so neither leaf is given writing. The
    blank neighbour may be a label no question accounts for (a misread "(i)").
    """
    events = [index for index in sorted(node_at) if index not in repeats]
    bounds = [*events, len(items)]
    blocks = [
        sum(isinstance(item, SeenWriting) for item in items[bounds[k] : bounds[k + 1]])
        for k in range(len(events))
    ]

    doubled: set[int] = set()
    blank: set[int] = set()
    for k in range(len(events) - 1):
        first, second = node_at[events[k]], node_at[events[k + 1]]
        if second is None or first == second or paper.nodes[second].leaf_id is None:
            continue
        if first is None:
            if blocks[k] == 0 and blocks[k + 1] >= 2:
                doubled.add(second)
        elif paper.nodes[first].leaf_id is not None:
            if blocks[k] == 0 and blocks[k + 1] >= 2:
                blank.add(first)
                doubled.add(second)
            elif blocks[k] >= 2 and blocks[k + 1] == 0:
                doubled.add(first)
                blank.add(second)
    return doubled, blank


def bind_stream(items: Sequence[StreamItem], mark_scheme: MarkScheme) -> BoundStream:
    """Decide which question each label is and which leaf each block of writing answers.

    Never raises: an id the scheme spells in a way no label can name costs that leaf,
    and a list that makes no sense binds nothing.
    """
    paper = _build(mark_scheme)
    labels = _labels(items)
    alignment = _align(paper, labels)
    bounds = [*(label.index for label in labels), len(items)]
    # Part labels with writing under them. A label that opens with a number is left out:
    # a numbered line or a continuation label says nothing about the parts around it.
    written_under = {
        position
        for position, label in enumerate(labels)
        if label.number is None
        and any(isinstance(i, SeenWriting) for i in items[bounds[position] : bounds[position + 1]])
    }
    opened, doubted, unreadable = _open_leaves(paper, alignment, labels, written_under)
    inferred = set(alignment.inferred)

    node_at: dict[int, int | None] = {}  # item index of a label -> the node it names
    repeats: set[int] = set()  # a label read twice is reported once
    for position, label in enumerate(labels):
        chain = alignment.placed.get(position)
        repeats.update(label.repeats)
        for index in (label.index, *label.repeats):
            node_at[index] = chain[-1] if chain is not None else None

    doubled, blank = _beside_a_blank(paper, items, node_at, repeats)
    writings: dict[int, list[SeenWriting]] = {}
    doubts: dict[int, set[str]] = {}
    seen: dict[int, str] = {}
    # Leaves with something in their stretch that was not bound (writing, or a label
    # with no place): they are not blank answers.
    set_aside: set[int] = set(blank)
    unbound: list[UnboundWriting] = []
    unplaced: list[SeenLabel] = []
    target: int | None = None
    stretch: int | None = None  # the leaf whose label was the last placed label
    reason: UnboundReason = "before_first_label"
    labelled: set[int] = set()
    written: set[int] = set()
    # Runs of leaves for ``listing_suspects``: (the container that opens the run, whether
    # a block fell straight after it, the leaves listed in the run). A block is unbound
    # for "after_container_label" or "before_first_label" only until the next label,
    # so the reason alone says that it fell at the opening of the run.
    runs: list[tuple[int | None, bool, list[int]]] = []
    opener: int | None = None
    fell = False
    listed: list[int] = []
    for index, item in enumerate(items):
        if isinstance(item, SeenLabel):
            if index not in node_at:
                continue  # not a label: ignored, and no barrier
            labelled.add(item.page)
            node = node_at[index]
            if node is not None and paper.nodes[node].container:
                runs.append((opener, fell, listed))
                opener, fell, listed = node, False, []
            if node is None or not (paper.nodes[node].leaf_id or paper.nodes[node].container):
                # No question accounts for it, or two leaves share the id it names.
                target, reason = None, "after_unplaced_label"
                if stretch is not None:
                    set_aside.add(stretch)  # something was listed under the leaf
                if node is not None:
                    stretch = None
                if index not in repeats:
                    unplaced.append(item)
            elif paper.nodes[node].container:
                target, stretch, reason = None, None, "after_container_label"
            else:
                seen.setdefault(node, item.text)
                writings.setdefault(node, [])
                stretch = node
                if node not in listed:
                    listed.append(node)
                if node in doubled:
                    target, reason = None, "neighbour_left_blank"
                elif node in unreadable:
                    target, reason = None, "next_label_unreadable"
                elif node not in opened:
                    target, reason = None, "next_label_not_seen"
                else:
                    target = node
            continue
        first_on_page = item.page not in written
        written.add(item.page)
        if item.placed_by == "uncertain" or target is None:
            why: UnboundReason = "uncertain" if item.placed_by == "uncertain" else reason
            unbound.append(UnboundWriting(writing=item, reason=why))
            if stretch is not None:
                set_aside.add(stretch)
            fell = fell or why in ("after_container_label", "before_first_label")
            continue
        writings[target].append(item)
        if first_on_page and item.page not in labelled:
            doubts.setdefault(target, set()).add(DOUBT_PREVIOUS_PAGE)
        if item.placed_by == "arrow":
            doubts.setdefault(target, set()).add(DOUBT_ARROW)

    leaves: list[BoundLeaf] = []
    for node in sorted(writings):
        if not writings[node] and node in set_aside:
            continue  # its writing was set aside: not a blank answer
        mine = doubts.get(node, set())
        number_inferred = paper.nodes[node].path[0] in inferred
        if number_inferred:
            mine.add(DOUBT_NUMBER_NOT_SEEN)
        if node in doubted:
            mine.add(DOUBT_NEXT_NUMBER_NOT_SEEN)
        leaf_id = paper.nodes[node].leaf_id
        if leaf_id is not None:
            leaves.append(
                BoundLeaf(
                    question_id=leaf_id,
                    label_seen=seen[node],
                    number_inferred=number_inferred,
                    writings=writings[node],
                    doubts=[doubt for doubt in DOUBTS if doubt in mine],
                )
            )
    aligned = {leaf.question_id for leaf in leaves}
    blank_ids = {leaf.question_id for leaf in leaves if not leaf.writings}
    suspects = [
        paper.nodes[run[0] if opened_by is None else opened_by].question_id
        for opened_by, block_fell, run in [*runs, (opener, fell, listed)]
        if block_fell and run and paper.nodes[run[-1]].leaf_id in blank_ids
    ]
    inferred_numbers = [
        step.token for root in sorted(inferred) if (step := paper.nodes[root].step) is not None
    ]
    return BoundStream(
        leaves=leaves,
        unbound=unbound,
        unaligned_ids=[leaf_id for leaf_id in paper.leaf_ids if leaf_id not in aligned],
        unplaced_labels=unplaced,
        inferred_numbers=inferred_numbers,
        listing_suspects=list(dict.fromkeys(suspects)),
    )
