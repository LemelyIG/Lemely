"""Unit tests for binding a reading-order stream to questions, rule by rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.core.binding import SeenLabel, SeenWriting, StreamItem
from lemely.core.label_sequence import (
    CONTENT_DOUBTS,
    DOUBTS,
    INFERENCE_DOUBTS,
    MAX_SCHEME_DEPTH,
    MAX_STREAM_ITEMS,
    UNALIGNED_REASONS,
    BoundStream,
    LabelStep,
    bind_stream,
    duplicate_leaf_ids,
    parse_label,
)
from lemely.core.loose_schemas import MarkScheme

_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "mark-schemes"
_SCHEME_41 = _CORPUS / "0625_w24_ms_41.json"


def _load(path: Path) -> MarkScheme:
    return MarkScheme.model_validate(json.loads(path.read_text()))


@pytest.fixture(scope="module")
def scheme_41() -> MarkScheme:
    return _load(_SCHEME_41)


def _scheme(template: MarkScheme, tree: dict | list) -> MarkScheme:
    """A scheme with the given ``{id: {child id: ...}}`` shape, built from a real one."""
    leaf = template.all_questions_flat()[2]  # 1a_i, a leaf

    def build(spec: dict | list, parent_id: str | None) -> list:
        pairs = spec.items() if isinstance(spec, dict) else spec
        return [
            leaf.model_copy(
                update={"id": qid, "parent_id": parent_id, "parts": build(children, qid)}
            )
            for qid, children in pairs
        ]

    return template.model_copy(update={"questions": build(tree, None)})


def _w(answer: str, *, page: int = 1, placed_by: str = "position") -> SeenWriting:
    return SeenWriting.model_validate({"page": page, "answer": answer, "placed_by": placed_by})


def _items(*parts: str | StreamItem, page: int = 1) -> list[StreamItem]:
    """A stream: a plain string is a label, ``"=x"`` is writing ``x``."""
    out: list[StreamItem] = []
    for part in parts:
        if not isinstance(part, str):
            out.append(part)
        elif part.startswith("="):
            out.append(_w(part[1:], page=page))
        else:
            out.append(SeenLabel(page=page, text=part, kind="printed"))
    return out


def _clean(scheme: MarkScheme) -> list[str]:
    """The paper as a perfect reader lists it: every label, and ``=id`` after each leaf."""
    out: list[str] = []
    for question in scheme.all_questions_flat():
        parent = question.parent_id or ""
        token = question.id[len(parent) :].removeprefix("_")
        out.append(f"({token})" if parent else token)
        if not question.parts:
            out.append(f"={question.id}")
    return out


def _cut(stream: list[str], *, drop: tuple[str, ...] = (), after: dict | None = None) -> list[str]:
    """``stream`` without the labels of the ids in ``drop``; ``after`` adds parts after a part.

    Ids are located through the ``=id`` writing that follows a leaf label, or through
    the position of a container label counted from the clean stream.
    """
    out = list(stream)
    for part, extra in (after or {}).items():
        at = out.index(part)
        out[at + 1 : at + 1] = list(extra)
    for leaf in drop:
        at = out.index(f"={leaf}")
        del out[at - 1]
    return out


def _on(bound: BoundStream) -> dict[str, list[str]]:
    return {leaf.question_id: [w.answer for w in leaf.writings] for leaf in bound.leaves}


def _unbound(bound: BoundStream) -> list[tuple[str, str]]:
    return [(u.writing.answer, u.reason) for u in bound.unbound]


def _unplaced(bound: BoundStream) -> list[str]:
    return [label.text for label in bound.unplaced_labels]


def _own_or_absent(bound: BoundStream) -> None:
    """No writing sits on a leaf other than the one its text names."""
    for leaf_id, answers in _on(bound).items():
        assert set(answers) <= {leaf_id}, (leaf_id, answers)


# Question 1 and 2 of the 0625 paper as a clean reader lists them.
_Q1 = [
    "1",
    "(a)",
    "(i)",
    "=1a_i",
    "(ii)",
    "=1a_ii",
    "(b)",
    "=1b",
    "(c)",
    "(i)",
    "=1c_i",
    "(ii)",
    "=1c_ii",
]
_Q2 = [
    "2",
    "(a)",
    "(i)",
    "=2a_i",
    "(ii)",
    "=2a_ii",
    "(iii)",
    "=2a_iii",
    "(b)",
    "(i)",
    "=2b_i",
    "(ii)",
    "=2b_ii",
    "(c)",
    "=2c",
]


# --------------------------------------------------------------------------------------
# parse_label
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", [LabelStep("number", "1")]),
        ("(a)", [LabelStep("letter", "a")]),
        ("a)", [LabelStep("letter", "a")]),
        ("(ii)", [LabelStep("roman", "ii")]),
        ("ii)", [LabelStep("roman", "ii")]),
        ("iv", [LabelStep("roman", "iv")]),
        ("Q3 b ii", [LabelStep("number", "3"), LabelStep("letter", "b"), LabelStep("roman", "ii")]),
        (
            "3(b)(ii)",
            [LabelStep("number", "3"), LabelStep("letter", "b"), LabelStep("roman", "ii")],
        ),
        ("2bii", [LabelStep("number", "2"), LabelStep("letter", "b"), LabelStep("roman", "ii")]),
        ("Q5 (b)", [LabelStep("number", "5"), LabelStep("letter", "b")]),
        ("Question 4", [LabelStep("number", "4")]),
        ("1.", [LabelStep("number", "1")]),
        ("(1)", [LabelStep("number", "1")]),
        ("12", [LabelStep("number", "12")]),
        ("(l)", [LabelStep("letter", "l")]),
        (
            "7aiia",
            [
                LabelStep("number", "7"),
                LabelStep("letter", "a"),
                LabelStep("roman", "ii"),
                LabelStep("letter", "a"),
            ],
        ),
        ("3b,", [LabelStep("number", "3"), LabelStep("letter", "b")]),
        ("3b.", [LabelStep("number", "3"), LabelStep("letter", "b")]),
        ("(a),", [LabelStep("letter", "a")]),
        ("No. 3", [LabelStep("number", "3")]),
        ("No 3", [LabelStep("number", "3")]),
        ("no.3 (b)", [LabelStep("number", "3"), LabelStep("letter", "b")]),
        ("No", []),
        ("1, 2", []),
        ("aiia", []),  # the compact fourth level is read only after its number
        ("[2]", []),
        ("Fig. 1.2", []),
        ("0", []),
        ("007", []),
        ("130", []),
        ("", []),
        (" ", []),
        ("Total", []),
        ("continued", []),
        ("1 1", []),
        ("a b c d e", []),
        ("x" * 5000, []),
    ],
)
def test_parse_label_table(text: str, expected: list[LabelStep]) -> None:
    assert parse_label(text) == expected


@pytest.mark.parametrize("token", ["i", "v", "x"])
def test_roman_is_tried_before_letter(token: str) -> None:
    assert parse_label(f"({token})") == [LabelStep("roman", token)]


def test_an_upper_case_label_is_a_label_that_matches_no_question(scheme_41: MarkScheme) -> None:
    # "(A)" is not what the paper prints for part (a). It is kept as a label, so that
    # it stops the writing before it from running on, and it never names a question.
    assert parse_label("(A)") == [LabelStep("letter", "A")]
    stream = _cut(_clean(scheme_41), after={"=1a_i": ["(A)"]})
    bound = bind_stream(_items(*stream, "=after"), scheme_41)
    assert _unplaced(bound) == ["(A)"]
    assert bound.unaligned_ids == []
    assert _on(bound)["1a_i"] == ["1a_i"]
    stream = _cut(_clean(scheme_41), after={"(i)": ["(A)"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert ("1a_i", "after_unplaced_label") in _unbound(bound)
    assert "1a_i" in bound.unaligned_ids


# --------------------------------------------------------------------------------------
# The clean paper
# --------------------------------------------------------------------------------------
def test_a_clean_stream_binds_every_leaf_to_its_own_writing(scheme_41: MarkScheme) -> None:
    bound = bind_stream(_items(*_clean(scheme_41)), scheme_41)
    leaves = [q.id for q in scheme_41.all_questions_flat() if not q.parts]
    assert [leaf.question_id for leaf in bound.leaves] == leaves
    assert _on(bound) == {leaf: [leaf] for leaf in leaves}
    assert bound.unbound == []
    assert bound.unaligned_ids == []
    assert bound.unplaced_labels == []
    assert bound.inferred_numbers == []
    assert bound.listing_suspects == []
    assert all(not leaf.number_inferred and leaf.doubts == [] for leaf in bound.leaves)
    assert bound.leaves[0].label_seen == "(i)"


def test_the_doubts_fall_into_two_classes_and_no_doubt_is_in_neither() -> None:
    # What the gate does with a doubt depends on its class, so the classes are named
    # here and imported, not spelled again elsewhere.
    assert CONTENT_DOUBTS == (
        "next question number not seen",
        "continues from the previous page",
        "tied by an arrow",
    )
    assert INFERENCE_DOUBTS == ("question number not seen",)
    assert sorted(CONTENT_DOUBTS + INFERENCE_DOUBTS) == sorted(DOUBTS)
    assert not set(CONTENT_DOUBTS) & set(INFERENCE_DOUBTS)


def test_an_empty_stream_binds_nothing(scheme_41: MarkScheme) -> None:
    bound = bind_stream([], scheme_41)
    assert bound.leaves == []
    assert len(bound.unaligned_ids) == 43
    assert bound.unbound == []


def test_a_blank_answer_is_an_aligned_leaf_with_no_writing(scheme_41: MarkScheme) -> None:
    stream = [part for part in _clean(scheme_41) if part != "=7c"]
    bound = bind_stream(_items(*stream), scheme_41)
    assert _on(bound)["7c"] == []
    assert "7c" not in bound.unaligned_ids


# --------------------------------------------------------------------------------------
# Rule 1: labels to steps
# --------------------------------------------------------------------------------------
def test_a_multi_step_label_binds_as_one_chain_or_not_at_all(scheme_41: MarkScheme) -> None:
    # "Q5 (b)" on a continuation sheet inside question 1: it names question 5, so it is
    # never question 1's (b). Question 5 has its own number further on, so this label
    # is not where question 5 starts either, and the writing after it is not bound.
    stream = _cut(_clean(scheme_41), after={"=1a_ii": ["Q5 (b)", "=more of 5b"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert _unplaced(bound) == ["Q5 (b)"]
    assert ("more of 5b", "after_unplaced_label") in _unbound(bound)
    assert _unbound(bound) == [("more of 5b", "after_unplaced_label")]
    assert bound.unaligned_ids == []
    assert _on(bound)["1a_ii"] == ["1a_ii"]
    assert _on(bound)["5b"] == ["5b"]


def test_a_multi_step_label_is_not_split_over_a_missed_label(scheme_41: MarkScheme) -> None:
    # C4: question 1's own (b) was missed and "Q5 (b)" stands where it was.
    stream = _clean(scheme_41)
    stream[stream.index("=1b") - 1] = "Q5 (b)"
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert "1b" in bound.unaligned_ids
    assert ("1b", "after_unplaced_label") in _unbound(bound)
    assert _on(bound)["5b"] == ["5b"]


def test_a_merged_label_binds_both_of_its_steps(scheme_41: MarkScheme) -> None:
    stream = _clean(scheme_41)
    at = stream.index("1")
    stream[at : at + 2] = ["1 (a)"]
    at = stream.index("=2a_iii") + 1
    stream[at : at + 2] = ["(b) (i)"]
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.unaligned_ids == []
    assert bound.unplaced_labels == []
    assert _on(bound)["1a_i"] == ["1a_i"]
    assert _on(bound)["2b_i"] == ["2b_i"]
    assert next(leaf for leaf in bound.leaves if leaf.question_id == "2b_i").label_seen == "(b) (i)"


def test_a_full_path_label_in_its_own_place_binds_its_leaf(scheme_41: MarkScheme) -> None:
    # "3(b)(ii)" where "(ii)" stands, after "3" and "(b)" were listed on their own. It
    # names the question and the part the list is already in, and one part more: only
    # that last step is new. It is no second anchor for question 3.
    stream = _clean(scheme_41)
    at = stream.index("=3b_ii") - 1
    for text in ("3(b)(ii)", "Q3 b ii", "(b)(ii)", "3bii"):
        stream[at] = text
        bound = bind_stream(_items(*stream), scheme_41)
        assert bound.unaligned_ids == [], text
        assert bound.unplaced_labels == [], text
        assert _on(bound)["3b_ii"] == ["3b_ii"], text
        assert next(leaf for leaf in bound.leaves if leaf.question_id == "3b_ii").label_seen == text


def test_a_paper_labelled_with_full_paths_binds_every_leaf(scheme_41: MarkScheme) -> None:
    # Answers on separate sheets, every label written with its path.
    scheme = _scheme(
        scheme_41,
        {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {}}, "2": {"2a": {}}, "3": {}},
    )
    stream = ["1(a)(i)", "=1a_i", "1(a)(ii)", "=1a_ii", "1b", "=1b", "Q2 a", "=2a", "3", "=3"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound) == {leaf: [leaf] for leaf in ("1a_i", "1a_ii", "1b", "2a", "3")}
    assert bound.unplaced_labels == []
    assert bound.unbound == []
    assert [leaf.label_seen for leaf in bound.leaves] == ["1(a)(i)", "1(a)(ii)", "1b", "Q2 a", "3"]
    # Bare labels after full ones go on from where the full ones left the list.
    scheme_b = _scheme(
        scheme_41,
        {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {"1b_i": {}, "1b_ii": {}}}, "2": {"2a": {}}},
    )
    for opening in (["1(a)(i)", "=1a_i", "1(a)(ii)"], ["1", "(a)", "(i)", "=1a_i", "(ii)"]):
        stream = [*opening, "=1a_ii", "1(b)(i)", "=1b_i", "(ii)", "=1b_ii", "2", "(a)", "=2a"]
        bound = bind_stream(_items(*stream), scheme_b)
        assert bound.unaligned_ids == [], opening
        assert _on(bound)["1b_ii"] == ["1b_ii"], opening
    # With the last part of question 1 left blank, "Q2 a" comes straight after "1b":
    # a label of question 1, not a numbered line before the number 2.
    stream = ["1(a)(i)", "=1a_i", "1(a)(ii)", "=1a_ii", "1b", "Q2 a", "=2a", "3", "=3"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound) == {"1a_i": ["1a_i"], "1a_ii": ["1a_ii"], "1b": [], "2a": ["2a"], "3": ["3"]}


def test_a_part_label_may_repeat_the_part_it_sits_under(scheme_41: MarkScheme) -> None:
    scheme = _scheme(scheme_41, {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {}}, "2": {"2a": {}}})
    stream = ["1", "(a)(i)", "=1a_i", "(a)(ii)", "=1a_ii", "(b)", "=1b", "2", "(a)", "=2a"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound) == {leaf: [leaf] for leaf in ("1a_i", "1a_ii", "1b", "2a")}
    assert bound.unplaced_labels == []


def test_a_full_path_label_that_goes_back_binds_nothing(scheme_41: MarkScheme) -> None:
    # A restated path must still move forward. "1(a)(i)" after "1(a)(ii)" is out of
    # order; "(a)(i)" after "(a)(ii)" repeats a part already passed, which is a restart.
    scheme = _scheme(scheme_41, {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {}}, "2": {"2a": {}}})
    for late in ("1(a)(i)", "(a)(i)"):
        stream = ["1", "(a)", "(ii)", "=1a_ii", late, "=1a_i", "(b)", "=1b", "2", "(a)", "=2a"]
        bound = bind_stream(_items(*stream), scheme)
        _own_or_absent(bound)
        assert "1a_i" in bound.unaligned_ids, late
        assert ("1a_i", "after_unplaced_label") in _unbound(bound), late
        assert _on(bound)["2a"] == ["2a"], late


def test_two_full_path_labels_for_one_leaf_decide_nothing(scheme_41: MarkScheme) -> None:
    scheme = _scheme(scheme_41, {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {}}, "2": {"2a": {}}})
    stream = ["1(a)(i)", "=1a_i", "1(a)(i)", "=again", "1(a)(ii)", "=1a_ii", "1b", "=1b"]
    bound = bind_stream(_items(*stream, "2", "(a)", "=2a"), scheme)
    _own_or_absent(bound)
    assert "again" not in [answer for answers in _on(bound).values() for answer in answers]
    assert "1a_i" in bound.unaligned_ids
    assert _on(bound)["2a"] == ["2a"]


def test_a_label_item_whose_text_names_no_step_is_a_barrier(scheme_41: MarkScheme) -> None:
    # The reader typed it as a label, so something stands there that ends the answer
    # before it. A heading on a continuation needs no fault from the reader: what is
    # written under it is 3(b)(ii)'s, and the leaf listed before it is 5(d).
    for heading in (
        "Q3 (b)(ii) continued",
        "3b(ii) cont.",
        "3(b)(ii) ctd",
        "Extra space for 3(b)(ii)",
        "continued",
    ):
        assert parse_label(heading) == []
        stream = _cut(_clean(scheme_41), after={"=5d": [heading, "=more of 3b_ii"]})
        bound = bind_stream(_items(*stream), scheme_41)
        _own_or_absent(bound)
        assert _on(bound)["5d"] == ["5d"], heading
        assert _unbound(bound) == [("more of 3b_ii", "after_unplaced_label")], heading
        assert _unplaced(bound) == [heading]
        assert bound.unaligned_ids == []
    # It is not a part label, so it does not unsettle the leaves around it, and writing
    # under it is not writing under the label before it: here a stray "(x)" has none.
    stream = _cut(_clean(scheme_41), after={"=1a_i": ["(x)", "continued", "=more"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert _on(bound)["1a_i"] == ["1a_i"]
    assert _on(bound)["1a_ii"] == ["1a_ii"]
    assert _unbound(bound) == [("more", "after_unplaced_label")]
    # The same at the foot of the last page: the last leaf keeps its own writing.
    bound = bind_stream(_items(*_clean(scheme_41), "continued", "=more of 3b_ii"), scheme_41)
    assert _on(bound)["9c_iv"] == ["9c_iv"]
    assert _unbound(bound) == [("more of 3b_ii", "after_unplaced_label")]


def test_any_text_typed_as_a_label_is_a_barrier_whatever_it_says(scheme_41: MarkScheme) -> None:
    # No exception: a mark allocation, a caption or a total that the reader types as a
    # label costs the writing listed after it. That is the price of never reading a
    # heading as nothing. The leaf is not reported blank.
    stream = _cut(_clean(scheme_41), after={"(i)": ["[1]", "Fig. 1.1"], "=1a_ii": ["Total"]})
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert _unplaced(bound) == ["[1]", "Fig. 1.1", "Total"]
    assert _unbound(bound) == [("1a_i", "after_unplaced_label")]
    assert bound.unaligned_ids == ["1a_i"]
    assert _on(bound)["1a_ii"] == ["1a_ii"]
    assert _on(bound)["1b"] == ["1b"]


def test_equal_labels_one_after_the_other_are_two_labels(scheme_41: MarkScheme) -> None:
    # A part left blank on the printed paper puts two equal labels side by side: the
    # blank fourth-level "(b)" and the top-level "(b)" after it. Each has its place.
    scheme = _scheme(
        scheme_41,
        {
            "7": {
                "7a": {"7a_i": {}, "7a_ii": {"7a_ii_a": {}, "7a_ii_b": {}}},
                "7b": {"7b_i": {}, "7b_ii": {}},
            },
            "8": {"8a": {}},
        },
    )
    stream = [part for part in _clean(scheme) if part != "=7a_ii_b"]
    assert stream[stream.index("=7a_ii_a") + 1 :][:2] == ["(b)", "(b)"]
    bound = bind_stream(_items(*stream), scheme)
    assert bound.unaligned_ids == []
    assert bound.unbound == []
    assert bound.unplaced_labels == []
    answered = {leaf: [leaf] for leaf in ("7a_i", "7a_ii_a", "7b_i", "7b_ii", "8a")}
    assert _on(bound) == {**answered, "7a_ii_b": []}


def test_two_equal_labels_that_are_two_parts_are_not_read_as_one(scheme_41: MarkScheme) -> None:
    # A page is missing: 1(c)(i)'s writing, 1(c)(ii), the number 2 and 2(a) are gone,
    # and "(i)" of 1(c) is followed by "(i)" of 2(a). Read as one label, 1c_i would
    # hold 2a_i's writing.
    stream = _clean(scheme_41)
    del stream[stream.index("=1c_i") : stream.index("=2a_i") - 1]
    assert stream[stream.index("=2a_i") - 2 :][:3] == ["(i)", "(i)", "=2a_i"]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert "1c_i" not in _on(bound)
    # A stutter: the labels of question 1 are listed, then listed again with the
    # writing. The second "(i)" of the pair is 1(a)(i), not 1(c)(i).
    head = ["1", "(a)", "(i)", "(ii)", "(b)", "(c)", "(i)"]
    bound = bind_stream(_items(*head, *_clean(scheme_41)[2:]), scheme_41)
    _own_or_absent(bound)
    assert "1c_i" not in _on(bound)


def test_a_question_number_read_twice_in_a_row_opens_one_question(
    scheme_41: MarkScheme,
) -> None:
    # Two equal numbers side by side cannot be two questions. Whichever opens question
    # 2, the same labels follow, so nothing is lost. With writing between them they
    # are two places for the number again, and neither is taken.
    for twice in (["2"], ["2."], ["2", "2"]):
        stream = _cut(_clean(scheme_41), after={"2": twice})
        bound = bind_stream(_items(*stream), scheme_41)
        assert bound.unaligned_ids == [], twice
        assert bound.unbound == [], twice
        assert _unplaced(bound) == ["2", *twice][:-1]
    # The last of the pair is the label that opens the question, so that a question
    # with no parts keeps the writing after it.
    plain = _scheme(scheme_41, {"1": {}, "2": {}, "3": {}})
    bound = bind_stream(_items("1", "=1", "2", "2", "=2", "3", "=3"), plain)
    assert _on(bound) == {"1": ["1"], "2": ["2"], "3": ["3"]}
    assert bound.unbound == []
    stream = _cut(_clean(scheme_41), after={"2": ["=stem", "2"]})
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert not [leaf for leaf in _on(bound) if leaf.startswith("2")]
    # A part label with its full path, read twice, is two labels for one part like any
    # other pair: neither is the part's, and on a paper where every label opens with
    # the number that leaves the number unsettled too.
    full = ["1(a)(i)", "=1a_i", "1(a)(ii)", "1(a)(ii)", "=1a_ii", "1(b)", "=1b", "2", "=2"]
    scheme = _scheme(scheme_41, {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {}}, "2": {}})
    bound = bind_stream(_items(*full), scheme)
    assert _on(bound) == {"2": ["2"]}
    assert set(bound.unaligned_reasons.values()) == {"number_not_settled"}
    # Two different labels that open with the number are two places for it, side by
    # side or not: "1(b)" then "1(a)".
    bound = bind_stream(_items("1(b)", "1(a)", "=1a_i", "2", "=2"), scheme)
    assert _on(bound) == {"2": ["2"]}
    assert set(bound.unaligned_reasons.values()) == {"number_not_settled"}


def test_a_label_read_twice_in_a_row_is_not_resolved(scheme_41: MarkScheme) -> None:
    # "(i) (i) writing": nothing says which of the two is the part's label, or whether
    # the second opens a part whose own label was missed. The leaf is not bound, and
    # no other leaf pays for it.
    stream = _cut(_clean(scheme_41), after={"(i)": ["(i)"]})
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert "1a_i" in bound.unaligned_ids
    assert _on(bound)["1b"] == ["1b"]
    assert _on(bound)["2a_i"] == ["2a_i"]


def test_a_label_seen_again_after_writing_decides_nothing(scheme_41: MarkScheme) -> None:
    # (i), writing, (i) again: nothing says which of the two is 1a_i's label. And if
    # the second opens a part whose own label was missed, the (ii) after it is that
    # part's, so 1a_ii is not bound either.
    stream = _cut(_clean(scheme_41), after={"=1a_i": ["(i)", "=second"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert {"1a_i", "1a_ii"} <= set(bound.unaligned_ids)
    assert _unplaced(bound) == ["(i)", "(i)", "(ii)"]
    assert {"1a_i", "second", "1a_ii"} <= {answer for answer, _ in _unbound(bound)}
    assert _on(bound)["1b"] == ["1b"]
    _own_or_absent(bound)


# --------------------------------------------------------------------------------------
# Rule 2: question numbers
# --------------------------------------------------------------------------------------
def test_a_number_the_scheme_does_not_have_is_unplaced(scheme_41: MarkScheme) -> None:
    stream = _cut(_clean(scheme_41), after={"=1a_i": ["12"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert _unplaced(bound) == ["12"]
    assert bound.unbound == []
    assert bound.unaligned_ids == []


def test_a_stray_number_loses_to_the_real_one_by_a_wide_margin(scheme_41: MarkScheme) -> None:
    # C1: a stray 2 read between 1 and (a).
    stream = _cut(_clean(scheme_41), after={"1": ["2"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.unaligned_ids == []
    assert _unplaced(bound) == ["2"]
    assert _on(bound)["1a_i"] == ["1a_i"]
    assert _on(bound)["2a_i"] == ["2a_i"]


def test_numbered_answer_lines_inside_a_leaf_are_not_questions(scheme_41: MarkScheme) -> None:
    # "1." and "2." listed as labels under 1(a)(i), each with its line of writing.
    stream = [part for part in _clean(scheme_41) if part != "=1a_i"]
    stream = _cut(stream, after={"(i)": ["1.", "=43", "2.", "=63"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert _unplaced(bound) == ["1.", "2."]
    assert _unbound(bound) == [("43", "after_unplaced_label"), ("63", "after_unplaced_label")]
    # 1a_i has writing in its stretch that was not bound: it is not reported blank.
    assert bound.unaligned_ids == ["1a_i"]
    assert _on(bound)["1a_ii"] == ["1a_ii"]
    assert _on(bound)["2a_i"] == ["2a_i"]


def test_a_lone_number_after_an_unanchored_number_is_no_anchor(scheme_41: MarkScheme) -> None:
    # Numbered lines 1. 2. 3. under question 2, listed as labels, and the real 3
    # missed: "3." is the only candidate for question 3, and it is one of the lines.
    scheme = _scheme(scheme_41, {str(n): {} for n in range(1, 6)})
    stream = ["1", "=1", "2", "1.", "2.", "3.", "=2", "=3", "4", "=4", "5", "=5"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert "3" in bound.unaligned_ids
    assert _on(bound)["5"] == ["5"]
    # The same with question 3 left blank: one block, and it is question 2's.
    stream = ["1", "=1", "2", "1.", "2.", "3.", "=2", "4", "=4", "5", "=5"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert {"2", "3"} <= set(bound.unaligned_ids)
    assert ("2", "after_unplaced_label") in _unbound(bound)


def test_the_last_of_a_run_of_numbered_lines_is_no_anchor(scheme_41: MarkScheme) -> None:
    # 3 and 4 are both missed, and three numbered lines under 3(b) are listed as
    # labels. "3." is the only candidate for question 3 and question 4's parts follow
    # it: as an anchor it would put question 4's writing on question 3. It comes
    # straight after "2.", which is no anchor: a run of lines, not a question number.
    scheme = _scheme(
        scheme_41,
        {
            "2": {"2a": {}},
            "3": {"3a": {}, "3b": {}},
            "4": {"4a": {}, "4b": {}},
            "5": {"5a": {}},
        },
    )
    stream = ["2", "(a)", "=2a", "(a)", "=3a", "(b)", "=3b", "1.", "2.", "3."]
    stream += ["(a)", "=4a", "(b)", "=4b", "5", "(a)", "=5a"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"5a": ["5a"]}
    assert bound.inferred_numbers == []
    # A page number before a question number is not such a run.
    stream = _cut(_clean(scheme_41), after={"=2c": ["7"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.unaligned_ids == []
    assert _unplaced(bound) == ["7"]


def test_a_number_that_may_open_an_unanchored_question_ends_the_one_before(
    scheme_41: MarkScheme,
) -> None:
    # Two 4s that tie, so question 4 has no anchor; 3c's own (i) and (ii) were missed.
    # The (i) (ii) after the 4s are question 4's and must not fill 3c.
    scheme = _scheme(
        scheme_41,
        {
            "3": {"3a": {}, "3b": {}, "3c": {"3c_i": {}, "3c_ii": {}}},
            "4": {"4i": {}, "4ii": {}},
            "5": {"5a": {}},
        },
    )
    stream = ["3", "(a)", "=3a", "(b)", "=3b", "(c)", "4", "=x", "4", "(i)", "=4i", "(ii)", "=4ii"]
    bound = bind_stream(_items(*stream, "5", "(a)", "=5a"), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"3a": ["3a"], "3b": ["3b"], "5a": ["5a"]}
    assert _unplaced(bound) == ["4", "4", "(i)", "(ii)"]


def test_two_candidates_that_tie_leave_the_question_unaligned(scheme_41: MarkScheme) -> None:
    # Two bare 2s in front of a question with no parts: nothing separates them.
    scheme = _scheme(scheme_41, {"1": {}, "2": {}, "3": {"3a": {}, "3b": {}}})
    stream = ["1", "=1", "2", "=x", "2", "=2", "3", "(a)", "=3a", "(b)", "=3b"]
    bound = bind_stream(_items(*stream), scheme)
    assert "2" in bound.unaligned_ids
    assert _unplaced(bound) == ["2", "2"]
    assert _on(bound) == {"3a": ["3a"], "3b": ["3b"]}
    # Question 1's writing may be question 2's: the label that should follow was not seen.
    assert ("1", "next_label_not_seen") in _unbound(bound)


def test_a_question_number_misread_as_the_next_one_binds_neither(scheme_41: MarkScheme) -> None:
    # C2: question 2's number read as 3. Two 3s score the same; neither is question 3.
    stream = _clean(scheme_41)
    stream[stream.index("2")] = "3"
    bound = bind_stream(_items(*stream), scheme_41)
    on = _on(bound)
    assert not [leaf for leaf in on if leaf.startswith(("2", "3"))]
    assert on["4a"] == ["4a"]
    _own_or_absent(bound)
    # The first "3" has no anchor, so it is read both ways (D7). As the end of question
    # 1 it leaves question 1 whole. As a stray it lets question 2's "(a) (i) (ii) ..."
    # run on under question 1, where they are second labels for 1(a) and for 1(c)'s
    # parts. Only what both readings bind is kept: 1(b).
    assert [leaf for leaf in on if leaf.startswith("1")] == ["1b"]
    assert on["1b"] == ["1b"]
    # A label with a place in one reading only has no place: the leaves are reported
    # as unsettled, not as leaves whose label was seen and whose writing was not kept.
    assert bound.unaligned_reasons["1a_i"] == "path_not_aligned"
    assert bound.unaligned_reasons["1c_i"] == "label_not_settled"


def test_a_number_with_no_anchor_is_read_as_an_end_and_as_a_stray(scheme_41: MarkScheme) -> None:
    # D7. Two pages listed in the other order: after "11" come question 8's "(i) (ii)
    # (b)" and its writing, then "9", then question 11's own "(i) (ii) (iii) (iv)". The
    # "9" has no anchor (it comes after 11). Read only as the end of question 11, it
    # hides 11's own labels behind it, and 11(i) would take 8(a)(i)'s writing. Read as
    # a stray as well, there are two "(i)"s for 11(i), and neither is taken.
    scheme = _scheme(
        scheme_41,
        {
            "8": {"8a": {"8a_i": {}, "8a_ii": {}}, "8b": {}},
            "9": {},
            "10": {"10i": {}, "10ii": {}, "10iii": {}},
            "11": {"11i": {}, "11ii": {}, "11iii": {}, "11iv": {}},
            "12": {},
        },
    )
    stream = ["8", "(a)", "10", "(i)", "=10i", "(ii)", "=10ii", "(iii)", "=10iii", "11"]
    stream += ["(i)", "=8a_i", "(ii)", "=8a_ii", "(b)", "=8b", "9", "=9"]
    stream += ["(i)", "=11i", "(ii)", "=11ii", "(iii)", "=11iii", "(iv)", "=11iv", "12", "=12"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"10i": ["10i"], "10ii": ["10ii"], "10iii": ["10iii"], "12": ["12"]}


def test_a_leaf_must_be_open_in_both_readings_of_a_number_with_no_anchor(
    scheme_41: MarkScheme,
) -> None:
    # D7 again. Two "7"s, so question 7 has no anchor and the first "7" is read both
    # ways. Question 6 is not in the list but for its "(c)". As the end of question 5,
    # the first "7" leaves 5(a) bracketed by "(b)". As a stray it puts the "(c)" in
    # question 5's stretch, a part question 5 lacks and the unseen question 6 has
    # (class C), and "(b)" may then be question 6's. The label "(a)" has the same
    # place in both readings; the leaf is open in one only, and is not bound.
    scheme = _scheme(
        scheme_41,
        {
            "5": {"5a": {}, "5b": {}},
            "6": {"6a": {}, "6b": {}, "6c": {}},
            "7": {"7a": {}},
            "8": {},
        },
    )
    stream = ["5", "(a)", "=5a", "(b)", "=5b", "7", "(c)", "=6c", "7", "(a)", "=7a", "8", "=8"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound) == {"8": ["8"]}
    assert bound.unaligned_reasons["5a"] == "not_bracketed"
    # With one "7" the question has its anchor and there is one reading.
    stream = ["5", "(a)", "=5a", "(b)", "=5b", "7", "(a)", "=7a", "8", "=8"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound) == {"5a": ["5a"], "7a": ["7a"], "8": ["8"]}


def test_a_continuation_label_is_no_anchor_when_the_number_itself_was_missed(
    scheme_41: MarkScheme,
) -> None:
    # "Q5 (b)" inside question 1, and the real 5 missed. As question 5's anchor it
    # would earn (c) (i) (ii) from the labels after it: exactly what it takes from
    # question 1. An anchor has to earn more than that.
    stream = _cut(_clean(scheme_41), after={"=1a_ii": ["Q5 (b)", "=more of 5b"]})
    del stream[stream.index("5")]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert _unplaced(bound)[0] == "Q5 (b)"
    assert ("more of 5b", "after_unplaced_label") in _unbound(bound)
    # It may still be where question 5 starts, so question 1 is not read past it.
    assert {"1b", "1c_i", "1c_ii"} <= set(bound.unaligned_ids)
    # Question 5's own labels, between 4 and 6, are every one its own: rule 4.
    assert bound.inferred_numbers == ["5"]
    assert _on(bound)["5c_i"] == ["5c_i"]


def test_a_stray_number_is_no_anchor_for_a_question_that_was_not_listed(
    scheme_41: MarkScheme,
) -> None:
    # Question 5 is not in the list at all, and a stray 5 sits inside question 4. As
    # an anchor it would turn 4(b) and 4(c) into 5(b) and 5(c), with nothing left to
    # contradict it. It earns two parts and takes the same two from question 4.
    scheme = _scheme(
        scheme_41,
        {
            "4": {"4a": {}, "4b": {}, "4c": {}},
            "5": {"5a": {}, "5b": {}, "5c": {}},
            "6": {"6a": {}},
        },
    )
    stream = ["4", "(a)", "=4a", "5", "(b)", "=4b", "(c)", "=4c", "6", "(a)", "=6a"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"6a": ["6a"]}
    assert _unplaced(bound) == ["5", "(b)", "(c)"]


def test_an_anchor_must_earn_more_than_it_takes_from_its_neighbour(scheme_41: MarkScheme) -> None:
    # The real 5 is missed and a stray 5 sits inside question 4. Anchoring question 5
    # there would put 4(b)'s parts on question 5; the stray gains nothing of its own.
    scheme = _scheme(
        scheme_41,
        {
            "4": {"4a": {}, "4b": {}},
            "5": {"5a": {}, "5b": {}, "5c": {}},
            "6": {"6a": {}},
        },
    )
    stream = [
        "4",
        "(a)",
        "=4a",
        "5",
        "(b)",
        "=4b",
        "(a)",
        "=5a",
        "(b)",
        "=5b",
        "(c)",
        "=5c",
        "6",
        "(a)",
        "=6a",
    ]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert "5b" not in _on(bound)
    assert _on(bound)["6a"] == ["6a"]


# --------------------------------------------------------------------------------------
# Rule 3: inside a span
# --------------------------------------------------------------------------------------
def test_a_restart_of_letters_ends_the_question(scheme_41: MarkScheme) -> None:
    # C5: 2b's (i) and the number 3 are both missed, and so is 4. Question 3's labels
    # must not fill the hole in question 2.
    stream = _cut(_clean(scheme_41), drop=("2b_i",))
    del stream[stream.index("3")]
    del stream[stream.index("4")]
    bound = bind_stream(_items(*stream), scheme_41)
    on = _on(bound)
    _own_or_absent(bound)
    assert on["2a_ii"] == ["2a_ii"]
    assert {"2b_i", "3a", "3b_i", "3b_ii", "3c", "4a", "4b_i"} <= set(bound.unaligned_ids)
    assert bound.inferred_numbers == []
    assert on["5a"] == ["5a"]
    # Read on past the restart, question 2 aligns one part more: (b) (i) (ii) (c) of
    # question 3 fit its hole. Two readings, so 2b_ii and 2c are not bound either,
    # and 2a_iii, the last leaf before them, cannot be sure where its writing ends.
    assert {"2b_ii", "2c"} <= set(bound.unaligned_ids)
    assert ("2a_iii", "next_label_not_seen") in _unbound(bound)


def test_a_question_with_no_hole_is_not_unsettled_by_what_follows_it(
    scheme_41: MarkScheme,
) -> None:
    # 3 and 4 both missed, nothing else: question 2 is complete, and reading on past
    # the restart aligns no more of it.
    stream = _clean(scheme_41)
    del stream[stream.index("3")]
    del stream[stream.index("4")]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    # 2c is the last leaf before the unseen number: its label is aligned, and its
    # writing cannot be told from what was written under the 3 that was not seen.
    assert [leaf for leaf in bound.unaligned_ids if leaf.startswith("2")] == ["2c"]
    assert ("2c", "next_label_not_seen") in _unbound(bound)
    assert _on(bound)["2b_ii"] == ["2b_ii"]


def test_a_stray_label_that_jumps_ahead_does_not_take_the_parts_after_it(
    scheme_41: MarkScheme,
) -> None:
    # A stray (c) between (a) and (i). Read as a restart at (b), the question would be
    # 1, (a), (c), (i), (ii): 1a's writing on 1c's parts. Read on, it is the clean
    # paper. Only what both readings make is kept.
    stream = _cut(_clean(scheme_41), after={"(a)": ["(c)"]})
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert {"1a_i", "1a_ii", "1c_i", "1c_ii"} <= set(bound.unaligned_ids)
    assert _on(bound)["2a_i"] == ["2a_i"]


def test_a_repeated_top_level_label_decides_nothing(scheme_41: MarkScheme) -> None:
    # (i) (ii) writing (ii) writing under a question whose parts are romans: the second
    # (ii) looks like a restart, and may as well be the true label.
    scheme = _scheme(scheme_41, {"3": {"3i": {}, "3ii": {}}, "4": {"4a": {}}})
    stream = ["3", "(i)", "(ii)", "=3i", "(ii)", "=3ii", "4", "(a)", "=4a"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert "3ii" in bound.unaligned_ids
    assert _on(bound)["4a"] == ["4a"]


def test_a_restart_below_the_top_level_orphans_the_labels_after_it(
    scheme_41: MarkScheme,
) -> None:
    # 1a's (i) read as (l) and (b) missed: (ii) (i) (ii) is left under (a). The (i)
    # after (ii) opens a part whose label was not seen; it is not 1a_i.
    scheme = _scheme(
        scheme_41,
        {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {"1b_i": {}, "1b_ii": {}}}, "2": {"2a": {}}},
    )
    stream = _clean(scheme)
    stream[stream.index("=1a_i") - 1] = "(l)"
    del stream[stream.index("=1a_ii") + 1]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert {"1a_i", "1a_ii", "1b_i", "1b_ii"} <= set(bound.unaligned_ids)
    assert _on(bound) == {"2a": ["2a"]}


def test_a_label_with_a_deeper_reading_after_an_orphan_ends_the_question(
    scheme_41: MarkScheme,
) -> None:
    # (a), a fourth-level (b) and the top-level (b) are missed. What is left reads
    # 7 (i) (ii) (a) (i) (ii) (c): the (a) is 7a_ii_a, not question 7's part (a).
    scheme = _scheme(
        scheme_41,
        {
            "7": {
                "7a": {"7a_i": {}, "7a_ii": {"7a_ii_a": {}, "7a_ii_b": {}}},
                "7b": {"7b_i": {}, "7b_ii": {}},
                "7c": {},
            },
            "8": {"8a": {}},
        },
    )
    stream = [
        "7",
        "(i)",
        "=7a_i",
        "(ii)",
        "(a)",
        "=7a_ii_a",
        "=7a_ii_b",
        "(i)",
        "=7b_i",
        "(ii)",
        "=7b_ii",
        "(c)",
        "=7c",
        "8",
        "(a)",
        "=8a",
    ]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"8a": ["8a"]}


def test_a_restart_hands_the_orphan_segment_to_rule_4(scheme_41: MarkScheme) -> None:
    # The same two misses with question 4's number seen: question 3 sits between two
    # anchors and every label of the segment is its own.
    stream = _cut(_clean(scheme_41), drop=("2b_i",))
    del stream[stream.index("3")]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert bound.inferred_numbers == ["3"]
    assert bound.unaligned_ids == ["2b_i"]
    assert ("2b_i", "after_container_label") in _unbound(bound)
    assert _on(bound)["3a"] == ["3a"]


def test_a_restart_is_judged_at_the_top_level_of_the_question(scheme_41: MarkScheme) -> None:
    # A letter under a roman is not a restart: 7(a)(i)(a) follows 7(a)(i).
    scheme = _scheme(
        scheme_41,
        {
            "7": {"7a": {"7a_i": {"7a_i_a": {}, "7a_i_b": {}}, "7a_ii": {}}, "7b": {}},
            "8": {"8i": {}, "8ii": {}},
            "9": {"9a": {}},
        },
    )
    bound = bind_stream(_items(*_clean(scheme)), scheme)
    assert bound.unaligned_ids == []
    assert bound.unplaced_labels == []
    # Question 8's romans restart when its number is missed.
    stream = _clean(scheme)
    stream[stream.index("8") : stream.index("8") + 1] = ["(i)", "=stray", "(ii)"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)


def test_a_leaf_is_bound_only_when_no_other_label_does_as_well(scheme_41: MarkScheme) -> None:
    # C2b: 2a's (i) read as (l), and (b) missed. What is left under (a) is
    # (ii) (iii) (i) (ii): "2a_ii, 2a_iii" and "2a_i, 2a_ii" align equally well, so
    # no label is 2a_ii's for certain and none of the three is bound.
    stream = _clean(scheme_41)
    stream[stream.index("=2a_i") - 1] = "(l)"
    del stream[stream.index("=2a_iii") + 1]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert {"2a_i", "2a_ii", "2a_iii", "2b_i", "2b_ii"} <= set(bound.unaligned_ids)
    assert _unplaced(bound) == ["(l)", "(ii)", "(iii)", "(i)", "(ii)"]
    assert _on(bound)["2c"] == ["2c"]
    # With (b) seen, each label has one place.
    stream = _clean(scheme_41)
    stream[stream.index("=2a_i") - 1] = "(l)"
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.unaligned_ids == ["2a_i"]
    assert _on(bound)["2a_ii"] == ["2a_ii"]


def test_a_label_that_matches_no_part_is_unplaced(scheme_41: MarkScheme) -> None:
    stream = _cut(_clean(scheme_41), after={"=1a_ii": ["(iv)"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert _unplaced(bound) == ["(iv)"]
    assert bound.unaligned_ids == []
    assert bound.unbound == []


def test_a_leaf_needs_its_whole_path(scheme_41: MarkScheme) -> None:
    # (c) missed: its (i) and (ii) are not 1c_i and 1c_ii, and not 1a's either.
    stream = _clean(scheme_41)
    del stream[stream.index("=1b") + 1]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert {"1c_i", "1c_ii"} <= set(bound.unaligned_ids)
    assert _on(bound)["1a_ii"] == ["1a_ii"]
    assert _on(bound)["2a_i"] == ["2a_i"]


def test_only_the_questions_own_top_level_parts_count_for_a_restart(
    scheme_41: MarkScheme,
) -> None:
    # Question 1 has parts (a), (b), (c). A stray "(e)", and an "(i)" read as "(l)", are
    # letters, and neither is a part of this question: the "(b)" after them is not "a
    # letter not greater than one already seen", and the question goes on. (Read
    # literally, the brief's restart rule would end question 1 at that "(b)".)
    for stray in ("(e)", "(l)", "(z)"):
        stream = _cut(_clean(scheme_41), after={"=1a_ii": [stray]})
        bound = bind_stream(_items(*stream), scheme_41)
        assert bound.unaligned_ids == [], stray
        assert _unplaced(bound) == [stray], stray
        assert _on(bound)["1b"] == ["1b"], stray
        assert _on(bound)["1c_ii"] == ["1c_ii"], stray
    # The misread itself: 1a's "(i)" listed as "(l)". It costs its own leaf only.
    stream = _clean(scheme_41)
    stream[stream.index("=1a_i") - 1] = "(l)"
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.unaligned_ids == ["1a_i"]
    assert _on(bound)["1a_ii"] == ["1a_ii"]
    assert _on(bound)["1b"] == ["1b"]
    # One of the question's own parts out of order is a restart, as before.
    stream = _cut(_clean(scheme_41), after={"=1a_ii": ["(c)"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert "1b" in bound.unaligned_ids


def test_i_is_a_letter_when_the_paper_says_so(scheme_41: MarkScheme) -> None:
    scheme = _scheme(scheme_41, {"1": {f"1{c}": {} for c in "abcdefghi"}})
    bound = bind_stream(_items(*_clean(scheme)), scheme)
    assert bound.unaligned_ids == []
    assert _on(bound)["1i"] == ["1i"]


# --------------------------------------------------------------------------------------
# Rule 4: inferred question number
# --------------------------------------------------------------------------------------
def _without_number(scheme: MarkScheme, number: str) -> list[str]:
    stream = _clean(scheme)
    del stream[stream.index(number)]
    return stream


def test_a_missed_question_number_is_inferred_between_two_anchors(scheme_41: MarkScheme) -> None:
    bound = bind_stream(_items(*_without_number(scheme_41, "4")), scheme_41)
    assert bound.inferred_numbers == ["4"]
    assert bound.unaligned_ids == []
    assert bound.unplaced_labels == []
    for leaf in bound.leaves:
        inferred = leaf.question_id.startswith("4")
        assert leaf.number_inferred is inferred
        assert ("question number not seen" in leaf.doubts) is inferred
        assert leaf.writings[0].answer == leaf.question_id
    # The leaf before the missing number keeps its writing, and says what it cannot know.
    before = next(leaf for leaf in bound.leaves if leaf.question_id == "3c")
    assert before.doubts == ["next question number not seen"]


@pytest.mark.parametrize("number", ["1", "9"])
def test_the_first_and_last_questions_are_never_inferred(
    scheme_41: MarkScheme, number: str
) -> None:
    bound = bind_stream(_items(*_without_number(scheme_41, number)), scheme_41)
    assert bound.inferred_numbers == []
    assert not [leaf for leaf in _on(bound) if leaf.startswith(number)]
    _own_or_absent(bound)


def test_no_inference_when_a_candidate_for_the_number_was_seen(scheme_41: MarkScheme) -> None:
    # Two readings of where question 4 starts: nothing is inferred over them.
    stream = _cut(_clean(scheme_41), after={"=4a": ["4"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.inferred_numbers == []
    _own_or_absent(bound)


def test_no_inference_when_a_candidate_stands_before_the_restart(scheme_41: MarkScheme) -> None:
    # A "4." listed inside question 3, and the real 4 missed. It may be where question
    # 4 starts: question 3 ends there, and nothing is inferred from what follows.
    stream = _cut(_without_number(scheme_41, "4"), after={"=3a": ["4."]})
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert bound.inferred_numbers == []
    assert not [leaf for leaf in _on(bound) if leaf.startswith("4")]
    assert _on(bound)["5a"] == ["5a"]


def test_a_stray_number_before_the_restart_does_not_stop_the_inference(
    scheme_41: MarkScheme,
) -> None:
    # A page number 2 between 3c's writing and question 4's (a): question 2 has its
    # anchor, so this 2 opens nothing.
    stream = _cut(_without_number(scheme_41, "4"), after={"=3c": ["2"]})
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert bound.inferred_numbers == ["4"]
    assert _unplaced(bound) == ["2"]
    assert bound.unaligned_ids == []


def test_no_inference_when_a_neighbour_has_no_anchor(scheme_41: MarkScheme) -> None:
    stream = _without_number(scheme_41, "4")
    del stream[stream.index("5")]
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.inferred_numbers == []
    assert not [leaf for leaf in _on(bound) if leaf.startswith(("4", "5"))]
    _own_or_absent(bound)


def test_no_inference_when_a_label_of_the_segment_does_not_align(scheme_41: MarkScheme) -> None:
    stream = _cut(_without_number(scheme_41, "4"), after={"=4a": ["(e)"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.inferred_numbers == []
    assert not [leaf for leaf in _on(bound) if leaf.startswith("4")]
    _own_or_absent(bound)


def test_no_inference_over_two_orphan_segments(scheme_41: MarkScheme) -> None:
    # The labels restart twice between 3 and 5: that is more than question 4.
    stream = _cut(_without_number(scheme_41, "4"), after={"=4b_iii": ["(a)", "=x", "(b)"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.inferred_numbers == []
    _own_or_absent(bound)


def test_a_question_with_no_parts_is_never_inferred(scheme_41: MarkScheme) -> None:
    scheme = _scheme(scheme_41, {"1": {"1a": {}, "1b": {}}, "2": {}, "3": {"3a": {}}})
    stream = ["1", "(a)", "=1a", "(b)", "=1b", "=2", "3", "(a)", "=3a"]
    bound = bind_stream(_items(*stream), scheme)
    assert bound.inferred_numbers == []
    assert "2" in bound.unaligned_ids
    _own_or_absent(bound)
    assert "1b" not in _on(bound) or _on(bound)["1b"] == []


def test_an_inferred_question_missing_its_first_part_does_not_feed_the_leaf_before(
    scheme_41: MarkScheme,
) -> None:
    # 4 and 4(a) both missed: 4a's writing follows 3c's with no label between them.
    stream = _cut(_without_number(scheme_41, "4"), drop=("4a",))
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert ("4a", "next_label_not_seen") in _unbound(bound)
    assert ("3c", "next_label_not_seen") in _unbound(bound)


def test_an_inferred_question_is_not_an_unseen_one(scheme_41: MarkScheme) -> None:
    # Question 4's number is missed and its (a) (b) (c) are all there, so 4 is
    # inferred. A stray "(c)" in question 3, which has no (c), is then not a label of
    # an unseen question standing in question 3's stretch: it costs the leaf whose
    # writing follows it and no other.
    scheme = _scheme(
        scheme_41,
        {
            "2": {},
            "3": {"3a": {}, "3b": {}},
            "4": {"4a": {}, "4b": {}, "4c": {}},
            "5": {"5a": {}},
        },
    )
    stream = ["2", "=2", "3", "(a)", "=3a", "(b)", "(c)", "=3b"]
    stream += ["(a)", "=4a", "(b)", "=4b", "(c)", "=4c", "5", "(a)", "=5a"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert bound.inferred_numbers == ["4"]
    assert _on(bound)["3a"] == ["3a"]
    assert ("3b", "after_unplaced_label") in _unbound(bound)


# --------------------------------------------------------------------------------------
# Rule 5: attachment
# --------------------------------------------------------------------------------------
def test_writing_before_the_first_label_is_unbound(scheme_41: MarkScheme) -> None:
    bound = bind_stream(_items("=name", *_clean(scheme_41)), scheme_41)
    assert _unbound(bound) == [("name", "before_first_label")]


def test_writing_after_a_container_label_is_unbound(scheme_41: MarkScheme) -> None:
    stream = _cut(_clean(scheme_41), after={"2": ["=graph"]})
    stream = _cut(stream, after={"=2a_iii": []})
    at = stream.index("=2a_iii") + 2  # after the (b) that follows 2a_iii
    stream[at:at] = ["=stem"]
    bound = bind_stream(_items(*stream), scheme_41)
    assert _unbound(bound) == [
        ("graph", "after_container_label"),
        ("stem", "after_container_label"),
    ]
    assert bound.unaligned_ids == []
    _own_or_absent(bound)


def test_writing_flagged_uncertain_is_unbound_whatever_the_target(scheme_41: MarkScheme) -> None:
    stream = _clean(scheme_41)
    items = _items(*stream)
    at = stream.index("=1b") + 1
    items[at:at] = [_w("note", placed_by="uncertain")]
    bound = bind_stream(items, scheme_41)
    assert _unbound(bound) == [("note", "uncertain")]
    assert _on(bound)["1b"] == ["1b"]


def test_several_blocks_of_writing_stay_on_the_leaf_they_follow(scheme_41: MarkScheme) -> None:
    stream = _cut(_clean(scheme_41), after={"=1a_i": ["=43", "=63"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert _on(bound)["1a_i"] == ["1a_i", "43", "63"]
    assert _on(bound)["1a_ii"] == ["1a_ii"]


def test_writing_at_the_top_of_a_page_before_any_label_is_marked(scheme_41: MarkScheme) -> None:
    stream = _clean(scheme_41)
    cut = stream.index("=6b") + 1
    items = [*_items(*stream[:cut], page=12), _w("LDR", page=13), *_items(*stream[cut:], page=13)]
    bound = bind_stream(items, scheme_41)
    leaf = next(leaf for leaf in bound.leaves if leaf.question_id == "6b")
    assert [w.answer for w in leaf.writings] == ["6b", "LDR"]
    assert leaf.doubts == ["continues from the previous page"]
    # Writing after a label of its own page carries no such doubt.
    assert all(other.doubts == [] for other in bound.leaves if other is not leaf)


def test_writing_tied_by_an_arrow_is_marked(scheme_41: MarkScheme) -> None:
    stream = _clean(scheme_41)
    items = _items(*stream)
    at = stream.index("=4b_i") + 1
    items[at:at] = [_w("so heat is transferred", placed_by="arrow")]
    bound = bind_stream(items, scheme_41)
    leaf = next(leaf for leaf in bound.leaves if leaf.question_id == "4b_i")
    assert leaf.doubts == ["tied by an arrow"]
    assert len(leaf.writings) == 2


def test_a_missed_label_does_not_hand_its_writing_to_the_leaf_before(
    scheme_41: MarkScheme,
) -> None:
    # The reader missed "(ii)" and still listed what was written under it. Nothing in
    # the list says where 1a_i's writing ends, so neither block is bound.
    stream = _cut(_clean(scheme_41), drop=("1a_ii",))
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert ("1a_i", "next_label_not_seen") in _unbound(bound)
    assert ("1a_ii", "next_label_not_seen") in _unbound(bound)
    # A leaf whose writing was set aside is not reported as a blank answer.
    assert {"1a_i", "1a_ii"} <= set(bound.unaligned_ids)
    assert _on(bound)["1b"] == ["1b"]


def test_two_blocks_beside_a_blank_leaf_are_not_bound(scheme_41: MarkScheme) -> None:
    # A label listed a little out of place leaves this trace: one leaf with nothing,
    # its neighbour with two blocks. Early: (i) (ii) writing writing.
    stream = _clean(scheme_41)
    at = stream.index("=1a_i")
    stream[at], stream[at + 1] = stream[at + 1], stream[at]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert {"1a_i", "1a_ii"} <= set(bound.unaligned_ids)
    assert [u for u in _unbound(bound) if u[1] == "neighbour_left_blank"] == [
        ("1a_i", "neighbour_left_blank"),
        ("1a_ii", "neighbour_left_blank"),
    ]
    assert _on(bound)["1b"] == ["1b"]
    # Late: (i) writing writing (ii).
    stream = _clean(scheme_41)
    at = stream.index("=1a_ii")
    stream[at - 1], stream[at] = stream[at], stream[at - 1]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert {"1a_i", "1a_ii"} <= set(bound.unaligned_ids)
    assert len([u for u in _unbound(bound) if u[1] == "neighbour_left_blank"]) == 2
    # Two blocks beside a leaf that has writing of its own are left alone.
    stream = _cut(_clean(scheme_41), after={"=1a_i": ["=more"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert _on(bound)["1a_i"] == ["1a_i", "more"]


def test_writing_under_a_label_with_no_place_unsettles_the_leaf_before(
    scheme_41: MarkScheme,
) -> None:
    # 1a's (ii) and (b) are missed and 1b's (i) is read as (l). What is left reads
    # (a) (i) w w (l) w (ii) w: the (ii) looks like the label after 1a_i, and it is
    # 1b's. The (l) with writing under it is the sign that something began there.
    scheme = _scheme(
        scheme_41,
        {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {"1b_i": {}, "1b_ii": {}}}, "2": {"2a": {}}},
    )
    stream = [
        "1",
        "(a)",
        "(i)",
        "=1a_i",
        "=1a_ii",
        "(l)",
        "=1b_i",
        "(ii)",
        "=1b_ii",
        "2",
        "(a)",
        "=2a",
    ]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"2a": ["2a"]}
    assert ("1a_i", "next_label_not_seen") in _unbound(bound)
    # A part label with no place and nothing written under it is only a stray.
    stream = _cut(_clean(scheme_41), after={"=1a_i": ["(l)"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.unaligned_ids == []
    assert _on(bound)["1a_i"] == ["1a_i"]


def test_known_limit_a_label_listed_out_of_place_beside_a_blank_leaf(
    scheme_41: MarkScheme,
) -> None:
    # The student answered 1(a)(i) and left 1(a)(ii) blank; the reader listed "(ii)"
    # before the writing of (i). The labels are in paper order and writing follows a
    # label: this is, item for item, the list of a script with (i) blank and (ii)
    # answered. Order cannot tell the two apart, so the writing lands on 1a_ii. Only a
    # check on what the writing says (the gate's G8) can catch it. This test pins the
    # limit; it does not approve of it.
    stream = [part for part in _clean(scheme_41) if part != "=1a_ii"]
    at = stream.index("=1a_i")
    stream[at], stream[at + 1] = stream[at + 1], stream[at]
    assert stream[2:6] == ["(i)", "(ii)", "=1a_i", "(b)"]
    bound = bind_stream(_items(*stream), scheme_41)
    assert _on(bound)["1a_ii"] == ["1a_i"]
    assert _on(bound)["1a_i"] == []


def test_the_last_leaf_of_the_paper_is_bracketed_by_the_end_of_the_list(
    scheme_41: MarkScheme,
) -> None:
    # Nothing is printed after 9c_iv, so nothing has to follow its writing.
    bound = bind_stream(_items(*_clean(scheme_41), "=a second block"), scheme_41)
    assert _on(bound)["9c_iv"] == ["9c_iv", "a second block"]
    # Any label listed after it is one the paper does not have there: a continuation
    # sheet, a stray. The same rule then applies and 9c_iv's writing is not bound.
    for extra in (["3", "(c)", "=more of 3c"], ["Q3 (c)", "=more of 3c"], ["(v)"], ["12"]):
        bound = bind_stream(_items(*_clean(scheme_41), *extra), scheme_41)
        _own_or_absent(bound)
        assert bound.unaligned_ids == ["9c_iv"], extra
        assert _unbound(bound)[0] == ("9c_iv", "next_label_not_seen"), extra
        assert _on(bound)["9c_iii"] == ["9c_iii"], extra
        assert _on(bound)["3c"] == ["3c"], extra
    # A label item whose text names no step is no label of the paper: it ends the
    # last leaf's answer and the leaf keeps what was written before it.
    bound = bind_stream(_items(*_clean(scheme_41), "[2]", "Total"), scheme_41)
    assert bound.unaligned_ids == []
    assert _unplaced(bound) == ["[2]", "Total"]
    assert _on(bound)["9c_iv"] == ["9c_iv"]


def test_a_leaf_with_only_a_stray_label_under_it_is_not_reported_blank(
    scheme_41: MarkScheme,
) -> None:
    # A reader that lists the circled option as a label ("1", "A", "2", "C") has
    # listed no writing at all. The questions were answered; they are not blank.
    scheme = _scheme(scheme_41, {str(n): {} for n in range(1, 5)})
    bound = bind_stream(_items("1", "A", "2", "C", "3", "4", "=4"), scheme)
    assert _on(bound) == {"3": [], "4": ["4"]}
    assert bound.unaligned_ids == ["1", "2"]
    assert _unplaced(bound) == ["A", "C"]


def test_writing_under_a_label_with_no_place_unsettles_the_leaf_after_it_too(
    scheme_41: MarkScheme,
) -> None:
    # 1a's (i) is read as (l), its (ii) and the (b) after it are missed. What is left
    # reads (a) (l) w w (i) w (ii) w: the (i) and (ii) are 1b's and look like 1a's. The
    # (l) has writing under it and the paper has no part between (a) and (a)(i).
    scheme = _scheme(
        scheme_41,
        {"1": {"1a": {"1a_i": {}, "1a_ii": {}}, "1b": {"1b_i": {}, "1b_ii": {}}}, "2": {"2a": {}}},
    )
    stream = ["1", "(a)", "(l)", "=1a_i", "=1a_ii", "(i)", "=1b_i", "(ii)", "=1b_ii"]
    bound = bind_stream(_items(*stream, "2", "(a)", "=2a"), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"2a": ["2a"]}
    # A misread (i) alone has a part to be: the (ii) after it keeps its writing.
    stream = ["1", "(a)", "(l)", "=1a_i", "(ii)", "=1a_ii", "(b)", "(i)", "=1b_i", "(ii)", "=1b_ii"]
    bound = bind_stream(_items(*stream, "2", "(a)", "=2a"), scheme)
    assert _on(bound) == {"1a_ii": ["1a_ii"], "1b_i": ["1b_i"], "1b_ii": ["1b_ii"], "2a": ["2a"]}


def test_a_part_label_listed_before_its_parent_unsettles_the_leaf_before(
    scheme_41: MarkScheme,
) -> None:
    # 8(c) and its (i) are missed, and a (c) is listed after (ii). The list reads
    # (b) w w (ii) (c) w (d): the (ii) before (c) shows that part (c) began before
    # its label did, so the second block under (b) may be (c)'s.
    stream = _clean(scheme_41)
    at = stream.index("=8b") + 1
    assert stream[at : at + 5] == ["(c)", "(i)", "=8c_i", "(ii)", "=8c_ii"]
    stream[at : at + 5] = ["=8c_i", "(ii)", "(c)", "=8c_ii"]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert ("8b", "next_label_not_seen") in _unbound(bound)
    assert _on(bound)["8a"] == ["8a"]
    assert _on(bound)["8d"] == ["8d"]


def test_known_limit_a_reader_that_lists_writing_before_its_label_shifts_the_paper(
    scheme_41: MarkScheme,
) -> None:
    # The whole module rests on one habit of the reader: a label comes before what is
    # written under it. If the reader lists every block before its label, each block
    # follows the label of the part above, and the paper is one part late: the failure
    # this fix exists for, with a new cause. The labels are clean, so nothing here can
    # see it. What is left to see: the first block of each group falls after a
    # container label, and the last leaf of the group is blank. This test pins the
    # limit; it does not approve of it.
    stream = _writing_first(_clean(scheme_41))
    bound = bind_stream(_items(*stream), scheme_41)
    on = _on(bound)
    assert on["1a_i"] == ["1a_ii"]
    assert on["1a_ii"] == ["1b"]
    assert on["1b"] == []
    assert ("1a_i", "after_container_label") in _unbound(bound)
    assert bound.unplaced_labels == []


def _writing_first(clean: list[str]) -> list[str]:
    """``clean`` as a reader lists it who puts each block before the label it is under."""
    stream: list[str] = []
    at = 0
    while at < len(clean):
        if at + 1 < len(clean) and clean[at + 1].startswith("="):
            stream += [clean[at + 1], clean[at]]
            at += 2
        else:
            stream.append(clean[at])
            at += 1
    return stream


def test_listing_suspects_name_every_group_of_the_known_limit_stream(
    scheme_41: MarkScheme,
) -> None:
    # Writing listed before its label: within each run of leaves that follows a
    # container label, the first block falls after the container and the last leaf is
    # blank. Every such run is named by the container that opens it.
    bound = bind_stream(_items(*_writing_first(_clean(scheme_41))), scheme_41)
    containers = [q.id for q in scheme_41.all_questions_flat() if q.parts]
    # A container followed straight by another container (1 then 1a) opens no run.
    opens_a_run = [q.id for q in scheme_41.all_questions_flat() if q.parts and not q.parts[0].parts]
    assert bound.listing_suspects == opens_a_run
    assert set(bound.listing_suspects) < set(containers)
    assert bound.listing_suspects[:5] == ["1a", "1c", "2a", "2b", "3"]


def test_listing_suspects_on_a_paper_with_no_parts(scheme_41: MarkScheme) -> None:
    scheme = _scheme(scheme_41, {str(n): {} for n in range(1, 6)})
    bound = bind_stream(_items(*_writing_first(_clean(scheme))), scheme)
    assert _unbound(bound) == [("1", "before_first_label")]
    assert _on(bound)["5"] == []
    # The run opens before any label; it is named by the first leaf listed in it.
    assert bound.listing_suspects == ["1"]


def test_a_clean_stream_has_no_listing_suspects(scheme_41: MarkScheme) -> None:
    assert bind_stream(_items(*_clean(scheme_41)), scheme_41).listing_suspects == []
    # A blank last leaf alone is no suspect, and neither is a note beside a number.
    stream = [part for part in _clean(scheme_41) if part not in ("=1c_ii", "=7c")]
    assert bind_stream(_items(*stream), scheme_41).listing_suspects == []
    stream = _cut(_clean(scheme_41), after={"2": ["=graph note"], "(c)": ["=stem note"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert [reason for _, reason in _unbound(bound)] == ["after_container_label"] * 2
    assert bound.listing_suspects == []
    # Both at once in one run is the trace: a block after "(c)" and 1c_ii blank.
    stream = [part for part in stream if part != "=1c_ii"]
    assert bind_stream(_items(*stream), scheme_41).listing_suspects == ["1c"]


def test_listing_suspects_change_no_binding(scheme_41: MarkScheme) -> None:
    stream = [part for part in _clean(scheme_41) if part != "=1c_ii"]
    plain = bind_stream(_items(*stream), scheme_41)
    noted = bind_stream(_items(*_cut(stream, after={"(c)": ["=stem note"]})), scheme_41)
    assert noted.listing_suspects == ["1c"]
    assert _on(noted) == _on(plain)
    assert noted.unaligned_ids == plain.unaligned_ids


def test_known_limit_a_label_that_names_the_wrong_part(scheme_41: MarkScheme) -> None:
    """A label read as a different valid label, while the real one is missed.

    9(c)(iii) is read as "(iv)" and the real "(iv)" is missed. The label says (iv) and
    two blocks follow it: item for item, a script whose (iii) label was missed with
    nothing written under it. No order-based rule can see it, so 9c_iii's writing is
    on 9c_iv.

    Measured on the five battery schemes with bare labels: a label read as the label
    listed beside it, and that label missed, puts writing on a wrong leaf in 226 of
    526 trials. Each of the two faults alone: 0 of 526. What can still catch it: the
    marker's check that an answer addresses its question (G8), and a second read that
    disagrees on the label.

    This test pins the limit; it does not approve of it.
    """
    stream = _clean(scheme_41)
    stream[stream.index("=9c_iii") - 1] = "(iv)"
    del stream[stream.index("=9c_iv") - 1]
    assert stream[-5:] == ["(ii)", "=9c_ii", "(iv)", "=9c_iii", "=9c_iv"]
    bound = bind_stream(_items(*stream), scheme_41)
    assert _on(bound)["9c_iv"] == ["9c_iii", "9c_iv"]
    assert ("9c_ii", "next_label_not_seen") in _unbound(bound)


def test_known_limit_a_question_number_that_names_the_wrong_question(
    scheme_41: MarkScheme,
) -> None:
    """The same limit on a paper with no parts: 3 read as 2, and the real 2 missed.

    The list reads 1, w, w, 2, w, 4: question 1 answered in two blocks, 2 answered, 3
    not listed. Question 2's writing is on question 1, and question 3's would be on 2
    if the unseen 3 did not leave question 2 unbracketed. With parts, a number read as
    its neighbour while the neighbour's own number is missed goes wrong in 90 of 150
    trials. This test pins the limit; it does not approve of it.
    """
    scheme = _scheme(scheme_41, {str(n): {} for n in range(1, 6)})
    bound = bind_stream(_items("1", "=1", "=2", "2", "=3", "4", "=4", "5", "=5"), scheme)
    assert _on(bound) == {"1": ["1", "2"], "4": ["4"], "5": ["5"]}
    assert ("3", "next_label_not_seen") in _unbound(bound)


# The independent review's wrong bindings that are ruled known limits: a gap in the
# list (several labels in a row, a page, pages out of order), found on its own
# generators. Each test pins the limit; it does not approve of it.
_GAP_SCHEME = {
    "1": {"1a": {}},
    "2": {
        "2a": {"2a_i": {}, "2a_ii": {}},
        "2b": {"2b_i": {}, "2b_ii": {}, "2b_iii": {}},
    },
    "3": {"3a": {}},
}


def test_known_limit_three_labels_in_a_row_missed(scheme_41: MarkScheme) -> None:
    """2(a)'s "(i)" and "(ii)" and the "(b)" after them are missed; the writing is listed.

    The "(i)" that follows is 2(b)'s. It stands under the last container label listed,
    "(a)", and it is the label the paper prints there: 2a_i takes 2b_i's writing. The
    bracket (D1) looks only at the label after a leaf, and that one, "(ii)", is the
    paper's next. Two blocks fall straight after the "(a)", which is what a stem with
    writing under it looks like on any script.

    Rate, on the independent review's generator over five schemes: k labels in a row
    missed and the writing kept, k from 1 to 6, puts writing on a wrong leaf in 100 of
    5,112 trials (bare labels 38 of 1,539; first part carries the number 41 of 1,251;
    mixed 21 of 1,203; full path on every leaf 0 of 1,119). None for one label; with
    bare labels none for two. It was 63 while the tail rule of class C was in.

    What can still see it: the marker's check that an answer addresses its question
    (G8); a second read that lists the labels (G9); the unaligned 2b leaves (G5).
    """
    scheme = _scheme(scheme_41, _GAP_SCHEME)
    stream = ["1", "(a)", "=1a", "2", "(a)", "=2a_i", "=2a_ii"]
    stream += ["(i)", "=2b_i", "(ii)", "=2b_ii", "(iii)", "=2b_iii", "3", "(a)", "=3a"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound)["2a_i"] == ["2b_i"]
    assert _reasons(bound) == {
        "2a_ii": "not_bracketed",
        "2b_i": "label_not_seen",
        "2b_ii": "label_not_seen",
        "2b_iii": "path_not_aligned",
    }


def test_known_limit_a_region_of_the_page_not_read(scheme_41: MarkScheme) -> None:
    """The same gap with the writing gone too: 2(a)'s parts and "(b)" are not in the list.

    Rate, same generator: 48 of 5,112 trials (bare labels 24, first part carries the
    number 20, mixed 4, full path on every leaf 0). What can still see it: as above.
    """
    scheme = _scheme(scheme_41, _GAP_SCHEME)
    stream = ["1", "(a)", "=1a", "2", "(a)"]
    stream += ["(i)", "=2b_i", "(ii)", "=2b_ii", "(iii)", "=2b_iii", "3", "(a)", "=3a"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound)["2a_i"] == ["2b_i"]


_PAGES_SCHEME = {
    "3": {"3a": {}, "3b": {}},
    "4": {
        "4a": {},
        "4b": {"4b_i": {}, "4b_ii": {}},
        "4c": {"4c_i": {}, "4c_ii": {}, "4c_iii": {}},
    },
    "5": {"5a": {}},
}


def test_known_limit_a_page_missing(scheme_41: MarkScheme) -> None:
    """The page that held 4(b)'s parts and "(c)" is not in the list.

    "(b)" closes one page and "(i) (ii) (iii)" of 4(c) open the next but one: the
    list reads as question 4 with its (b) answered, and 4b_i holds 4c_i's writing.

    Rate, on the review's generator (pages of 5, 8, 12 and 17 items, each page in
    turn, ten labellings, five schemes): 18 of 2,129 trials with no doubt on the leaf,
    15 with one. None where every leaf carries its full path.

    What can still see it: the page count of the reply against the scan (a page with
    no item); G8; G9.
    """
    scheme = _scheme(scheme_41, _PAGES_SCHEME)
    stream = ["3", "(a)", "=3a", "(b)", "=3b", "4", "(a)", "=4a", "(b)"]
    stream += ["(i)", "=4c_i", "(ii)", "=4c_ii", "(iii)", "=4c_iii", "5", "(a)", "=5a"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound)["4b_i"] == ["4c_i"]


def test_known_limit_two_pages_listed_in_the_other_order(scheme_41: MarkScheme) -> None:
    """Pages of five items; the page with 4(b)'s parts is listed before the one with "4".

    The same gap as a missing page: after "4 (a) (b)" comes the page with 4(c)'s
    parts, and 4b_i holds 4c_i's writing. The page listed early does no harm here:
    its writing is unbound.

    Rate, same generator, each pair of neighbouring pages in turn: 17 of 1,929 trials
    with no doubt on the leaf, 282 with one. None silent where every leaf carries its
    full path.

    What can still see it: page numbers out of order in the reply; G8; G9.
    """
    scheme = _scheme(scheme_41, _PAGES_SCHEME)
    stream = ["3", "(a)", "=3a", "(b)"]
    stream += ["(i)", "=4b_i", "(ii)", "=4b_ii", "(c)"]  # listed one page early
    stream += ["=3b", "4", "(a)", "=4a", "(b)"]
    stream += ["(i)", "=4c_i", "(ii)", "=4c_ii", "(iii)", "=4c_iii", "5", "(a)", "=5a"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound)["4b_i"] == ["4c_i"]
    assert "4b_i" not in [answer for answer, _ in _unbound(bound) if answer == "4c_i"]
    assert ("4b_i", "after_unplaced_label") in _unbound(bound)


def test_known_limit_two_labels_missed_where_the_first_part_carries_the_number(
    scheme_41: MarkScheme,
) -> None:
    """Class C is not closed: "(ii)" of 1(c) and the whole label "2(a)(i)" are missed.

    The paper is labelled as on separate sheets: the first part of each question
    carries the number. What is left of question 2 is "(ii) (iii) (b) (i) (ii) (c)".
    Its "(ii)" is the label the paper prints after 1c_i, and question 2 is inferred
    from "(b) (i) (ii) (c)": an inferred question is not an unseen one, so the first
    form of class C does not run. 1c_i holds three blocks, two of them not its own,
    and carries no doubt.

    Rate, given two labels in a row missed (the review's generator): 2 of 216 trials
    where the first part carries the number, 5 of 208 on mixed labels, 0 of 264 on
    bare labels. The random battery, which seldom draws two misses side by side, put
    it at 2 of 15,000.

    What can still see it: G8; G9; three blocks on one leaf where one is expected.
    """
    stream = ["1(a)(i)", "=1a_i", "(ii)", "=1a_ii", "(b)", "=1b", "(c)", "(i)", "=1c_i"]
    stream += ["=1c_ii", "=2a_i", "(ii)", "=2a_ii", "(iii)", "=2a_iii"]
    stream += ["(b)", "(i)", "=2b_i", "(ii)", "=2b_ii", "(c)", "=2c", "3(a)", "=3a"]
    bound = bind_stream(_items(*stream), scheme_41)
    assert bound.inferred_numbers == ["2"]
    assert _on(bound)["1c_i"] == ["1c_i", "1c_ii", "2a_i"]
    assert [leaf.doubts for leaf in bound.leaves if leaf.question_id == "1c_i"] == [[]]


def test_known_limit_numbered_lines_with_writing_and_a_number_missed(
    scheme_41: MarkScheme,
) -> None:
    """Question 1 is answered in three numbered lines, and the number 3 is missed.

    The reader lists "1." "2." "3." as labels, each with its line. "3." is then the
    only candidate for question 3 and earns its parts "(i) (ii)", so the line "2."
    before it beats the real "2" by the margin: question 2 holds the second line of
    question 1. D8 does not apply, because writing lies between the lines. With the
    number 3 in the list nothing is bound wrongly.

    Rate, on the review's generator: one to four numbered lines with writing under
    each leaf in turn, and each question number in turn missed, bare labels, five
    schemes: 9 of 12,604 trials.

    What can still see it: G8; G9; the prompt, which tells the reader that numbered
    lines inside one answer are not labels.
    """
    scheme = _scheme(scheme_41, {"1": {}, "2": {}, "3": {"3i": {}, "3ii": {}}, "4": {"4a": {}}})
    lines = ["1.", "=1 line 1", "2.", "=1 line 2", "3.", "=1 line 3"]
    rest = ["(i)", "=3i", "(ii)", "=3ii", "4", "(a)", "=4a"]
    bound = bind_stream(_items("1", *lines, "2", "=2", *rest), scheme)
    assert _on(bound)["2"] == ["1 line 2"]
    bound = bind_stream(_items("1", *lines, "2", "=2", "3", *rest), scheme)
    _own_or_absent(bound)


def test_known_limit_full_path_labels_listed_in_the_other_order(scheme_41: MarkScheme) -> None:
    """Two labels listed in each other's place across a question boundary; the writing stays.

    A listing-order fault, like the label out of place beside a blank leaf, on a
    paper where every label carries its full path. "2(a)(i)" is listed where
    "1(c)(ii)" stands: it is a well-formed start of question 2, 1(c)(ii)'s block
    follows it, and "1(c)(ii)" after it has no place. With bare labels the same
    move is caught (D10 or the bracket).

    Rate, on the review's generator: two neighbouring labels in each other's place,
    full path on every leaf, 27 of 194 trials, all 27 across a question boundary.
    With bare labels 0 of 264; where only the first part carries the number, 0 of 216.
    What can still see it: G8; G9.
    """
    stream = ["1(a)(i)", "=1a_i", "1(a)(ii)", "=1a_ii", "1(b)", "=1b", "1(c)(i)", "=1c_i"]
    stream += ["2(a)(i)", "=1c_ii", "1(c)(ii)", "=2a_i", "2(a)(ii)", "=2a_ii"]
    stream += ["2(a)(iii)", "=2a_iii", "2(b)(i)", "=2b_i", "2(b)(ii)", "=2b_ii", "2(c)", "=2c"]
    bound = bind_stream(_items(*stream, "3(a)", "=3a"), scheme_41)
    assert _on(bound)["2a_i"] == ["1c_ii"]
    assert _unplaced(bound) == ["1(c)(ii)"]


def test_known_limit_a_continuation_block_with_no_label(scheme_41: MarkScheme) -> None:
    """An answer continued elsewhere, its heading not listed: the block before it grows.

    More of 3(b)(ii) is written under 5(d) and the reader lists no label for it. It
    is a second block under "(d)", as two paragraphs of one answer are. Order cannot
    tell them apart. Where the heading is listed, whatever it says, the block is
    unbound (``test_a_label_item_whose_text_names_no_step_is_a_barrier``), and where
    the block opens a page the leaf carries "continues from the previous page".

    Rate, on the review's generator: the block lands on the leaf before it in 2,416
    of 2,784 placements with no doubt and in the other 368 with one; on a page of its
    own, in all 1,065 with the doubt. What can still see it: G8; G9.
    """
    stream = _cut(_clean(scheme_41), after={"=5d": ["=more of 3b_ii"]})
    bound = bind_stream(_items(*stream), scheme_41)
    assert _on(bound)["5d"] == ["5d", "more of 3b_ii"]
    assert bound.unbound == []


def test_two_labels_that_each_claim_sub_parts_unbind_the_part(scheme_41: MarkScheme) -> None:
    # 5(b) is read as "(c)", so the list has two (c)s, each followed by "(i)". Alone
    # that is a tie and neither is 5c. With 5c's own "(ii)" read as "(d)" as well, the
    # false (c) is followed by (i) (ii) and the true one by (i) only: the false one
    # aligns one part more. That does not say which is the real (c). The true one has
    # an "(i)" of its own that the best alignment leaves unbound, so there are two
    # places for part (c), and none of it is bound.
    scheme = _questions_4_to_6(scheme_41)
    stream = _clean(scheme)
    stream[stream.index("=5b_i") - 2] = "(c)"
    bound = bind_stream(_items(*stream), scheme)
    assert not [leaf for leaf in _on(bound) if leaf.startswith(("5b", "5c"))]  # the tie
    stream[stream.index("=5c_ii") - 1] = "(d)"
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert not [leaf for leaf in _on(bound) if leaf.startswith(("5b", "5c"))]
    assert _on(bound)["4c_iii"] == ["4c_iii"]
    assert _on(bound)["6a"] == ["6a"]


def test_a_second_label_for_a_part_that_claims_nothing_unbinds_nothing(
    scheme_41: MarkScheme,
) -> None:
    # A plain repeat, and strays that earn nothing of their own, cost what they cost
    # before and no more: the part and its sub-parts stay bound.
    scheme = _questions_4_to_6(scheme_41)
    clean = _clean(scheme)
    # "(c)" of question 4 seen again after its last sub-part: nothing follows it.
    bound = bind_stream(_items(*_cut(clean, after={"=4c_iii": ["(c)"]})), scheme)
    assert _on(bound)["4c_i"] == ["4c_i"]
    assert _on(bound)["4c_ii"] == ["4c_ii"]
    # A second "(b)" in question 4 after 4c's parts: it is a restart, and question 4
    # keeps what it had before it.
    bound = bind_stream(_items(*_cut(clean, after={"=4c_ii": ["(b)"]})), scheme)
    _own_or_absent(bound)
    assert _on(bound)["4b_i"] == ["4b_i"]
    assert _on(bound)["4b_ii"] == ["4b_ii"]


def test_known_gap_a_stray_takes_a_fourth_level_part_and_its_label_fills_a_missed_one(
    scheme_41: MarkScheme,
) -> None:
    """Fourth level only; found by the brief's own random battery on a new seed.

    A stray "(b)" between 7(a)(ii)(a) and its writing, and question 7's top-level
    "(b)" missed. The stray is taken for 7a_ii_b, and the real 7a_ii_b label, one
    line on, for the missed top-level (b), whose (i) and (ii) follow it: every label
    has a place and the alignment is unique. 7a_ii_a's writing is on 7a_ii_b. It has
    gone wrong since the first commit of this module. Rate: one trial in about
    800,000 random trials of two to four faults over all the seeds run, on the one
    battery scheme with a fourth level. Not ruled on.
    """
    scheme = _scheme(
        scheme_41,
        {
            "7": {
                "7a": {"7a_i": {}, "7a_ii": {"7a_ii_a": {}, "7a_ii_b": {}}},
                "7b": {"7b_i": {}, "7b_ii": {}},
                "7c": {},
            },
            "8": {"8a": {}},
        },
    )
    stream = _clean(scheme)
    stream[stream.index("=7a_ii_a") : stream.index("=7a_ii_a")] = ["(b)"]
    del stream[stream.index("=7b_i") - 2]
    assert stream[5:11] == ["(a)", "(b)", "=7a_ii_a", "(b)", "=7a_ii_b", "(i)"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound)["7a_ii_b"] == ["7a_ii_a"]


def _questions_4_to_6(template: MarkScheme) -> MarkScheme:
    return _scheme(
        template,
        {
            "4": {
                "4a": {},
                "4b": {"4b_i": {}, "4b_ii": {}},
                "4c": {"4c_i": {}, "4c_ii": {}, "4c_iii": {}},
            },
            "5": {
                "5a": {},
                "5b": {"5b_i": {}, "5b_ii": {}},
                "5c": {"5c_i": {}, "5c_ii": {}},
                "5d": {},
            },
            "6": {"6a": {}},
        },
    )


def test_two_numbers_that_each_claim_parts_unanchor_the_question(scheme_41: MarkScheme) -> None:
    # Question 5's number is read as 4. There are then two 4s, and each is followed by
    # parts of the right shape. Which earns more says nothing about which is the real
    # one: with question 4's own "(b)" missed, or a stray "(b)" cutting it short, the
    # false one earns more, and on points alone question 5's writing would land on
    # question 4's leaves. Neither is kept, whatever the margin.
    scheme = _questions_4_to_6(scheme_41)
    misread = _clean(scheme)
    misread[misread.index("5")] = "4"
    missed = list(misread)
    del missed[missed.index("(b)")]
    stray = _cut(misread, after={"=4b_i": ["(b)"]})
    for name, stream in (("misread alone", misread), ("(b) missed", missed), ("stray (b)", stray)):
        bound = bind_stream(_items(*stream), scheme)
        _own_or_absent(bound)
        assert _on(bound) == {"6a": ["6a"]}, name
        assert [label for label in _unplaced(bound) if label == "4"] == ["4", "4"], name


def test_a_true_number_claims_its_parts_however_little_it_earns(scheme_41: MarkScheme) -> None:
    # Two more streams of the same kind, from the battery. In each the true number is
    # followed by parts of its own that the false one, further on, cannot reach, and
    # that is enough to make it a rival.
    # The last question's number read as 8, and 8's own (a) missed: on points the true
    # 8 is best aligned to question 9's labels, past the false 8; its own stretch ends
    # at the false one, and there it still has (b) and (c).
    scheme = _scheme(
        scheme_41,
        {
            "7": {"7a": {}},
            "8": {"8a": {"8a_i": {}, "8a_ii": {}, "8a_iii": {}}, "8b": {}, "8c": {}},
            "9": {"9a": {"9a_i": {}, "9a_ii": {}, "9a_iii": {}}, "9b": {}},
        },
    )
    stream = _clean(scheme)
    stream[stream.index("9")] = "8"
    del stream[stream.index("=8a_i") - 2]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {}
    assert [label for label in _unplaced(bound) if label == "8"] == ["8", "8"]
    # Question 8's number read as 7, and 7's own (a) missed, on a question with a
    # fourth level: read as it will be, the true 7 is cut short at once (D5) and binds
    # nothing. Read on, it has parts, and that is what counts for a claim.
    scheme = _scheme(
        scheme_41,
        {
            "7": {
                "7a": {"7a_i": {}, "7a_ii": {"7a_ii_a": {}, "7a_ii_b": {}}},
                "7b": {"7b_i": {}, "7b_ii": {}},
                "7c": {},
            },
            "8": {"8a": {"8a_i": {}, "8a_ii": {}}, "8b": {}, "8c": {}},
            "9": {"9a": {}},
        },
    )
    stream = _clean(scheme)
    stream[stream.index("8")] = "7"
    del stream[stream.index("=7a_i") - 2]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"9a": ["9a"]}


def test_a_number_where_its_question_cannot_start_is_no_rival(scheme_41: MarkScheme) -> None:
    # C1b: a page number 2 at the head of the list, and "(a)" listed before "1". The
    # stray 2 is followed by a part nobody else binds, but it stands before question
    # 1's anchor, where question 2 cannot start. The real 2 stands.
    stream = _clean(scheme_41)
    stream[0:2] = ["2", "(a)", "1"]
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert _unplaced(bound)[:2] == ["2", "(a)"]
    assert [leaf for leaf in bound.unaligned_ids if leaf.startswith("2")] == []
    assert _on(bound)["2a_i"] == ["2a_i"]


def test_a_number_that_takes_its_parts_from_a_neighbour_claims_nothing(
    scheme_41: MarkScheme,
) -> None:
    # A second candidate counts against the real one only when it earns parts of its
    # own. A stray 2 straight after 1 can be followed by "(a) (i) (ii) …", but those are
    # question 1's labels and question 1 loses what the stray gains: it claims nothing,
    # and the real 2 stands. The same for a numbered line "2." inside question 1.
    for extra in ({"1": ["2"]}, {"=1a_i": ["2."]}, {"(i)": ["1.", "2."]}):
        stream = _cut(_clean(scheme_41), after=extra)
        bound = bind_stream(_items(*stream), scheme_41)
        _own_or_absent(bound)
        assert [leaf for leaf in bound.unaligned_ids if leaf.startswith("2")] == [], extra
        assert _on(bound)["2a_i"] == ["2a_i"], extra
        assert _on(bound)["2c"] == ["2c"], extra


def test_a_part_label_the_question_does_not_have_breaks_the_bracket(
    scheme_41: MarkScheme,
) -> None:
    # 6(b) and the whole first label of question 7 are missed ("7(a)" as one label:
    # one miss takes the number with it). The "(b)" that follows is 7's, and it is
    # exactly the label the paper prints after 6a. But a "(c)" comes after it: a part
    # question 6 does not have and question 7, which has no anchor, does. So question
    # 7's labels are in question 6's stretch of the list, and the "(b)" may be one of
    # them: 6a is not bracketed by it.
    scheme = _scheme(
        scheme_41,
        {"6": {"6a": {}, "6b": {}}, "7": {"7a": {}, "7b": {}, "7c": {}}, "8": {"8a": {}}},
    )
    for stream in (
        ["6(a)", "=6a", "=6b", "=7a", "(b)", "=7b", "(c)", "=7c", "8(a)", "=8a"],
        ["6", "(a)", "=6a", "=6b", "=7a", "(b)", "=7b", "(c)", "=7c", "8", "(a)", "=8a"],
    ):
        bound = bind_stream(_items(*stream), scheme)
        _own_or_absent(bound)
        assert _on(bound) == {"8a": ["8a"]}
        assert _unbound(bound)[0] == ("6a", "next_label_not_seen")
        assert _unplaced(bound) == ["(c)"]
    # Roman parts: 7(ii) and "8(a)(i)" missed; the "(ii)" is 8a's, and "(b)" shows it.
    scheme = _scheme(
        scheme_41,
        {
            "7": {"7i": {}, "7ii": {}},
            "8": {"8a": {"8a_i": {}, "8a_ii": {}}, "8b": {}},
            "9": {},
        },
    )
    stream = ["7(i)", "=7i", "=7ii", "=8a_i", "(ii)", "=8a_ii", "(b)", "=8b", "9", "=9"]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert _on(bound) == {"9": ["9"]}


def test_known_gap_a_later_label_stands_in_and_no_foreign_label_follows(
    scheme_41: MarkScheme,
) -> None:
    """What is left of class C after the foreign-label rule; not ruled on.

    5(b), the number 6 and 6(a) are missed (two misses where the label is "6(a)").
    The "(b)" that follows is 6's and is the label the paper prints after 5a_iii.
    Question 6 has no part that question 5 lacks, so no foreign label follows, and
    5a_iii keeps three blocks. What the list still shows: question 6 has no anchor
    and nothing separates question 5 from it. Rate: 2 of 15,000 random trials on
    the labelling where the first part carries the number; none on the other two.
    That battery seldom draws two misses side by side, and the gap is wider than
    this one stream: ``test_known_limit_two_labels_missed_where_the_first_part_carries_the_number``
    has the case where the unseen question is inferred, with its rate.
    """
    scheme = _scheme(
        scheme_41,
        {
            "5": {"5a": {"5a_i": {}, "5a_ii": {}, "5a_iii": {}}, "5b": {}},
            "6": {"6a": {}, "6b": {}},
            "7": {"7a": {}},
        },
    )
    stream = ["5(a)(i)", "=5a_i", "(ii)", "=5a_ii", "(iii)", "=5a_iii", "=5b", "=6a", "(b)", "=6b"]
    bound = bind_stream(_items(*stream, "7(a)", "=7a"), scheme)
    assert _on(bound)["5a_iii"] == ["5a_iii", "5b", "6a"]
    assert ("6b", "next_label_not_seen") in _unbound(bound)


def test_a_stray_part_label_breaks_no_bracket_when_the_next_question_has_its_anchor(
    scheme_41: MarkScheme,
) -> None:
    # The same "(c)" where question 7 has its number: it is no sign of question 7's
    # labels (they are under the 7), only a label with no place.
    scheme = _scheme(
        scheme_41,
        {"6": {"6a": {}, "6b": {}}, "7": {"7a": {}, "7b": {}, "7c": {}}, "8": {"8a": {}}},
    )
    stream = _cut(_clean(scheme), after={"=6a": ["(c)"]})
    bound = bind_stream(_items(*stream), scheme)
    assert bound.unaligned_ids == []
    assert _on(bound)["6a"] == ["6a"]
    assert _unplaced(bound) == ["(c)"]
    # The label that breaks a bracket is one after the leaf's next label. Question 7
    # is not in the list but for a "(c)" between 6's "(a)" and "(b)": the next label
    # of 6a and of 6b is past it, and both keep their writing.
    other = _scheme(
        scheme_41,
        {"6": {"6a": {}, "6b": {}, "6d": {}}, "7": {"7a": {}, "7b": {}, "7c": {}}, "8": {"8a": {}}},
    )
    stream = ["6", "(a)", "=6a", "(c)", "(b)", "=6b", "(d)", "=6d", "8", "(a)", "=8a"]
    bound = bind_stream(_items(*stream), other)
    _own_or_absent(bound)
    assert _on(bound) == {"6a": ["6a"], "6b": ["6b"], "8a": ["8a"]}
    assert ("6d", "next_label_not_seen") in _unbound(bound)
    # And a part label that the unanchored question does not have either says nothing
    # about it: 7's number missed (inferred from what follows), a stray "(z)" in 6.
    stream = _cut(_clean(scheme), after={"=6a": ["(z)"]})
    del stream[stream.index("7")]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound)["6a"] == ["6a"]
    assert bound.inferred_numbers == ["7"]


def test_a_missed_label_with_nothing_written_near_it_leaves_a_blank(scheme_41: MarkScheme) -> None:
    stream = _cut(_clean(scheme_41), drop=("1a_ii",))
    stream = [part for part in stream if part not in ("=1a_i", "=1a_ii")]
    bound = bind_stream(_items(*stream), scheme_41)
    assert _on(bound)["1a_i"] == []
    assert "1a_ii" in bound.unaligned_ids


def test_a_misread_label_unbinds_its_own_writing_and_the_leaf_before(scheme_41: MarkScheme) -> None:
    stream = _clean(scheme_41)
    stream[stream.index("=1a_ii") - 1] = "(11)"
    bound = bind_stream(_items(*stream), scheme_41)
    _own_or_absent(bound)
    assert _unplaced(bound) == ["(11)"]
    assert ("1a_ii", "after_unplaced_label") in _unbound(bound)
    assert ("1a_i", "next_label_not_seen") in _unbound(bound)
    assert _on(bound)["1b"] == ["1b"]


def test_a_leaf_whose_only_writing_is_unbound_is_not_reported_blank(scheme_41: MarkScheme) -> None:
    stream = _clean(scheme_41)
    items = _items(*stream)
    at = stream.index("=1b")
    items[at] = _w("1b", placed_by="uncertain")
    bound = bind_stream(items, scheme_41)
    assert "1b" in bound.unaligned_ids
    assert "1b" not in _on(bound)
    assert _unbound(bound) == [("1b", "uncertain")]


def test_the_last_leaf_keeps_its_writing_only_when_the_paper_ends_there(
    scheme_41: MarkScheme,
) -> None:
    bound = bind_stream(_items(*_Q1, *_Q2), scheme_41)
    _own_or_absent(bound)
    assert _on(bound)["2b_ii"] == ["2b_ii"]
    assert ("2c", "next_label_not_seen") in _unbound(bound)


def test_every_writing_item_is_accounted_for_once(scheme_41: MarkScheme) -> None:
    stream = _cut(
        _without_number(scheme_41, "4"), drop=("1a_ii", "6b"), after={"=2c": ["(z)", "=q"]}
    )
    items = _items("=cover", *stream)
    bound = bind_stream(items, scheme_41)
    seen = [w for leaf in bound.leaves for w in leaf.writings] + [u.writing for u in bound.unbound]
    listed = [item.answer for item in items if isinstance(item, SeenWriting)]
    assert sorted(w.answer for w in seen) == sorted(listed)


# --------------------------------------------------------------------------------------
# Scheme shapes the alignment cannot use
# --------------------------------------------------------------------------------------
def test_a_duplicated_leaf_id_is_never_bound_and_is_unaligned_once(scheme_41: MarkScheme) -> None:
    scheme = _scheme(
        scheme_41,
        [("1", {"1a": {}, "1b": {}}), ("2", {}), ("2", {}), ("3", {"3a": {}, "3b": {}})],
    )
    assert duplicate_leaf_ids(scheme) == ["2"]
    stream = ["1", "(a)", "=1a", "(b)", "=1b", "2", "=2", "3", "(a)", "=3a", "(b)", "=3b"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound) == {"1a": ["1a"], "1b": ["1b"], "3a": ["3a"], "3b": ["3b"]}
    assert bound.unaligned_ids == ["2"]
    assert _unbound(bound) == [("2", "after_unplaced_label")]
    # The label of the doubled id is still the paper's next label: a blank leaf before
    # it is a blank leaf, with nothing set aside.
    stream = ["1", "(a)", "=1a", "(b)", "2", "=2", "3", "(a)", "=3a", "(b)", "=3b"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound) == {"1a": ["1a"], "1b": [], "3a": ["3a"], "3b": ["3b"]}
    assert bound.unaligned_reasons == {"2": "duplicate_id"}


def test_the_leaf_before_an_id_no_label_can_name_says_why_it_is_not_bound(
    scheme_41: MarkScheme,
) -> None:
    # "1B" cannot be decomposed: no label names it, so nothing can show where 1a's
    # writing ends. 1a is never bound on this scheme, and the reason says which case.
    scheme = _scheme(scheme_41, {"1": {"1a": {}, "1B": {}, "1c": {}}, "2": {"2a": {}}})
    stream = ["1", "(a)", "=1a", "(B)", "=1B", "(c)", "=1c", "2", "(a)", "=2a"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound) == {"1c": ["1c"], "2a": ["2a"]}
    assert bound.unaligned_ids == ["1a", "1B"]
    assert _unbound(bound) == [("1a", "next_label_unreadable"), ("1B", "after_unplaced_label")]
    # The same when the unreadable id is the last of the paper.
    scheme = _scheme(scheme_41, {"1": {"1a": {}, "1B": {}}})
    bound = bind_stream(_items("1", "(a)", "=1a", "(B)", "=1B"), scheme)
    assert _unbound(bound) == [("1a", "next_label_unreadable"), ("1B", "after_unplaced_label")]
    # A label that really is missing keeps the other reason.
    scheme = _scheme(scheme_41, {"1": {"1a": {}, "1b": {}, "1B": {}, "1c": {}}, "2": {"2a": {}}})
    bound = bind_stream(_items("1", "(a)", "=1a", "(c)", "=1c", "2", "(a)", "=2a"), scheme)
    assert _unbound(bound) == [("1a", "next_label_not_seen")]


def test_a_duplicated_id_does_not_cost_the_leaf_before_it(scheme_41: MarkScheme) -> None:
    scheme = _scheme(
        scheme_41,
        [("1", {"1a": {}, "1b": {}}), ("2", {}), ("2", {}), ("3", {"3a": {}, "3b": {}})],
    )
    # One printed label for the doubled id: it is placed, binds nothing, and brackets 1b.
    stream = ["1", "(a)", "=1a", "(b)", "=1b", "2", "=2", "3", "(a)", "=3a", "(b)", "=3b"]
    bound = bind_stream(_items(*stream), scheme)
    assert _on(bound)["1b"] == ["1b"]
    assert _unplaced(bound) == ["2"]
    # Two labels for it, with writing between them: neither is the one, so the label
    # the paper prints after 1b was not seen, and 1b says so.
    stream = [
        "1",
        "(a)",
        "=1a",
        "(b)",
        "=1b",
        "2",
        "=2",
        "2",
        "=2",
        "3",
        "(a)",
        "=3a",
        "(b)",
        "=3b",
    ]
    bound = bind_stream(_items(*stream), scheme)
    _own_or_absent(bound)
    assert ("1b", "next_label_not_seen") in _unbound(bound)
    assert _on(bound)["1a"] == ["1a"]
    assert _on(bound)["3a"] == ["3a"]
    assert bound.unaligned_ids == ["1b", "2"]


def test_an_id_that_cannot_be_decomposed_costs_its_leaf_not_the_paper(
    scheme_41: MarkScheme,
) -> None:
    scheme = _scheme(
        scheme_41,
        {"1": {"1a": {"1a_i": {"1a_i_A": {}, "1a_i_B": {}}}, "1b": {}}, "2": {"2a": {}, "2b": {}}},
    )
    stream = [
        "1",
        "(a)",
        "(i)",
        "(A)",
        "=1a_i_A",
        "(B)",
        "=1a_i_B",
        "(b)",
        "=1b",
        "2",
        "(a)",
        "=2a",
        "(b)",
        "=2b",
    ]
    bound = bind_stream(_items(*stream), scheme)
    assert {"1a_i_A", "1a_i_B"} <= set(bound.unaligned_ids)
    assert _on(bound) == {"1b": ["1b"], "2a": ["2a"], "2b": ["2b"]}
    _own_or_absent(bound)
    # Even with no stream at all, the scheme does not raise.
    assert bind_stream([], scheme).leaves == []


# --------------------------------------------------------------------------------------
# Never raises, never runs long
# --------------------------------------------------------------------------------------
def test_a_list_longer_than_the_cap_is_not_read(scheme_41: MarkScheme) -> None:
    assert MAX_STREAM_ITEMS == 600
    clean = _items(*_clean(scheme_41))
    padding = _items(*["(z)"] * (MAX_STREAM_ITEMS + 1 - len(clean)))
    items = [*clean, *padding]
    assert len(items) == MAX_STREAM_ITEMS + 1
    bound = bind_stream(items, scheme_41)
    assert bound.leaves == []
    assert [u.writing for u in bound.unbound] == [i for i in items if isinstance(i, SeenWriting)]
    assert {u.reason for u in bound.unbound} == {"list_too_long"}
    assert bound.unplaced_labels == [i for i in items if isinstance(i, SeenLabel)]
    assert len(bound.unaligned_ids) == 43
    assert bound.unaligned_reasons == dict.fromkeys(bound.unaligned_ids, "list_too_long")
    assert bound.inferred_numbers == []
    assert bound.listing_suspects == []
    # One item fewer is read as any list is.
    bound = bind_stream(items[:-1], scheme_41)
    assert _on(bound)["1a_i"] == ["1a_i"]
    assert "list_too_long" not in bound.unaligned_reasons.values()


def test_a_scheme_nested_without_end_is_not_read(scheme_41: MarkScheme) -> None:
    leaf = scheme_41.all_questions_flat()[2]

    def nested(depth: int) -> MarkScheme:
        question = leaf.model_copy(update={"id": "deepest", "parts": []})
        for level in range(depth - 1, 0, -1):
            question = leaf.model_copy(update={"id": f"level{level}", "parts": [question]})
        return scheme_41.model_copy(update={"questions": [question]})

    scheme = nested(2000)
    items = _items("1", "(a)", "=written")
    bound = bind_stream(items, scheme)
    assert bound.leaves == []
    assert _unbound(bound) == [("written", "scheme_too_deep")]
    assert bound.unaligned_ids == ["deepest"]
    assert bound.unaligned_reasons == {"deepest": "scheme_too_deep"}
    assert duplicate_leaf_ids(scheme) == []
    # A scheme at the limit is read: its one leaf has an id no label can name.
    assert MAX_SCHEME_DEPTH == 12
    bound = bind_stream(items, nested(MAX_SCHEME_DEPTH))
    assert bound.unaligned_reasons == {"deepest": "undecomposable_id"}
    assert bind_stream(items, nested(MAX_SCHEME_DEPTH + 1)).unaligned_reasons == {
        "deepest": "scheme_too_deep"
    }


# --------------------------------------------------------------------------------------
# Why a leaf is unaligned
# --------------------------------------------------------------------------------------
def _reasons(bound: BoundStream) -> dict[str, str]:
    assert list(bound.unaligned_reasons) == bound.unaligned_ids
    assert set(bound.unaligned_reasons.values()) <= set(UNALIGNED_REASONS)
    return bound.unaligned_reasons


def test_an_aligned_paper_has_no_unaligned_reason(scheme_41: MarkScheme) -> None:
    assert _reasons(bind_stream(_items(*_clean(scheme_41)), scheme_41)) == {}
    assert len(UNALIGNED_REASONS) == len(set(UNALIGNED_REASONS)) == 14


def test_reasons_that_come_from_the_scheme(scheme_41: MarkScheme) -> None:
    scheme = _scheme(
        scheme_41,
        [("1", {"1a": {}, "1B": {}, "1c": {}}), ("2", {}), ("2", {}), ("3", {"3a": {}})],
    )
    stream = ["1", "(a)", "=1a", "(B)", "=1B", "(c)", "=1c", "2", "=2", "3", "(a)", "=3a"]
    assert _reasons(bind_stream(_items(*stream), scheme)) == {
        "1a": "next_label_unreadable",
        "1B": "undecomposable_id",
        "2": "duplicate_id",
    }


def test_reasons_that_come_from_the_question_number(scheme_41: MarkScheme) -> None:
    # The first question is never inferred: with its number missed nothing names it.
    bound = bind_stream(_items(*_clean(scheme_41)[1:]), scheme_41)
    reasons = _reasons(bound)
    assert {reasons[leaf] for leaf in reasons if leaf.startswith("1")} == {"number_not_seen"}
    assert len(reasons) == 5
    # Question 2's number read as 3: no label names 2, and two name 3.
    stream = _clean(scheme_41)
    stream[stream.index("2")] = "3"
    reasons = _reasons(bind_stream(_items(*stream), scheme_41))
    assert {reasons[leaf] for leaf in reasons if leaf.startswith("2")} == {"number_not_seen"}
    assert {reasons[leaf] for leaf in reasons if leaf.startswith("3")} == {"number_not_settled"}


def test_reasons_that_come_from_the_part_label(scheme_41: MarkScheme) -> None:
    # 1(a)(ii)'s label missed: it was not seen, and 1(a)(i) before it is not bracketed.
    stream = _cut(_clean(scheme_41), drop=("1a_ii",))
    assert _reasons(bind_stream(_items(*stream), scheme_41)) == {
        "1a_i": "not_bracketed",
        "1a_ii": "label_not_seen",
    }
    # 1(c)'s label missed: its (i) and (ii) are in the list, under a part with no place.
    stream = _clean(scheme_41)
    del stream[stream.index("=1c_i") - 2]
    reasons = _reasons(bind_stream(_items(*stream), scheme_41))
    assert reasons["1c_i"] == reasons["1c_ii"] == "path_not_aligned"
    # (i) seen again after its writing: two labels for one part.
    stream = _cut(_clean(scheme_41), after={"=1a_i": ["(i)", "=second"]})
    reasons = _reasons(bind_stream(_items(*stream), scheme_41))
    assert reasons["1a_i"] == "label_not_settled"


def test_reasons_that_come_from_the_writing(scheme_41: MarkScheme) -> None:
    # Two blocks beside a blank leaf.
    stream = _clean(scheme_41)
    at = stream.index("=1a_i")
    stream[at], stream[at + 1] = stream[at + 1], stream[at]
    reasons = _reasons(bind_stream(_items(*stream), scheme_41))
    assert reasons == {"1a_i": "neighbour_left_blank", "1a_ii": "neighbour_left_blank"}
    # The only block is marked uncertain.
    items = _items(*_clean(scheme_41))
    items[_clean(scheme_41).index("=1b")] = _w("1b", placed_by="uncertain")
    assert _reasons(bind_stream(items, scheme_41)) == {"1b": "writing_uncertain"}
    # A label with no place stands under the leaf, and the writing after it.
    stream = _cut(_clean(scheme_41), after={"(b)": ["continued"]})
    assert _reasons(bind_stream(_items(*stream), scheme_41)) == {"1b": "unplaced_label_follows"}


# Known defects in the extracted corpus schemes: (file name, duplicated leaf id).
_KNOWN_DUPLICATES = {
    ("0625_m19_ms_52.json", "4"),
    ("0625_m19_ms_62.json", "4"),
    ("0625_m20_ms_52.json", "4"),
    ("0625_s20_ms_53.json", "4"),
    ("0625_s20_ms_63.json", "4"),
    ("0625_s22_ms_51.json", "4"),
    ("0625_s20_ms_61.json", "3b_iii"),
}


def test_the_corpus_has_exactly_the_known_duplicated_leaf_ids() -> None:
    paths = sorted(_CORPUS.rglob("*.json"))
    assert len(paths) == 289
    found: set[tuple[str, str]] = set()
    for path in paths:
        scheme = _load(path)
        found |= {(path.name, leaf_id) for leaf_id in duplicate_leaf_ids(scheme)}
    assert found == _KNOWN_DUPLICATES
