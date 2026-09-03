"""Tests for the pure helpers in `lemely.io.grade_boundaries`.

`GradeBoundaryStore` itself is exercised against Postgres in
`tests/test_grade_boundaries_db.py` — these cover `_make_key` and
`raw_to_percentage`, which are unchanged by the move off the bundled JSON.
"""

from __future__ import annotations

import pytest

from lemely.core.schemas import ExamMetadata
from lemely.io.grade_boundaries import _make_key, _percentages, raw_to_percentage

# ── _make_key ──────────────────────────────────────────────────────────────


def _meta(**kw) -> ExamMetadata:
    defaults = dict(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    defaults.update(kw)
    return ExamMetadata(**defaults)


class TestMakeKey:
    def test_may_june_2020_p12(self) -> None:
        assert _make_key(_meta()) == "0625_m20_p12"

    def test_oct_nov(self) -> None:
        meta = _meta(session_month="Oct/Nov", session_year=2019)
        assert _make_key(meta) == "0625_w19_p12"

    def test_feb_mar(self) -> None:
        meta = _meta(session_month="Feb/Mar", session_year=2021)
        assert _make_key(meta) == "0625_s21_p12"

    def test_none_session_year(self) -> None:
        meta = _meta(session_year=None)
        assert _make_key(meta) is None

    def test_specimen_returns_none(self) -> None:
        meta = _meta(session_month="Specimen", session_year=2020)
        assert _make_key(meta) is None

    def test_paper_number_variant_in_key(self) -> None:
        meta = _meta(paper_number=3, paper_variant=1)
        assert _make_key(meta) == "0625_m20_p31"


# ── raw_to_percentage ──────────────────────────────────────────────────────


class TestRawToPercentage:
    def test_basic_conversion(self) -> None:
        result = raw_to_percentage({"A": 69}, 80)
        assert result == pytest.approx({"A": 86.25})

    def test_zero_max_mark_raises(self) -> None:
        with pytest.raises(ValueError, match="max_mark"):
            raw_to_percentage({"A": 0}, 0)

    def test_negative_max_mark_raises(self) -> None:
        with pytest.raises(ValueError):
            raw_to_percentage({"A": 50}, -1)

    def test_multiple_grades(self) -> None:
        result = raw_to_percentage({"A": 80, "B": 70, "C": 60}, 100)
        assert result == pytest.approx({"A": 80.0, "B": 70.0, "C": 60.0})


# ── _percentages ─────────────────────────────────────────────────────────


class TestPercentages:
    """Finding C3: `_percentages` (the read-path helper `_load` uses to build
    the exact/default maps) did not guard non-positive `max_mark`, unlike
    `raw_to_percentage`. A zero raised `ZeroDivisionError` deep inside
    `_load` instead of a clear error; a negative value silently produced a
    grade-inflating percentage (`_percentages({"A": 24}, -1) ==
    {"A": -2400.0}`)."""

    def test_zero_max_mark_raises(self) -> None:
        with pytest.raises(ValueError, match="max_mark"):
            _percentages({"A": 24}, 0)

    def test_negative_max_mark_raises(self) -> None:
        with pytest.raises(ValueError, match="max_mark"):
            _percentages({"A": 24}, -1)

    def test_basic_conversion(self) -> None:
        assert _percentages({"A": 69}, 80) == {"A": 86.25}
