"""``/api/me/student-profile`` DTOs — onboarding data (P4.3 chunk B, D4.5).

Wire format for the student-only onboarding routes in
``lemely.web.routers.me``. Field names mirror
:mod:`lemely.db.student_profile_repo`'s row dataclasses one-for-one,
camelCased, following :mod:`lemely.web.schemas_me`'s style (an explicit
``ApiModel`` subclass per DTO, no alias generator — camelCase names are
declared directly, matching this codebase's established convention).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the real type at runtime

from lemely.web.schemas import ApiModel


class ConfidenceRatingDTO(ApiModel):
    """One (topic, rating) pair.

    Mirrors :class:`~lemely.db.student_profile_repo.ConfidenceRatingRow`.
    """

    topic: str
    rating: int


class SubjectEnrolmentDTO(ApiModel):
    """One subject enrolment, with its papers and confidence ratings (S-01).

    Confidence ratings are embedded here rather than served by a separate
    GET route: the brief leaves "one combined DTO or separate nested GETs"
    to implementation judgement, and a student's onboarding screen renders
    every enrolled subject's ratings at once, so one round trip for the
    whole profile is the natural shape. A dedicated PUT route still exists
    for updating one subject's ratings in isolation.
    """

    subjectCode: str
    targetGrade: str | None = None
    sessionMonth: str | None = None
    sessionYear: int | None = None
    papers: list[int]
    confidenceRatings: list[ConfidenceRatingDTO]


class StudentProfileDTO(ApiModel):
    """The scalar onboarding fields (S-02) — the ``PATCH``/``complete-onboarding`` echo."""

    qualificationLevel: str | None = None
    gradeLevel: str | None = None
    schoolName: str | None = None
    hasExternalLessons: bool | None = None
    weeklyStudyHours: int | None = None
    onboardingCompletedAt: datetime | None = None
    leaderboardOptOut: bool = False
    """D5.1 §9: ``True`` hides this student from every board, including one
    their own friends see. Reversible — opting back in restores the exact
    previous ranked position, since no XP history is ever touched by this
    flag."""


class StudentProfileWithEnrolmentsDTO(ApiModel):
    """``GET /api/me/student-profile`` response: profile scalars + every enrolment."""

    profile: StudentProfileDTO
    enrolments: list[SubjectEnrolmentDTO]


class StudentProfileUpdateDTO(ApiModel):
    """Body for ``PATCH /api/me/student-profile``. Every field is optional.

    A genuine partial update: a field omitted from the request body is left
    untouched server-side (``payload.model_fields_set`` tells "omitted"
    apart from "explicitly sent", the same mechanism
    ``put_notification_preferences`` uses); an explicit ``null`` on any
    field clears it, since every one of these fields is skippable per S-02.
    """

    qualificationLevel: str | None = None
    gradeLevel: str | None = None
    schoolName: str | None = None
    hasExternalLessons: bool | None = None
    weeklyStudyHours: int | None = None
    leaderboardOptOut: bool | None = None
    """Not nullable on the model (D5.1 §9), so unlike every other field on
    this DTO an explicit ``null`` here is rejected rather than clearing
    anything -- see the route for the exact check. ``None`` here only ever
    means "omitted"."""


class EnrolmentUpsertDTO(ApiModel):
    """One item of a ``PUT /api/me/student-profile/enrolments`` request body.

    Unlike :class:`StudentProfileUpdateDTO`, this is not a PATCH — every
    field carries the enrolment's full desired state for this call
    (including ``None``, which clears ``targetGrade``/``sessionMonth``/
    ``sessionYear``); there is no "omitted means unchanged" for fields
    *within* one enrolment object, only for enrolments not mentioned in the
    list at all (see the route docstring for that choice).
    """

    subjectCode: str
    targetGrade: str | None = None
    sessionMonth: str | None = None
    sessionYear: int | None = None
    papers: list[int] | None = None
    """The full desired paper-number set for this subject. ``None``/omitted means "no papers"."""


class EnrolmentListRequestDTO(ApiModel):
    """Body for ``PUT /api/me/student-profile/enrolments``."""

    enrolments: list[EnrolmentUpsertDTO]


class ConfidenceRatingsUpdateDTO(ApiModel):
    """Body for ``PUT /api/me/student-profile/enrolments/{subject_code}/confidence-ratings``.

    ``ratings`` is the full desired topic->rating map for this enrolment
    (PUT/full-replace semantics) — a topic omitted from this map has its
    existing rating deleted, mirroring
    :meth:`~lemely.db.student_profile_repo.StudentProfileService.set_confidence_ratings`.
    """

    ratings: dict[str, int]


__all__ = [
    "ConfidenceRatingDTO",
    "ConfidenceRatingsUpdateDTO",
    "EnrolmentListRequestDTO",
    "EnrolmentUpsertDTO",
    "StudentProfileDTO",
    "StudentProfileUpdateDTO",
    "StudentProfileWithEnrolmentsDTO",
    "SubjectEnrolmentDTO",
]
