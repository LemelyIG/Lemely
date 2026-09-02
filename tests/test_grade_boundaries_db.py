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
    # Same subject and paper number as the seed row (so the subject-default
    # rung, scoped to (subject_code, paper_number), still has a bucket to
    # fall into), but a different session/variant so it misses the exact key.
    _, source = store.resolve(
        ExamMetadata(
            subject_code="0625",
            session_month="May/June",
            session_year=2099,
            paper_number=1,
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


# ── Unverified rows must never grade (Finding 1) ────────────────────────────


def _add_row(
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0625",
    session_year: int = 2024,
    paper_number: int = 1,
    paper_variant: int = 2,
    max_mark: int = 40,
    thresholds: dict[str, int],
    verified: bool,
) -> None:
    with sm.begin() as s:
        s.add(
            ComponentThreshold(
                subject_code=subject_code,
                session_month=SessionMonth.may_june,
                session_year=session_year,
                paper_number=paper_number,
                paper_variant=paper_variant,
                max_mark=max_mark,
                thresholds=thresholds,
                verified=verified,
                source_url="https://example.invalid/gt.pdf",
            )
        )


def test_a_paper_whose_only_row_is_unverified_does_not_resolve_as_exact(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    _add_row(
        migrated_sessionmaker,
        thresholds={"C": 20, "D": 18, "E": 16},
        verified=False,
    )
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    _, source = store.resolve(
        ExamMetadata(
            subject_code="0625",
            session_month="May/June",
            session_year=2024,
            paper_number=1,
            paper_variant=2,
        )
    )
    assert source != "exact"
    assert source == "global_default"  # no other verified row for this paper number


def test_a_verified_row_still_resolves_as_exact(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    _add_row(
        migrated_sessionmaker,
        thresholds={"C": 20, "D": 18, "E": 16},
        verified=True,
    )
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    _, source = store.resolve(
        ExamMetadata(
            subject_code="0625",
            session_month="May/June",
            session_year=2024,
            paper_number=1,
            paper_variant=2,
        )
    )
    assert source == "exact"


# ── A fallback map must never award a grade the paper can't give (Finding 2) ─


def test_a_core_papers_fallback_map_has_no_grade_absent_from_core_rows(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    # Core paper (0580 Paper 1): only ever publishes C-G.
    _add_row(
        migrated_sessionmaker,
        subject_code="0580",
        paper_number=1,
        paper_variant=1,
        session_year=2022,
        thresholds={"C": 30, "D": 25, "E": 20, "F": 15, "G": 10},
        verified=True,
    )
    # Extended paper (0580 Paper 3), same subject: publishes A*-G.
    _add_row(
        migrated_sessionmaker,
        subject_code="0580",
        paper_number=3,
        paper_variant=1,
        session_year=2022,
        thresholds={"A*": 70, "A": 60, "B": 50, "C": 40, "D": 30, "E": 20, "F": 10, "G": 5},
        verified=True,
    )
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    # A different Core session/variant falls to the subject_default rung.
    boundaries, source = store.resolve(
        ExamMetadata(
            subject_code="0580",
            session_month="May/June",
            session_year=2023,
            paper_number=1,
            paper_variant=1,
        )
    )
    assert source == "subject_default"
    assert "A" not in boundaries
    assert "A*" not in boundaries
    assert "B" not in boundaries
    assert set(boundaries) <= {"C", "D", "E", "F", "G"}


# ── Re-verify the real exact case still works ───────────────────────────────


def test_0625_s24_paper_2_1_still_resolves_exact_at_60_percent(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    invalidate_reference_cache()
    _add_row(
        migrated_sessionmaker,
        subject_code="0625",
        paper_number=2,
        paper_variant=1,
        session_year=2024,
        max_mark=40,
        thresholds={"A": 24},
        verified=True,
    )
    store = GradeBoundaryStore(sessionmaker=migrated_sessionmaker)
    boundaries, source = store.resolve(
        ExamMetadata(
            subject_code="0625",
            session_month="May/June",
            session_year=2024,
            paper_number=2,
            paper_variant=1,
        )
    )
    assert source == "exact"
    assert boundaries["A"] == 60.0
