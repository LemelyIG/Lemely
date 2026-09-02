"""Parser tests against two real CAIE grade-threshold PDFs.

The two fixtures are the two layout eras. 2024 prints the option header as
"Option mark after A* A B C D E F G" with a maximum-mark column; 2019 prints
"Option A* A B C D E F G" without one. A parser that handles only the current
layout returns zero options for every older session and does so silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lemely.io.threshold_pdf import parse_threshold_pdf

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def s24() -> tuple[list, list]:
    return parse_threshold_pdf((FIXTURES / "0625_s24_gt.pdf").read_bytes())


@pytest.fixture(scope="module")
def s19() -> tuple[list, list]:
    return parse_threshold_pdf((FIXTURES / "0625_s19_gt.pdf").read_bytes())


def test_components_parse_with_their_raw_marks(s24: tuple[list, list]) -> None:
    components, _ = s24
    assert len(components) == 18
    p21 = next(c for c in components if (c.paper_number, c.paper_variant) == (2, 1))
    assert p21.max_mark == 40
    assert p21.thresholds == {"A": 24, "B": 21, "C": 18, "D": 16, "E": 15, "F": 14, "G": 13}


def test_a_core_component_omits_the_grades_marked_with_an_en_dash(s24: tuple[list, list]) -> None:
    """CAIE prints an en dash where a grade is not available at that tier. That
    is an absence, and must not become a threshold."""
    components, _ = s24
    p11 = next(c for c in components if (c.paper_number, c.paper_variant) == (1, 1))
    assert "A" not in p11.thresholds
    assert "B" not in p11.thresholds
    assert p11.thresholds["C"] == 27


def test_no_component_anywhere_carries_a_star(
    s24: tuple[list, list], s19: tuple[list, list]
) -> None:
    """The documents state it outright: "Grade A* does not exist at the level of
    an individual component." This is why an awarded single-paper grade tops out
    at A, and why A* lives only in the option table."""
    for components, _ in (s24, s19):
        assert all("A*" not in c.thresholds for c in components)


def test_options_carry_a_star_and_their_component_combination(s24: tuple[list, list]) -> None:
    _, options = s24
    bx = next(o for o in options if o.option_code == "BX")
    assert bx.component_numbers == [21, 41, 51]
    assert bx.max_mark_after_weighting == 200
    assert bx.thresholds["A*"] == 144
    assert bx.thresholds["G"] == 44


def test_the_older_layout_parses_without_a_maximum_mark_column(s19: tuple[list, list]) -> None:
    _, options = s19
    assert len(options) == 12
    bx = next(o for o in options if o.option_code == "BX")
    assert bx.max_mark_after_weighting is None
    assert bx.component_numbers == [21, 41, 51]
    assert bx.thresholds["A*"] == 130


def test_an_unparseable_document_yields_empty_lists_rather_than_raising() -> None:
    """Pre-2014 documents carry a watermark that bleeds into the text layer. The
    ingest stores those sessions unverified rather than failing the whole run."""
    assert parse_threshold_pdf(b"%PDF-1.4 not really a pdf") == ([], [])


def test_option_row_regex_does_not_match_a_component_line() -> None:
    """A component line starts with the word "Component", not a 1-3 letter
    option code, so the option-row regex must not match it even though both
    rows are dense sequences of numbers."""
    from lemely.io.threshold_pdf import _OPTION_ROW

    assert _OPTION_ROW.match("Component 11 40 – – 27 24 22 19 17") is None  # noqa: RUF001
