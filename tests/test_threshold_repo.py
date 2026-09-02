"""Target grade vocabularies, derived from what Cambridge actually publishes.

The numbers below are transcribed from the real June 2024 documents. They are
the reason this is derived rather than declared: a generic per-qualification
rule would give 0580 Extended an F and a G it does not publish.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.db.models.enums import SessionMonth
from lemely.db.models.thresholds import OptionThreshold
from lemely.db.threshold_repo import ThresholdService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _option(
    code: str, option: str, components: list[int], thresholds: dict[str, int]
) -> OptionThreshold:
    return OptionThreshold(
        subject_code=code,
        session_month=SessionMonth.may_june,
        session_year=2024,
        option_code=option,
        component_numbers=components,
        max_mark_after_weighting=200,
        thresholds=thresholds,
        source_url="https://example.invalid/gt.pdf",
    )


def _seed(sm: sessionmaker[Session]) -> None:
    # `migrated_sessionmaker` already runs `alembic upgrade head`, which backfills
    # the real subjects/syllabus_papers catalogue (0580/0606/0625 with their real
    # tiers) as part of migration 0024. Re-inserting those rows here would
    # collide with that seed, so this only adds the `option_thresholds` rows the
    # migrations never populate (0025 is schema-only).
    with sm.begin() as s:
        # Real June 2024 rows.
        s.add(_option("0580", "AX", [11, 31], {"C": 77, "D": 63, "E": 50, "F": 36, "G": 22}))
        s.add(
            _option(
                "0580", "BX", [21, 41], {"A*": 152, "A": 125, "B": 98, "C": 72, "D": 56, "E": 40}
            )
        )
        s.add(
            _option(
                "0606", "AX", [11, 21], {"A*": 132, "A": 105, "B": 76, "C": 47, "D": 35, "E": 23}
            )
        )


def test_core_and_extended_get_different_vocabularies(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _seed(migrated_sessionmaker)
    vocabularies = {
        (v.subject_code, v.tier): v.grades
        for v in ThresholdService(migrated_sessionmaker).target_vocabularies()
    }
    # Core caps at C — Cambridge publishes no A* or A for a Core option.
    assert vocabularies[("0580", "core")] == ["C", "D", "E", "F", "G", "U"]
    # Extended reaches A* but publishes no F/G for 0580.
    assert vocabularies[("0580", "extended")] == ["A*", "A", "B", "C", "D", "E", "U"]


def test_an_untiered_subject_yields_a_null_tier_vocabulary(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _seed(migrated_sessionmaker)
    vocabularies = {
        (v.subject_code, v.tier): v.grades
        for v in ThresholdService(migrated_sessionmaker).target_vocabularies()
    }
    assert vocabularies[("0606", None)] == ["A*", "A", "B", "C", "D", "E", "U"]


def test_grades_come_back_in_descending_order_with_u_last(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A picker renders them in this order, and `gradeRank` indexes into it, so
    the order is contract rather than presentation."""
    _seed(migrated_sessionmaker)
    extended = next(
        v
        for v in ThresholdService(migrated_sessionmaker).target_vocabularies()
        if v.subject_code == "0580" and v.tier == "extended"
    )
    assert extended.grades[0] == "A*"
    assert extended.grades[-1] == "U"


def test_the_vocabulary_carries_the_subjects_qualification_level(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _seed(migrated_sessionmaker)
    assert all(
        v.qualification_level == "igcse"
        for v in ThresholdService(migrated_sessionmaker).target_vocabularies()
    )
