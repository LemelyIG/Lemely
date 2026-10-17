"""``GET /api/reference`` DTOs — the catalogue and every enumeration the UI needs.

One endpoint rather than several (spec D4): one round trip, one cache key, one
hook, and one place the frontend's "no hardcoded reference data" gate can point
at. Field names are camelCase declared directly, matching
``schemas_student_profile.py``'s convention — an explicit ``ApiModel`` subclass
per DTO, no alias generator.
"""

from __future__ import annotations

from pydantic import Field

from lemely.web.schemas import ApiModel


class SubjectPaperDTO(ApiModel):
    """One paper a student can tick in S-01."""

    number: int
    name: str
    tier: str | None = None
    practical: bool


class SubjectCatalogueDTO(ApiModel):
    """One offered subject.

    ``qualificationLevel`` is the subject's own (spec D10) — 0580/0606/0625 are
    all IGCSE syllabuses — not a student-declared preference. S-01 displays it
    rather than asking, which is what removes "A-Level Physics 0625" from the
    set of expressible answers.
    """

    code: str
    name: str
    board: str
    qualificationLevel: str | None = None
    papers: list[SubjectPaperDTO]
    topics: list[str]


class LabelledValueDTO(ApiModel):
    """A ``(value, label)`` pair for an enumeration the UI renders."""

    value: str
    label: str


class TargetGradeVocabularyDTO(ApiModel):
    """The grades a student may aim for in one subject at one tier.

    Keyed by **subject**, not only by qualification level, because the measured
    data differs that way: 0580 Extended options publish A*-E with no F/G,
    while 0625 Extended options publish A*-G. A vocabulary keyed on
    ``(qualificationLevel, tier)`` alone would offer a 0580 student an F they
    cannot be awarded.

    Populated in a later stage from ``option_thresholds``; declared now so the
    wire contract does not change shape underneath the frontend.
    """

    subjectCode: str
    qualificationLevel: str | None = None
    tier: str | None = None
    grades: list[str]


class ReferenceDTO(ApiModel):
    """Everything the frontend used to hardcode."""

    subjects: list[SubjectCatalogueDTO]
    targetGradeVocabularies: list[TargetGradeVocabularyDTO] = Field(default_factory=list)
    qualificationLevels: list[LabelledValueDTO]
    sessionMonths: list[LabelledValueDTO]
    difficultyBands: list[str]
