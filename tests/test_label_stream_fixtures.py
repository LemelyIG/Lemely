"""The five recorded reading-order streams of the 0625/41 scan, bound by ``bind_stream``.

The streams are what ``gemini-3.8-flash`` returned (see the README beside them). The
reference is ``aligned.json``: one run in which every answer sits on its own question.
"""

from __future__ import annotations

import difflib
import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from lemely.core.binding import SeenLabel, SeenWriting, StreamItem
from lemely.core.label_sequence import BoundLeaf, BoundStream, bind_stream, parse_label
from lemely.core.loose_schemas import MarkScheme

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _ROOT / "tests" / "fixtures" / "binding" / "0625_w24_41"
_SCHEME = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
_RUNS = (1, 2, 3, 4, 5)
# Drawings: the model describes them in its own words, so text cannot judge them.
_DRAWINGS = {"7b_i", "8a"}
_Q4 = ["4a", "4b_i", "4b_ii", "4b_iii"]
_DOUBT_PAGE = "continues from the previous page"
_DOUBT_ARROW = "tied by an arrow"


def _coerce(raw: Any) -> StreamItem | None:
    """One recorded item as a stream item, or ``None`` when it is malformed.

    A stand-in for the coercion a later task owns: an item is read by its ``type``, the
    other type's fields are dropped, and anything pydantic rejects is dropped whole.
    """
    if not isinstance(raw, dict):
        return None
    box = raw.get("box")
    if not (isinstance(box, list) and len(box) == 4 and all(isinstance(c, int) for c in box)):
        box = None
    try:
        if raw.get("type") == "label":
            return SeenLabel(page=raw["page"], text=raw["text"], kind=raw["kind"], box=box)
        if raw.get("type") == "answer":
            return SeenWriting(
                page=raw["page"],
                answer=raw.get("answer") or "",
                working_out=raw.get("working_out") or None,
                confidence=raw.get("confidence") or 0.0,
                box=box,
                placed_by=raw.get("placed_by") or "position",
            )
    except (KeyError, ValidationError):
        return None
    return None


def _stream(run: int) -> list[StreamItem]:
    record = json.loads((_FIXTURES / "streams" / f"A_run{run}.json").read_text())
    assert set(record) == {"model", "prompt_version", "page_count", "items"}
    items = [_coerce(raw) for raw in record["items"]]
    assert None not in items, "a recorded item was dropped as malformed"
    return [item for item in items if item is not None]


@pytest.fixture(scope="module")
def scheme() -> MarkScheme:
    return MarkScheme.model_validate(json.loads(_SCHEME.read_text()))


@pytest.fixture(scope="module")
def bound(scheme: MarkScheme) -> dict[int, tuple[list[StreamItem], BoundStream]]:
    out = {}
    for run in _RUNS:
        items = _stream(run)
        out[run] = (items, bind_stream(items, scheme))
    return out


@pytest.fixture(scope="module")
def reference() -> dict[str, dict[str, str]]:
    doc = json.loads((_FIXTURES / "aligned.json").read_text())
    return {
        a["question_id"]: {
            "answer": a["answer"] or "",
            "all": f"{a['answer'] or ''} {a['working_out'] or ''}",
        }
        for a in doc["answers"]
    }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _sim(x: str, y: str) -> float:
    return difflib.SequenceMatcher(None, x, y, autojunk=False).ratio()


def _text(writings: list[SeenWriting]) -> str:
    return _norm(" ".join(f"{w.answer} {w.working_out or ''}" for w in writings))


def _leaf(result: BoundStream, question_id: str) -> BoundLeaf | None:
    return next((leaf for leaf in result.leaves if leaf.question_id == question_id), None)


def _holder(result: BoundStream, item: SeenWriting) -> BoundLeaf | None:
    return next((leaf for leaf in result.leaves if any(w is item for w in leaf.writings)), None)


def test_the_fixtures_hold_no_path_and_no_scan() -> None:
    for run in _RUNS:
        text = (_FIXTURES / "streams" / f"A_run{run}.json").read_text()
        assert "/home" not in text
        assert ".pdf" not in text
        assert ".png" not in text


@pytest.mark.parametrize("run", [1, 2, 3])
def test_runs_1_to_3_align_every_leaf(
    run: int, scheme: MarkScheme, bound: dict[int, tuple[list[StreamItem], BoundStream]]
) -> None:
    _, result = bound[run]
    leaves = [q.id for q in scheme.all_questions_flat() if not q.parts]
    assert len(leaves) == 43
    assert [leaf.question_id for leaf in result.leaves] == leaves
    assert result.unaligned_ids == []
    assert result.inferred_numbers == []
    assert not any(leaf.number_inferred for leaf in result.leaves)
    # The cover is page 0; no run listed a label there, so nothing at all is unplaced.
    assert [label for label in result.unplaced_labels if label.page != 0] == []


@pytest.mark.parametrize("run", [4, 5])
def test_runs_4_and_5_infer_question_4(
    run: int,
    scheme: MarkScheme,
    bound: dict[int, tuple[list[StreamItem], BoundStream]],
    reference: dict[str, dict[str, str]],
) -> None:
    items, result = bound[run]
    assert not [i for i in items if isinstance(i, SeenLabel) and i.text.strip("().") == "4"]
    assert result.inferred_numbers == ["4"]
    assert result.unaligned_ids == []
    assert result.unplaced_labels == []
    for leaf in result.leaves:
        inferred = leaf.question_id in _Q4
        assert leaf.number_inferred is inferred, leaf.question_id
        assert ("question number not seen" in leaf.doubts) is inferred, leaf.question_id
    # 3c keeps its own two numbered lines and nothing of question 4.
    before = _leaf(result, "3c")
    assert before is not None
    assert "next question number not seen" in before.doubts
    text = _text(before.writings)
    assert "total upward force" in text
    for question_id in _Q4:
        assert _sim(text, _norm(reference["3c"]["all"])) > _sim(
            text, _norm(reference[question_id]["all"])
        )
    first_of_4 = next(k for k, i in enumerate(items) if isinstance(i, SeenWriting) and i.page >= 8)
    later = {id(i) for i in items[first_of_4:]}
    assert not [w for w in before.writings if id(w) in later]


def _containment(block: str, ref: str) -> float:
    """Share of the block's characters found, in order, inside ``ref``."""
    matcher = difflib.SequenceMatcher(None, block, ref, autojunk=False)
    return sum(m.size for m in matcher.get_matching_blocks()) / len(block)


# Leaves the joined-text measure fails although both of their blocks are their own.
# Run 4 lists the arrow-tied last sentence of 4(b)(i) before the body of the answer;
# the reference has it last. difflib matches the longest common block first and only
# looks to its left and right after that, so two blocks in the opposite order score
# 0.23 against a reference each of them is 94% contained in. The test below pins the
# case and checks each block on its own instead of passing it by.
_BLOCK_ORDER = {(4, "4b_i")}


@pytest.mark.parametrize("run", _RUNS)
def test_every_reference_answer_is_on_its_own_leaf(
    run: int,
    bound: dict[int, tuple[list[StreamItem], BoundStream]],
    reference: dict[str, dict[str, str]],
) -> None:
    _, result = bound[run]
    failures = []
    for question_id, ref in reference.items():
        if question_id in _DRAWINGS:
            continue
        leaf = _leaf(result, question_id)
        text = _text(leaf.writings) if leaf else ""
        closest = max(reference, key=lambda other: _sim(text, _norm(reference[other]["all"])))
        final = _squeeze(ref["answer"])
        if text and (closest == question_id or (final and final in _squeeze(text))):
            continue
        failures.append(question_id)
    assert {(run, question_id) for question_id in failures} == {
        pinned for pinned in _BLOCK_ORDER if pinned[0] == run
    }
    for question_id in failures:
        leaf = _leaf(result, question_id)
        assert leaf is not None
        assert len(leaf.writings) == 2
        for writing in leaf.writings:
            block = _text([writing])
            closest = max(
                reference, key=lambda other: _containment(block, _norm(reference[other]["all"]))
            )
            assert closest == question_id
            assert _containment(block, _norm(reference[question_id]["all"])) > 0.9


@pytest.mark.parametrize("run", _RUNS)
def test_q1_a_i_keeps_both_numbered_lines(
    run: int, bound: dict[int, tuple[list[StreamItem], BoundStream]]
) -> None:
    _, result = bound[run]
    first, second = _leaf(result, "1a_i"), _leaf(result, "1a_ii")
    assert first is not None
    assert second is not None
    assert "43" in _text(first.writings)
    assert "63" in _text(first.writings)
    assert "20" in _text(second.writings)
    assert "20 cm" not in _text(first.writings)


@pytest.mark.parametrize("run", _RUNS)
def test_top_of_page_and_arrow_writing_is_marked_doubtful_not_silent(
    run: int, bound: dict[int, tuple[list[StreamItem], BoundStream]]
) -> None:
    """Writing whose place the list cannot vouch for is unbound, or leaves a doubt.

    That is every block listed before the first label of its page, and every block the
    reader tied by an arrow. The notes at the top of pages 13 and 15 and the arrow-tied
    sentence of 4(b)(i) are checked by name below.
    """
    items, result = bound[run]
    unbound = {id(u.writing) for u in result.unbound}
    labelled: set[int] = set()
    written: set[int] = set()
    checked = 0
    for item in items:
        if isinstance(item, SeenLabel):
            labelled.add(item.page)
            continue
        top_of_page = item.page not in labelled and item.page not in written
        written.add(item.page)
        for applies, doubt in (
            (top_of_page, _DOUBT_PAGE),
            (item.placed_by == "arrow", _DOUBT_ARROW),
        ):
            if not applies:
                continue
            checked += 1
            holder = _holder(result, item)
            assert id(item) in unbound or (holder is not None and doubt in holder.doubts), (
                run,
                item.page,
                item.answer,
                item.working_out,
            )
    assert checked >= 2

    arrows = [i for i in items if isinstance(i, SeenWriting) and i.placed_by == "arrow"]
    assert len(arrows) == 1
    assert "heat is transfered from hot water" in arrows[0].answer


# Where each run lists the two top-of-page notes: (run, page) -> listed before the
# first label of its page. Where it is not, the model moved the note under a label of
# the page or merged it into that part's block; nothing in the list marks the move.
_NOTE_AT_TOP = {
    (1, 13): False, (1, 15): True,
    (2, 13): True, (2, 15): True,
    (3, 13): True, (3, 15): True,
    (5, 13): True, (5, 15): True,
}  # fmt: skip


@pytest.mark.parametrize(("run", "page"), sorted(_NOTE_AT_TOP))
def test_the_notes_at_the_top_of_pages_13_and_15(
    run: int, page: int, bound: dict[int, tuple[list[StreamItem], BoundStream]]
) -> None:
    items, result = bound[run]
    needle = "ldr" if page == 13 else "v = i"
    note = next(
        i
        for i in items
        if isinstance(i, SeenWriting)
        and i.page == page
        and needle in _norm(f"{i.answer} {i.working_out or ''}")
        and len(_norm(f"{i.answer} {i.working_out or ''}")) < 20
    )
    first_label = next(
        k for k, i in enumerate(items) if isinstance(i, SeenLabel) and i.page == page
    )
    at_top = next(k for k, i in enumerate(items) if i is note) < first_label
    assert at_top is _NOTE_AT_TOP[(run, page)]
    holder = _holder(result, note)
    if at_top:
        assert holder is None or _DOUBT_PAGE in holder.doubts
    else:
        # Run 1, page 13: listed after 6(c)'s "(i)", so it is bound there like any
        # other writing. The list gives no sign that it was moved.
        assert holder is not None
        assert holder.question_id == "6c_i"


@pytest.mark.parametrize("run", _RUNS)
def test_no_recorded_run_has_a_listing_suspect(
    run: int, bound: dict[int, tuple[list[StreamItem], BoundStream]]
) -> None:
    # Every run has blocks unbound after a container label (graph notes beside "1" and
    # "2", a sketch beside 3(b), the arrow-tied sentence after "(b)" in run 1). None of
    # those runs of leaves ends in a blank one: the reader put labels before writing.
    items, result = bound[run]
    assert [u for u in result.unbound if u.reason == "after_container_label"]
    assert result.listing_suspects == []


@pytest.mark.parametrize("run", _RUNS)
def test_no_writing_is_lost(
    run: int, bound: dict[int, tuple[list[StreamItem], BoundStream]]
) -> None:
    items, result = bound[run]
    writings = [i for i in items if isinstance(i, SeenWriting)]
    on_leaves = [id(w) for leaf in result.leaves for w in leaf.writings]
    set_aside = [id(u.writing) for u in result.unbound]
    assert sorted(on_leaves + set_aside) == sorted(id(w) for w in writings)
    assert len(set(on_leaves + set_aside)) == len(writings)


@pytest.mark.parametrize("run", _RUNS)
def test_every_label_item_of_a_recorded_run_has_a_place(
    run: int, bound: dict[int, tuple[list[StreamItem], BoundStream]]
) -> None:
    # No recorded item typed as a label has text that names no step, and no two equal
    # labels stand side by side: neither rule about such labels moves a recorded run.
    items, result = bound[run]
    labels = [item for item in items if isinstance(item, SeenLabel)]
    assert all(parse_label(label.text) for label in labels)
    assert all(a.text != b.text for a, b in itertools.pairwise(labels))
    assert result.unplaced_labels == []
    assert result.unaligned_reasons == {}


# Leaves that are answered and had a block under their label set aside, per run. Runs 2
# and 5: a block the reader marked "uncertain" under 6(b), 7(b)(i) and 8(d) (for 8(d)
# it is the working of the answer); run 5 also under 3(c), which already carries a
# doubt for the unseen number 4. Runs 1, 3 and 4 have none: their unbound blocks all
# fell straight after a container label, where no leaf has been opened (in run 1 that is
# the last sentence of 4(b)(i), listed after "(b)"). That case is a known limit.
_SET_ASIDE = {1: [], 2: ["6b", "7b_i", "8d"], 3: [], 4: [], 5: ["3c", "6b", "7b_i", "8d"]}
# Blocks that fell straight after a container label, per run: unbound, under no leaf.
_AFTER_CONTAINER = {1: 3, 2: 5, 3: 3, 4: 2, 5: 3}


@pytest.mark.parametrize("run", _RUNS)
def test_an_answered_leaf_with_writing_set_aside_carries_the_doubt(
    run: int, bound: dict[int, tuple[list[StreamItem], BoundStream]]
) -> None:
    items, result = bound[run]
    doubt = "some writing under this label was set aside"
    assert [leaf.question_id for leaf in result.leaves if doubt in leaf.doubts] == _SET_ASIDE[run]
    # Each such leaf is marked on what it holds, and every block that was set aside
    # for the reader's "uncertain" stands under one of them or under a container label.
    assert all(leaf.writings for leaf in result.leaves if doubt in leaf.doubts)
    uncertain = sum(u.reason == "uncertain" for u in result.unbound)
    assert (uncertain > 0) == bool(_SET_ASIDE[run])
    # Every question of the recorded paper has its number or is inferred: no leaf is
    # past an unseen question, whatever kind the reader gave a label.
    unseen = "a question after this one has no label: its answers may be here"
    assert not [leaf.question_id for leaf in result.leaves if unseen in leaf.doubts]
    after_container = sum(u.reason == "after_container_label" for u in result.unbound)
    assert after_container == _AFTER_CONTAINER[run]
    assert len(result.unbound) == uncertain + after_container
