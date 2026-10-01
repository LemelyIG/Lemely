"""API DTOs for student self-review (``/api/student/attempts/.../self-review``).

Two response shapes, on purpose. :class:`SelfReviewPendingDTO` is what a
student sees **before** committing to their own verdicts and its point type
carries no ``awarded``, no marks, no verdict — the reveal is enforced by the
payload's shape, not by a client hiding a field (spec 2026-09-17
self-review, "Flow"). :class:`SelfReviewRevealedDTO` exists only after the
pass. Nothing here carries an integrity flag, and no copy mentions one.

Input is bounded at this edge: evidence is at most
:data:`~lemely.db.self_review_repo.MAX_EVIDENCE_CHARS` characters and may not
contain NUL, which Postgres rejects in ``text`` and JSONB — the spec-1
lesson that loosely-validated input meeting a strict constraint aborts the
whole transaction.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Literal

from pydantic import Field, field_validator

#: Re-exported from :data:`lemely.core.schemas.PointVerdictWire`, the same
#: pattern ``lemely/web/schemas_review.py`` uses for the teacher wire.
#: pydantic needs the real type at class-creation time, not just for
#: annotations, so this stays out of ``TYPE_CHECKING`` (``noqa: TC001``).
from lemely.core.schemas import PointVerdictWire as PointVerdictWire  # noqa: TC001
from lemely.db.self_review_repo import MAX_EVIDENCE_CHARS
from lemely.web.schemas import ApiModel

EvidenceVerdictWire = Literal["accepted", "rejected", "not_required"]


class SelfReviewPendingPointDTO(ApiModel):
    """A mark point before the reveal. No ``awarded`` — by construction.

    ``isAlternative`` / ``isOptional`` / ``groupKey`` / ``groupMaxMarks`` are
    scheme-derived and verdict-free: the panel renders an either/or or
    any-N group as one unit worth ``groupMaxMarks`` (Task 6a).
    """

    markPointId: str
    ordinal: int
    markType: str | None
    tariff: int
    pointText: str
    isAlternative: bool
    isOptional: bool
    groupKey: str | None
    groupMaxMarks: int | None


class SelfReviewRevealedPointDTO(SelfReviewPendingPointDTO):
    """A mark point after the reveal: the marker's verdict beside the student's.

    ``verdict``/``evidenceSpan``/``ecfApplied`` are I6/I7's marker verdict, on
    the REVEALED shape only. They cannot join
    :class:`SelfReviewPendingPointDTO`: a verdict is strictly more informative
    than ``awarded``, which that shape deliberately omits until the student has
    committed their self-mark.
    """

    awarded: bool
    studentSelfmark: bool
    studentEvidence: str | None
    evidenceVerdict: EvidenceVerdictWire | None
    markChanged: bool
    absorbedByGroup: bool
    judgeReason: str | None
    verdict: PointVerdictWire | None
    evidenceSpan: str
    ecfApplied: bool


class SelfReviewPendingDTO(ApiModel):
    """``GET`` before submission."""

    state: Literal["not_started"]
    attemptId: str
    questionResultId: str
    questionId: str
    maxMarks: int
    evidenceRequired: bool
    points: list[SelfReviewPendingPointDTO]


class SelfReviewRevealedDTO(ApiModel):
    """``GET`` after submission, and every ``POST`` response."""

    state: Literal["revealed", "settled"]
    attemptId: str
    questionResultId: str
    questionId: str
    maxMarks: int
    evidenceRequired: bool
    aiMarks: int
    effectiveMarks: int
    studentMarks: int | None
    teacherSettled: bool
    pendingTeacher: bool
    submittedAt: datetime
    points: list[SelfReviewRevealedPointDTO]


class SelfReviewPointVerdictDTO(ApiModel):
    """One point of the student's submission."""

    markPointId: str = Field(min_length=1, max_length=200)
    earned: bool
    evidence: str | None = Field(default=None, max_length=MAX_EVIDENCE_CHARS)

    @field_validator("evidence")
    @classmethod
    def _no_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("evidence must not contain NUL characters")
        return value


class SelfReviewSubmissionDTO(ApiModel):
    """``POST`` body: a verdict for **every** point of the question."""

    points: list[SelfReviewPointVerdictDTO] = Field(min_length=1, max_length=100)


__all__ = [
    "SelfReviewPendingDTO",
    "SelfReviewPendingPointDTO",
    "SelfReviewPointVerdictDTO",
    "SelfReviewRevealedDTO",
    "SelfReviewRevealedPointDTO",
    "SelfReviewSubmissionDTO",
]
