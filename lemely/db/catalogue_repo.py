"""Read side of the syllabus catalogue.

The only module that queries ``subjects`` / ``syllabus_papers`` /
``subject_topics`` for presentation. Returns plain frozen dataclasses rather
than ORM rows so the router never holds a detached instance, matching how the
other ``*_repo`` modules hand rows to their routers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.topics import topic_sort_key
from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class CataloguePaper:
    """One paper offered for selection in S-01."""

    number: int
    name: str
    tier: str | None
    practical: bool


@dataclass(frozen=True, slots=True)
class CatalogueSubject:
    """One offered subject with its papers and top-level topics."""

    code: str
    name: str
    board: str
    qualification_level: str | None
    papers: list[CataloguePaper]
    topics: list[str]


class CatalogueService:
    """Reads the offered catalogue."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def subjects(self) -> list[CatalogueSubject]:
        """Every active subject, ordered by ``code``.

        Ordered by code rather than by a display-order column: the spec (D3)
        drops that column, and code order is deterministic without one.
        Top-level topics only — S-02 asks about those, and the subtopic tree
        exists for the classifier, not for a picker.
        """
        with self._sessionmaker() as session:
            subjects = session.scalars(
                sa.select(Subject).where(Subject.active.is_(True)).order_by(Subject.code)
            ).all()
            papers = session.scalars(
                sa.select(SyllabusPaper).order_by(SyllabusPaper.paper_number)
            ).all()
            topics = session.scalars(
                sa.select(SubjectTopic).where(SubjectTopic.parent_id.is_(None))
            ).all()
            # Ordered in Python, not SQL: `ORDER BY code` is a text sort, and
            # 0606 has fourteen top-level topics, so it would return 1, 10, 11
            # before 2. S-02 shows the first three of these, so the wrong order
            # is a wrong question asked of the student.
            topics = sorted(topics, key=lambda t: topic_sort_key(t.code))

        papers_by_subject: dict[str, list[CataloguePaper]] = {}
        for row in papers:
            papers_by_subject.setdefault(row.subject_code, []).append(
                CataloguePaper(
                    number=row.paper_number,
                    name=row.name,
                    tier=row.tier.value if row.tier else None,
                    practical=row.practical,
                )
            )

        topics_by_subject: dict[str, list[str]] = {}
        for topic in topics:
            # `"<code> <name>"` is the vocabulary `ConfidenceRating.topic` and
            # the weakness engine already use. Composed here, once, so no
            # caller has to know the convention.
            topics_by_subject.setdefault(topic.subject_code, []).append(
                f"{topic.code} {topic.name}"
            )

        return [
            CatalogueSubject(
                code=s.code,
                name=s.name,
                board=s.board.value,
                qualification_level=(
                    s.qualification_level.value if s.qualification_level else None
                ),
                papers=papers_by_subject.get(s.code, []),
                topics=topics_by_subject.get(s.code, []),
            )
            for s in subjects
        ]
