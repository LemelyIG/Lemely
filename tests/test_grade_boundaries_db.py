"""`GradeBoundaryStore` must keep its fallback chain after moving to Postgres.

`attempts.boundary_source` records which rung answered, so the three-way
distinction is a stored fact about every graded paper, not an implementation
detail free to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lemely.core.schemas import ExamMetadata
from lemely.db.models.enums import SessionMonth
from lemely.db.models.thresholds import ComponentThreshold
from lemely.io.grade_boundaries import GradeBoundaryStore, invalidate_reference_cache

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(autouse=True)
def _reset_reference_cache() -> Iterator[None]:
    """Keep this module's fake seed data out of the process-wide cache.

    `GradeBoundaryStore()` (no args, used all over the web layer) defaults to
    `get_sessionmaker()` — the ambient database, not this module's throwaway
    `migrated_sessionmaker` database. Without this reset, a fake row seeded
    here would leak into every other test file's `GradeBoundaryStore()` for
    the rest of the process.
    """
    invalidate_reference_cache()
    yield
    invalidate_reference_cache()


def _seed(sm: sessionmaker[Session]) -> None:
    with sm.begin() as s:
        s.add(
            ComponentThreshold(
                subject_code="0625",
                session_month=SessionMonth.may_june,
                session_year=2024,
                paper_number=1,
                paper_variant=2,
                max_mark=40,
                thresholds={"C": 20, "D": 18, "E": 16},
                verified=True,
                source_url="https://example.invalid/0625_s24_gt.pdf",
            )
        )


def test_an_exact_match_reports_itself_as_exact(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    _seed(migrated_sessionmaker)
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    boundaries, source = store.resolve(
        ExamMetadata(
            subject_code="0625",
            session_month="May/June",
            session_year=2024,
            paper_number=1,
            paper_variant=2,
        )
    )
    assert source == "exact"
    # 20/40 → 50%. Raw marks are stored; the percentage is derived here.
    assert boundaries["C"] == 50.0


def test_an_unknown_paper_falls_back_to_the_subject_default(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    _seed(migrated_sessionmaker)
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    _, source = store.resolve(
        ExamMetadata(
            subject_code="0625",
            session_month="May/June",
            session_year=2099,
            paper_number=9,
            paper_variant=9,
        )
    )
    assert source == "subject_default"


def test_an_unknown_subject_falls_back_to_the_global_default(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    _seed(migrated_sessionmaker)
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    _, source = store.resolve(
        ExamMetadata(
            subject_code="9999",
            session_month="May/June",
            session_year=2024,
            paper_number=1,
            paper_variant=1,
        )
    )
    assert source == "global_default"
