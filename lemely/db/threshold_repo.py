r"""Read side of the threshold tables, and the target vocabularies they imply.

A *target* grade is a syllabus-level aspiration, so its vocabulary comes from
``option_thresholds`` — the only table where A\* appears, because Cambridge
states that "Grade A\* does not exist at the level of an individual component".

An option's tier is derived by looking its component numbers up in
``syllabus_papers`` rather than by reading its code letter. ``0580 AX =
[11, 31]`` maps to papers 1 and 3, both Core; ``BX = [21, 41]`` maps to papers
2 and 4, both Extended. That uses the catalogue we already have instead of
trusting a naming convention, and it produces the right answer for 0606, whose
papers carry no tier at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.models.thresholds import OptionThreshold

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger("lemely.db.threshold_repo")

#: Descending grade order, the order a picker renders and `gradeRank` indexes.
#: `U` is appended rather than published: no threshold table lists it, because
#: it is what a candidate gets when they clear none of the others.
_GRADE_ORDER = ("A*", "A", "B", "C", "D", "E", "F", "G")
_UNGRADED = "U"


@dataclass(frozen=True, slots=True)
class TargetVocabulary:
    """The grades a student may aim for in one subject at one tier."""

    subject_code: str
    qualification_level: str | None
    tier: str | None
    grades: list[str]


class ThresholdService:
    """Reads thresholds and derives the vocabularies the UI offers."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def target_vocabularies(self) -> list[TargetVocabulary]:
        """One vocabulary per ``(subject, tier)`` Cambridge publishes options for."""
        with self._sessionmaker() as session:
            subjects = {s.code: s for s in session.scalars(sa.select(Subject))}
            tier_by_paper = {
                (p.subject_code, p.paper_number): (p.tier.value if p.tier else None)
                for p in session.scalars(sa.select(SyllabusPaper))
            }
            options = session.scalars(sa.select(OptionThreshold)).all()

        # Subjects with at least one tiered paper. An option for one of these
        # whose component numbers still resolve to no tier is a lookup
        # failure (typo, deleted paper, ...), not a genuinely untiered
        # subject like 0606 — see the warning below.
        tiered_subjects = {
            subject_code for (subject_code, _number), tier in tier_by_paper.items() if tier
        }

        grades_by_key: dict[tuple[str, str | None], set[str]] = {}
        for option in options:
            tiers = {
                tier_by_paper.get((option.subject_code, number // 10 or number))
                for number in option.component_numbers
            }
            tiers.discard(None)
            if not tiers and option.subject_code in tiered_subjects:
                logger.warning(
                    "target vocabulary: option %s/%s has component numbers %r that match no"
                    " tiered paper, treating as untiered",
                    option.subject_code,
                    option.option_code,
                    option.component_numbers,
                )
            # Extended wins a mixed option: a candidate sitting any Extended
            # component is an Extended candidate.
            tier = "extended" if "extended" in tiers else ("core" if "core" in tiers else None)
            grades_by_key.setdefault((option.subject_code, tier), set()).update(option.thresholds)

        vocabularies = []
        for (code, tier), grades in sorted(
            grades_by_key.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
        ):
            subject = subjects.get(code)
            if subject is None:
                logger.warning(
                    "target vocabulary: subject %s has option thresholds but no catalogue"
                    " entry, qualification level will be unknown",
                    code,
                )
            level = subject.qualification_level if subject else None
            vocabularies.append(
                TargetVocabulary(
                    subject_code=code,
                    qualification_level=level.value if level else None,
                    tier=tier,
                    grades=[g for g in _GRADE_ORDER if g in grades] + [_UNGRADED],
                )
            )
        return vocabularies
