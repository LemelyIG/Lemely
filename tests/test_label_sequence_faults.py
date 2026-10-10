"""Fault battery for ``bind_stream``: a faulty read must never move writing.

A stream is built from a mark scheme: every label in paper order, and after each leaf
label one block of writing whose text is that leaf's id. Faults are then applied to the
labels: the writing stays where it was, as it does when a reader misses or misreads a
label. The one rule every battery checks:

    no leaf holds writing whose text is another leaf's id.

Unbound writing and unaligned leaves are safe outcomes and never fail a trial. They are
counted, so that the cost of a fault can be reported.

Every leaf of these streams has writing. That matters for one fault the generators can
compose: a label dropped and a stray of the same text put back on the other side of its
writing, which is a label listed out of place. With writing under every leaf it leaves a
trace (two blocks beside none) and is caught. Where the neighbouring leaf is blank it
leaves none: ``tests/test_label_sequence.py`` pins that limit.

The streams of ``CRITICAL`` and ``VARIANTS`` are the reproductions from the review of
the first version of the module, which bound by position on the page.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import pytest

from lemely.core.binding import SeenLabel, SeenWriting, StreamItem
from lemely.core.label_sequence import BoundStream, bind_stream, duplicate_leaf_ids
from lemely.core.loose_schemas import MarkScheme

_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "mark-schemes"
_BATTERY_SCHEMES = (
    "0625_w24_ms_41.json",
    "0625_w24_ms_12.json",  # numbers only
    "0606_s19_ms_23.json",  # roman under number
    "0580_s21_ms_31.json",  # fourth level
    "0625_s23_ms_42.json",
)
_LARGEST_SCHEME = "0580_w23_ms_33.json"


# --------------------------------------------------------------------------------------
# Streams
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Entry:
    """One item of a probe stream: a label, or the writing of the leaf ``text`` names."""

    text: str
    writing: bool = False


def _label(text: str) -> Entry:
    return Entry(text)


def _writing(leaf: str) -> Entry:
    return Entry(leaf, writing=True)


@dataclass
class Paper:
    """A scheme with the tree facts the fault generators need."""

    name: str
    scheme: MarkScheme
    ids: list[str] = field(default_factory=list)
    parent: list[int | None] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    is_leaf: list[bool] = field(default_factory=list)

    @classmethod
    def load(cls, name: str) -> Paper:
        scheme = MarkScheme.model_validate(json.loads((_CORPUS / name).read_text()))
        paper = cls(name, scheme)
        index: dict[str, int] = {}

        def visit(questions: list, up: int | None) -> None:
            for question in questions:
                if question.id in index:
                    # A duplicated id is one printed label as far as the paper goes.
                    visit(question.parts, index[question.id])
                    continue
                index[question.id] = len(paper.ids)
                above = paper.ids[up] if up is not None else ""
                paper.ids.append(question.id)
                paper.parent.append(up)
                paper.tokens.append(question.id[len(above) :].removeprefix("_"))
                paper.is_leaf.append(not question.parts)
                visit(question.parts, index[question.id])

        visit(scheme.questions, None)
        return paper

    @property
    def bindable(self) -> set[str]:
        """Leaves a perfect read can bind: every leaf whose id appears once."""
        doubled = set(duplicate_leaf_ids(self.scheme))
        return {i for i, leaf in zip(self.ids, self.is_leaf, strict=True) if leaf} - doubled

    def label(self, j: int) -> str:
        return self.tokens[j] if self.parent[j] is None else f"({self.tokens[j]})"

    def path(self, j: int) -> list[int]:
        out = [j]
        while (up := self.parent[out[0]]) is not None:
            out.insert(0, up)
        return out

    def question(self, j: int) -> int:
        return self.path(j)[0]

    def children(self, j: int) -> list[int]:
        return [k for k in range(j + 1, len(self.ids)) if self.parent[k] == j]

    def subtree_leaves(self, j: int) -> set[str]:
        """Leaves at or under node j: what missing or misreading its label may cost."""
        return {self.ids[k] for k in range(len(self.ids)) if self.is_leaf[k] and j in self.path(k)}

    def is_first_sub_label(self, j: int) -> bool:
        up = self.parent[j]
        return up is not None and self.parent[up] is None and self.children(up)[0] == j

    def full_path_text(self, j: int, style: int) -> str:
        tokens = [self.tokens[k] for k in self.path(j)]
        if style == 0:
            return tokens[0] + "".join(f"({t})" for t in tokens[1:])  # 3(b)(ii)
        if style == 1:
            return "Q" + " ".join(tokens)  # Q3 b ii
        return f"Q{tokens[0]} " + " ".join(f"({t})" for t in tokens[1:])  # Q5 (b) (i)

    def perfect(self) -> tuple[list[Entry], list[int]]:
        """The clean stream, and for each node the index of its label in it."""
        stream: list[Entry] = []
        at: list[int] = []
        for j, leaf_id in enumerate(self.ids):
            at.append(len(stream))
            stream.append(_label(self.label(j)))
            if self.is_leaf[j]:
                stream.append(_writing(leaf_id))
        return stream, at


@cache
def _paper(name: str) -> Paper:
    return Paper.load(name)


def _battery_papers() -> list[Paper]:
    return [_paper(name) for name in _BATTERY_SCHEMES]


def _render(stream: list[Entry]) -> list[StreamItem]:
    """Stream items, 14 to a page, so that page breaks fall everywhere over a battery."""
    items: list[StreamItem] = []
    for k, entry in enumerate(stream):
        page = 1 + k // 14
        if entry.writing:
            items.append(SeenWriting(page=page, answer=entry.text, confidence=0.9))
        else:
            items.append(SeenLabel(page=page, text=entry.text, kind="printed"))
    return items


# --------------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------------
@dataclass
class Verdict:
    wrong: list[tuple[str, str]]  # (leaf, the id on the writing it holds)
    own: set[str]  # leaves holding their own writing


def judge(paper: Paper, stream: list[Entry]) -> Verdict:
    items = _render(stream)
    result = bind_stream(items, paper.scheme)
    _check_contract(paper, items, result)
    wrong = [
        (leaf.question_id, w.answer)
        for leaf in result.leaves
        for w in leaf.writings
        if w.answer != leaf.question_id
    ]
    own = {
        leaf.question_id
        for leaf in result.leaves
        if any(w.answer == leaf.question_id for w in leaf.writings)
    }
    return Verdict(wrong, own)


def _check_contract(paper: Paper, items: list[StreamItem], result: BoundStream) -> None:
    """What ``bind_stream`` promises whatever it is given."""
    leaf_ids = [i for i, leaf in zip(paper.ids, paper.is_leaf, strict=True) if leaf]
    bound_ids = [leaf.question_id for leaf in result.leaves]
    assert len(bound_ids) == len(set(bound_ids))
    assert set(bound_ids) <= paper.bindable
    assert bound_ids == [i for i in leaf_ids if i in set(bound_ids)], "leaves out of paper order"
    assert len(result.unaligned_ids) == len(set(result.unaligned_ids))
    assert set(bound_ids) | set(result.unaligned_ids) == set(leaf_ids)
    assert not set(bound_ids) & set(result.unaligned_ids)
    writings = [id(i) for i in items if isinstance(i, SeenWriting)]
    placed = [id(w) for leaf in result.leaves for w in leaf.writings]
    placed += [id(u.writing) for u in result.unbound]
    assert sorted(placed) == sorted(writings), "writing lost or bound twice"
    labels = {id(i) for i in items if isinstance(i, SeenLabel)}
    assert all(id(label) in labels for label in result.unplaced_labels)
    for leaf in result.leaves:
        number = leaf.question_id[
            : len(leaf.question_id) - len(leaf.question_id.lstrip("0123456789"))
        ]
        assert leaf.number_inferred == (number in result.inferred_numbers)
        assert ("question number not seen" in leaf.doubts) == leaf.number_inferred


@dataclass
class Tally:
    name: str
    trials: int = 0
    wrong_trials: int = 0
    wrong_writings: int = 0
    collateral_trials: int = 0
    leaves_lost: int = 0
    examples: list[str] = field(default_factory=list)

    def add(self, paper: Paper, stream: list[Entry], may_lose: set[str], what: str) -> None:
        verdict = judge(paper, stream)
        self.trials += 1
        if verdict.wrong:
            self.wrong_trials += 1
            self.wrong_writings += len(verdict.wrong)
            if len(self.examples) < 3:
                where = " ".join(f"{leaf}<-{text}" for leaf, text in verdict.wrong[:4])
                texts = " ".join(f"={e.text}" if e.writing else e.text for e in stream[:60])
                self.examples.append(f"{paper.name}: {what} -> {where} | {texts}")
        present = {e.text for e in stream if e.writing}
        extra = (paper.bindable & present) - verdict.own - may_lose
        if extra:
            self.collateral_trials += 1
            self.leaves_lost += len(extra)

    def line(self) -> str:
        return (
            f"{self.name:<48} trials={self.trials:<6d} wrong_trials={self.wrong_trials:<3d} "
            f"wrong_writings={self.wrong_writings:<3d} "
            f"collateral_trials={self.collateral_trials:<5d} "
            f"leaves_lost={self.leaves_lost}"
        )


# --------------------------------------------------------------------------------------
# The five Critical reproductions and the six variants, as literal streams.
#
# Each stream entry is (label text, leaf this label truly belongs to or None). A block
# of writing carrying the leaf's id follows every label that has one. ``binds`` names
# leaves that must still hold their own writing, so that no case passes by binding
# nothing at all.
# --------------------------------------------------------------------------------------
CRITICAL = [
    {
        "name": "C1 a stray 2 read between 1 and (a)",
        "scheme": "0625_w24_ms_41.json",
        "stream": [
            ("1", None),
            ("2", None),
            ("(a)", None),
            ("(i)", "1a_i"),
            ("(ii)", "1a_ii"),
            ("(b)", "1b"),
            ("(c)", None),
            ("(i)", "1c_i"),
            ("(ii)", "1c_ii"),
            ("2", None),
            ("(a)", None),
            ("(i)", "2a_i"),
            ("(ii)", "2a_ii"),
            ("(iii)", "2a_iii"),
            ("(b)", None),
            ("(i)", "2b_i"),
            ("(ii)", "2b_ii"),
            ("(c)", "2c"),
        ],
        "binds": [
            "1a_i",
            "1a_ii",
            "1b",
            "1c_i",
            "1c_ii",
            "2a_i",
            "2a_ii",
            "2a_iii",
            "2b_i",
            "2b_ii",
        ],
    },
    {
        "name": "C2 question number 2 misread as 3",
        "scheme": "0625_w24_ms_41.json",
        "stream": [
            ("1", None),
            ("(a)", None),
            ("(i)", "1a_i"),
            ("(ii)", "1a_ii"),
            ("(b)", "1b"),
            ("(c)", None),
            ("(i)", "1c_i"),
            ("(ii)", "1c_ii"),
            ("3", None),  # really question 2
            ("(a)", None),
            ("(i)", "2a_i"),
            ("(ii)", "2a_ii"),
            ("(iii)", "2a_iii"),
            ("(b)", None),
            ("(i)", "2b_i"),
            ("(ii)", "2b_ii"),
            ("(c)", "2c"),
            ("3", None),
            ("(a)", "3a"),
            ("(b)", None),
            ("(i)", "3b_i"),
            ("(ii)", "3b_ii"),
            ("(c)", "3c"),
        ],
        "binds": ["1a_i", "1a_ii", "1b", "1c_i"],
    },
    {
        "name": "C3 numbered answer lines under a childless question",
        "scheme": "0606_s19_ms_23.json",
        "stream": [
            ("1", "1"),
            ("1.", None),
            ("2.", None),
            ("2", "2"),
            ("3", None),
            ("(i)", "3i"),
            ("(ii)", "3ii"),
        ],
        "binds": ["3i"],
    },
    {
        "name": "C4 'Q5 (b)' written inside question 1",
        "scheme": "0625_w24_ms_41.json",
        "stream": [
            ("1", None),
            ("(a)", None),
            ("(i)", "1a_i"),
            ("(ii)", "1a_ii"),
            ("Q5 (b)", "5b"),
        ],
        "binds": ["1a_i"],
    },
    {
        "name": "C5 2b's (i) missed and number 3 missed",
        "scheme": "0625_w24_ms_41.json",
        "stream": [
            ("1", None),
            ("(a)", None),
            ("(i)", "1a_i"),
            ("(ii)", "1a_ii"),
            ("(b)", "1b"),
            ("(c)", None),
            ("(i)", "1c_i"),
            ("(ii)", "1c_ii"),
            ("2", None),
            ("(a)", None),
            ("(i)", "2a_i"),
            ("(ii)", "2a_ii"),
            ("(iii)", "2a_iii"),
            ("(b)", None),
            ("(ii)", "2b_ii"),
            ("(c)", "2c"),
            ("(a)", "3a"),
            ("(b)", None),
            ("(i)", "3b_i"),
            ("(ii)", "3b_ii"),
            ("(c)", "3c"),
        ],
        # 2b_ii and 2c are not bound: read on, question 3's (b) (i) (ii) (c) fill the
        # hole in question 2 just as well. 2a_iii is the last leaf before them.
        "binds": ["1a_i", "1a_ii", "1b", "1c_i", "1c_ii", "2a_i", "2a_ii"],
    },
]

VARIANTS = [
    {
        "name": "C1b page number 2, and (a) listed before 1",
        "scheme": "0625_w24_ms_41.json",
        "stream": [
            ("2", None),
            ("(a)", None),
            ("1", None),
            ("(i)", "1a_i"),
            ("(ii)", "1a_ii"),
            ("(b)", "1b"),
            ("(c)", None),
            ("(i)", "1c_i"),
            ("(ii)", "1c_ii"),
            ("2", None),
            ("(a)", None),
            ("(i)", "2a_i"),
            ("(ii)", "2a_ii"),
            ("(iii)", "2a_iii"),
        ],
        "binds": ["1b", "1c_i", "1c_ii", "2a_i", "2a_ii"],
    },
    {
        "name": "C2b 2a's (i) read as (l), and (b) missed",
        "scheme": "0625_w24_ms_41.json",
        "stream": [
            ("2", None),
            ("(a)", None),
            ("(l)", None),
            ("(ii)", "2a_ii"),
            ("(iii)", "2a_iii"),
            ("(i)", "2b_i"),
            ("(ii)", "2b_ii"),
            ("(c)", "2c"),
        ],
        "binds": [],
    },
    {
        "name": "C2c MCQ: question number 3 misread as 4",
        "scheme": "0625_w24_ms_12.json",
        "stream": [("1", "1"), ("2", "2"), ("4", None), ("4", "4"), ("5", "5")],
        "binds": ["1"],
    },
    {
        "name": "C3b MCQ: numbered lines under question 1",
        "scheme": "0625_w24_ms_12.json",
        "stream": [("1", "1"), ("1.", None), ("2.", None), ("2", "2"), ("3", "3")],
        "binds": [],
    },
    {
        "name": "C4b '3(b)(ii)' after 2,(a)",
        "scheme": "0625_w24_ms_41.json",
        "stream": [("2", None), ("(a)", None), ("3(b)(ii)", "3b_ii")],
        "binds": [],
    },
    {
        "name": "C5b 2's (c) and 3's (a) missed",
        "scheme": "0625_w24_ms_41.json",
        "stream": [
            ("2", None),
            ("(a)", None),
            ("(i)", "2a_i"),
            ("(ii)", "2a_ii"),
            ("(iii)", "2a_iii"),
            ("(b)", None),
            ("(i)", "2b_i"),
            ("(ii)", "2b_ii"),
            ("3", None),
            ("(b)", None),
            ("(i)", "3b_i"),
            ("(ii)", "3b_ii"),
            ("(c)", "3c"),
        ],
        "binds": ["2a_i", "2a_ii", "2a_iii", "2b_i", "3b_i", "3b_ii"],
    },
]


def _literal(case: dict) -> list[Entry]:
    stream: list[Entry] = []
    for text, leaf in case["stream"]:
        stream.append(_label(text))
        if leaf is not None:
            stream.append(_writing(leaf))
    return stream


# --------------------------------------------------------------------------------------
# Single-fault generators. Each yields (stream, leaves the fault itself may cost, what).
# --------------------------------------------------------------------------------------
Fault = Iterator[tuple[list[Entry], set[str], str]]
STRAY_NUMBERS = ["2", "12", "1", "3", "7"]
STRAY_LETTERS = ["(a)", "(b)", "(c)", "(e)"]
STRAY_ROMANS = ["(i)", "(ii)", "(v)", "(x)"]


def _insert(stream: list[Entry], p: int, *entries: Entry) -> list[Entry]:
    return [*stream[:p], *entries, *stream[p:]]


def _replace(stream: list[Entry], i: int, text: str) -> list[Entry]:
    return [*stream[:i], _label(text), *stream[i + 1 :]]


def _drop(paper: Paper, wanted: Callable[[int], bool]) -> Fault:
    """The label is missed; whatever was written under it is still listed."""
    base, at = paper.perfect()
    for j in range(len(paper.ids)):
        if wanted(j):
            i = at[j]
            yield (
                [*base[:i], *base[i + 1 :]],
                paper.subtree_leaves(j),
                f"drop {base[i].text} of {paper.ids[j]}",
            )


def drop_label(paper: Paper) -> Fault:
    """Every label that is neither a question number nor a first sub-label."""
    return _drop(paper, lambda j: paper.parent[j] is not None and not paper.is_first_sub_label(j))


def drop_question_number(paper: Paper) -> Fault:
    return _drop(paper, lambda j: paper.parent[j] is None)


def drop_first_sub_label(paper: Paper) -> Fault:
    return _drop(paper, paper.is_first_sub_label)


def duplicate(paper: Paper) -> Fault:
    """A label read twice in a row, and a label seen again after its writing."""
    base, at = paper.perfect()
    for j in range(len(paper.ids)):
        i = at[j]
        yield _insert(base, i + 1, base[i]), set(), f"read {base[i].text} of {paper.ids[j]} twice"
        if paper.is_leaf[j]:
            yield (
                _insert(base, i + 2, base[i]),
                set(),
                f"{base[i].text} of {paper.ids[j]} again after its writing",
            )


def _stray(paper: Paper, texts: list[str]) -> Fault:
    """A stray label at every place in the list, between a label and its writing too."""
    base, _ = paper.perfect()
    for text in texts:
        for p in range(len(base) + 1):
            yield _insert(base, p, _label(text)), set(), f"stray {text} at item {p}"


def stray_number(paper: Paper) -> Fault:
    return _stray(paper, STRAY_NUMBERS)


def stray_letter(paper: Paper) -> Fault:
    return _stray(paper, STRAY_LETTERS)


def stray_roman(paper: Paper) -> Fault:
    return _stray(paper, STRAY_ROMANS)


def misread_i(paper: Paper) -> Fault:
    """A roman (i) read as (l) or as (1)."""
    base, at = paper.perfect()
    for j in range(len(paper.ids)):
        if paper.parent[j] is not None and paper.tokens[j] == "i" and base[at[j]].text == "(i)":
            for wrong in ("(l)", "(1)"):
                yield (
                    _replace(base, at[j], wrong),
                    paper.subtree_leaves(j),
                    f"(i) of {paper.ids[j]} read as {wrong}",
                )


def misread_question_number(paper: Paper) -> Fault:
    """A question number read as each other question number of the paper."""
    base, at = paper.perfect()
    numbers = [paper.tokens[j] for j in range(len(paper.ids)) if paper.parent[j] is None]
    for j in range(len(paper.ids)):
        if paper.parent[j] is None:
            for wrong in numbers:
                if wrong != paper.tokens[j]:
                    yield (
                        _replace(base, at[j], wrong),
                        paper.subtree_leaves(j),
                        f"{paper.tokens[j]} read as {wrong}",
                    )


def numbered_answer_lines(paper: Paper) -> Fault:
    """Lines 1., 2., ... under each childless leaf, up to past the next question's number.

    Listed as labels straight after the leaf's label (so its writing follows them), and
    after the leaf's writing.
    """
    base, at = paper.perfect()
    for j in range(len(paper.ids)):
        if not paper.is_leaf[j]:
            continue
        current = int(paper.tokens[paper.question(j)])
        for count in range(1, min(current + 3, 14) + 1):
            lines = [_label(f"{k}.") for k in range(1, count + 1)]
            for offset, where in ((1, "before"), (2, "after")):
                yield (
                    _insert(base, at[j] + offset, *lines),
                    set(),
                    f"lines 1..{count} {where} the writing of {paper.ids[j]}",
                )


def multi_step_label(paper: Paper) -> Fault:
    """Labels that carry more than one step, in four variants.

    merged: a label and its first sub-label read as one ("1 (a)", "(a) (i)").
    in place: a label written with its full path ("3(b)(ii)", "Q3 b ii").
    foreign: the full-path label of a leaf written at the end of another question, with
    writing under it (a continuation); that writing may go nowhere but its own leaf.
    foreign over a missed label: the same label where the host question's own label of
    that text should be ("Q5 (b)" where question 1's "(b)" was).
    """
    base, at = paper.perfect()
    n = len(paper.ids)
    for j in range(n - 1):
        if paper.parent[j + 1] == j:
            merged = _label(f"{base[at[j]].text} {base[at[j + 1]].text}")
            yield [*base[: at[j]], merged, *base[at[j] + 2 :]], set(), f"merged '{merged.text}'"
    for j in range(n):
        if paper.parent[j] is not None:
            for style in (0, 1):
                text = paper.full_path_text(j, style)
                yield _replace(base, at[j], text), set(), f"in place '{text}' for {paper.ids[j]}"
    tops = [j for j in range(n) if paper.parent[j] is None]
    ends = {q: (at[tops[k + 1]] if k + 1 < len(tops) else len(base)) for k, q in enumerate(tops)}
    for j in range(n):
        if not paper.is_leaf[j] or paper.parent[j] is None:
            continue  # a bare number is the stray-number generator's business
        text = paper.full_path_text(j, 2)
        for q in tops:
            if q != paper.question(j):
                yield (
                    _insert(base, ends[q], _label(text), _writing(paper.ids[j])),
                    set(),
                    f"foreign '{text}' at the end of question {paper.tokens[q]}",
                )
    for i in range(n):
        if paper.parent[i] is None:
            continue
        twins = [
            j
            for j in range(n)
            if paper.label(j) == paper.label(i)
            and paper.question(j) != paper.question(i)
            and len(paper.path(j)) == len(paper.path(i))
        ]
        nearest = {
            max((j for j in twins if j < i), default=None),
            min((j for j in twins if j > i), default=None),
        }
        for j in sorted(k for k in nearest if k is not None):
            text = paper.full_path_text(j, 2)
            yield (
                _replace(base, at[i], text),
                paper.subtree_leaves(i),
                f"foreign '{text}' over the label of {paper.ids[i]}",
            )


SINGLE_FAULTS: list[tuple[str, Callable[[Paper], Fault]]] = [
    ("drop label", drop_label),
    ("drop question number", drop_question_number),
    ("drop first sub-label", drop_first_sub_label),
    ("duplicate", duplicate),
    ("stray number", stray_number),
    ("stray letter", stray_letter),
    ("stray roman", stray_roman),
    ("misread (i) as (l)/(1)", misread_i),
    ("misread a question number", misread_question_number),
    ("numbered lines under a childless leaf", numbered_answer_lines),
    ("multi-step label", multi_step_label),
]


def run_single_faults(papers: list[Paper]) -> list[Tally]:
    tallies = []
    for name, generator in SINGLE_FAULTS:
        tally = Tally(name)
        for paper in papers:
            for stream, may_lose, what in generator(paper):
                tally.add(paper, stream, may_lose, what)
        tallies.append(tally)
    return tallies


# --------------------------------------------------------------------------------------
# Random 2 to 4 faults per paper
# --------------------------------------------------------------------------------------
RANDOM_LABELS = ["(a)", "(b)", "(c)", "(d)", "(i)", "(ii)", "(iii)", "(v)", "(x)", "(e)"]
TIERS = {
    "R1 labels only": ["drop", "dup", "stray-label", "misread-i"],
    "R2 + answer lines": ["drop", "dup", "stray-label", "misread-i", "answer-lines"],
    "R3 + stray numbers": [
        "drop",
        "dup",
        "stray-label",
        "misread-i",
        "answer-lines",
        "stray-number",
    ],
}
RANDOM_TRIALS = 160  # per scheme and tier: 5 x 3 x 160 = 2,400 trials


def _own_leaves(paper: Paper, stream: list[Entry], i: int) -> set[str]:
    """Leaves a fault on the label at ``i`` may cost: the leaves whose writing follows it
    before the next label of the same or a higher level cannot be known from the stream
    alone, so the cost is taken from the clean paper by the writing that follows."""
    after = next((e.text for e in stream[i + 1 :] if e.writing), None)
    if after is None or after not in paper.ids:
        return set()
    j = paper.ids.index(after)
    for k in paper.path(j):
        if paper.label(k) == stream[i].text:
            return paper.subtree_leaves(k)
    return {after}


def random_fault(
    rng: random.Random, paper: Paper, stream: list[Entry], kinds: list[str]
) -> tuple[list[Entry], set[str], str]:
    kind = rng.choice(kinds)
    labels = [k for k, e in enumerate(stream) if not e.writing]
    n = len(stream)
    if kind == "drop" and len(labels) > 1:
        i = rng.choice(labels)
        return (
            [*stream[:i], *stream[i + 1 :]],
            _own_leaves(paper, stream, i),
            f"drop@{i}:{stream[i].text}",
        )
    if kind == "dup":
        i = rng.choice(labels)
        return _insert(stream, i + 1, stream[i]), set(), f"dup@{i}:{stream[i].text}"
    if kind == "stray-label":
        p = rng.randrange(n + 1)
        text = rng.choice(RANDOM_LABELS)
        return _insert(stream, p, _label(text)), set(), f"ins@{p}:{text}"
    if kind == "stray-number":
        p = rng.randrange(n + 1)
        text = str(rng.randint(1, 14))
        return _insert(stream, p, _label(text)), set(), f"ins@{p}:{text}"
    if kind == "misread-i":
        candidates = [k for k in labels if stream[k].text == "(i)"]
        if candidates:
            i = rng.choice(candidates)
            wrong = rng.choice(["(l)", "(1)"]) if "stray-number" in kinds else "(l)"
            return (
                _replace(stream, i, wrong),
                _own_leaves(paper, stream, i),
                f"misread@{i}:(i)->{wrong}",
            )
    if kind == "answer-lines":
        candidates = [k for k in labels if k + 1 < n and stream[k + 1].writing]
        if candidates:
            i = rng.choice(candidates)
            count = rng.randint(1, 4)
            lines = [_label(f"{k}.") for k in range(1, count + 1)]
            return _insert(stream, i + rng.choice([1, 2]), *lines), set(), f"lines@{i}:1..{count}"
    return stream, set(), "noop"


def run_random_faults(papers: list[Paper], trials: int, salt: str = "") -> list[Tally]:
    tallies = []
    for tier, kinds in TIERS.items():
        tally = Tally(tier)
        for paper in papers:
            rng = random.Random(f"{paper.name}/{tier}{salt}")
            for _ in range(trials):
                stream, _ = paper.perfect()
                may_lose: set[str] = set()
                what = []
                for _ in range(rng.randint(2, 4)):
                    stream, cost, description = random_fault(rng, paper, stream, kinds)
                    may_lose |= cost
                    what.append(description)
                tally.add(paper, stream, may_lose, ", ".join(what))
        tallies.append(tally)
    return tallies


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------
def test_clean_stream_binds_every_unique_leaf_of_every_corpus_scheme() -> None:
    paths = sorted(_CORPUS.rglob("*.json"))
    assert len(paths) == 289
    with_duplicates = 0
    for path in paths:
        paper = Paper.load(path.name)
        stream, _ = paper.perfect()
        items = _render(stream)
        result = bind_stream(items, paper.scheme)
        _check_contract(paper, items, result)
        held = {leaf.question_id: [w.answer for w in leaf.writings] for leaf in result.leaves}
        assert held == {leaf: [leaf] for leaf in sorted(paper.bindable, key=paper.ids.index)}, (
            path.name
        )
        doubled = duplicate_leaf_ids(paper.scheme)
        with_duplicates += bool(doubled)
        assert result.unaligned_ids == doubled, path.name
        assert sorted(u.writing.answer for u in result.unbound) == sorted(doubled), path.name
        assert result.inferred_numbers == [], path.name
        # The stream is cut into pages of 14 items: where a page ends between a label
        # and its writing, the writing opens the next page, and that is the one doubt.
        assert {d for leaf in result.leaves for d in leaf.doubts} <= {
            "continues from the previous page"
        }, path.name
    assert with_duplicates == 7


@pytest.mark.parametrize("case", CRITICAL, ids=[c["name"] for c in CRITICAL])
def test_the_five_critical_reproductions_bind_nothing_wrongly(case: dict) -> None:
    verdict = judge(_paper(case["scheme"]), _literal(case))
    assert verdict.wrong == []
    assert set(case["binds"]) <= verdict.own


@pytest.mark.parametrize("case", VARIANTS, ids=[c["name"] for c in VARIANTS])
def test_the_six_variants_bind_nothing_wrongly(case: dict) -> None:
    verdict = judge(_paper(case["scheme"]), _literal(case))
    assert verdict.wrong == []
    assert set(case["binds"]) <= verdict.own


def test_single_fault_never_puts_writing_on_another_leaf() -> None:
    tallies = run_single_faults(_battery_papers())
    assert [t.name for t in tallies] == [name for name, _ in SINGLE_FAULTS]
    assert all(t.trials >= 30 for t in tallies), [t.line() for t in tallies]
    assert sum(t.trials for t in tallies) > 10_000
    assert [t.examples for t in tallies if t.wrong_trials] == []


def test_random_faults_never_put_writing_on_another_leaf() -> None:
    tallies = run_random_faults(_battery_papers(), RANDOM_TRIALS)
    assert sum(t.trials for t in tallies) >= 2_000
    assert [t.examples for t in tallies if t.wrong_trials] == []


def test_the_judge_sees_writing_on_another_leaf() -> None:
    # The rule above must be able to fail: a stream whose labels are clean and whose
    # writing is swapped is the one fault no label can reveal.
    paper = _paper("0625_w24_ms_41.json")
    stream, at = paper.perfect()
    i, j = at[paper.ids.index("1a_i")] + 1, at[paper.ids.index("1a_ii")] + 1
    stream[i], stream[j] = stream[j], stream[i]
    verdict = judge(paper, stream)
    assert sorted(verdict.wrong) == [("1a_i", "1a_ii"), ("1a_ii", "1a_i")]
    tally = Tally("swap")
    tally.add(paper, stream, set(), "swap")
    assert (tally.wrong_trials, tally.wrong_writings, tally.leaves_lost) == (1, 2, 2)


FUZZ_TEXTS = [
    *("1", "2", "3", "10", "12", "1.", "2.", "(a)", "(b)", "(c)", "(i)", "(ii)", "(iii)", "(iv)"),
    *(
        "(v)",
        "(x)",
        "Q3 b ii",
        "3(b)(ii)",
        "Q2 (a)",
        "2 (a) (i)",
        "",
        " ",
        "Fig. 1.1",
        "[2]",
        "(A)",
    ),
    *("Total", "1a", "2bii", "a", "x", "Question 4", "Q", "q7", "(1)", "0", "007", "i.", "((a))"),
    *("a b c d e", "1 a i a", "1 1", "(l)", "1\n(a)", "\x00", "(" * 400, "9" * 400, "i" * 400),
    *("1 " * 200, "Q" * 50 + "1", "(a)(i)(a)(i)(a)", "1(a)(i)(a)", "1e5", "-1", "+2", "1,2", "a-b"),
    *("\t(a)\t", "(a", "a)", ")a(", "..", "Q.3", "q 3 b"),
    # Digits, letters and brackets of other scripts: none is a label here.
    *("\u0663", "\u00b2", "\u00c9", "\u2173", "\u2170", "\ud7ff", "\U0001f642", "\u0131"),
    *("\u0130", "\u00df", "\uff08a\uff09"),
]


def test_bind_stream_never_raises() -> None:
    rng = random.Random(3)
    lists = 0
    for paper in _battery_papers():
        for _ in range(500):
            items: list[StreamItem] = []
            for _ in range(rng.randint(0, 40)):
                page = rng.choice([0, 1, 1, 2, 3, -1, 10**9])
                if rng.random() < 0.3:
                    items.append(
                        SeenWriting(
                            page=page,
                            answer=rng.choice(FUZZ_TEXTS),
                            working_out=rng.choice([None, "", "x"]),
                            confidence=rng.choice([0.0, 1.0, -5.0, float("inf")]),
                            placed_by=rng.choice(["position", "arrow", "uncertain"]),
                        )
                    )
                else:
                    items.append(
                        SeenLabel(
                            page=page,
                            text=rng.choice(FUZZ_TEXTS),
                            kind=rng.choice(["printed", "handwritten"]),
                            box=rng.choice([None, [], [1, 2, 3, 4], [-1] * 9]),
                        )
                    )
            result = bind_stream(items, paper.scheme)
            _check_contract(paper, items, result)
            lists += 1
    assert lists == 2_500
    # A tuple, a generator's list, and the same items twice over are all sequences.
    paper = _battery_papers()[0]
    items = _render(paper.perfect()[0])
    assert bind_stream(tuple(items), paper.scheme).unaligned_ids == []
    _check_contract(paper, items + items, bind_stream(items + items, paper.scheme))


def test_bind_stream_is_fast_enough() -> None:
    """The largest scheme, read with four stray labels after every true one."""
    paths = sorted(_CORPUS.rglob("*.json"))
    sizes = {path.name: len(Paper.load(path.name).scheme.all_questions_flat()) for path in paths}
    assert max(sizes, key=lambda name: sizes[name]) == _LARGEST_SCHEME
    paper = _paper(_LARGEST_SCHEME)
    noise = ["(a)", "(b)", "(i)", "(ii)", "(iii)", "1.", "2.", "3", "(c)", "(v)"]
    worst = 0.0
    for factor in (1, 5, 30):
        rng = random.Random(7)
        stream: list[Entry] = []
        for entry in paper.perfect()[0]:
            stream.append(entry)
            if not entry.writing:
                stream.extend(_label(rng.choice(noise)) for _ in range(factor - 1))
        items = _render(stream)
        start = time.perf_counter()
        result = bind_stream(items, paper.scheme)
        elapsed = time.perf_counter() - start
        _check_contract(paper, items, result)
        if factor <= 5:
            worst = max(worst, elapsed)
        assert elapsed < 5.0, f"{factor}x: {elapsed:.2f} s"
    assert worst < 1.0, f"{worst:.2f} s"
