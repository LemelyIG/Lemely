"""Decoding tests for the ciegt payload, against a captured real response.

The site is a SvelteKit app and its data route serves devalue: a flat pool where
a number *inside* an object or array is an index into the pool, and a number
*in* the pool is a literal value. Getting that distinction wrong yields
plausible-looking nonsense rather than an error, which is why it is pinned here
against a real captured payload rather than a hand-written one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.db.models.enums import SessionMonth
from lemely.io.ciegt import decode_devalue, parse_component, parse_session_label, rows_from_payload

FIXTURE = Path(__file__).parent / "fixtures" / "ciegt_0625.json"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("M/J 24", (SessionMonth.may_june, 2024)),
        ("O/N 23", (SessionMonth.oct_nov, 2023)),
        ("F/M 26", (SessionMonth.feb_mar, 2026)),
    ],
)
def test_session_labels_map_to_enum_and_year(
    label: str, expected: tuple[SessionMonth, int]
) -> None:
    assert parse_session_label(label) == expected


def test_an_unknown_session_label_raises_rather_than_guessing() -> None:
    with pytest.raises(ValueError, match="Unrecognised session label"):
        parse_session_label("Q4 24")


@pytest.mark.parametrize(("component", "expected"), [("11", (1, 1)), ("50", (5, 0)), ("1", (1, 0))])
def test_component_codes_split_into_paper_and_variant(
    component: str, expected: tuple[int, int]
) -> None:
    assert parse_component(component) == expected


def test_decode_finds_the_threshold_table() -> None:
    rows = decode_devalue(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert len(rows) > 500, "0625 has ~660 rows across ~50 sessions"
    assert {"session", "component", "max"} <= set(rows[0])


def test_rows_carry_raw_marks_and_drop_the_not_applicable_sentinel() -> None:
    """`-1` is how the payload encodes CAIE's en dash — "not available at this
    tier". It is an absence, not a threshold of minus one mark."""
    rows = rows_from_payload(json.loads(FIXTURE.read_text(encoding="utf-8")), "0625")
    core = next(
        r
        for r in rows
        if r.session_year == 2024
        and r.session_month is SessionMonth.may_june
        and (r.paper_number, r.paper_variant) == (1, 1)
    )
    assert "A" not in core.thresholds
    assert "B" not in core.thresholds
    assert core.thresholds["C"] == 27
    assert core.max_mark == 40


def test_zero_valued_thresholds_survive_the_decode_and_the_sentinel_filter() -> None:
    """0 is a real, if unusual, raw-mark threshold — only the payload's -1
    "not available at this tier" sentinel must be dropped. A later task treats
    a threshold at or below zero as its own fallback signal for rows it cannot
    verify against the official PDF; if this client silently dropped zeros
    upstream, that filter would become a no-op and the rows it exists to catch
    would be invisible. Do not "simplify" the filter in ciegt.py to
    `not in (None, 0, _NOT_APPLICABLE)` — it must stay `(None, _NOT_APPLICABLE)`.

    0625's captured fixture happens to carry no 0-mark rows (they cluster in
    0606 and 0580), so this is exercised against a small hand-built devalue
    payload instead: pool[0] is the root object, pool[1] is the table array,
    pool[2] is the one row (whose field values are indices into the pool),
    and pool[3:] are the literals those indices resolve to — a number
    *inside* a dict/list is an index, a number *in* the pool is a literal.
    """
    pool = [
        {"table": 1},  # 0: root
        [2],  # 1: table = [row]
        {"session": 3, "component": 4, "max": 5, "A": 6, "B": 7, "C": 8},  # 2: row
        "M/J 24",  # 3: session
        "11",  # 4: component
        40,  # 5: max
        0,  # 6: A threshold = 0 (a real, if unusual, mark)
        -1,  # 7: B threshold = not available at this tier
        27,  # 8: C threshold = 27
    ]
    payload = {"nodes": [{"type": "data", "data": pool}]}

    (row,) = rows_from_payload(payload, "0625")

    assert row.thresholds["A"] == 0
    assert "B" not in row.thresholds
    assert row.thresholds["C"] == 27


def test_source_url_points_at_the_official_document() -> None:
    rows = rows_from_payload(json.loads(FIXTURE.read_text(encoding="utf-8")), "0625")
    row = next(
        r for r in rows if r.session_year == 2024 and r.session_month is SessionMonth.may_june
    )
    assert row.source_url.endswith("0625_s24_gt.pdf")
