"""``GET /api/reference`` — the reference data the frontend must not hardcode.

Authenticated for any role: onboarding is a student flow, but the seven screens
that resolve a syllabus code to a display name span the student portal, and the
payload contains nothing user-specific.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.core.difficulty import _BANDS
from lemely.db.catalogue_repo import CatalogueService
from lemely.db.models.enums import SESSION_MONTH_LABELS, QualificationLevel
from lemely.db.threshold_repo import ThresholdService
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_catalogue_service,
    get_threshold_service,
)
from lemely.web.schemas_reference import (
    LabelledValueDTO,
    ReferenceDTO,
    SubjectCatalogueDTO,
    SubjectPaperDTO,
    TargetGradeVocabularyDTO,
)

router = APIRouter(prefix="/api")

#: Display labels for `QualificationLevel`. The backend owns this table now —
#: `web/src/lib/qualificationLevels.ts` used to declare its own copy.
QUALIFICATION_LEVEL_LABELS: dict[QualificationLevel, str] = {
    QualificationLevel.igcse: "IGCSE",
    QualificationLevel.o_level: "O-Level",
    QualificationLevel.as_level: "AS-Level",
    QualificationLevel.a_level: "A-Level",
}


@router.get("/reference", response_model=ReferenceDTO)
def get_reference(
    _auth: Annotated[AuthContext, Depends(get_auth_context)],
    catalogue: Annotated[CatalogueService, Depends(get_catalogue_service)],
    thresholds: Annotated[ThresholdService, Depends(get_threshold_service)],
) -> ReferenceDTO:
    """Return the subject catalogue and every UI enumeration.

    An empty ``subjects`` list is returned honestly rather than as an error: an
    unseeded environment has no catalogue, and the screen renders that as a
    failure the student can retry, never as a bundled default list.
    """
    return ReferenceDTO(
        subjects=[
            SubjectCatalogueDTO(
                code=s.code,
                name=s.name,
                board=s.board,
                qualificationLevel=s.qualification_level,
                papers=[
                    SubjectPaperDTO(
                        number=p.number, name=p.name, tier=p.tier, practical=p.practical
                    )
                    for p in s.papers
                ],
                topics=s.topics,
            )
            for s in catalogue.subjects()
        ],
        targetGradeVocabularies=[
            TargetGradeVocabularyDTO(
                subjectCode=v.subject_code,
                qualificationLevel=v.qualification_level,
                tier=v.tier,
                grades=v.grades,
            )
            for v in thresholds.target_vocabularies()
        ],
        qualificationLevels=[
            LabelledValueDTO(value=level.value, label=label)
            for level, label in QUALIFICATION_LEVEL_LABELS.items()
        ],
        sessionMonths=[
            LabelledValueDTO(value=month.value, label=label)
            for month, label in SESSION_MONTH_LABELS.items()
        ],
        difficultyBands=list(_BANDS),
    )
