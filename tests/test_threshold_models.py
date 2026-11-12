"""Model-shape tests for the threshold tables (no database required)."""

from __future__ import annotations

from lemely.db.models.thresholds import ComponentThreshold, OptionThreshold


def test_component_threshold_records_whether_it_was_verified() -> None:
    """`verified` is the honest half of the ingest: a row sourced from ciegt
    alone must not be indistinguishable from one a Cambridge PDF confirmed."""
    cols = ComponentThreshold.__table__.columns
    assert cols["verified"].nullable is False
    assert cols["source_url"].nullable is False


def test_component_threshold_is_unique_per_paper_and_session() -> None:
    uniques = {
        tuple(sorted(c.name for c in con.columns))
        for con in ComponentThreshold.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert (
        "board",
        "paper_number",
        "paper_variant",
        "session_month",
        "session_year",
        "subject_code",
    ) in uniques


def test_option_max_mark_is_nullable_for_the_pre_2020_layout() -> None:
    """Older CAIE threshold tables print `Option A* A B C D E F G` with no
    "maximum mark after weighting" column at all. A NOT NULL column here would
    make those sessions unstorable."""
    assert OptionThreshold.__table__.columns["max_mark_after_weighting"].nullable is True
