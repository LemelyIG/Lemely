"""Expected shape and expected numeric values of a mark scheme leaf."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lemely.core.binding_expect import (
    answer_shape,
    expected_numeric_values,
    expected_shape,
    matches_expected,
)
from lemely.core.loose_schemas import MarkScheme, Question

CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "mark-schemes"


def _leaves(scheme: MarkScheme) -> dict[str, Question]:
    return {q.id: q for q in scheme.all_questions_flat() if not q.parts and q.marks > 0}


@pytest.fixture(scope="module")
def leaves() -> dict[str, Question]:
    with (CORPUS / "0625_w24_ms_41.json").open() as handle:
        return _leaves(MarkScheme.model_validate(json.load(handle)))


def _question(points: list[dict[str, Any]], **extra: Any) -> Question:
    return Question.model_validate(
        {
            "id": "1",
            "marks": 2,
            "type": "recall",
            "answer_points": [{"id": f"p{i}", "marks": 1, **p} for i, p in enumerate(points)],
            **extra,
        }
    )


def test_expected_values_table_for_0625_w24_41(leaves: dict[str, Question]) -> None:
    table = {
        "1a_i": ["43", "63"],
        "1a_ii": ["20"],
        "1b": ["0.28"],
        "1c_i": ["4.9"],
        "1c_ii": ["3.2"],
        "2a_i": ["1.8e5"],
        "2a_iii": ["420"],
        "3b_ii": ["2.2e7"],
        "2a_ii": [],
        "8d": ["17000"],
        "9b": ["9.5e17"],
        "9c_iv": ["4.5e17"],
        "8a": [],
        "5b": [],
    }
    assert {key: expected_numeric_values(leaves[key]) for key in table} == table


def test_method_points_are_not_expected_values() -> None:
    method = _question([{"point": "k = F / x OR (k =) F / x OR 5.6 / 20", "math_mark_type": "C"}])
    assert expected_numeric_values(method) == []
    mixed = _question(
        [
            {"point": "6 OR 7", "math_mark_type": "M"},
            {"point": "12 N", "math_mark_type": "A"},
        ]
    )
    assert expected_numeric_values(mixed) == ["12"]


def test_calculated_answer_is_used_when_set() -> None:
    question = _question(
        [
            {
                "point": "see value",
                "math_mark_type": "A",
                "calculated_answer": {"value": 180000.0, "unit": "kg m/s"},
            }
        ]
    )
    assert expected_numeric_values(question) == ["180000"]


def test_product_is_not_mistaken_for_standard_form() -> None:
    question = _question([{"point": "2 \u00d7 1000 N", "math_mark_type": "A"}])
    assert expected_numeric_values(question) == []


def test_matches_expected_accepts_rounding(leaves: dict[str, Question]) -> None:
    assert matches_expected("180,000kg m/s", leaves["2a_i"])
    assert matches_expected("1.8 x 10^5 kg m/s", leaves["2a_i"])
    assert matches_expected("1. 43cm 2. 63cm", leaves["1a_i"])
    assert matches_expected("3.25 m/s²", leaves["1c_ii"])  # plain decimal, within 2%
    # 0.6% away from 420, still no match: an integer needs an exact value.
    assert not matches_expected("422.5 m", leaves["2a_iii"])
    assert matches_expected("420 m", leaves["2a_iii"])


def test_matches_expected_rejects_neighbours_and_unreadable(leaves: dict[str, Question]) -> None:
    assert not matches_expected("20cm", leaves["1a_i"])  # a neighbour's value
    assert not matches_expected("13m/s²", leaves["1c_ii"])
    assert not matches_expected("area under the graph line.", leaves["2a_iii"])
    assert not matches_expected("44000000 N/m", leaves["2a_ii"])  # nothing expected
    assert not matches_expected("1.7 x 10^5 kg m/s", leaves["2a_i"])


@pytest.mark.parametrize(
    ("answer", "shape"),
    [
        ("1. 43cm 2. 63cm", "number"),
        ("20cm", "number"),
        ("0.28 N/cm", "number"),
        ("4.9 N", "number"),
        ("13m/s²", "number"),
        ("180,000kg m/s", "number"),
        ("422.5 m", "number"),
        ("44000000 N/m", "number"),
        ("1700 Hz", "number"),
        ("9.5 x 10^17 km", "number"),
        ("4.5 x 10^17 s", "number"),
        ("the force is 4.9 N", "number"),
        ("area under the graph line.", "text"),
        ("iron", "text"),
        ("curved lines from N to S pole, denser at poles", "text"),
        ("the speed went up to 5 because the car was driven faster than before", "text"),
        ("[drawn field lines around bar magnet]", "drawing"),
        ("see diagram", "drawing"),
        ("field lines from N to S", "drawing"),
    ],
)
def test_answer_shape_table(answer: str, shape: str) -> None:
    assert answer_shape(answer) == shape


def test_expected_shape_table(leaves: dict[str, Question]) -> None:
    table = {
        "1a_i": "number",
        "2a_iii": "number",
        "2a_ii": "text",
        "7a": "text",
        "8c_i": "text",
        "8a": "unknown",
        "3c": "unknown",
    }
    assert {key: expected_shape(leaves[key]) for key in table} == table
    drawing = _question(
        [{"point": "one field line", "math_mark_type": "B"}],
        drawing_criteria=[
            {"id": "d1", "criterion": "outline", "requirement": "closed shape", "marks": 1}
        ],
    )
    assert expected_shape(drawing) == "drawing"
    plot = _question(
        [{"point": "5 N", "math_mark_type": "B"}],
        plot_requirements=[{"id": "r1", "requirement": "points plotted", "marks": 1}],
    )
    assert expected_shape(plot) == "drawing"


def test_expected_values_never_raise_on_any_corpus_leaf() -> None:
    schemes = leaves_total = non_mcq = with_values = skipped = 0
    for path in sorted(CORPUS.rglob("*.json")):
        try:
            with path.open() as handle:
                scheme = MarkScheme.model_validate(json.load(handle))
        except (ValueError, OSError):  # not every JSON file is a scheme
            skipped += 1
            continue
        schemes += 1
        for leaf in _leaves(scheme).values():
            leaves_total += 1
            expected_shape(leaf)
            values = expected_numeric_values(leaf)
            if leaf.mcq_answer is None:
                non_mcq += 1
                with_values += bool(values)
    share = with_values / non_mcq if non_mcq else 0.0
    print(  # noqa: T201
        f"corpus: {schemes} schemes ({skipped} skipped), {leaves_total} leaves, "
        f"{non_mcq} non-MCQ, {with_values} with expected values ({share:.1%})"
    )
    assert schemes > 0


@pytest.mark.parametrize(
    ("point", "values"),
    [
        ("1220", ["1220"]),
        ("\u221214", ["-14"]),
        ("0.047", ["0.047"]),
        ("2.76 \u00d7 106", ["2.76e6"]),
        ("4100000 oe", ["4100000"]),
        ("3.2(0)", ["3.2"]),
        ("64.5 cm cao", ["64.5"]),
        ("467.42 OR 467.4", ["467.42", "467.4"]),
    ],
)
def test_untyped_bare_value_points_are_expected_values(point: str, values: list[str]) -> None:
    assert expected_numeric_values(_question([{"point": point}])) == values
    assert expected_shape(_question([{"point": point}])) == "number"


@pytest.mark.parametrize(
    "point",
    [
        "1, 2, 3, 4, 6, 12",
        "4.15, 4.25",
        "5.6 / 20",
        "x = 3",
        "area under the line",
        "2 + 3",
        "3 and 5",
        "3\n5",
        "2 pairs of equal angles oe",
        "2 \u00d7 1000",
    ],
)
def test_untyped_lists_and_expressions_are_not_expected_values(point: str) -> None:
    assert expected_numeric_values(_question([{"point": point}])) == []


def test_typed_method_points_still_excluded() -> None:
    for mark in ("C", "M"):
        assert expected_numeric_values(_question([{"point": "1220", "math_mark_type": mark}])) == []
    # a typed A point keeps its permissive reading (list-free, units allowed)
    assert expected_numeric_values(_question([{"point": "12 N", "math_mark_type": "A"}])) == ["12"]
