"""Parts a student skipped on a handwritten answer sheet, and what G5 makes of them.

On a sheet the student labels by hand a skipped part has no label. ``bind_stream``
cannot tell that from a label the reader missed, so the leaf is unaligned and the
answered leaf before it is unbound (D1). ``skipped_parts`` says which of those a read
may leave out of G5's rate; ``check_label_coverage`` takes them as ``skipped``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.core.binding import BindingCheck, SeenLabel, SeenWriting, StreamItem
from lemely.core.binding_gate import (
    GateThresholds,
    SkippedParts,
    check_label_coverage,
    skipped_parts,
)
from lemely.core.label_sequence import BoundStream, bind_stream
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "mark-schemes"
DEFAULTS = GateThresholds()
# Three parts of 0625/41 a student did not attempt, and the answered leaf before each
# that D1 unbinds. 2(a)(i) is the first leaf of its question: the leaf before it,
# 1(c)(ii), is closed by the number "2".
_SKIPPED = ("2a_i", "5b", "7b_ii")
_BEFORE = ("5a", "7b_i")


@pytest.fixture(scope="module")
def scheme_41() -> MarkScheme:
    return MarkScheme.model_validate(json.loads((_CORPUS / "0625_w24_ms_41.json").read_text()))


def _sheet(
    scheme: MarkScheme,
    *,
    skipped: tuple[str, ...] = (),
    not_attempted: tuple[str, ...] = (),
    printed: tuple[str, ...] = (),
    kind: str = "handwritten",
) -> list[StreamItem]:
    """A separate sheet as a perfect reader lists it: bare labels, each once, in order.

    A part in ``skipped`` has neither label nor writing; a question whose number is in
    ``not_attempted`` has none of its labels. Labels of the questions whose number is
    in ``printed`` are reported as printed, the rest as ``kind``.
    """
    out: list[StreamItem] = []
    for question in scheme.all_questions_flat():
        number = question.id.split("_")[0].rstrip("abcdefghijklmnopqrstuvwxyz")
        if question.id in skipped or number in not_attempted:
            continue
        parent = question.parent_id or ""
        token = question.id[len(parent) :].removeprefix("_")
        out.append(
            SeenLabel(
                page=1,
                text=f"({token})" if parent else token,
                kind="printed" if number in printed else kind,  # type: ignore[arg-type]
            )
        )
        if not question.parts:
            out.append(SeenWriting(page=1, answer=f"answer to {question.id}"))
    return out


def _g5(scheme: MarkScheme, read: BoundStream, skipped: SkippedParts | None = None) -> BindingCheck:
    extracted = ExtractedAnswers(
        paper_id="",
        source_scan="",
        answers=[
            ExtractedAnswer(question_id=leaf.question_id, answer="x", confidence=1.0)
            for leaf in read.leaves
            if leaf.writings
        ],
    )
    return check_label_coverage(
        extracted,
        scheme,
        read.unaligned_ids,
        len(read.unplaced_labels),
        DEFAULTS,
        listing_suspects=read.listing_suspects,
        skipped=skipped,
    )


def test_three_skipped_parts_hold_the_paper_until_they_are_excused(scheme_41: MarkScheme) -> None:
    read = bind_stream(_sheet(scheme_41, skipped=_SKIPPED), scheme_41)
    assert read.unaligned_reasons == {
        "2a_i": "label_not_seen",
        "5a": "not_bracketed",
        "5b": "label_not_seen",
        "7b_i": "not_bracketed",
        "7b_ii": "label_not_seen",
    }
    # Five of 43 leaves: over the limit, and nothing here is bound wrongly.
    held = _g5(scheme_41, read)
    assert (held.passed, held.scope) == (False, "paper")
    assert "5 of 43 questions could not be lined up" in held.detail

    excused = skipped_parts(read, read, scheme_41)
    assert excused == SkippedParts(skipped=_SKIPPED, before=_BEFORE)
    check = _g5(scheme_41, read, excused)
    # Not held, and every one of them still goes to review, with the answered leaf
    # before each gap, exactly as a paper under the limit does today.
    assert (check.passed, check.scope) == (False, "question")
    assert check.question_ids == ["1c_ii", "2a_i", "4b_iii", "5a", "5b", "7a", "7b_i", "7b_ii"]
    assert check.detail.startswith("5 questions had no label to line up with: ")


def test_with_one_read_nothing_is_excused(scheme_41: MarkScheme) -> None:
    read = bind_stream(_sheet(scheme_41, skipped=_SKIPPED), scheme_41)
    assert skipped_parts(read, None, scheme_41) == SkippedParts()
    assert SkippedParts() == SkippedParts(skipped=(), before=())


def test_a_label_the_other_read_saw_is_a_missed_label_not_a_skipped_part(
    scheme_41: MarkScheme,
) -> None:
    # A part the student skipped is absent from both reads of the sheet. A label one
    # reader missed is in the other read. That is the one thing that tells them apart.
    read = bind_stream(_sheet(scheme_41, skipped=_SKIPPED), scheme_41)
    whole = bind_stream(_sheet(scheme_41), scheme_41)
    assert whole.unaligned_ids == []
    assert skipped_parts(read, whole, scheme_41) == SkippedParts()
    assert skipped_parts(whole, read, scheme_41) == SkippedParts()
    # The other read lacks 5(b) only: 5(b) is excused with the leaf before it, and
    # the other two absent leaves count as today, each with the leaf D1 unbound.
    other = bind_stream(_sheet(scheme_41, skipped=("5b",)), scheme_41)
    excused = skipped_parts(read, other, scheme_41)
    assert excused == SkippedParts(skipped=("5b",), before=("5a",))
    assert skipped_parts(other, read, scheme_41) == excused
    # Where the other read has the leaf unaligned for another reason, it saw the label.
    crowded = _sheet(scheme_41, skipped=("2a_i", "7b_ii"))
    at = next(i for i, item in enumerate(crowded) if getattr(item, "answer", "").endswith(" 5b"))
    crowded[at:at] = [SeenLabel(page=1, text="continued", kind="handwritten")]
    seen = bind_stream(crowded, scheme_41)
    assert seen.unaligned_reasons["5b"] == "unplaced_label_follows"
    assert skipped_parts(read, seen, scheme_41) == SkippedParts(
        skipped=("2a_i", "7b_ii"), before=("7b_i",)
    )


def test_a_read_that_stopped_before_the_gap_is_no_witness_for_it(scheme_41: MarkScheme) -> None:
    # The other read's list ends after 5(a)'s answer: every label after that is absent
    # from it, the gap's labels with the rest. A list that stops early says nothing
    # about what lies past its end, so it excuses nothing there.
    read = bind_stream(_sheet(scheme_41, skipped=_SKIPPED), scheme_41)
    sheet = _sheet(scheme_41)
    at = next(i for i, item in enumerate(sheet) if getattr(item, "answer", "").endswith(" 5a"))
    stopped = bind_stream(sheet[: at + 1], scheme_41)
    assert stopped.unaligned_reasons["5b"] == "label_not_seen"
    assert skipped_parts(read, stopped, scheme_41) == SkippedParts()
    held = _g5(scheme_41, read, skipped_parts(read, stopped, scheme_41))
    assert (held.passed, held.scope) == (False, "paper")
    # Complete in the same parts as this read, with the last label past the gap: excused.
    honest = bind_stream(_sheet(scheme_41, skipped=_SKIPPED), scheme_41)
    assert skipped_parts(read, honest, scheme_41) == SkippedParts(skipped=_SKIPPED, before=_BEFORE)


def test_a_question_not_attempted_at_the_end_needs_a_read_that_reached_it(
    scheme_41: MarkScheme,
) -> None:
    # The last question not attempted, in both reads: excused. The other read stops two
    # questions earlier: it never reached the gap, and nothing is excused.
    read = bind_stream(_sheet(scheme_41, not_attempted=("9",)), scheme_41)
    assert skipped_parts(read, read, scheme_41).skipped[0] == "9a"
    sheet = _sheet(scheme_41, not_attempted=("9",))
    at = next(i for i, item in enumerate(sheet) if getattr(item, "answer", "").endswith(" 7a"))
    early = bind_stream(sheet[:at], scheme_41)
    assert skipped_parts(read, early, scheme_41) == SkippedParts()
    assert _g5(scheme_41, read, skipped_parts(read, early, scheme_41)).scope == "paper"


def test_the_rate_counts_what_is_not_excused(scheme_41: MarkScheme) -> None:
    # Six absent leaves and the five leaves before them: 11 of 43. The other read has
    # two of them absent, so nine leaves still count, and the paper is held on those.
    six = ("2a_i", "3b_ii", "5b", "6c_ii", "7b_ii", "9b")
    read = bind_stream(_sheet(scheme_41, skipped=six), scheme_41)
    other = bind_stream(_sheet(scheme_41, skipped=("5b", "9b")), scheme_41)
    excused = skipped_parts(read, other, scheme_41)
    assert excused == SkippedParts(skipped=("5b", "9b"), before=("5a", "9a"))
    check = _g5(scheme_41, read, excused)
    assert (check.passed, check.scope) == (False, "paper")
    assert check.question_ids == read.unaligned_ids
    assert (
        "7 of 43 questions could not be lined up with a label on the page "
        "(4 more are not counted: no label in either reading of the scan, between "
        "handwritten labels, or the answer before such a gap)" in check.detail
    )
    # Absent in both reads: none counts, and the paper is not held.
    excused = skipped_parts(read, read, scheme_41)
    assert len(excused.skipped) == 6
    assert len(excused.before) == 5
    assert _g5(scheme_41, read, excused).scope == "question"


def test_printed_labels_are_never_excused(scheme_41: MarkScheme) -> None:
    # On the printed paper every label is printed: one that is not in the list was
    # missed by the reader, in both reads or not.
    read = bind_stream(_sheet(scheme_41, skipped=_SKIPPED, kind="printed"), scheme_41)
    assert [read.unaligned_reasons[leaf] for leaf in _SKIPPED] == ["label_not_seen"] * 3
    assert skipped_parts(read, read, scheme_41) == SkippedParts()
    assert _g5(scheme_41, read, skipped_parts(read, read, scheme_41)).scope == "paper"


def test_a_gap_is_excused_only_between_handwritten_labels(scheme_41: MarkScheme) -> None:
    # Questions 1 to 4 on the printed paper, 5 to 9 on sheets. The gap at 2(a)(i) lies
    # between printed labels; the gaps at 5(b) and 7(b)(ii) between handwritten ones.
    read = bind_stream(_sheet(scheme_41, skipped=_SKIPPED, printed=("1", "2", "3", "4")), scheme_41)
    assert read.absent_between == {
        "2a_i": ("printed", "printed"),
        "5b": ("handwritten", "handwritten"),
        "7b_ii": ("handwritten", "handwritten"),
    }
    assert skipped_parts(read, read, scheme_41) == SkippedParts(
        skipped=("5b", "7b_ii"), before=_BEFORE
    )
    # One printed neighbour is enough to keep a gap counted: with question 5 not
    # attempted, the gap lies between the last printed label and the handwritten "6".
    edge = bind_stream(
        _sheet(scheme_41, not_attempted=("5",), printed=("1", "2", "3", "4")), scheme_41
    )
    five = ("5a", "5b", "5c_i", "5c_ii", "5d")
    assert edge.absent_between == dict.fromkeys(five, ("printed", "handwritten"))
    assert skipped_parts(edge, edge, scheme_41) == SkippedParts()
    # At the end of the list there is one side only.
    last = bind_stream(_sheet(scheme_41, skipped=("9c_iv",)), scheme_41)
    assert last.absent_between == {"9c_iv": ("handwritten", None)}
    assert skipped_parts(last, last, scheme_41) == SkippedParts(
        skipped=("9c_iv",), before=("9c_iii",)
    )


def test_a_list_that_shows_anything_else_excuses_nothing(scheme_41: MarkScheme) -> None:
    clean = _sheet(scheme_41, skipped=_SKIPPED)
    assert skipped_parts(bind_stream(clean, scheme_41), bind_stream(clean, scheme_41), scheme_41)
    # A label no question accounts for.
    stray = [*clean[:10], SeenLabel(page=1, text="(q)", kind="handwritten"), *clean[10:]]
    read = bind_stream(stray, scheme_41)
    assert [label.text for label in read.unplaced_labels] == ["(q)"]
    assert skipped_parts(read, read, scheme_41) == SkippedParts()
    # A leaf that is unaligned for any other reason: here two blocks beside a blank
    # leaf (D10), which is a label listed out of place and not an absent one.
    moved = list(clean)
    at = next(i for i, item in enumerate(moved) if getattr(item, "answer", "").endswith(" 3b_ii"))
    moved[at - 1], moved[at - 2] = moved[at - 2], moved[at - 1]
    read = bind_stream(moved, scheme_41)
    assert read.unplaced_labels == []
    assert "neighbour_left_blank" in read.unaligned_reasons.values()
    assert skipped_parts(read, read, scheme_41) == SkippedParts()
    # A group with the trace of writing listed before its label: in question 6 the
    # answers to (a) and (b) each stand before their label. No leaf is unaligned by
    # it, and the list is still not one that shows absent labels and nothing else.
    shifted = list(clean)
    at = next(i for i, item in enumerate(shifted) if getattr(item, "answer", "").endswith(" 6a"))
    shifted[at - 1], shifted[at] = shifted[at], shifted[at - 1]
    shifted[at + 1], shifted[at + 2] = shifted[at + 2], shifted[at + 1]
    read = bind_stream(shifted, scheme_41)
    assert read.listing_suspects == ["6"]
    assert read.unplaced_labels == []
    assert set(read.unaligned_reasons) == {"2a_i", "5a", "5b", "7b_i", "7b_ii"}
    assert skipped_parts(read, read, scheme_41) == SkippedParts()


def test_a_question_not_attempted_is_excused_and_too_many_hold_the_paper(
    scheme_41: MarkScheme,
) -> None:
    # The last question not attempted: 6 of 43 leaves, their number absent. Today that
    # holds the paper (7 with the leaf before); excused, it does not.
    read = bind_stream(_sheet(scheme_41, not_attempted=("9",)), scheme_41)
    nine = ("9a", "9b", "9c_i", "9c_ii", "9c_iii", "9c_iv")
    assert read.unaligned_reasons == {"8d": "not_bracketed"} | dict.fromkeys(
        nine, "number_not_seen"
    )
    assert _g5(scheme_41, read).scope == "paper"
    excused = skipped_parts(read, read, scheme_41)
    assert excused == SkippedParts(skipped=nine, before=("8d",))
    assert _g5(scheme_41, read, excused).scope == "question"
    # The last three: 15 of 43 leaves have no label in either read. That is over a
    # third of the paper, and a list that stops early looks the same: the paper is held.
    read = bind_stream(_sheet(scheme_41, not_attempted=("7", "8", "9")), scheme_41)
    excused = skipped_parts(read, read, scheme_41)
    assert len(excused.skipped) == 15
    assert DEFAULTS.skipped_parts_rate == 0.33
    check = _g5(scheme_41, read, excused)
    assert (check.passed, check.scope) == (False, "paper")
    assert (
        "15 of 43 questions have no label in either reading of the scan: too many to "
        "take for parts the student skipped" in check.detail
    )
    assert "could not be lined up" not in check.detail
    # Fourteen are within the limit: the last two questions (11 leaves) and three parts.
    read = bind_stream(_sheet(scheme_41, not_attempted=("8", "9"), skipped=_SKIPPED), scheme_41)
    excused = skipped_parts(read, read, scheme_41)
    assert len(excused.skipped) == 14
    assert _g5(scheme_41, read, excused).scope == "question"


def test_the_gate_ignores_excused_ids_that_are_not_unaligned(scheme_41: MarkScheme) -> None:
    # ``skipped`` is a claim about leaves the read could not align. An id that is
    # aligned, or is no leaf, changes nothing.
    read = bind_stream(_sheet(scheme_41, skipped=_SKIPPED), scheme_41)
    bogus = SkippedParts(skipped=("1a_i", "nope"), before=("1b",))
    assert _g5(scheme_41, read, bogus) == _g5(scheme_41, read)
    assert _g5(scheme_41, read, SkippedParts()) == _g5(scheme_41, read)
