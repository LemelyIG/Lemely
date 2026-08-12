"""Tests for Phase 1: GradeBoundaryStore resolver and helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from lemely.core.schemas import ExamMetadata
from lemely.data import DATA_DIR
from lemely.io.grade_boundaries import (
    GradeBoundaryStore,
    _make_key,
    raw_to_percentage,
)

if TYPE_CHECKING:
    from pathlib import Path

_BOUNDARIES_PATH = DATA_DIR / "grade_boundaries.json"
_PROVENANCE_PATH = DATA_DIR / "grade_boundaries_provenance.json"

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


# ── GradeBoundaryStore ─────────────────────────────────────────────────────


@pytest.fixture()
def boundary_data(tmp_path: Path) -> Path:
    data = {
        "0625_m20_p12": {"A": 85.0, "B": 75.0, "C": 60.0, "D": 50.0, "E": 40.0},
        "_defaults": {"0625": {"A": 82.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0}},
        "_global": {"A": 80.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0},
    }
    p = tmp_path / "grade_boundaries.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class TestGradeBoundaryStore:
    def test_exact_match(self, boundary_data: Path) -> None:
        store = GradeBoundaryStore(boundary_data)
        meta = _meta()
        boundaries, source = store.resolve(meta)
        assert source == "exact"
        assert boundaries["A"] == pytest.approx(85.0)

    def test_subject_default_fallback(self, boundary_data: Path) -> None:
        store = GradeBoundaryStore(boundary_data)
        # Different year — no exact match
        meta = _meta(session_year=2021)
        boundaries, source = store.resolve(meta)
        assert source == "subject_default"
        assert boundaries["A"] == pytest.approx(82.0)

    def test_global_default_fallback(self, boundary_data: Path) -> None:
        store = GradeBoundaryStore(boundary_data)
        # Unknown subject code
        meta = _meta(subject_code="9999", session_year=2021)
        boundaries, source = store.resolve(meta)
        assert source == "global_default"
        assert boundaries["A"] == pytest.approx(80.0)

    def test_specimen_uses_subject_default(self, boundary_data: Path) -> None:
        store = GradeBoundaryStore(boundary_data)
        meta = _meta(session_month="Specimen", session_year=2020)
        _, source = store.resolve(meta)
        assert source == "subject_default"

    def test_none_year_uses_subject_default(self, boundary_data: Path) -> None:
        store = GradeBoundaryStore(boundary_data)
        meta = _meta(session_year=None)
        _, source = store.resolve(meta)
        assert source == "subject_default"


# ── Real bundled data (P2.2 ingestion) ────────────────────────────────────


_INGESTED_SUBJECTS = ("0580", "0606", "0625")


class TestBundledRealData:
    """Exercise the actual shipped lemely/data/grade_boundaries.json (P2.2)."""

    def test_defaults_are_computed_averages_not_guesses(self) -> None:
        # The old bundled defaults were hand-guessed round numbers identical
        # across all three subjects (80/70/60/50/40). Real per-subject averages
        # computed from scraped official data should differ subject-to-subject.
        store = GradeBoundaryStore()
        seen = set()
        for subject_code in _INGESTED_SUBJECTS:
            meta = _meta(subject_code=subject_code, session_year=None)
            boundaries, source = store.resolve(meta)
            assert source == "subject_default"
            seen.add(tuple(sorted(boundaries.items())))
        assert len(seen) == len(_INGESTED_SUBJECTS), "expected distinct real averages per subject"

    def test_defaults_are_monotonically_ordered(self) -> None:
        store = GradeBoundaryStore()
        for subject_code in _INGESTED_SUBJECTS:
            meta = _meta(subject_code=subject_code, session_year=None)
            boundaries, _ = store.resolve(meta)
            ordered_grades = [g for g in ("A", "B", "C", "D", "E", "F", "G") if g in boundaries]
            thresholds = [boundaries[g] for g in ordered_grades]
            assert thresholds == sorted(thresholds, reverse=True)

    def test_known_scraped_session_resolves_exact(self) -> None:
        # 0580 May/June 2022 Paper 1 Variant 1 was ingested from the official
        # CAIE grade-threshold PDF (see lemely/data/grade_boundaries_provenance.json).
        store = GradeBoundaryStore()
        meta = _meta(subject_code="0580", paper_number=1, paper_variant=1, session_year=2022)
        boundaries, source = store.resolve(meta)
        assert source == "exact"
        assert boundaries  # non-empty real threshold map

    def test_unscraped_year_falls_back_to_subject_average(self) -> None:
        store = GradeBoundaryStore()
        meta = _meta(subject_code="0580", session_year=2000)
        boundaries, source = store.resolve(meta)
        assert source == "subject_default"
        assert boundaries


class TestProvenance:
    """The provenance file records where every exact boundary entry came from."""

    def test_every_exact_key_has_provenance_with_source_url(self) -> None:
        raw_data = json.loads(_BOUNDARIES_PATH.read_text(encoding="utf-8"))
        provenance = json.loads(_PROVENANCE_PATH.read_text(encoding="utf-8"))
        exact_keys = {k for k in raw_data if not k.startswith("_")}
        assert exact_keys, "expected real ingested boundary keys"
        assert exact_keys <= set(provenance)
        for key in exact_keys:
            assert provenance[key]["source_url"].startswith("https://cambridgeinternational.org")
