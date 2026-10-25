"""Printed numbered items under a part ("7(c)(ii) 1." / "2.") bind as that part."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.core.label_sequence import (
    BoundStream,
    _bind,
    bind_stream,
    collapse_numbered_items,
    numbered_item_groups,
)
from lemely.core.loose_schemas import MarkScheme
from lemely.io.prompts.label_binding import _printed_labels, build_label_binding_user_prompt
from tests.test_label_sequence import _items, _scheme

_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "mark-schemes"
_SCHEME_41 = _CORPUS / "0625_w24_ms_41.json"

_TREE = {
    "6": {"6a": {}},
    "7": {"7a": {}, "7c": {"7c_i": {}, "7c_ii": {"7c_ii_1": {}, "7c_ii_2": {}}}},
    "8": {"8a": {}},
}


@pytest.fixture(scope="module")
def template() -> MarkScheme:
    return MarkScheme.model_validate(json.loads(_SCHEME_41.read_text()))


@pytest.fixture
def grouped(template: MarkScheme) -> MarkScheme:
    return _scheme(template, _TREE)


def _writings(bound: BoundStream) -> dict[str, list[str]]:
    return {leaf.question_id: [w.answer for w in leaf.writings] for leaf in bound.leaves}


_BOTH = ["E = Pt", "I = P/V"]


def _assert_items_bound(bound: BoundStream) -> None:
    got = _writings(bound)
    assert got["7c_ii_1"] == _BOTH
    assert got["7c_ii_2"] == _BOTH
    assert got["8a"] == ["w"]
    assert "7c_ii" not in got
    assert "7c_ii_1" not in bound.unaligned_ids
    assert "undecomposable_id" not in bound.unaligned_reasons.values()


def test_groups_found(template: MarkScheme) -> None:
    assert numbered_item_groups(_scheme(template, _TREE)) == {"7c_ii": ["7c_ii_1", "7c_ii_2"]}
    for items in (
        {"7c_ii_1": {}},
        {"7c_ii_2": {}, "7c_ii_3": {}},
        {"7c_ii_1a": {}, "7c_ii_2a": {}},
    ):
        tree = {"7": {"7c": {"7c_ii": items}}}
        assert numbered_item_groups(_scheme(template, tree)) == {}


def test_items_bound_with_item_labels(grouped: MarkScheme) -> None:
    stream = _items(
        "6", "(a)", "=x", "7", "(a)", "=y", "(c)", "(i)", "=z",
        "(ii)", "1.", "=E = Pt", "2.", "=I = P/V", "8", "(a)", "=w",
    )  # fmt: skip
    _assert_items_bound(bind_stream(stream, grouped))


def test_items_bound_without_item_labels(grouped: MarkScheme) -> None:
    stream = _items(
        "6", "(a)", "=x", "7", "(a)", "=y", "(c)", "(i)", "=z",
        "(ii)", "=E = Pt", "=I = P/V", "8", "(a)", "=w",
    )  # fmt: skip
    _assert_items_bound(bind_stream(stream, grouped))


def test_items_bound_with_joined_labels(grouped: MarkScheme) -> None:
    stream = _items(
        "6", "(a)", "=x", "7", "(a)", "=y", "(c)", "(i)", "=z",
        "(ii) 1.", "=E = Pt", "2.", "=I = P/V", "8", "(a)", "=w",
    )  # fmt: skip
    _assert_items_bound(bind_stream(stream, grouped))
    full = _items(
        "6", "(a)", "=x", "7", "(a)", "=y", "(c)", "(i)", "=z",
        "7(c)(ii) 1", "=E = Pt", "2", "=I = P/V", "8", "(a)", "=w",
    )  # fmt: skip
    _assert_items_bound(bind_stream(full, grouped))


def test_a_real_next_question_is_never_taken_for_an_item(template: MarkScheme) -> None:
    scheme = _scheme(template, {"1": {"1a": {"1a_1": {}, "1a_2": {}}}, "2": {"2a": {}}})
    stream = _items("1", "(a)", "1.", "=E", "2", "(a)", "=next")
    bound = bind_stream(stream, scheme)
    got = _writings(bound)
    assert got["2a"] == ["next"]
    assert got["1a_1"] == got["1a_2"] == ["E"]


def test_reader_prompt_lists_the_part(grouped: MarkScheme, template: MarkScheme) -> None:
    assert ("7(c)(ii)", sum(p.marks for p in grouped.questions[1].parts[1].parts[1].parts)) in (
        _printed_labels(grouped)
    )
    prompt = build_label_binding_user_prompt(grouped, page_count=2)
    assert "7(c)(ii)" in prompt
    assert "7c_ii_1" not in prompt
    plain = MarkScheme.model_validate(json.loads(_SCHEME_41.read_text()))
    assert collapse_numbered_items(plain) is plain


def test_no_groups_identical(template: MarkScheme) -> None:
    stream = _items("1", "(a)", "(i)", "=x", "(ii)", "=y", "2", "(a)", "=z")
    assert numbered_item_groups(template) == {}
    assert bind_stream(stream, template) == _bind(stream, template)
    plain = _scheme(template, {"6": {"6a": {}}, "7": {"7a": {}, "7b": {}}})
    s2 = _items("6", "(a)", "=x", "7", "(a)", "=y", "(b)", "=z")
    assert bind_stream(s2, plain) == _bind(s2, plain)
