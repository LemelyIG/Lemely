"""Target grade vocabularies, derived from what Cambridge actually publishes.

The numbers below are transcribed from the real June 2024 documents. They are
the reason this is derived rather than declared: a generic per-qualification
rule would give 0580 Extended an F and a G it does not publish.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from lemely.db.models.enums import SessionMonth
from lemely.db.models.thresholds import OptionThreshold
from lemely.db.threshold_repo import ThresholdService

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.orm import Session, sessionmaker


def _option(
    code: str,
    option: str,
    components: list[int],
    thresholds: dict[str, int],
    *,
    parse_incomplete: bool = False,
) -> OptionThreshold:
    return OptionThreshold(
        parse_incomplete=parse_incomplete,
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


def _reenable_logger() -> None:
    """``migrated_sessionmaker`` runs ``alembic upgrade head``, and Alembic's
    ``env.py`` calls ``logging.config.fileConfig``, which (per its default
    ``disable_existing_loggers=True``) disables every already-instantiated
    logger not named in ``alembic.ini`` — including this module's, created at
    import time. Undo that so ``caplog`` can see our warnings; production
    never runs migrations in-process this way, so this is a test-only wrinkle."""
    logging.getLogger("lemely.db.threshold_repo").disabled = False


def test_a_tiered_subjects_unresolvable_option_warns_rather_than_silently_untiering(
    migrated_sessionmaker: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """0580 is tiered (papers 1-4 are all Core or Extended). An option whose
    component numbers match none of them — a typo, a deleted paper, a subject
    not yet in the catalogue — must not disappear into `tier=None` next to a
    genuinely untiered subject like 0606 with no trace it happened."""
    _seed(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        s.add(_option("0580", "ZZ", [99], {"C": 1}))
    _reenable_logger()
    with caplog.at_level(logging.WARNING, logger="lemely.db.threshold_repo"):
        ThresholdService(migrated_sessionmaker).target_vocabularies()
    [record] = [r for r in caplog.records if "ZZ" in r.getMessage()]
    assert "0580" in record.getMessage()
    assert "[99]" in record.getMessage()


def test_a_genuinely_untiered_subjects_option_does_not_warn(
    migrated_sessionmaker: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """0606 has no tiered papers at all, so its options landing under
    `tier=None` is the correct outcome and must stay silent — otherwise a
    silent bug was traded for a noisy false alarm on every untiered subject."""
    _seed(migrated_sessionmaker)
    _reenable_logger()
    with caplog.at_level(logging.WARNING, logger="lemely.db.threshold_repo"):
        ThresholdService(migrated_sessionmaker).target_vocabularies()
    assert not any("0606" in r.getMessage() for r in caplog.records)


def test_an_incomplete_option_row_still_contributes_but_is_reported(
    migrated_sessionmaker: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A row with an unreadable cell is counted, not excluded.

    `target_vocabularies` unions across every session on record, so a grade
    lost from one row is normally restored by another. Excluding flagged rows
    would shrink that union and make the loss the flag exists to catch MORE
    likely, so they still contribute -- and the operator gets a warning naming
    them instead.
    """
    with migrated_sessionmaker.begin() as s:
        s.add(
            _option(
                "0580",
                "BX",
                [21, 41],
                {"A": 125, "B": 98, "C": 72},
                parse_incomplete=True,
            )
        )
    service = ThresholdService(migrated_sessionmaker)

    with caplog.at_level(logging.WARNING, logger="lemely.db.threshold_repo"):
        vocabularies = service.target_vocabularies()

    extended = next(v for v in vocabularies if v.subject_code == "0580" and v.tier == "extended")
    assert "A" in extended.grades, "the flagged row must still contribute its grades"
    assert any("unreadable grade cell" in r.getMessage() for r in caplog.records)
