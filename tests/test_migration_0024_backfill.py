"""The 0024 backfill must reproduce exactly what the retiring JSON held.

This is the one chance to prove nothing was lost in transcription: after this
migration the JSON files are deleted, so any divergence becomes permanent and
silent. The expectations below are transcribed from the files as they stood at
the time of the migration.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper

EXPECTED_PAPERS = {
    "0625": [
        (1, "Multiple Choice (Core)", "core", False),
        (2, "Multiple Choice (Extended)", "extended", False),
        (3, "Theory (Core)", "core", False),
        (4, "Theory (Extended)", "extended", False),
        (5, "Practical Test", None, True),
        (6, "Alternative to Practical", None, True),
    ],
    "0580": [
        (1, "Non-calculator (Core)", "core", False),
        (2, "Non-calculator (Extended)", "extended", False),
        (3, "Calculator (Core)", "core", False),
        (4, "Calculator (Extended)", "extended", False),
    ],
    "0606": [
        (1, "Non-calculator", None, False),
        (2, "Calculator", None, False),
    ],
}

EXPECTED_TOP_TOPIC_COUNTS = {"0625": 6, "0580": 9, "0606": 14}

EXPECTED_FIRST_TOPICS = {
    "0625": ["1 Motion, forces and energy", "2 Thermal physics", "3 Waves"],
    "0580": ["1 Number", "2 Algebra and graphs", "3 Coordinate geometry"],
    "0606": ["1 Functions", "2 Quadratic functions", "3 Factors of polynomials"],
}


@pytest.mark.parametrize("code", sorted(EXPECTED_PAPERS))
def test_papers_match_the_retired_json(
    migrated_sessionmaker: sessionmaker[Session], code: str
) -> None:
    with migrated_sessionmaker() as s:
        rows = s.scalars(
            sa.select(SyllabusPaper)
            .where(SyllabusPaper.subject_code == code)
            .order_by(SyllabusPaper.paper_number)
        ).all()
    actual = [(r.paper_number, r.name, r.tier.value if r.tier else None, r.practical) for r in rows]
    assert actual == EXPECTED_PAPERS[code]


@pytest.mark.parametrize("code", sorted(EXPECTED_TOP_TOPIC_COUNTS))
def test_top_level_topic_counts_match(
    migrated_sessionmaker: sessionmaker[Session], code: str
) -> None:
    with migrated_sessionmaker() as s:
        n = s.scalar(
            sa.select(sa.func.count())
            .select_from(SubjectTopic)
            .where(SubjectTopic.subject_code == code, SubjectTopic.parent_id.is_(None))
        )
    assert n == EXPECTED_TOP_TOPIC_COUNTS[code]


@pytest.mark.parametrize("code", sorted(EXPECTED_FIRST_TOPICS))
def test_first_three_topics_match_the_onboarding_vocabulary(
    migrated_sessionmaker: sessionmaker[Session], code: str
) -> None:
    """The exact strings S-02's confidence step used to hardcode.

    Ordered by the *numeric* value of ``code`` rather than the column's raw
    text order: top-level topic codes are plain integers ("1".."14" for
    0606), and Postgres's default collation sorts text byte-wise, so a plain
    ``ORDER BY code`` would put "10" before "2". Casting to integer recovers
    the syllabus's actual topic order — the same order the retired JSON's
    list held and that S-02's onboarding step displayed.
    """
    with migrated_sessionmaker() as s:
        rows = s.scalars(
            sa.select(SubjectTopic)
            .where(SubjectTopic.subject_code == code, SubjectTopic.parent_id.is_(None))
            .order_by(sa.cast(SubjectTopic.code, sa.Integer))
        ).all()
    assert [f"{r.code} {r.name}" for r in rows][:3] == EXPECTED_FIRST_TOPICS[code]


def test_every_paper_names_its_source_document(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as s:
        rows = s.scalars(sa.select(SyllabusPaper)).all()
    assert rows
    assert all(r.source_document and r.source_url and r.syllabus_version for r in rows)
