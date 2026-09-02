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


@pytest.fixture(scope="module")
def s11() -> tuple[list, list]:
    """0580 s11: 2011-era layout. Grade cells use the literal string "N/A"
    (not a dash) for "not applicable at this tier", and the component-table
    header wraps onto its own lines rather than sharing one line with the
    grade letters. A parser that raises on "N/A" or only recognises the
    single-line header aborts the whole ingest run on this document."""
    return parse_threshold_pdf((FIXTURES / "0580_s11_gt.pdf").read_bytes())


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


def test_option_row_parser_does_not_match_a_component_line() -> None:
    """A component line starts with the word "Component", not a 1-3 letter
    option code, so the option-row parser must not match it even though both
    rows are dense sequences of numbers."""
    from lemely.io.threshold_pdf import _parse_option_row

    grades = ["A*", "A", "B", "C", "D", "E", "F", "G"]
    line = "Component 11 40 – – 27 24 22 19 17"  # noqa: RUF001
    assert _parse_option_row(line, grades, has_max_mark_column=False) is None
    assert _parse_option_row(line, grades, has_max_mark_column=True) is None


# The four option-row shapes: old/new layout era crossed with single/multi
# component. Each is a synthetic line, not a new PDF fixture -- the fixtures
# happen to contain no single-component option, which is exactly why the
# earlier regex-based parser's ambiguity went unnoticed.
_GRADES_8 = ["A*", "A", "B", "C", "D", "E", "F", "G"]


def test_old_era_single_component_option_row() -> None:
    """No max-mark column, one component: nothing disambiguates the leading
    number from a max mark except knowing, from the header, that this table
    has no max-mark column at all."""
    from lemely.io.threshold_pdf import _parse_option_row

    option = _parse_option_row(
        "AX 40 130 106 84 62 50 38 26 14", _GRADES_8, has_max_mark_column=False
    )
    assert option is not None
    assert option.option_code == "AX"
    assert option.component_numbers == [40]
    assert option.max_mark_after_weighting is None
    assert option.thresholds == {
        "A*": 130,
        "A": 106,
        "B": 84,
        "C": 62,
        "D": 50,
        "E": 38,
        "F": 26,
        "G": 14,
    }


def test_old_era_multi_component_option_row() -> None:
    from lemely.io.threshold_pdf import _parse_option_row

    option = _parse_option_row(
        "BX 21, 41, 51 130 106 84 62 50 38 26 14", _GRADES_8, has_max_mark_column=False
    )
    assert option is not None
    assert option.option_code == "BX"
    assert option.component_numbers == [21, 41, 51]
    assert option.max_mark_after_weighting is None
    assert option.thresholds["A*"] == 130
    assert option.thresholds["G"] == 14


def test_new_era_single_component_option_row() -> None:
    from lemely.io.threshold_pdf import _parse_option_row

    option = _parse_option_row(
        "AX 200 40 144 119 94 70 63 56 50 44", _GRADES_8, has_max_mark_column=True
    )
    assert option is not None
    assert option.option_code == "AX"
    assert option.component_numbers == [40]
    assert option.max_mark_after_weighting == 200
    assert option.thresholds["A*"] == 144
    assert option.thresholds["G"] == 44


def test_new_era_multi_component_option_row() -> None:
    from lemely.io.threshold_pdf import _parse_option_row

    option = _parse_option_row(
        "BX 200 21, 41, 51 144 119 94 70 63 56 50 44", _GRADES_8, has_max_mark_column=True
    )
    assert option is not None
    assert option.option_code == "BX"
    assert option.component_numbers == [21, 41, 51]
    assert option.max_mark_after_weighting == 200
    assert option.thresholds["A*"] == 144
    assert option.thresholds["G"] == 44


@pytest.mark.parametrize(
    "component_field",
    ["21, 41, 51", "21,41,51", "21,41, 51"],
    ids=["spaced", "unspaced", "mixed-spacing"],
)
def test_component_list_comma_spacing_is_immaterial(component_field: str) -> None:
    """CAIE is not consistent about the space after a comma in the component
    list. `component_numbers` must come out identical regardless."""
    from lemely.io.threshold_pdf import _parse_option_row

    line = f"BX {component_field} 130 106 84 62 50 38 26 14"
    option = _parse_option_row(line, _GRADES_8, has_max_mark_column=False)
    assert option is not None
    assert option.component_numbers == [21, 41, 51]
    assert option.max_mark_after_weighting is None
    assert option.thresholds["A*"] == 130


def test_a_too_short_option_row_is_dropped_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A row that matches the leading option-code pattern but does not carry
    enough tokens for the active header must not disappear silently."""
    from lemely.io.threshold_pdf import _parse_option_row

    with caplog.at_level("WARNING", logger="lemely.io.threshold_pdf"):
        option = _parse_option_row("AX 40 130 106 84", _GRADES_8, has_max_mark_column=False)
    assert option is None
    assert any("skipping" in record.message for record in caplog.records)


def test_the_2011_era_document_parses_without_raising(s11: tuple[list, list]) -> None:
    """The bug this guards against: 2011-era documents use "N/A" instead of a
    dash, and previously `int("N/A")` propagated a ValueError out of the
    parser and aborted the whole ingest run -- 0625 was never even reached."""
    components, options = s11
    assert len(components) == 12
    assert len(options) == 6

    p11 = next(c for c in components if (c.paper_number, c.paper_variant) == (1, 1))
    assert p11.max_mark == 56
    assert p11.thresholds == {"C": 33, "E": 21, "F": 14}

    ax = next(o for o in options if o.option_code == "AX")
    assert ax.component_numbers == [11, 31]
    assert ax.max_mark_after_weighting is None


def test_n_slash_a_cell_is_omitted_not_stored_as_zero_or_string(
    s11: tuple[list, list],
) -> None:
    """ "N/A" means "not available at this tier", exactly like a dash. It must
    be absent from the thresholds dict, not coerced to 0 and not left as the
    literal string."""
    components, _ = s11
    p11 = next(c for c in components if (c.paper_number, c.paper_variant) == (1, 1))
    assert "A" not in p11.thresholds
    assert "B" not in p11.thresholds
    assert 0 not in p11.thresholds.values()
    assert all(isinstance(v, int) for v in p11.thresholds.values())


@pytest.mark.parametrize("marker", ["N/A", "n/a", "N/a"])
def test_grade_value_recognises_n_slash_a_case_insensitively(marker: str) -> None:
    from lemely.io.threshold_pdf import _grade_value

    assert _grade_value(marker, "irrelevant line") is None


def test_an_unrecognised_grade_cell_is_omitted_and_logged_rather_than_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A convention this parser has never seen (here, junk "??") must not
    raise. It is treated as not-applicable, exactly like a dash or "N/A",
    and the drop is logged so it stays visible rather than silent."""
    from lemely.io.threshold_pdf import _grade_value

    with caplog.at_level("WARNING", logger="lemely.io.threshold_pdf"):
        value = _grade_value("??", "Component 11 40 ?? 21 18 16 15 14 13")
    assert value is None
    assert any("unrecognised grade cell" in record.message for record in caplog.records)


def test_option_row_with_a_junk_grade_cell_does_not_raise() -> None:
    """The exact call path that used to crash on "N/A": a full option row
    parsed end to end, with one cell replaced by junk instead of a
    recognised not-applicable marker."""
    from lemely.io.threshold_pdf import _parse_option_row

    option = _parse_option_row(
        "BX 21, 41, 51 ?? 106 84 62 50 38 26 14", _GRADES_8, has_max_mark_column=False
    )
    assert option is not None
    assert "A*" not in option.thresholds
    assert option.thresholds["A"] == 106
