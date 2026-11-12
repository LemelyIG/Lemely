"""The golden fixtures are in shapes the label binder can bind ($0, no model call).

The first cost-ladder baseline held 11 of 12 golden cases at binding gate G5: the
schemes were flat (``12a`` at top level, its parent missing) and the scans printed the
scheme spelling (``Q1a_i``), shapes no production scheme or printed paper has
(``.superpowers/sdd/binder-hold-diagnosis.md``). No test ran ``bind_stream`` over
``tests/golden``, so nothing caught it. These tests do, on the files as committed:

- every leaf of every golden scheme has a label the binder can name;
- the labels the renderer prints on each scan bind, against that case's own scheme,
  every leaf to its own answer with nothing unaligned;
- the corpus digest the cost-ladder runner pins is the digest of this corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.accuracy.cost_ladder.runner import PINNED_CORPUS_DIGEST
from lemely.accuracy.harness import _corpus_digest, load_golden_cases
from lemely.accuracy.synth import AnswerBlock, printed_labels
from lemely.core.binding import SeenLabel, SeenWriting, StreamItem
from lemely.core.label_sequence import bind_stream, parse_label
from lemely.core.loose_schemas import MarkScheme, Question

GOLDEN = Path(__file__).resolve().parent / "golden"
CASES = sorted(p for p in GOLDEN.iterdir() if (p / "answers.json").exists())


def _scheme(case: Path) -> MarkScheme:
    return MarkScheme.model_validate_json((case / "mark_scheme.json").read_text("utf-8"))


def _answers(case: Path) -> list[AnswerBlock]:
    """The blocks ``scripts/regenerate_golden_fixtures.py`` renders, in the same order."""
    raw = json.loads((case / "answers.json").read_text("utf-8"))
    return [
        AnswerBlock(question_id=qid, text=entry["student_answer"]) for qid, entry in raw.items()
    ]


def _leaf_ids(scheme: MarkScheme) -> list[str]:
    return [q.id for q in scheme.all_questions_flat() if not q.parts]


def _rendered_stream(answers: list[AnswerBlock]) -> list[StreamItem]:
    """A perfect reading of the scan: each printed label, then the writing under it."""
    items: list[StreamItem] = []
    for block, label in zip(answers, printed_labels(answers), strict=True):
        items.append(SeenLabel(page=1, text=label, kind="printed"))
        if block.text.strip():
            items.append(SeenWriting(page=1, answer=block.text, confidence=1.0))
    return items


def test_there_are_twelve_golden_cases() -> None:
    assert len(CASES) == 12


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_every_golden_leaf_has_a_label_the_binder_can_name(case: Path) -> None:
    scheme = _scheme(case)
    # No labels at all: each leaf is unaligned, and the reason says whether a label
    # could ever have named it. ``undecomposable_id`` is a scheme no scan can bind.
    reasons = bind_stream([], scheme).unaligned_reasons
    assert set(reasons) == set(_leaf_ids(scheme))
    assert [qid for qid, why in reasons.items() if why == "undecomposable_id"] == []
    # The production shape: every top-level question is a question number.
    assert [q.id for q in scheme.questions if not q.id.isdigit()] == []


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_golden_parent_ids_match_the_nesting(case: Path) -> None:
    def walk(
        questions: list[Question], parent: str | None
    ) -> list[tuple[str, str | None, str | None]]:
        out: list[tuple[str, str | None, str | None]] = []
        for q in questions:
            out.append((q.id, q.parent_id, parent))
            out.extend(walk(q.parts, q.id))
        return out

    wrong = [row for row in walk(_scheme(case).questions, None) if row[1] != row[2]]
    assert wrong == []


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_rendered_labels_bind_every_leaf_to_its_own_answer(case: Path) -> None:
    scheme = _scheme(case)
    answers = _answers(case)
    assert [b.question_id for b in answers] == _leaf_ids(scheme)  # paper order
    labels = printed_labels(answers)
    assert [label for label in labels if not parse_label(label)] == []
    bound = bind_stream(_rendered_stream(answers), scheme)
    assert bound.unaligned_ids == []
    assert bound.unbound == []
    assert bound.unplaced_labels == []
    by_id = {leaf.question_id: [w.answer for w in leaf.writings] for leaf in bound.leaves}
    expected = {b.question_id: [b.text] if b.text.strip() else [] for b in answers}
    assert by_id == expected


def test_printed_labels_follow_the_paper() -> None:
    ids = ["1a_i", "1a_ii", "1b", "2", "12b", "12c", "4b_iii"]
    labels = printed_labels([AnswerBlock(question_id=i, text="x") for i in ids])
    assert labels == ["1(a)(i)", "(ii)", "(b)", "2", "12(b)", "(c)", "4(b)(iii)"]
    assert printed_labels([AnswerBlock("3", "x"), AnswerBlock("3", "y")]) == ["3", "3"]


def test_printed_labels_refuse_an_id_no_paper_prints() -> None:
    with pytest.raises(ValueError, match="1a_i_A"):
        printed_labels([AnswerBlock(question_id="1a_i_A", text="x")])


def test_pinned_corpus_digest_is_this_corpus() -> None:
    loaded = load_golden_cases(GOLDEN)
    assert loaded.unparseable == []
    assert _corpus_digest(list(loaded)) == PINNED_CORPUS_DIGEST
