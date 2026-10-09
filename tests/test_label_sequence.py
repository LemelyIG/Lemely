"""Tests for the expected label sequence, label parsing and alignment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.core.binding import LabelMarker
from lemely.core.label_sequence import (
    LabelDecompositionError,
    LabelStep,
    align,
    expected_steps,
    parse_marker,
)
from lemely.core.loose_schemas import MarkScheme

_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "mark-schemes"
_SCHEME_41 = _CORPUS / "0625_w24_ms_41.json"


def _load(path: Path) -> MarkScheme:
    return MarkScheme.model_validate(json.loads(path.read_text()))


@pytest.fixture(scope="module")
def scheme_41() -> MarkScheme:
    return _load(_SCHEME_41)


def _markers(*texts: str, page: int = 1) -> list[LabelMarker]:
    """Markers on one page, top-to-bottom in the order given."""
    return [
        LabelMarker(page=page, top=100 * (k + 1), text=text, kind="printed")
        for k, text in enumerate(texts)
    ]


def _ids(aligned: list) -> list[str]:
    return [a.question_id for a in aligned]


# Every label of question 1 of the 0625 paper, in reading order.
_Q1 = ["1", "(a)", "(i)", "(ii)", "(b)", "(c)", "(i)", "(ii)"]
_Q1_LEAVES = ["1a_i", "1a_ii", "1b", "1c_i", "1c_ii"]


def test_expected_steps_for_the_0625_w24_41_scheme(scheme_41: MarkScheme) -> None:
    steps = expected_steps(scheme_41)
    assert steps[:8] == [
        (LabelStep("number", "1"), None),
        (LabelStep("letter", "a"), None),
        (LabelStep("roman", "i"), "1a_i"),
        (LabelStep("roman", "ii"), "1a_ii"),
        (LabelStep("letter", "b"), "1b"),
        (LabelStep("letter", "c"), None),
        (LabelStep("roman", "i"), "1c_i"),
        (LabelStep("roman", "ii"), "1c_ii"),
    ]
    assert sum(1 for _, leaf in steps if leaf is not None) == 43


@pytest.mark.parametrize(
    ("text", "expected"),
    [
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
        ("Question 4", [LabelStep("number", "4")]),
        ("1.", [LabelStep("number", "1")]),
        ("2", [LabelStep("number", "2")]),
        ("Fig. 1.2", []),
        ("[2]", []),
        ("", []),
        ("Total", []),
        ("(A)", []),
    ],
)
def test_parse_marker_table(text: str, expected: list[LabelStep]) -> None:
    assert parse_marker(text) == expected


@pytest.mark.parametrize("token", ["i", "v", "x"])
def test_roman_is_tried_before_letter(token: str) -> None:
    assert parse_marker(f"({token})") == [LabelStep("roman", token)]


def test_align_clean_stream_binds_every_leaf(scheme_41: MarkScheme) -> None:
    texts = [
        "1", "(a)", "(i)", "(ii)", "(b)", "(c)", "(i)", "(ii)",
        "2", "(a)", "(i)", "(ii)", "(iii)", "(b)", "(i)", "(ii)", "(c)",
    ]  # fmt: skip
    markers = _markers(*texts)
    aligned, unaligned, unmatched = align(markers, scheme_41)
    assert _ids(aligned) == [
        *_Q1_LEAVES, "2a_i", "2a_ii", "2a_iii", "2b_i", "2b_ii", "2c",
    ]  # fmt: skip
    assert unmatched == []
    assert "1a_i" not in unaligned
    assert unaligned[0] == "3a"
    first = aligned[0]
    assert (first.page, first.top, first.label_seen) == (1, 300, "(i)")


def test_numbered_lines_inside_a_leaf_do_not_consume_the_next_leaf(
    scheme_41: MarkScheme,
) -> None:
    # Q1(a)(i) "when 1. no weight ... 2. a weight of 5.6 N": the numbered
    # answer lines are not question 1 or question 2.
    markers = _markers("1", "(a)", "(i)", "1.", "2.", "(ii)", "(b)")
    aligned, unaligned, unmatched = align(markers, scheme_41)
    assert _ids(aligned) == ["1a_i", "1a_ii", "1b"]
    assert "1c_i" in unaligned
    assert [m.text for m in unmatched] == ["1.", "2."]


def test_a_real_next_question_number_is_not_mistaken_for_an_answer_line(
    scheme_41: MarkScheme,
) -> None:
    markers = _markers(*_Q1, "2", "(a)", "(i)", "(ii)")
    aligned, _, unmatched = align(markers, scheme_41)
    assert _ids(aligned) == [*_Q1_LEAVES, "2a_i", "2a_ii"]
    assert unmatched == []


def test_a_numbered_line_after_the_last_leaf_does_not_stand_in_for_the_next_question(
    scheme_41: MarkScheme,
) -> None:
    markers = _markers(*_Q1, "1.", "2.", "2", "(a)", "(i)")
    aligned, _, unmatched = align(markers, scheme_41)
    assert _ids(aligned) == [*_Q1_LEAVES, "2a_i"]
    assert [m.text for m in unmatched] == ["1.", "2."]


def test_a_missing_marker_costs_only_its_leaf(scheme_41: MarkScheme) -> None:
    texts = [t for k, t in enumerate(_Q1) if k != 3]  # drop the first "(ii)"
    aligned, unaligned, _ = align(_markers(*texts, "2", "(a)", "(i)"), scheme_41)
    assert _ids(aligned) == ["1a_i", "1b", "1c_i", "1c_ii", "2a_i"]
    assert "1a_ii" in unaligned


def test_an_invented_marker_is_returned_as_unmatched(scheme_41: MarkScheme) -> None:
    texts = ["1", "(a)", "(i)", "(ii)", "(e)", "(b)", "(c)", "(i)", "(ii)"]
    aligned, _, unmatched = align(_markers(*texts), scheme_41)
    assert _ids(aligned) == _Q1_LEAVES
    assert [m.text for m in unmatched] == ["(e)"]


def test_a_misread_marker_costs_only_its_own_leaf(scheme_41: MarkScheme) -> None:
    # "(i)" read as "(l)" and as "(1)", and a stray "[2]" marks bracket.
    markers = _markers("1", "(a)", "(l)", "(ii)", "(b)", "[2]", "(c)", "(1)", "(ii)")
    aligned, unaligned, unmatched = align(markers, scheme_41)
    assert _ids(aligned) == ["1a_ii", "1b", "1c_ii"]
    assert {"1a_i", "1c_i"} <= set(unaligned)
    assert sorted(m.text for m in unmatched) == ["(1)", "(l)", "[2]"]


def test_a_label_read_twice_aligns_once(scheme_41: MarkScheme) -> None:
    aligned, _, unmatched = align(_markers("1", "(a)", "(i)", "(i)", "(ii)", "(b)"), scheme_41)
    assert _ids(aligned) == ["1a_i", "1a_ii", "1b"]
    assert len(unmatched) == 1


def test_leaf_needs_its_whole_path(scheme_41: MarkScheme) -> None:
    # (ii) with no "(a)" before it must not become 1a_ii.
    aligned, unaligned, unmatched = align(_markers("1", "(ii)"), scheme_41)
    assert aligned == []
    assert "1a_ii" in unaligned
    assert len(unmatched) == 2
    # Nor does a lone "(ii)" with nothing at all before it.
    aligned, _, unmatched = align(_markers("(ii)"), scheme_41)
    assert aligned == []
    assert [m.text for m in unmatched] == ["(ii)"]


def test_question_number_printed_on_an_earlier_page_carries_down(
    scheme_41: MarkScheme,
) -> None:
    markers = [
        LabelMarker(page=1, top=900, text="1", kind="printed"),
        LabelMarker(page=1, top=950, text="(a)", kind="printed"),
        LabelMarker(page=2, top=80, text="(i)", kind="printed"),
        LabelMarker(page=2, top=400, text="(ii)", kind="printed"),
    ]
    aligned, _, _ = align(markers, scheme_41)
    assert _ids(aligned) == ["1a_i", "1a_ii"]
    assert [a.page for a in aligned] == [2, 2]


def test_markers_are_ordered_by_page_then_top(scheme_41: MarkScheme) -> None:
    markers = [
        LabelMarker(page=2, top=50, text="(ii)", kind="printed"),
        LabelMarker(page=1, top=300, text="(i)", kind="printed"),
        LabelMarker(page=1, top=100, text="1", kind="printed"),
        LabelMarker(page=1, top=200, text="(a)", kind="printed"),
    ]
    aligned, _, _ = align(markers, scheme_41)
    assert _ids(aligned) == ["1a_i", "1a_ii"]


def _scheme(template: MarkScheme, tree: dict) -> MarkScheme:
    """A scheme with the given ``{id: {child id: ...}}`` shape, built from a real one."""
    leaf = template.all_questions_flat()[2]  # 1a_i, a leaf

    def build(spec: dict) -> list:
        return [
            leaf.model_copy(update={"id": qid, "parts": build(children)})
            for qid, children in spec.items()
        ]

    return template.model_copy(update={"questions": build(tree)})


def test_i_is_a_letter_when_the_paper_says_so(scheme_41: MarkScheme) -> None:
    # Letters a..i under one number: "(i)" follows "(h)" and is a letter there.
    letters = "abcdefghi"
    scheme = _scheme(scheme_41, {"1": {f"1{c}": {} for c in letters}})
    texts = ["1", *(f"({c})" for c in letters)]
    aligned, _, unmatched = align(_markers(*texts), scheme)
    assert _ids(aligned) == [f"1{c}" for c in letters]
    assert unmatched == []
    assert [s.level for s, _ in expected_steps(scheme)][-1] == "letter"


def test_roman_directly_under_a_number_and_a_letter_under_a_roman(
    scheme_41: MarkScheme,
) -> None:
    scheme = _scheme(
        scheme_41,
        {
            "7": {"7a": {"7a_i": {"7a_i_a": {}, "7a_i_b": {}}, "7a_ii": {}}},
            "8": {"8i": {}, "8ii": {}},
        },
    )
    levels = [(s.level, s.token) for s, _ in expected_steps(scheme)]
    assert levels == [
        ("number", "7"), ("letter", "a"), ("roman", "i"), ("letter", "a"), ("letter", "b"),
        ("roman", "ii"), ("number", "8"), ("roman", "i"), ("roman", "ii"),
    ]  # fmt: skip
    texts = ["7", "(a)", "(i)", "(a)", "(b)", "(ii)", "8", "(i)", "(ii)"]
    aligned, _, _ = align(_markers(*texts), scheme)
    assert _ids(aligned) == ["7a_i_a", "7a_i_b", "7a_ii", "8i", "8ii"]


def test_an_id_that_cannot_be_decomposed_raises(scheme_41: MarkScheme) -> None:
    with pytest.raises(LabelDecompositionError, match="1a_x1"):
        expected_steps(_scheme(scheme_41, {"1": {"1a": {"1a_x1": {}}}}))
    with pytest.raises(LabelDecompositionError, match="2a"):
        expected_steps(_scheme(scheme_41, {"1": {"2a": {}}}))


def test_no_markers_leaves_every_leaf_unaligned(scheme_41: MarkScheme) -> None:
    aligned, unaligned, unmatched = align([], scheme_41)
    assert (aligned, unmatched) == ([], [])
    assert len(unaligned) == 43


def test_expected_steps_decompose_every_corpus_scheme() -> None:
    paths = sorted(_CORPUS.rglob("*.json"))
    checked = 0
    failures: list[str] = []
    for path in paths:
        try:
            scheme = MarkScheme.model_validate(json.loads(path.read_text()))
        except ValueError:
            continue
        checked += 1
        leaves = [q.id for q in scheme.all_questions_flat() if not q.parts]
        try:
            steps = expected_steps(scheme)
        except LabelDecompositionError as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        completed = [leaf for _, leaf in steps if leaf is not None]
        if sorted(completed) != sorted(leaves) or len(set(completed)) != len(completed):
            failures.append(f"{path.name}: leaf-completing steps do not match the leaves")
    assert checked > 0
    assert not failures, f"{len(failures)} of {checked} schemes: {failures[:3]}"
