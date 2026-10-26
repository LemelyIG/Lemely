"""SP4: a tutor's past-student outcome figures, for students and parents (SPEC §b.2; ADR-T04).

``GET /api/tutors/{tutor_id}/outcomes`` is ``STUDENT_OR_PARENT`` behind a
verified email (SC-15) and answers SP2's own 404 (``tutoring_http.tutor_not_found``)
for a tutor the caller may not see: unlisted, paused, unknown, or in an active
block with a student caller in either direction (O11, PP-6). The figures are
computed live on every request from three statements
(:class:`~lemely.db.tutor_outcomes_repo.TutorOutcomesRepository`); nothing is
cached anywhere (decision row 13), and the response is ``private, no-store``
like every non-public tutoring route (:class:`~lemely.web.tutoring_http.TutoringRoute`).

This module also holds what T8 (``routers/tutor_preview.py``) shares: the
repository provider :func:`get_tutor_outcomes_repo` and the DTO builder
:func:`outcomes_dto`, so both routes serialise one ``OutcomesDTO`` the same way,
byte for byte (``test_outcomes_marking_complete_no_show_changes_nothing``).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.core.tutor_outcomes import BEFORE_LOOKBACK, DURING_WINDOW
from lemely.db.session import get_sessionmaker
from lemely.db.tutor_outcomes_repo import SubjectFigures, TutorOutcomes, TutorOutcomesRepository
from lemely.web.deps import AuthContext, get_settings, require_verified_email
from lemely.web.deps_tutoring import require_student_or_parent
from lemely.web.schemas_tutoring import (
    OutcomeBucketDTO,
    OutcomeChangeDTO,
    OutcomeDistributionDTO,
    OutcomesDTO,
    SubjectOutcomeDTO,
    SubjectRefDTO,
)
from lemely.web.tutoring_http import TutoringRoute, tutor_not_found

router = APIRouter(prefix="/api", tags=["tutoring"], route_class=TutoringRoute)


@lru_cache(maxsize=1)
def get_tutor_outcomes_repo() -> TutorOutcomesRepository:
    """The process-wide :class:`TutorOutcomesRepository` (it holds no results, only a factory)."""
    return TutorOutcomesRepository(get_sessionmaker(get_settings()))


def _subject_outcome_dto(item: SubjectFigures) -> SubjectOutcomeDTO:
    distribution = item.outcome.distribution
    change = item.outcome.change
    return SubjectOutcomeDTO(
        subject=SubjectRefDTO(code=item.subject.code, name=item.subject.name),
        distribution=OutcomeDistributionDTO(
            state=distribution.state,
            k=distribution.k,
            nGraded=distribution.n_graded,
            nWithoutGrade=distribution.n_without_grade,
            buckets=[
                OutcomeBucketDTO(grade=bucket.grade, count=bucket.count)
                for bucket in distribution.buckets
            ],
        ),
        change=OutcomeChangeDTO(
            state=change.state,
            k=change.k,
            nPaired=change.n_paired,
            higher=change.higher,
            same=change.same,
            lower=change.lower,
        ),
    )


def outcomes_dto(outcomes: TutorOutcomes) -> OutcomesDTO:
    """The ``OutcomesDTO`` SP4 and T8 return: the ladder, the window captions, every subject."""
    return OutcomesDTO(
        tutorId=str(outcomes.tutor_id),
        ladder=list(outcomes.ladder),
        duringWindowDays=DURING_WINDOW.days,
        beforeLookbackDays=BEFORE_LOOKBACK.days,
        subjects=[_subject_outcome_dto(item) for item in outcomes.subjects],
    )


@router.get("/tutors/{tutor_id}/outcomes", response_model=OutcomesDTO)
def get_outcomes(
    tutor_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_student_or_parent)],
    _verified: Annotated[AuthContext, Depends(require_verified_email)],
    repo: Annotated[TutorOutcomesRepository, Depends(get_tutor_outcomes_repo)],
) -> OutcomesDTO:
    """SP4: the figures per subject; 404 unless the tutor is listed, unpaused and unblocked."""
    outcomes = repo.outcomes_for_viewer(tutor_id, uuid.UUID(auth.user_id), auth.role)
    if outcomes is None:
        raise tutor_not_found()
    return outcomes_dto(outcomes)


__all__ = ["get_tutor_outcomes_repo", "outcomes_dto", "router"]
